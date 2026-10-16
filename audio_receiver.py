#!/usr/bin/env python3
"""Stabiler Audioempfänger: 192.168.10.2 -> 192.168.10.1:5000/UDP."""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path
import sys
import threading
import time
import wave
import numpy as np
import sounddevice as sd
from audio_devices import choose_device, list_devices, platform_settings
from audio_transport import ClockMatcher, JitterBuffer, PORT, RECEIVER_IP, SENDER_IP, parse_packet, udp_socket


def output_pcm(samples, channels=2, mode="both"):
    mono = np.clip(np.rint(samples), -32768, 32767).astype("=i2")
    if channels == 1:
        return mono.tobytes()
    stereo = np.zeros((len(mono), 2), dtype="=i2")
    if mode in ("both", "left"):
        stereo[:, 0] = mono
    if mode in ("both", "right"):
        stereo[:, 1] = mono
    return stereo.tobytes()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default=RECEIVER_IP)
    parser.add_argument("--source", default=SENDER_IP, help="Nur diese Sender-IP akzeptieren")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--device", type=int)
    parser.add_argument("--list-devices", action="store_true")
    parser.add_argument("--buffer-ms", type=float, default=120)
    parser.add_argument("--jitter", type=int, help="Kompatibilität: Puffer in 10-ms-Paketen")
    parser.add_argument("--profile", choices=("clean", "speech"), default="clean")
    parser.add_argument("--speech-filter", action="store_true", help="Alias für --profile speech")
    parser.add_argument("--channel", choices=("both", "left", "right"), default="both")
    parser.add_argument("--mains-hz", type=float, default=50)
    parser.add_argument("--gate-db", type=float, help="Optionales Gate; standardmäßig aus, um leise Sprache zu erhalten")
    parser.add_argument("--duration", type=float, help="Testdauer inklusive Warten auf Sender")
    parser.add_argument("--timeout", type=float, default=10)
    parser.add_argument("--record", type=Path, help="Originalpakete vor Filtern als Mono-WAV sichern")
    parser.add_argument("--stats-json", type=Path)
    parser.add_argument("--no-playback", action="store_true", help="Nur Empfang/Aufnahme prüfen")
    args = parser.parse_args(argv)
    if args.list_devices:
        list_devices("output")
        return 0
    if args.jitter is not None:
        args.buffer_ms = args.jitter * 10
    if args.speech_filter:
        args.profile = "speech"
    if not 1 <= args.port <= 65535 or not 20 <= args.buffer_ms <= 1000:
        parser.error("Port ungültig oder Puffer außerhalb 20..1000 ms")
    if args.duration is not None and not (0 < args.duration < math.inf):
        parser.error("--duration muss positiv und endlich sein")
    if (not 45 <= args.mains_hz <= 65 or
        (args.gate_db is not None and not -100 <= args.gate_db <= 0) or
        not (0 < args.timeout < math.inf)):
        parser.error("Filter- oder Timeout-Einstellung ungültig")
    jitter = JitterBuffer(args.buffer_ms)
    stop = threading.Event()
    stats = dict(invalid=0, foreign=0, output_blocks=0, underflows=0, nonzero_blocks=0,
                 input_rms_dbfs=-120.0, output_rms_dbfs=-120.0, clock_correction_ppm=0.0)
    errors = []
    sock = thread = record = receiver_device = None
    record_rate = None
    record_part = 0
    started = time.monotonic()
    return_code = 0

    def network_receiver():
        nonlocal record, record_rate, record_part
        try:
            while not stop.is_set():
                try:
                    data, address = sock.recvfrom(65535)
                except TimeoutError:
                    continue
                if address[0] != args.source:
                    stats["foreign"] += 1
                    continue
                packet = parse_packet(data)
                if packet is None:
                    stats["invalid"] += 1
                    continue
                if jitter.push(packet, address) and args.record:
                    if record is None or record_rate != packet.samplerate:
                        if record:
                            record.close()
                        args.record.parent.mkdir(parents=True, exist_ok=True)
                        record_part += 1
                        record_path = args.record if record_part == 1 else args.record.with_name(
                            f"{args.record.stem}.part{record_part}{args.record.suffix}")
                        record = wave.open(str(record_path), "wb")
                        record.setnchannels(1)
                        record.setsampwidth(2)
                        record.setframerate(packet.samplerate)
                        record_rate = packet.samplerate
                    if record_rate == packet.samplerate:
                        record.writeframesraw(packet.pcm)
        except Exception as exc:
            if not stop.is_set():
                errors.append(str(exc))
                stop.set()
        finally:
            if record:
                record.close()

    def expired():
        return args.duration is not None and time.monotonic() - started >= args.duration

    try:
        # Den teuren ersten SciPy-Import erledigen, bevor UDP-Pakete gepuffert werden.
        if args.profile == "speech":
            import scipy.signal
        sock = udp_socket(args.bind, args.port, receive=True)
        if not args.no_playback:
            device_id, receiver_device = choose_device("output", args.device)
            channels = min(2, int(receiver_device["max_output_channels"]))
            settings = platform_settings(receiver_device)
            print(f"Ausgang: {receiver_device['name']} | Device-ID {device_id} | Modus {args.channel}")
        print(f"Empfänger {args.bind}:{args.port} | Sender {args.source} | Puffer {args.buffer_ms:g} ms | Profil {args.profile}")
        print("Warte auf Audiopakete. Strg+C beendet.")
        thread = threading.Thread(target=network_receiver, daemon=True)
        thread.start()
        warned = False
        next_report = started + 5
        while not stop.is_set() and not expired():
            if jitter.format is None:
                stop.wait(0.05)
                if not warned and time.monotonic() - started > args.timeout:
                    print("Noch kein Sender: Sender-Skript, feste IPs und UDP-Port prüfen.")
                    warned = True
                continue
            if args.no_playback:
                stop.wait(0.01)
                if time.monotonic() >= next_report:
                    print("Empfang:", json.dumps(jitter.snapshot()))
                    next_report = time.monotonic() + 5
                continue
            current_format = jitter.format
            rate, frames = current_format
            processor = None
            if args.profile == "speech":
                from audio_filters import VoiceProcessor
                processor = VoiceProcessor(rate, args.mains_hz, args.gate_db)
            matcher = ClockMatcher()
            with sd.RawOutputStream(device=device_id, samplerate=rate, channels=channels,
                                    dtype="int16", blocksize=0, latency=0.06,
                                    extra_settings=settings) as stream:
                print(f"Audioausgabe läuft: {rate} Hz, Pufferziel {jitter.target} Pakete, Gerätelatenz {stream.latency * 1000:.0f} ms")
                jitter.prime()
                while not stop.is_set() and not expired() and jitter.format == current_format:
                    samples = jitter.read(current_format)
                    if samples is None:
                        continue
                    rms = float(np.sqrt(np.mean(samples * samples))) / 32768
                    stats["input_rms_dbfs"] = round(20 * math.log10(max(rms, 1e-6)), 1)
                    if processor:
                        samples = processor.process_samples(samples)
                    state = jitter.snapshot()
                    if state["ready"]:
                        samples = matcher.process(samples, state["buffer_packets"], max(0, state["target_packets"] - 1))
                    else:
                        matcher = ClockMatcher()
                    if not len(samples):
                        continue
                    if stream.write(output_pcm(samples, channels, args.channel)):
                        stats["underflows"] += 1
                    stats["output_blocks"] += 1
                    stats["nonzero_blocks"] += int(bool(np.any(samples)))
                    rms = float(np.sqrt(np.mean(samples * samples))) / 32768
                    stats["output_rms_dbfs"] = round(20 * math.log10(max(rms, 1e-6)), 1)
                    stats["clock_correction_ppm"] = round(matcher.correction * 1e6, 1)
                    if time.monotonic() >= next_report:
                        print(f"Empfangen {state['received']} | Abgespielt {state['played']} | Fehlend {state['lost']} | "
                              f"Unterläufe {stats['underflows']} | Puffer {state['buffer_packets']} | "
                              f"Neustarts {state['restarts']} | Pegel {stats['input_rms_dbfs']:.1f} -> {stats['output_rms_dbfs']:.1f} dBFS")
                        next_report = time.monotonic() + 5
        if errors:
            raise RuntimeError(errors[0])
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, RuntimeError, sd.PortAudioError) as exc:
        print(f"Empfängerfehler: {exc}", file=sys.stderr)
        if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 10048:
            print("Es läuft bereits ein Empfänger auf diesem Port. Diese Instanz wurde nicht gestartet.", file=sys.stderr)
        return_code = 1
    finally:
        stop.set()
        if thread:
            thread.join(timeout=2)
        if sock:
            sock.close()
        summary = {**jitter.snapshot(), **stats, "elapsed_s": round(time.monotonic() - started, 3),
                   "profile": args.profile, "source": args.source,
                   "output_device": receiver_device["name"] if receiver_device else None}
        if args.stats_json:
            args.stats_json.parent.mkdir(parents=True, exist_ok=True)
            args.stats_json.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print("Empfänger beendet:", json.dumps(summary, ensure_ascii=False))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
