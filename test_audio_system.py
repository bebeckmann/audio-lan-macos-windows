import json
from pathlib import Path
import socket
import struct
import subprocess
import sys
import tempfile
import unittest
import wave

import numpy as np

from audio_transport import ClockMatcher, JitterBuffer, LEGACY_HEADER, Packet, encode_packet, parse_packet, udp_socket
from audio_receiver import output_pcm
from audio_filters import VoiceProcessor

ROOT = Path(__file__).resolve().parent


def packet(seq, session=1, frames=480, rate=48000, value=1000):
    return Packet(rate, frames, session, seq, seq * frames,
                  np.full(frames, value, dtype="<i2").tobytes())


class ProtocolTests(unittest.TestCase):
    def test_bit_exact_roundtrip_and_corruption(self):
        rng = np.random.default_rng(1)
        p = Packet(48000, 480, 999, 0xffffffff, 99, rng.integers(-32768, 32768, 480, dtype=np.int16).astype("<i2").tobytes())
        data = encode_packet(p)
        self.assertEqual(parse_packet(data), p)
        for position in (10, 20, len(data) - 1):
            broken = bytearray(data)
            broken[position] ^= 1
            self.assertIsNone(parse_packet(broken))
        for end in (0, 3, 10, 35, len(data) - 1):
            self.assertIsNone(parse_packet(data[:end]))

    def test_legacy_and_malformed(self):
        pcm = np.arange(441, dtype="<i2").tobytes()
        data = LEGACY_HEADER.pack(b"AUD0", 1, 1, 441, 44100, 10, 123) + pcm
        self.assertEqual(parse_packet(data).pcm, pcm)
        self.assertEqual(parse_packet(data).version, 1)
        for rate, frames in ((0, 0), (1, 1), (48000, 0)):
            self.assertIsNone(parse_packet(LEGACY_HEADER.pack(b"AUD0", 1, 1, frames, rate, 0, 0)))

    def test_exclusive_port(self):
        first = udp_socket("127.0.0.1", 0, receive=True)
        try:
            with self.assertRaises(OSError):
                second = udp_socket("127.0.0.1", first.getsockname()[1], receive=True)
                second.close()
        finally:
            first.close()


class BufferTests(unittest.TestCase):
    def test_format_change_cannot_enter_old_output_stream(self):
        j = JitterBuffer(20)
        j.push(packet(0), ("sender", 1))
        j.push(packet(0, session=2, frames=441, rate=44100), ("sender", 1))
        self.assertIsNone(j.read((48000, 480)))
        self.assertEqual(j.snapshot()["format"], (44100, 441))

    def test_reorder_and_wraparound(self):
        j = JitterBuffer(30)
        for seq in (0xfffffffe, 0, 0xffffffff):
            j.push(packet(seq, value=seq % 30000), ("sender", 1))
        self.assertTrue(j.prime())
        for seq in (0xfffffffe, 0xffffffff, 0):
            samples = j.read()
            self.assertEqual(samples[-1], seq % 30000)
        self.assertEqual(j.snapshot()["lost"], 0)

    def test_restart_is_immediate_and_old_session_stays_retired(self):
        j = JitterBuffer(20)
        for seq in (100, 101, 102):
            j.push(packet(seq), ("sender", 1))
        j.prime()
        j.read()
        for seq in (0, 1):
            j.push(packet(seq, session=2), ("sender", 1))
        self.assertEqual(j.read()[-1], 1000)
        self.assertFalse(j.push(packet(103), ("sender", 1)))
        self.assertEqual(j.snapshot()["restarts"], 1)

    def test_gap_recovery_and_bounded_memory(self):
        j = JitterBuffer(20)
        for seq in range(2):
            j.push(packet(seq), ("sender", 1))
        j.prime()
        j.read(); j.read()
        for _ in range(10):
            samples = j.read()
        self.assertFalse(j.snapshot()["ready"])
        self.assertTrue(np.all(samples == 0))
        for seq in range(5000, 5200):
            j.push(packet(seq), ("sender", 1))
        self.assertLessEqual(j.snapshot()["buffer_packets"], j.maximum)
        self.assertTrue(j.prime())
        self.assertEqual(j.read()[-1], 1000)

    def test_legacy_restart_same_port_without_pause(self):
        j = JitterBuffer(20)
        for seq in (1000, 1001):
            p = packet(seq, session=0)
            j.push(Packet(p.samplerate, p.frames, 0, seq, 0, p.pcm, 1), ("sender", 1), now=1)
        j.prime(); j.read()
        p = packet(0)
        self.assertTrue(j.push(Packet(48000, 480, 0, 0, 0, p.pcm, 1), ("sender", 1), now=1.01))
        self.assertEqual(j.snapshot()["restarts"], 1)

    def test_single_loss_fades_without_loud_click(self):
        j = JitterBuffer(20)
        for seq in (0, 1, 3):
            j.push(packet(seq, value=1000), ("sender", 1))
        # Nicht prime(): beim automatischen Start die ersten Pakete behalten.
        j.read(); j.read()
        missing = j.read()
        self.assertEqual(missing[0], 1000)
        self.assertEqual(missing[-1], 0)
        returned = j.read()
        self.assertEqual(returned[0], 0)
        self.assertEqual(j.snapshot()["lost"], 1)


