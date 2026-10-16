"""Versioniertes Mono-PCM-Protokoll und begrenzter Echtzeit-Jitterpuffer."""
from __future__ import annotations

from dataclasses import dataclass
import socket
import struct
import threading
import time
import zlib

import numpy as np

SENDER_IP = "192.168.10.2"
RECEIVER_IP = "192.168.10.1"
PORT = 5000
HEADER = struct.Struct("!4sBBHIQIQI")
LEGACY_HEADER = struct.Struct("!4sBBHIIQ")
RATES = {16000, 24000, 32000, 44100, 48000, 88200, 96000}


def sequence_distance(a, b):
    return ((a - b + 0x80000000) & 0xffffffff) - 0x80000000


@dataclass(frozen=True)
class Packet:
    samplerate: int
    frames: int
    session: int
    sequence: int
    sample_index: int
    pcm: bytes
    version: int = 2

    @property
    def format(self):
        return self.samplerate, self.frames


def encode_packet(packet):
    if packet.samplerate not in RATES or not 1 <= packet.frames <= 4096:
        raise ValueError("Ungültiges Audioformat")
    if len(packet.pcm) != packet.frames * 2:
        raise ValueError("PCM-Länge stimmt nicht mit der Framezahl überein")
    header = HEADER.pack(b"AUD2", 2, 1, packet.frames, packet.samplerate,
                         packet.session, packet.sequence, packet.sample_index, 0)
    crc = zlib.crc32(header[:-4] + packet.pcm)
    return header[:-4] + struct.pack("!I", crc) + packet.pcm


def parse_packet(data):
    try:
        if data[:4] == b"AUD2" and len(data) >= HEADER.size:
            magic, version, channels, frames, rate, session, seq, index, crc = HEADER.unpack_from(data)
            pcm = data[HEADER.size:]
            if version != 2 or zlib.crc32(data[:HEADER.size - 4] + pcm) != crc:
                return None
        elif data[:4] == b"AUD0" and len(data) >= LEGACY_HEADER.size:
            magic, version, channels, frames, rate, seq, stamp = LEGACY_HEADER.unpack_from(data)
            if version != 1:
                return None
            session, index = 0, seq * frames
            pcm = data[LEGACY_HEADER.size:]
        else:
            return None
    except struct.error:
        return None
    if channels != 1 or rate not in RATES or not 1 <= frames <= 4096 or len(pcm) != 2 * frames:
        return None
    return Packet(rate, frames, session, seq, index, pcm, version)


def udp_socket(bind_ip, port, receive=False):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # Windows darf keine zwei Empfänger an denselben Port binden.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        if receive:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024 * 1024)
        sock.bind((bind_ip, port))
        sock.settimeout(0.2)
        return sock
    except BaseException:
        sock.close()
        raise


