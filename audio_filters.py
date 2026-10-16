"""Optionaler Filter fuer Mikrofon-Sprache mit 50-Hz-Netzbrummen.

Der Netzwerkpfad bleibt unveraendert. Nur --speech-filter aktiviert den Filter.
Abhaengigkeiten: numpy, scipy (zusaetzlich zu sounddevice).
"""

import math


class SpeechFilter:
    def __init__(self, samplerate, mains_hz=50):
        import numpy as np
        from scipy import signal

        self.np = np
        self.signal = signal
        # Ein Brumm-Kammfilter bis 8 kHz beschädigt auch die Sprachharmonischen.
        # Nur die Grundfrequenz sperren und tiefe Störungen sanft absenken.
        sections = [signal.butter(2, 65, btype="highpass", fs=samplerate, output="sos")]
        b, a = signal.iirnotch(mains_hz, 25, fs=samplerate)
        sections.append(signal.tf2sos(b, a))
        self.sos = np.concatenate(sections)
        self.state = np.zeros((len(self.sos), 2))
        self.input_energy = 0.0
        self.output_energy = 0.0
        self.samples = 0

    def process(self, pcm):
        np = self.np
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
        if not samples.size:
            return pcm
        filtered, self.state = self.signal.sosfilt(self.sos, samples, zi=self.state)
        self.input_energy += float(np.dot(samples, samples))
        self.output_energy += float(np.dot(filtered, filtered))
        self.samples += len(samples)
        return np.clip(np.rint(filtered), -32768, 32767).astype("<i2").tobytes()

    def reduction_db(self):
        if self.input_energy <= 0 or self.output_energy <= 0:
            return 0.0
        return 10 * math.log10(self.input_energy / self.output_energy)


class VoiceProcessor:
    """Sprachprofil ohne automatische Verstärkung des Hintergrundrauschens.

    Sanfter Hochpass und eine einzelne 50-/60-Hz-Sperre.
    Ein Gate ist nur auf ausdrückliche CLI-Auswahl aktiv.
    """
    def __init__(self, samplerate, mains_hz=50, gate_db=None):
        import numpy as np
        from scipy import signal
        self.np, self.signal = np, signal
        base = SpeechFilter(samplerate, mains_hz)
        self.sos = base.sos
        self.state = np.zeros((len(self.sos), 2))
        self.rate = samplerate
        self.threshold = None if gate_db is None else 32768 * 10 ** (gate_db / 20)
        self.gain = 0.0
        self.hold = 0

    def process_samples(self, samples):
        np = self.np
        filtered, self.state = self.signal.sosfilt(self.sos, samples, zi=self.state)
        if self.threshold is None:
            return filtered
        level = float(np.sqrt(np.mean(filtered * filtered))) if len(filtered) else 0
        if level > self.threshold * 1.4:
            self.hold = int(self.rate * 0.2)
        self.hold = max(0, self.hold - len(samples))
        target = 1.0 if self.hold else min(1.0, (level / max(self.threshold, 1e-9)) ** 2)
        tau = 0.005 if target > self.gain else 0.15
        ramp = target + (self.gain - target) * np.exp(-np.arange(1, len(samples) + 1) / (self.rate * tau))
        if len(ramp):
            self.gain = float(ramp[-1])
        return filtered * ramp
