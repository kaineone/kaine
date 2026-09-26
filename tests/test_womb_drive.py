# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import math

import numpy as np
import pytest

from kaine.modules.womb_drive import MaternalDriveProvider
from kaine.modules.womb_signal import WombParams, beat_pulse, heartbeat_phase


class QueueClock:
    def __init__(self, times):
        self._times = list(times)
        self._idx = 0

    def womb_seconds(self):
        if self._idx >= len(self._times):
            return self._times[-1]
        t = self._times[self._idx]
        self._idx += 1
        return t


class MutableClock:
    def __init__(self):
        self.t = 0.0

    def womb_seconds(self):
        return self.t


def _params(max_amp=0.5, drive_to_self=True):
    return WombParams.from_sections(
        {"external_drive_max_amplitude": max_amp, "external_drive_to_self_rhythm": drive_to_self},
        {},
        {},
    )


def test_first_call_is_point_value():
    params = _params(0.5)
    clock = QueueClock([0.0, 0.01])
    provider = MaternalDriveProvider(clock, params, seed=1)
    first = provider()
    expected = 0.5 * float(beat_pulse(heartbeat_phase(1, np.array([0.0]), params))[0])
    assert first == pytest.approx(expected, abs=1e-12)


def test_interval_call_averages_over_linspace():
    params = _params(0.7)
    clock = QueueClock([0.0, 0.05])
    provider = MaternalDriveProvider(clock, params, seed=2)
    provider()
    val = provider()
    dt = 0.05
    n = min(2001, max(2, math.ceil(dt / 0.002) + 1))
    ts = np.linspace(0.0, dt, n)
    expected = 0.7 * float(np.mean(beat_pulse(heartbeat_phase(2, ts, params))))
    assert val == pytest.approx(expected, abs=1e-12)


def test_scale_zero_mutes_drive():
    params = _params(0.6)
    clock = QueueClock([0.0, 0.03])
    provider = MaternalDriveProvider(clock, params, seed=3)
    provider.scale = 0.0
    assert provider() == 0.0
    assert provider() == 0.0


def test_values_stay_within_bounds():
    params = _params(0.9)
    rng = np.random.default_rng(0)
    clock = MutableClock()
    provider = MaternalDriveProvider(clock, params, seed=4)
    prev = 0.0
    for _ in range(2000):
        clock.t = prev + rng.random() * 0.1
        val = provider()
        assert 0.0 <= val <= 0.9
        assert math.isfinite(val)
        prev = clock.t


def test_scale_clamps_to_unit_interval():
    params = _params(1.0)
    clock = MutableClock()
    provider = MaternalDriveProvider(clock, params, seed=5)
    provider.scale = 1.5
    assert provider.scale == 1.0
    provider.scale = -0.2
    assert provider.scale == 0.0
    provider.scale = 0.3
    assert provider.scale == 0.3
