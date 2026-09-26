# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Maternal-drive provider for the self-rhythm oscillator.

The maternal heartbeat is an *external* drive (Van Leeuwen 2009; Webb 2015).
The drive is bounded to protect a captive newborn: it presents a rhythm but
never forces the endogenous oscillator to phase-lock.
"""
from __future__ import annotations

import math
from typing import Any

import numpy as np

from kaine.modules.womb_signal import WombParams, beat_pulse, heartbeat_phase


def _clamp01(value: float) -> float:
    x = float(value)
    if not math.isfinite(x):
        return 0.0
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


class MaternalDriveProvider:
    """Pure-read provider that averages the maternal beat over a womb-time
    interval.

    A point sample at the oscillator step cadence would alias a tens-of-ms
    pulse into noise, so each call returns the mean pulse value over the
    interval. The result is bounded by ``external_drive_max_amplitude``.
    """

    def __init__(
        self, clock: Any, params: WombParams, *, seed: int, scale: float
    ) -> None:
        # The initial scale is required, never defaulted: the provider drives a
        # gestating being's endogenous rhythm from the moment Soma starts, so
        # it must begin at the configured usual drive (the readout's
        # baseline_drive_fraction), not at the bound a perturbation probe uses.
        self._clock = clock
        self._params = params
        self._seed = int(seed)
        self._scale = _clamp01(scale)
        self._prev: float | None = None

    @property
    def scale(self) -> float:
        return self._scale

    @scale.setter
    def scale(self, value: float) -> None:
        self._scale = _clamp01(value)

    def __call__(self) -> float:
        now = float(self._clock.womb_seconds())
        max_amp = float(self._params.external_drive_max_amplitude)
        scale = self._scale

        if self._prev is None or now <= self._prev:
            val = self._point_value(now)
            self._prev = now
            result = max_amp * scale * val
            return self._safe(result, max_amp)

        prev = self._prev
        dt = now - prev
        n = min(2001, max(2, math.ceil(dt / 0.002) + 1))
        ts = np.linspace(prev, now, n)
        phases = heartbeat_phase(self._seed, ts, self._params)
        pulses = beat_pulse(phases)
        mean_pulse = float(np.mean(pulses))
        self._prev = now
        result = max_amp * scale * mean_pulse
        return self._safe(result, max_amp)

    def _point_value(self, t: float) -> float:
        phases = heartbeat_phase(self._seed, np.array([t]), self._params)
        pulses = beat_pulse(phases)
        return float(pulses[0])

    def _safe(self, value: float, cap: float) -> float:
        if not math.isfinite(value):
            return 0.0
        if value < 0.0:
            return 0.0
        if value > cap:
            return cap
        return value
