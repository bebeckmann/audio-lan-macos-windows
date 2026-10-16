"""Signaltests: python -m unittest test_audio_filters -v"""

import unittest

import numpy as np

from audio_filters import SpeechFilter


class SpeechFilterTests(unittest.TestCase):
    def test_hum_rejected_and_voice_band_preserved(self):
        rate = 44100
        t = np.arange(rate * 3) / rate
        hum_frequencies = (50,)
        hum = sum(2000 * np.sin(2 * np.pi * f * t) for f in hum_frequencies)
        wanted = 2000 * np.sin(2 * np.pi * 1200 * t)
        pcm = np.rint(hum + wanted).astype("<i2").tobytes()
        filtered = np.frombuffer(SpeechFilter(rate).process(pcm), dtype="<i2").astype(float)
        # Nach dem Einschwingen: gezielt die Amplitude jeder Frequenz messen.
        window = t[rate:]
        output = filtered[rate:]
        for frequency in hum_frequencies:
            amplitude = abs(2 * np.mean(output * np.exp(-2j * np.pi * frequency * window)))
            self.assertLess(amplitude, 30, f"Netzbrummen bei {frequency} Hz")
        amplitude = abs(2 * np.mean(output * np.exp(-2j * np.pi * 1200 * window)))
        self.assertGreater(amplitude, 1800, "Nutzsignal muss erhalten bleiben")

    def test_packet_boundaries_do_not_reset_filter(self):
        rng = np.random.default_rng(42)
        pcm = rng.integers(-10000, 10000, 44100, dtype=np.int16).tobytes()
        expected = SpeechFilter(44100).process(pcm)
        chunked = SpeechFilter(44100)
        actual = b"".join(chunked.process(pcm[i:i + 882]) for i in range(0, len(pcm), 882))
        self.assertEqual(actual, expected)

    def test_silence_and_saturation(self):
        filtered = SpeechFilter(48000)
        self.assertEqual(filtered.process(bytes(960)), bytes(960))
        self.assertEqual(filtered.process(b""), b"")
        pcm = np.tile(np.array([-32768, 32767], dtype="<i2"), 4800).tobytes()
        output = filtered.process(pcm)
        self.assertEqual(len(output), len(pcm))
        self.assertTrue(np.isfinite(filtered.state).all())


if __name__ == "__main__":
    unittest.main()
