#!/usr/bin/env python3
"""macOS/Windows/Linux: Mikrofon von 192.168.10.2 an 192.168.10.1 senden."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import queue
import secrets
import sys
import threading
import time
import wave
import numpy as np
import sounddevice as sd
from audio_devices import choose_device, list_devices, platform_settings
from audio_transport import Packet, PORT, RATES, RECEIVER_IP, SENDER_IP, encode_packet, udp_socket


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=RECEIVER_IP)
    parser.add_argument("--bind", default=SENDER_IP)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--device", type=int)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--samplerate", type=int, choices=sorted(RATES), default=48000)
    parser.add_argument("--packet-ms", type=int, choices=(5, 10), default=10)
    parser.add_argument("--input-channel", type=int, default=1, help="Kanal des Interfaces, ab 1")
    parser.add_argument("--duration", type=float)
    parser.add_argument("--test-tone", type=float, metavar="HZ", help="Testton statt Mikrofon, Pegel -24 dBFS")
    parser.add_argument("--wav", type=Path, help="Mono-PCM-WAV statt Mikrofon senden (Selbsttest)")
    parser.add_argument("--stats-json", type=Path)
    args = parser.parse_args(argv)
    if args.list_devices:
        list_devices("input")
        return 0
    if not 1 <= args.port <= 65535 or args.input_channel < 1:
        parser.error("Port oder Eingangskanal ungültig")
    if args.duration is not None and not (0 < args.duration < math.inf):
        parser.error("--duration muss positiv und endlich sein")
    if args.test_tone is not None and not (0 < args.test_tone < args.samplerate / 2):
        parser.error("Testton liegt außerhalb des Audiobereichs")
    if args.test_tone is not None and args.wav:
        parser.error("Nur eine Testquelle auswählen")
    stats = dict(sent=0, capture_overflows=0, queue_dropped=0, send_errors=0,
                 rms_dbfs=-120.0, peak_dbfs=-120.0, clipped_samples=0)
    blocks = queue.Queue(maxsize=12)
    stop = threading.Event()
    session = secrets.randbits(64)
    state = {"sequence": 0, "sample_index": 0}
    failure = []
    source_wav = stream = sock = worker = None
    return_code = 0

    def enqueue(pcm, frames):
        sequence, index = state["sequence"], state["sample_index"]
        state["sequence"] = (sequence + 1) & 0xffffffff
        state["sample_index"] += frames
        item = Packet(args.samplerate, frames, session, sequence, index, pcm)
        try:
            blocks.put_nowait(item)
        except queue.Full:
            try:
                blocks.get_nowait()
            except queue.Empty:
                pass
            stats["queue_dropped"] += 1
            try:
                blocks.put_nowait(item)
            except queue.Full:
                stats["queue_dropped"] += 1

    def callback(indata, frames, time_info, status):
        # Keine Konsole, kein Netzwerk und kein Filter im Audio-Callback.
        if status.input_overflow:
            stats["capture_overflows"] += 1
        data = np.frombuffer(indata, dtype="=i2").reshape(-1, args.input_channel)
        enqueue(data[:, args.input_channel - 1].astype("<i2").tobytes(), frames)

    def network_sender():
        try:
            while not stop.is_set() or not blocks.empty():
                try:
                    packet = blocks.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    sock.sendto(encode_packet(packet), (args.target, args.port))
                except OSError:
                    stats["send_errors"] += 1
                    continue
                samples = np.frombuffer(packet.pcm, dtype="<i2").astype(float)
                rms = float(np.sqrt(np.mean(samples * samples))) / 32768
                peak = float(np.max(np.abs(samples))) / 32768
                stats["rms_dbfs"] = round(20 * math.log10(max(rms, 1e-6)), 1)
                stats["peak_dbfs"] = round(20 * math.log10(max(peak, 1e-6)), 1)
                stats["clipped_samples"] += int(np.count_nonzero(np.abs(samples) >= 32760))
                stats["sent"] += 1
        except Exception as exc:
            failure.append(str(exc))
            stop.set()

    try:
        if args.wav:
            source_wav = wave.open(str(args.wav), "rb")
            if source_wav.getnchannels() != 1 or source_wav.getsampwidth() != 2 or source_wav.getframerate() not in RATES:
                raise ValueError("WAV muss Mono, PCM 16 Bit und eine unterstützte Sample-Rate haben")
            args.samplerate = source_wav.getframerate()
        frames = round(args.samplerate * args.packet_ms / 1000)
        if frames * 2 + 36 > 1400:
            raise ValueError("Paket zu groß: --packet-ms 5 verwenden")
        sock = udp_socket(args.bind, 0)
        if args.test_tone is None and not args.wav:
            device_id, device = choose_device("input", args.device)
            if args.input_channel > device["max_input_channels"]:
                raise ValueError("Eingangskanal existiert bei diesem Gerät nicht")
            settings = platform_settings(device)
            sd.check_input_settings(device=device_id, channels=args.input_channel,
                                    dtype="int16", samplerate=args.samplerate, extra_settings=settings)
            stream = sd.RawInputStream(device=device_id, samplerate=args.samplerate,
                                       channels=args.input_channel, dtype="int16", blocksize=frames,
                                       latency="high", extra_settings=settings, callback=callback)
            print(f"Quelle: {device['name']}, Eingangskanal {args.input_channel}")
        else:
            print("Quelle: WAV-Selbsttest" if args.wav else f"Quelle: Testton {args.test_tone:g} Hz / -24 dBFS")
        print(f"Sender {args.bind} -> {args.target}:{args.port} | {args.samplerate} Hz | Mono PCM16LE | Protokoll 2")
        print("Strg+C beendet. Mikrofonpegel: Spitzen möglichst -12 bis -6 dBFS.")
        worker = threading.Thread(target=network_sender, daemon=True)
        worker.start()
        if stream:
            stream.start()
        started = deadline = time.monotonic()
        report_at = started + 5
        while not stop.is_set():
            now = time.monotonic()
            if args.duration and now - started >= args.duration:
                break
            if stream:
                if not stream.active:
                    raise RuntimeError("Audioaufnahme wurde vom Gerät beendet")
                stop.wait(0.05)
            else:
                if source_wav:
                    pcm = source_wav.readframes(frames)
                    if not pcm:
                        break
                    pcm = pcm.ljust(frames * 2, b"\x00")
                else:
                    t = (state["sample_index"] + np.arange(frames)) / args.samplerate
                    pcm = np.rint(32768 * 10 ** (-24 / 20) * np.sin(2 * np.pi * args.test_tone * t)).astype("<i2").tobytes()
                enqueue(pcm, frames)
                deadline += frames / args.samplerate
                stop.wait(max(0, deadline - time.monotonic()))
            if now >= report_at:
                print(f"Gesendet {stats['sent']} | Aufnahmeüberläufe {stats['capture_overflows']} | "
                      f"Verworfen {stats['queue_dropped']} | Netzwerkfehler {stats['send_errors']} | "
                      f"Pegel {stats['rms_dbfs']:.1f} / Spitze {stats['peak_dbfs']:.1f} dBFS | Clipping {stats['clipped_samples']}")
                report_at = now + 5
        if failure:
            raise RuntimeError(failure[0])
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, sd.PortAudioError, RuntimeError) as exc:
        print(f"Senderfehler: {exc}", file=sys.stderr)
        return_code = 1
    finally:
        if stream:
            stream.close()
        stop.set()
        if worker:
            worker.join(timeout=2)
            if worker.is_alive() or failure:
                return_code = 1
        if sock:
            sock.close()
        if source_wav:
            source_wav.close()
        if args.stats_json:
            args.stats_json.parent.mkdir(parents=True, exist_ok=True)
            args.stats_json.write_text(json.dumps(stats, indent=2), encoding="utf-8")
        print("Sender beendet:", json.dumps(stats, ensure_ascii=False))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