class SignalTests(unittest.TestCase):
    def test_voice_harmonics_are_preserved_at_typical_pitches(self):
        rate = 48000
        t = np.arange(rate) / rate
        for fundamental in (100, 125, 150, 175, 200, 250):
            voice = sum(2000 / harmonic * np.sin(2 * np.pi * fundamental * harmonic * t)
                        for harmonic in range(1, 16))
            processor = VoiceProcessor(rate)
            output = np.concatenate([processor.process_samples(voice[i:i + 480])
                                     for i in range(0, len(voice), 480)])
            reference = voice[rate // 2:]
            actual = output[rate // 2:]
            difference_db = 20 * np.log10(np.sqrt(np.mean(actual ** 2) / np.mean(reference ** 2)))
            self.assertGreater(difference_db, -1, f"Stimme mit {fundamental} Hz wird zu stark abgesenkt")

    def test_quiet_voice_is_not_gated_by_default(self):
        rate = 48000
        t = np.arange(rate) / rate
        voice = 12 * np.sin(2 * np.pi * 150 * t)  # etwa -72 dBFS
        processor = VoiceProcessor(rate)
        output = np.concatenate([processor.process_samples(voice[i:i + 480])
                                 for i in range(0, len(voice), 480)])
        self.assertGreater(np.sqrt(np.mean(output[rate // 2:] ** 2)), 7)

    def test_two_minutes_with_different_audio_clocks(self):
        # Virtuelle Zeit: Senderquarz 500 ppm schneller, echter Resampler im Regelkreis.
        j = JitterBuffer(120)
        matcher = ClockMatcher()
        now, next_sequence = 0.12, 0
        packet_period = 0.01 / 1.0005
        maximum_queued = 0
        for _ in range(12000):
            while next_sequence * packet_period <= now:
                j.push(packet(next_sequence), ("sender", 1), now=now)
                next_sequence += 1
            samples = j.read()
            state = j.snapshot()
            maximum_queued = max(maximum_queued, state["buffer_packets"])
            output = matcher.process(samples, state["buffer_packets"], state["target_packets"] - 1)
            now += len(output) / 48000
        state = j.snapshot()
        self.assertEqual(state["lost"], 0)
        self.assertEqual(state["overflow"], 0)
        self.assertLess(maximum_queued, j.maximum)
        self.assertLess(abs(matcher.correction), 0.0021)

    def test_clock_interpolation_continuous_at_packet_boundaries(self):
        matcher = ClockMatcher()
        output = []
        for n in range(100):
            output.append(matcher.process(np.arange(n * 480, (n + 1) * 480), 12, 12))
        np.testing.assert_allclose(np.concatenate(output), np.arange(47999), atol=1e-5)

    def test_output_routing(self):
        samples = np.array([100, -100])
        result = np.frombuffer(output_pcm(samples, 2, "left"), dtype="=i2").reshape(-1, 2)
        np.testing.assert_array_equal(result, [[100, 0], [-100, 0]])

    def test_voice_profile_rejects_hum_preserves_intermediate_voice_tone(self):
        rate = 48000
        t = np.arange(rate * 2) / rate
        x = 4000 * np.sin(2 * np.pi * 50 * t) + 1000 * np.sin(2 * np.pi * 1200 * t)
        processor = VoiceProcessor(rate)
        y = np.concatenate([processor.process_samples(x[i:i+480]) for i in range(0, len(x), 480)])
        t, y = t[rate:], y[rate:]
        hum = abs(2 * np.mean(y * np.exp(-2j * np.pi * 50 * t)))
        wanted = abs(2 * np.mean(y * np.exp(-2j * np.pi * 1200 * t)))
        self.assertLess(hum, 4)
        self.assertGreater(wanted, 800)


class EndToEndTests(unittest.TestCase):
    def test_real_udp_sender_receiver_bit_exact(self):
        # Echte, getrennte Prozesse und echte UDP-Sockets.
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            rate = 48000
            t = np.arange(rate * 2) / rate
            samples = np.rint(2000 * np.sin(2 * np.pi * (300*t + 1200*t*t))).astype("<i2")
            source, captured = folder / "source.wav", folder / "captured.wav"
            with wave.open(str(source), "wb") as w:
                w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(samples.tobytes())
            probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]; probe.close()
            receiver = subprocess.Popen([sys.executable, "-u", str(ROOT / "audio_receiver.py"),
                "--bind", "127.0.0.1", "--source", "127.0.0.1", "--port", str(port),
                "--no-playback", "--duration", "5", "--record", str(captured),
                "--stats-json", str(folder / "stats.json")], cwd=ROOT,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                env={**__import__('os').environ, "PYTHONIOENCODING": "utf-8"})
            try:
                receiver.stdout.readline(); receiver.stdout.readline()
                sent = subprocess.run([sys.executable, str(ROOT / "audio_sender.py"),
                    "--bind", "127.0.0.1", "--target", "127.0.0.1", "--port", str(port),
                    "--wav", str(source)], cwd=ROOT, capture_output=True, timeout=15)
                self.assertEqual(sent.returncode, 0, sent.stderr)
                stdout, stderr = receiver.communicate(timeout=15)
                self.assertEqual(receiver.returncode, 0, stderr + stdout)
                stats = json.loads((folder / "stats.json").read_text())
                self.assertEqual(stats["invalid"], 0)
                self.assertEqual(stats["received"], 200)
                with wave.open(str(captured), "rb") as w:
                    actual = w.readframes(w.getnframes())
                self.assertEqual(actual, samples.tobytes())
            finally:
                if receiver.poll() is None:
                    receiver.kill(); receiver.communicate()


if __name__ == "__main__":
    unittest.main()
