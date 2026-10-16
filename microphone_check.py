"""Lokale Mikrofonaufnahme ohne Netzwerk: python microphone_check.py --play."""
import argparse
import json
import math
from pathlib import Path
import sys
import wave

import numpy as np
from scipy import signal
import sounddevice as sd
from audio_devices import choose_device, platform_settings


def analyze(samples, rate):
    samples = samples.astype(float)
    rms = float(np.sqrt(np.mean(samples * samples)))
    frequencies, power = signal.welch(samples, rate, nperseg=min(65536, len(samples)))
    total = float(power.sum())
    return {"rms_dbfs": round(20 * math.log10(max(rms / 32768, 1e-6)), 1),
            "peak_dbfs": round(20 * math.log10(max(float(np.max(np.abs(samples))) / 32768, 1e-6)), 1),
            "clipping_percent": round(float(100 * np.mean(np.abs(samples) >= 32760)), 4),
            "hum_45_55_hz_percent": round(float(100 * power[(frequencies > 45) & (frequencies < 55)].sum() / total), 1) if total else 0,
            "strongest_frequency_hz": round(float(frequencies[np.argmax(power)]), 1)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", type=int)
    parser.add_argument("--input-channel", type=int, default=1)
    parser.add_argument("--duration", type=float, default=8)
    parser.add_argument("--play", action="store_true")
    parser.add_argument("--analyze", type=Path, help="Vorhandene Mono-PCM16-WAV analysieren")
    args = parser.parse_args()
    if not 1 <= args.duration <= 60 or args.input_channel < 1:
        parser.error("Dauer muss 1..60 Sekunden und Kanal mindestens 1 sein")
    try:
        if args.analyze:
            with wave.open(str(args.analyze), "rb") as recording:
                if recording.getnchannels() != 1 or recording.getsampwidth() != 2:
                    raise ValueError("Analyse benötigt Mono-PCM16")
                rate = recording.getframerate()
                samples = np.frombuffer(recording.readframes(recording.getnframes()), dtype="<i2")
            if not len(samples):
                raise ValueError("Die Aufnahme ist leer")
            print(json.dumps(analyze(samples, rate), indent=2))
            return 0
        device_id, device = choose_device("input", args.device)
        if args.input_channel > device["max_input_channels"]:
            raise ValueError("Dieser Eingangskanal existiert nicht")
        rate = int(device["default_samplerate"])
        settings = platform_settings(device)
        sd.check_input_settings(device=device_id, channels=args.input_channel,
                                dtype="int16", samplerate=rate, extra_settings=settings)
        print(f"Lokale Aufnahme: {device['name']}, Eingang {args.input_channel}, {rate} Hz")
        print(f"JETZT {args.duration:g} Sekunden sprechen. Diese Aufnahme benutzt kein Netzwerk.", flush=True)
        recorded = sd.rec(round(rate * args.duration), samplerate=rate,
                          channels=args.input_channel, dtype="int16", device=device_id,
                          extra_settings=settings, blocking=True)
        samples = recorded[:, args.input_channel - 1]
        folder = Path(__file__).resolve().parent / "diagnostics"
        folder.mkdir(exist_ok=True)
        path = folder / "mikrofon_lokal.wav"
        with wave.open(str(path), "wb") as recording:
            recording.setnchannels(1)
            recording.setsampwidth(2)
            recording.setframerate(rate)
            recording.writeframes(samples.astype("<i2").tobytes())
        report = {"input_device": device["name"], "input_channel": args.input_channel,
                  "samplerate": rate, **analyze(samples, rate)}
        (folder / "mikrofon_lokal.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2, ensure_ascii=False))
        print(f"Gespeichert: {path}")
        if args.play:
            print("Ausgang für die lokale Wiedergabe auswählen:")
            output_id, output_device = choose_device("output")
            channels = min(2, int(output_device["max_output_channels"]))
            playback = np.repeat(samples[:, None].astype(float) / 32768 * 0.25, channels, axis=1).astype(np.float32)
            print("Wiedergabe der Aufnahme mit 25 % Originalpegel, ohne Netzwerk und ohne Filter.")
            sd.play(playback, samplerate=rate, device=output_id,
                    extra_settings=platform_settings(output_device), blocking=True)
        return 0
    except (OSError, ValueError, sd.PortAudioError) as exc:
        print(f"Mikrofontest fehlgeschlagen: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