class JitterBuffer:
    """Reihenfolge, Neustarts, Aussetzer und Rückkehr nach Netzunterbrechung.

    Der Ausgabetakt wartet niemals auf ein verspätetes Netzwerkpaket.
    Bei längeren Lücken wird Stille ausgegeben und neu vorgepuffert.
    """
    def __init__(self, buffer_ms=120):
        self.buffer_ms = buffer_ms
        self.lock = threading.Lock()
        self.changed = threading.Event()
        self.packets = {}
        self.identity = None
        self.retired = set()
        self.format = None
        self.expected = None
        self.target = 1
        self.maximum = 20
        self.ready = False
        self.started = False
        self.last_arrival = 0.0
        self.last_sample = 0.0
        self.fade_in = True
        self.consecutive_missing = 0
        self.stats = dict(received=0, played=0, lost=0, late=0, duplicate=0,
                          restarts=0, resyncs=0, overflow=0, startup_discarded=0)

    def push(self, packet, address, now=None):
        now = time.monotonic() if now is None else now
        identity = (address, packet.session, packet.version)
        with self.lock:
            if identity in self.retired:
                self.stats["late"] += 1
                return False
            legacy_restart = (packet.version == 1 and identity == self.identity and
                              self.expected is not None and
                              sequence_distance(packet.sequence, self.expected) < -self.maximum and
                              (now - self.last_arrival > 0.5 or packet.sequence < 4))
            if identity != self.identity or packet.format != self.format or legacy_restart:
                if self.identity is not None:
                    if identity != self.identity:
                        self.retired.add(self.identity)
                        if len(self.retired) > 32:
                            self.retired.pop()
                    self.stats["restarts"] += 1
                self.identity, self.format = identity, packet.format
                duration_ms = packet.frames * 1000 / packet.samplerate
                self.target = max(2, round(self.buffer_ms / duration_ms))
                self.maximum = max(self.target * 3, self.target + 10)
                self.packets.clear()
                self.expected = packet.sequence
                self.ready = False
                self.started = False
                self.last_sample = 0.0
                self.fade_in = True
                self.consecutive_missing = 0
                self.changed.set()
            self.last_arrival = now
            if self.expected is not None and sequence_distance(packet.sequence, self.expected) < 0:
                self.stats["late"] += 1
                return False
            if packet.sequence in self.packets:
                self.stats["duplicate"] += 1
                return False
            self.packets[packet.sequence] = packet
            self.stats["received"] += 1
            # Große Sequenzsprünge dürfen weder Sekunden Stille noch RAM-Wachstum erzeugen.
            if (len(self.packets) > self.maximum or
                sequence_distance(packet.sequence, self.expected) > self.maximum * 4):
                ordered = sorted(self.packets, key=lambda s: sequence_distance(s, packet.sequence))
                keep = ordered[-self.target:]
                counter = "overflow" if self.started else "startup_discarded"
                self.stats[counter] += max(0, len(self.packets) - len(keep))
                self.packets = {s: self.packets[s] for s in keep}
                self.expected = keep[0]
                self.ready = False
                self.fade_in = True
                if self.started:
                    self.stats["resyncs"] += 1
            self.changed.set()
            return True

    def prime(self):
        with self.lock:
            if len(self.packets) < self.target:
                return False
            # Auch eine langsame Initialisierung des Audiogeräts erhöht die Latenz nicht dauerhaft.
            ordered = sorted(self.packets, key=lambda s: sequence_distance(s, self.expected))
            keep = ordered[-self.target:]
            self.stats["startup_discarded"] += len(self.packets) - len(keep)
            self.packets = {s: self.packets[s] for s in keep}
            self.expected = keep[0]
            self.ready = True
            return True

    def read(self, expected_format=None):
        with self.lock:
            if self.format is None or (expected_format is not None and self.format != expected_format):
                return None
            rate, frames = self.format
            if not self.ready:
                if len(self.packets) >= self.target:
                    ordered = sorted(self.packets, key=lambda s: sequence_distance(s, self.expected))
                    self.expected = ordered[0]
                    self.ready = True
                    self.fade_in = True
                else:
                    return np.zeros(frames, dtype=np.float64)
            packet = self.packets.pop(self.expected, None)
            self.expected = (self.expected + 1) & 0xffffffff
            if packet is None:
                self.stats["lost"] += 1
                self.consecutive_missing += 1
                # Sanft auf Null statt harter Sprünge (keine Wiederholung alter Sprache).
                output = np.zeros(frames, dtype=np.float64)
                ramp = min(frames, max(1, round(rate * 0.003)))
                output[:ramp] = np.linspace(self.last_sample, 0, ramp)
                self.last_sample = 0.0
                self.fade_in = True
                if self.consecutive_missing >= 3:
                    self.ready = False
                    self.stats["resyncs"] += 1
                    if self.packets:
                        self.expected = min(self.packets, key=lambda s: sequence_distance(s, self.expected))
                return output
            self.consecutive_missing = 0
            self.stats["played"] += 1
            self.started = True
            output = np.frombuffer(packet.pcm, dtype="<i2").astype(np.float64)
            if self.fade_in:
                ramp = min(frames, max(1, round(rate * 0.003)))
                output[:ramp] *= np.linspace(0, 1, ramp)
                self.fade_in = False
            self.last_sample = float(output[-1])
            return output

    def snapshot(self):
        with self.lock:
            return {**self.stats, "buffer_packets": len(self.packets),
                    "target_packets": self.target, "ready": self.ready,
                    "format": self.format, "identity": self.identity}


class ClockMatcher:
    """Kontinuierliche Interpolation für kleine Unterschiede der Audioquarze.

    Korrektur auf +/-0,2 Prozent begrenzt; keine Paket-Duplikate oder Sprünge.
    """
    def __init__(self):
        self.tail = np.empty(0)
        self.position = 0.0
        self.error = 0.0
        self.correction = 0.0

    def process(self, samples, queued, target):
        self.error = 0.99 * self.error + 0.01 * (queued - target)
        self.correction = float(np.clip(self.error * 0.00015, -0.002, 0.002))
        data = np.concatenate((self.tail, samples))
        step = 1 + self.correction
        positions = np.arange(self.position, len(data) - 1, step)
        output = np.interp(positions, np.arange(len(data)), data)
        next_position = self.position + len(positions) * step
        consumed = min(int(next_position), len(data) - 1)
        self.tail = data[consumed:]
        self.position = next_position - consumed
        return output
