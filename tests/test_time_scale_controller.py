# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from typing import Callable, List, Tuple

import pytest

from kaine.cycle.time_scale_controller import (
    ScaleChange,
    TimeScaleController,
    TimeScaleSettings,
)


def simulate(
    controller: TimeScaleController,
    scale: float,
    rate: float,
    duration: float,
    busy_ms: float | Callable[[float], float],
) -> Tuple[float, List[Tuple[float, ScaleChange]]]:
    t = 0.0
    changes: List[Tuple[float, ScaleChange]] = []
    while t < duration:
        b = busy_ms(scale) if callable(busy_ms) else busy_ms
        period_ms = 1000.0 / (rate * scale)
        change = controller.observe(b, period_ms, t, current_scale=scale)
        if change is not None:
            scale = change.new
            changes.append((t, change))
        t += period_ms / 1000.0
    return scale, changes


def test_utilization_none_before_sample():
    settings = TimeScaleSettings(ceiling=1.0)
    ctrl = TimeScaleController(settings, initial_scale=1.0)
    assert ctrl.utilization is None


def test_overload_settles_near_target():
    settings = TimeScaleSettings(ceiling=1.0)
    ctrl = TimeScaleController(settings, initial_scale=1.0)
    final_scale, changes = simulate(ctrl, 1.0, 10.0, 300.0, 150.0)

    assert len(changes) == 1
    t, ch = changes[0]
    assert ch.reason == "overload"
    assert t >= settings.dwell_s
    assert ch.new == pytest.approx(1.0 * settings.target / 1.5)
    assert final_scale == ch.new
    assert ch.utilization == pytest.approx(1.5, abs=0.01)
    assert ctrl.utilization == pytest.approx(settings.target, abs=0.02)


def test_no_change_within_dwell():
    settings = TimeScaleSettings(ceiling=1.0, dwell_s=10.0)
    ctrl = TimeScaleController(settings, initial_scale=1.0)
    _, changes = simulate(ctrl, 1.0, 10.0, settings.dwell_s - 0.001, 150.0)
    assert not changes


def test_floor_holds():
    settings = TimeScaleSettings(ceiling=1.0, floor=0.1)
    ctrl = TimeScaleController(settings, initial_scale=1.0)
    _, changes = simulate(ctrl, 1.0, 10.0, 60.0, 950.0)

    assert len(changes) == 1
    t, ch = changes[0]
    assert ch.reason == "overload"
    assert ch.new == settings.floor
    assert t >= settings.dwell_s


def test_headroom_rises_in_steps():
    settings = TimeScaleSettings(ceiling=1.0, floor=0.1, dwell_s=10.0)
    ctrl = TimeScaleController(settings, initial_scale=0.3)
    final_scale, changes = simulate(ctrl, 0.3, 10.0, 250.0, 20.0)

    assert final_scale == settings.ceiling
    assert len(changes) >= 2
    assert changes[0][1].new <= 0.3 * settings.max_up_factor

    for i, (t, ch) in enumerate(changes):
        assert ch.reason == "headroom"
        assert settings.floor <= ch.new <= settings.ceiling
        if i > 0:
            prev_t, prev_ch = changes[i - 1]
            assert t - prev_t >= settings.dwell_s - 1e-6
            assert ch.new / prev_ch.new <= settings.max_up_factor + 1e-9
            assert ch.new > prev_ch.new


def test_dead_band_no_change():
    settings = TimeScaleSettings(ceiling=1.0)
    ctrl = TimeScaleController(settings, initial_scale=0.85)
    # busy 88 ms -> utilization ~0.748, inside the dead band.
    final_scale, changes = simulate(ctrl, 0.85, 10.0, 300.0, 88.0)

    assert not changes
    assert settings.low < ctrl.utilization < settings.high


def test_no_oscillation_with_falling_load():
    settings = TimeScaleSettings(ceiling=1.0)
    ctrl = TimeScaleController(settings, initial_scale=1.0)

    def busy(scale: float) -> float:
        return 60.0 + 90.0 * scale

    final_scale, changes = simulate(ctrl, 1.0, 10.0, 600.0, busy)

    assert len(changes) <= 2
    assert settings.low < ctrl.utilization < settings.high


def test_invalid_samples_ignored():
    settings = TimeScaleSettings(ceiling=1.0)
    ctrl = TimeScaleController(settings, initial_scale=1.0)

    # First valid sample establishes the EMA.
    assert ctrl.observe(150.0, 100.0, 0.0, current_scale=1.0) is None
    assert ctrl.utilization == pytest.approx(1.5)

    # Each of these must be ignored and leave state untouched.
    assert ctrl.observe(-1.0, 100.0, 0.1, current_scale=1.0) is None
    assert ctrl.observe(150.0, 0.0, 0.1, current_scale=1.0) is None
    assert ctrl.observe(150.0, -10.0, 0.1, current_scale=1.0) is None
    assert ctrl.observe(float("inf"), 100.0, 0.1, current_scale=1.0) is None
    assert ctrl.observe(150.0, float("nan"), 0.1, current_scale=1.0) is None
    assert ctrl.observe(150.0, 100.0, 0.1, current_scale=0.0) is None
    assert ctrl.observe(150.0, 100.0, 0.1, current_scale=-1.0) is None

    assert ctrl.utilization == pytest.approx(1.5)


@pytest.mark.parametrize(
    "override",
    [
        {"ceiling": 0.0},
        {"ceiling": -1.0},
        {"floor": 0.0},
        {"floor": -0.1},
        {"floor": 1.5, "ceiling": 1.0},
        {"target": 0.0},
        {"target": 1.0},
        {"high": 0.85},
        {"high": 0.8},
        {"low": 0.85},
        {"low": 0.9},
        {"low": 0.95, "target": 0.85, "high": 0.9},
        {"dwell_s": 0.0},
        {"window_s": -1.0},
        {"max_up_factor": 1.0},
        {"max_up_factor": 0.5},
        {"max_up_factor": float("inf")},
    ],
)
def test_settings_validation(override):
    base = {
        "ceiling": 1.0,
        "floor": 0.1,
        "target": 0.85,
        "high": 0.95,
        "low": 0.6,
        "dwell_s": 10.0,
        "window_s": 30.0,
        "max_up_factor": 1.25,
    }
    base.update(override)
    with pytest.raises(ValueError):
        TimeScaleSettings(**base)
