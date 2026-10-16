"""Echter lokaler UDP- und Audioausgabetest: python verify_audio.py --device 8.

Prüft Daten, die tatsächlich an PortAudio geschrieben werden. Ein physischer
Loopback oder Hörtest der Lautsprecher/Anlage ist weiterhin eine andere Messung.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import wave

import numpy as np
from scipy import signal
import sounddevice as sd

import audio_receiver as receiver


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", required=True, type=int)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    folder = root / "diagnostics"
    folder.mkdir(exist_ok=True)
    written, processes = [], []
    original_stream, original_socket = sd.RawOutputStream, receiver.udp_socket

    class CapturedOutput:
        def __init__(self, *a, **kw):
            self.stream = original_stream(*a, **kw)
        def __getattr__(self, name):
            return getattr(self.stream, name)
        def __enter__(self):
            self.stream.__enter__()
            return self
        def write(self, data):
            written.append(data)
            return self.stream.write(data)
        def __exit__(self, *a):
            return self.stream.__exit__(*a)

    def start_sender(*a, **kw):
        sock = original_socket(*a, **kw)
        # Erst nach erfolgreichem Binden senden: kein künstlicher Startverlust.
        processes.append(subprocess.Popen([sys.executable, "-u", str(root / "audio_sender.py"),
            "--bind", "127.0.0.1", "--target", "127.0.0.1", "--port", "5001",
            "--test-tone", "1000", "--duration", "7"], cwd=root,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE))
        return sock

    receiver.sd.RawOutputStream = CapturedOutput
    receiver.udp_socket = start_sender
    try:
        result = receiver.main(["--bind", "127.0.0.1", "--source", "127.0.0.1", "--port", "5001",
            "--device", str(args.device), "--duration", "6", "--profile", "clean",
            "--stats-json", str(folder / "v2_hardware_playback.json")])
    finally:
        receiver.sd.RawOutputStream = original_stream
        receiver.udp_socket = original_socket
        for process in processes:
            try:
                stdout, stderr = process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
            (folder / "v2_test_sender_stdout.log").write_bytes(stdout)
            (folder / "v2_test_sender_stderr.log").write_bytes(stderr)
    if result or not written or any(p.returncode for p in processes):
        print("Audioausgabetest fehlgeschlagen; Diagnoseprotokolle prüfen.")
        return 1
    channels = min(2, int(sd.query_devices(args.device)["max_output_channels"]))
    pcm = b"".join(written)
    with wave.open(str(folder / "v2_output_written.wav"), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(48000)
        output.writeframes(pcm)
    samples = np.frombuffer(pcm, dtype="=i2").reshape(-1, channels)[:, 0].astype(float)
    stable = samples[48000:48000 * 4]
    f, power = signal.welch(stable, 48000, nperseg=32768)
    inside = power[(f > 985) & (f < 1015)].sum()
    outside = power[(f < 980) | (f > 1020)].sum()
    output_stats = json.loads((folder / "v2_hardware_playback.json").read_text())
    report = dict(receiver_exit=result, sender_exit=processes[0].returncode,
                  written_frames=len(samples), peak_frequency_hz=float(f[np.argmax(power)]),
                  power_outside_tone_db=float(10 * np.log10(max(outside, 1e-30) / max(inside, 1e-30))),
                  underflows=output_stats["underflows"], invalid=output_stats["invalid"],
                  lost=output_stats["lost"])
    report["passed"] = bool(result == 0 and report["underflows"] == 0 and report["invalid"] == 0 and
                            report["lost"] == 0 and abs(report["peak_frequency_hz"] - 1000) < 5 and
                            report["power_outside_tone_db"] < -45)
    (folder / "v2_signal_quality.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
