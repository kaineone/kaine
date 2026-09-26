# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The oscillatory-binding oscillator on wetware.

A module's binding phase is read from the rhythm of its own substrate territory
instead of a silicon LIF population. Semantics match the silicon oscillator so
PLV coherence means the same thing on both. See
`openspec/changes/oscillator-on-wetware/`.
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any

import numpy as np

from kaine_cl1.substrate.broker import ChannelTerritory, SubstrateBroker
from kaine_cl1.substrate.codec import StimRequest

NEUTRAL_PHASE: float = 0.0
MIN_PLV_WINDOW: int = 10


def _hilbert_phase(series: np.ndarray) -> float:
    """Instantaneous phase of the last sample of the analytic signal.

    Uses the standard FFT Hilbert method to match `scipy.signal.hilbert`.
    """
    n = len(series)
    x = np.fft.fft(series)
    h = np.zeros(n)
    if n % 2 == 0:
        h[0] = h[n // 2] = 1.0
        h[1 : n // 2] = 2.0
    else:
        h[0] = 1.0
        h[1 : (n + 1) // 2] = 2.0
    analytic = np.fft.ifft(x * h)
    return float(np.angle(analytic[-1]))


class WetwareOscillator:
    """Drop-in for KAINE's `OscillatorProtocol`.

    The biological substrate replaces the silicon LIF population. The binding
    phase is recovered from the territory's firing history using the same Hilbert
    phase logic, so PLV coherence stays comparable across backends.
    """

    def __init__(
        self,
        broker: SubstrateBroker,
        territory: ChannelTerritory,
        *,
        plv_window: int = MIN_PLV_WINDOW,
        max_uA: float = 3.0,
        min_uA: float = 0.5,
    ) -> None:
        if plv_window < MIN_PLV_WINDOW:
            raise ValueError(f"plv_window must be at least {MIN_PLV_WINDOW}")
        self._broker = broker
        self._module = territory.module
        self._channels = territory.channels
        self._channel_set = set(self._channels)
        self._min_uA = float(min_uA)
        self._max_uA = float(max_uA)
        self._plv_window = int(plv_window)
        self._drive_scale = 1.0
        self._history: deque[float] = deque(maxlen=2 * plv_window)

    @property
    def drive_scale(self) -> float:
        return float(self._drive_scale)

    @property
    def samples(self) -> int:
        return len(self._history)

    def step(self, drive: float) -> None:
        """Convert salience drive into a stimulation level and record firing."""
        d = float(drive)
        if not math.isfinite(d) or d < 0.0:
            d = 0.0
        if d > 1.0:
            d = 1.0

        level = d * self._drive_scale
        if level > 1.0:
            level = 1.0

        if level > 0.0:
            amp = self._min_uA + level * (self._max_uA - self._min_uA)
            requests = [StimRequest(int(ch), amp) for ch in self._channels]
            self._broker.queue_stim(self._module, requests)

        obs = self._broker.run_cognitive_tick()[self._module]
        fired = {spike.channel for spike in obs.spikes if spike.channel in self._channel_set}
        fraction = len(fired) / len(self._channels) if self._channels else 0.0
        self._history.append(fraction)

    def phase(self) -> float:
        """Return the current binding phase, or the neutral phase if undefined."""
        if len(self._history) < self._plv_window:
            return NEUTRAL_PHASE

        series = np.asarray(self._history, dtype=float)
        series -= series.mean()
        if np.all(np.abs(series) <= 1e-9):
            return NEUTRAL_PHASE

        phase = _hilbert_phase(series)
        if not math.isfinite(phase):
            return NEUTRAL_PHASE
        return phase

    def set_frequency(self, scale: float) -> None:
        s = float(scale)
        if not math.isfinite(s) or s < 0.0:
            s = 0.0
        self._drive_scale = s

    def serialize(self) -> dict[str, Any]:
        return {"drive_scale": self._drive_scale}

    def deserialize(self, state: dict[str, Any]) -> None:
        if "drive_scale" in state:
            self.set_frequency(state["drive_scale"])
