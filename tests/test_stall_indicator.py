# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from typing import Callable, List, Tuple

import pytest

from kaine.cycle.time_scale_controller import (
    ScaleChange,
    TimeScaleController,
    TimeScaleSettings,
)


def simulate_stalled(
    controller: TimeScaleController,
    scale: float,
    rate: float,
    duration: float,
    busy_ms: float,
    stalled: bool | Callable[[float], bool] = False,
) -> Tuple[float, List[Tuple[float, ScaleChange]]]:
    t = 0.0
    changes: List[Tuple[float, ScaleChange]] = []
    while t < duration:
        is_stalled = stalled(t) if callable(stalled) else stalled
        period_ms = 1000.0 / (rate * scale)
        change = controller.observe(busy_ms, period_ms, t, current_scale=scale, stalled=is_stalled)
        if change is not None:
            scale = change.new
            changes.append((t, change))
        t += period_ms / 1000.0
    return scale, changes


def _make(**kw) -> TimeScaleController:
    return TimeScaleController(TimeScaleSettings(ceiling=1.0, **kw), initial_scale=1.0)


def test_stalled_false_default_no_effect():
    a = _make()
    b = _make()
    assert a.observe(10.0, 100.0, 0.0, current_scale=1.0) is None
    assert b.observe(10.0, 100.0, 0.0, current_scale=1.0, stalled=False) is None
    assert a.utilization == pytest.approx(0.1)
    assert b.utilization == a.utilization


def test_stalled_raises_utilization_to_one():
    ctrl = _make()
    ctrl.observe(10.0, 100.0, 0.0, current_scale=1.0, stalled=True)
    assert ctrl.utilization == pytest.approx(1.0)


def test_sustained_stall_triggers_overload():
    settings = TimeScaleSettings(ceiling=1.0)
    ctrl = TimeScaleController(settings, initial_scale=1.0)
    final_scale, changes = simulate_stalled(ctrl, 1.0, 10.0, 60.0, 10.0, stalled=True)
    assert changes
    t, ch = changes[0]
    assert ch.reason == "overload"
    assert t >= settings.dwell_s
    assert ch.new < 1.0
    assert final_scale < 1.0


def test_short_stall_within_dwell_no_change():
    ctrl = _make()
    _, changes = simulate_stalled(ctrl, 1.0, 10.0, 20.0, 10.0, stalled=lambda t: 1.0 <= t < 4.0)
    assert changes == []


def test_stalled_floor_holds():
    settings = TimeScaleSettings(ceiling=1.0)
    ctrl = TimeScaleController(settings, initial_scale=1.0)
    final_scale, changes = simulate_stalled(ctrl, 1.0, 10.0, 600.0, 5000.0, stalled=True)
    assert changes
    assert all(ch.new >= settings.floor - 1e-9 for _, ch in changes)
    assert final_scale >= settings.floor - 1e-9


def test_passive_residency_identical():
    a = _make()
    b = _make()
    scale_a = scale_b = 1.0
    t = 0.0
    while t < 120.0:
        busy = 150.0 if 20.0 <= t < 70.0 else 20.0
        pa = 1000.0 / (10.0 * scale_a)
        pb = 1000.0 / (10.0 * scale_b)
        ra = a.observe(busy, pa, t, current_scale=scale_a, stalled=False)
        rb = b.observe(busy, pb, t, current_scale=scale_b)
        assert ra == rb
        assert a.utilization == b.utilization
        if ra is not None:
            scale_a = scale_b = ra.new
        t += pa / 1000.0
