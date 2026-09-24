# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Encode module inputs into stimulation and decode spikes back into signals.

The two lossy interfaces between silicon and wetware. Encoders map a bounded
input to a stim plan that provably satisfies the SDK safety limits (clamped at
construction, so an out-of-range value can never produce an unsafe `StimDesign`).
Decoders are pure functions of the spikes recorded on a territory this tick.

Territories are passed as plain channel sequences so this module never imports the
broker. See `openspec/changes/wetware-substrate-foundation/` (requirement:
"Deterministic, safe, reversible codecs").
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Iterable, Sequence

import numpy as np

# SDK stim ceilings (see cl-sdk's StimDesign): |current| <= 3 uA,
# duration a multiple of 20 us, charge <= 3 nC/phase. A 200 us biphasic pulse at
# <= 3 uA is well within all three (200 us * 3 uA = 0.6 nC).
_MAX_UA = 3.0
_PULSE_US = 200


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else float(x)


@dataclass(frozen=True)
class StimRequest:
    """A single channel's stimulation this tick — a `(ChannelSet, StimDesign)`."""

    channel: int
    amplitude_uA: float

    def to_cl(self):
        from cl import ChannelSet, StimDesign

        a = min(abs(self.amplitude_uA), _MAX_UA)
        # Biphasic, charge-balanced, alternating polarity (SDK requirement).
        return ChannelSet(self.channel), StimDesign(_PULSE_US, -a, _PULSE_US, a)


class RateEncoder:
    """Rate-code a scalar in [0, 1] to stimulation amplitude on one channel."""

    def __init__(self, channel: int, *, min_uA: float = 0.5, max_uA: float = _MAX_UA):
        if not (0.0 < max_uA <= _MAX_UA):
            raise ValueError(f"max_uA must be in (0, {_MAX_UA}], got {max_uA}")
        self._channel = int(channel)
        self._min = float(min_uA)
        self._max = float(max_uA)

    def encode(self, value: float) -> StimRequest:
        v = _clamp01(value)
        return StimRequest(self._channel, self._min + v * (self._max - self._min))


class PopulationEncoder:
    """Population-code a vector across a territory: one channel per component."""

    def __init__(self, channels: Sequence[int], *, max_uA: float = _MAX_UA):
        self._channels = tuple(int(c) for c in channels)
        self._max = float(max_uA)

    def encode(self, vector: Iterable[float]) -> list[StimRequest]:
        vec = list(vector)
        if len(vec) != len(self._channels):
            raise ValueError(
                f"vector length {len(vec)} != territory size {len(self._channels)}"
            )
        return [
            RateEncoder(ch, max_uA=self._max).encode(v)
            for ch, v in zip(self._channels, vec)
        ]


def _to_local(spikes: Iterable, channels: Sequence[int]) -> dict[int, list]:
    """Group spikes by their territory-local channel index (0..len-1)."""
    index = {ch: i for i, ch in enumerate(channels)}
    out: dict[int, list] = {i: [] for i in range(len(channels))}
    for s in spikes:
        i = index.get(int(s.channel))
        if i is not None:
            out[i].append(s)
    return out


class FiringRateDecoder:
    """Decode a territory's spikes this tick into a per-channel count vector."""

    def __init__(self, channels: Sequence[int]):
        self._channels = tuple(int(c) for c in channels)

    def decode(self, spikes: Iterable) -> np.ndarray:
        grouped = _to_local(spikes, self._channels)
        return np.array([len(grouped[i]) for i in range(len(self._channels))], dtype=float)


def lempel_ziv_complexity(bits: Sequence[int]) -> int:
    """LZ76 complexity: the number of distinct substrings encountered by the
    Lempel-Ziv parsing of the binary sequence. Higher = less compressible = more
    disordered. Pure, deterministic, dependency-free."""
    s = "".join("1" if b else "0" for b in bits)
    n = len(s)
    if n == 0:
        return 0
    i, k, l, c = 0, 1, 1, 1  # noqa: E741 (LZ76 notation)
    while True:
        if s[i + k - 1] == s[l + k - 1]:
            k += 1
            if l + k > n:
                c += 1
                break
        else:
            i += 1
            if i == l:
                c += 1
                l += k  # noqa: E741
                if l + 1 > n:
                    break
                i, k = 0, 1
            else:
                k = 1
    return c


@dataclass
class SurpriseDecoder:
    """Decode a territory's response into a prediction-error scalar in [0, 1].

    Bins the territory's spikes into a binary population raster, measures its
    Lempel-Ziv complexity (response disorder), and compares it to a rolling
    baseline: a response more disordered than recent history reads as higher
    surprise. This is the free-energy bridge — the module maps it to salience.
    """

    channels: Sequence[int]
    bins: int = 32
    baseline_window: int = 32
    _history: deque = field(default_factory=lambda: deque(maxlen=32))

    def __post_init__(self) -> None:
        self.channels = tuple(int(c) for c in self.channels)
        self._history = deque(maxlen=self.baseline_window)

    def _raster_bits(self, spikes: Iterable, from_ts: int, frame_count: int) -> list[int]:
        grouped = _to_local(spikes, self.channels)
        step = max(1, frame_count // self.bins)
        bits: list[int] = []
        for i in range(len(self.channels)):
            counts = [0] * self.bins
            for s in grouped[i]:
                b = int((int(s.timestamp) - from_ts) // step)
                if 0 <= b < self.bins:
                    counts[b] += 1
            bits.extend(1 if c > 0 else 0 for c in counts)
        return bits

    def complexity(self, spikes: Iterable, from_ts: int, frame_count: int) -> int:
        return lempel_ziv_complexity(self._raster_bits(spikes, from_ts, frame_count))

    def decode(self, spikes: Iterable, from_ts: int, frame_count: int) -> float:
        c = float(self.complexity(spikes, from_ts, frame_count))
        if len(self._history) < 2:
            self._history.append(c)
            return 0.5  # no baseline yet — neutral surprise
        hist = np.array(self._history, dtype=float)
        mu, sigma = float(hist.mean()), float(hist.std())
        self._history.append(c)
        z = (c - mu) / (sigma + 1e-6)
        return float(1.0 / (1.0 + np.exp(-z)))  # logistic → (0, 1)
