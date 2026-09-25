# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import math
from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.cycle.access_rate import (
    AccessRateConfig,
    AccessRateController,
    max_report_salience,
    phasic_input,
    tonic_drive,
)


def _event(source: str, salience: float) -> tuple[str, Event]:
    return (
        "0-0",
        Event(
            source=source,
            type="report",
            payload={},
            salience=salience,
            timestamp=datetime.now(timezone.utc),
        ),
    )


def test_config_defaults():
    cfg = AccessRateConfig.from_section(None)
    assert cfg.enabled is True
    assert cfg.salience_floor == pytest.approx(0.5)
    assert cfg.phasic_decay_s == pytest.approx(1.0)
    assert cfg.baseline_arousal == pytest.approx(0.3)


def test_config_default_baseline_honoured():
    cfg = AccessRateConfig.from_section({}, default_baseline=0.4)
    assert cfg.baseline_arousal == pytest.approx(0.4)


def test_config_explicit_values():
    cfg = AccessRateConfig.from_section(
        {
            "enabled": False,
            "salience_floor": 0.2,
            "phasic_decay_s": 2.0,
            "baseline_arousal": 0.25,
        }
    )
    assert cfg.enabled is False
    assert cfg.salience_floor == pytest.approx(0.2)
    assert cfg.phasic_decay_s == pytest.approx(2.0)
    assert cfg.baseline_arousal == pytest.approx(0.25)


def test_config_rejects_unknown_key():
    with pytest.raises(ValueError, match="unknown"):
        AccessRateConfig.from_section({"enabled": True, "unknown": 1})


def test_config_rejects_bad_types():
    with pytest.raises(ValueError, match="bool"):
        AccessRateConfig.from_section({"enabled": "true"})
    with pytest.raises(ValueError, match="float"):
        AccessRateConfig.from_section({"salience_floor": "high"})
    with pytest.raises(ValueError, match="float"):
        AccessRateConfig.from_section({"phasic_decay_s": "fast"})
    with pytest.raises(ValueError, match="float"):
        AccessRateConfig.from_section({"baseline_arousal": "calm"})


def test_config_rejects_bool_for_floats():
    with pytest.raises(ValueError, match="float, not bool"):
        AccessRateConfig.from_section({"salience_floor": True})
    with pytest.raises(ValueError, match="float, not bool"):
        AccessRateConfig.from_section({"phasic_decay_s": True})
    with pytest.raises(ValueError, match="float, not bool"):
        AccessRateConfig.from_section({"baseline_arousal": True})


def test_config_validation_ranges():
    with pytest.raises(ValueError):
        AccessRateConfig.from_section({"salience_floor": -0.1})
    with pytest.raises(ValueError):
        AccessRateConfig.from_section({"salience_floor": 1.0})
    with pytest.raises(ValueError):
        AccessRateConfig.from_section({"phasic_decay_s": 0.0})
    with pytest.raises(ValueError):
        AccessRateConfig.from_section({"baseline_arousal": -0.1})
    with pytest.raises(ValueError):
        AccessRateConfig.from_section({"baseline_arousal": 1.0})


def test_tonic_drive_baseline_is_zero():
    assert tonic_drive(0.3, 0.3) == pytest.approx(0.0)


def test_tonic_drive_full_arousal_is_one():
    assert tonic_drive(1.0, 0.3) == pytest.approx(1.0)


def test_tonic_drive_below_baseline_is_zero():
    assert tonic_drive(0.1, 0.3) == pytest.approx(0.0)


def test_tonic_drive_none_is_zero():
    assert tonic_drive(None, 0.3) == pytest.approx(0.0)


def test_tonic_drive_nan_is_zero():
    assert tonic_drive(float("nan"), 0.3) == pytest.approx(0.0)


def test_tonic_drive_intermediate_value():
    # (0.58 - 0.3) / (1 - 0.3) == 0.4
    assert tonic_drive(0.58, 0.3) == pytest.approx(0.4, abs=1e-9)


def test_phasic_input_floor_is_zero():
    assert phasic_input(0.5, 0.5) == pytest.approx(0.0)


def test_phasic_input_full_salience_is_one():
    assert phasic_input(1.0, 0.5) == pytest.approx(1.0)


def test_phasic_input_below_floor_is_zero():
    assert phasic_input(0.3, 0.5) == pytest.approx(0.0)


def test_phasic_input_none_is_zero():
    assert phasic_input(None, 0.5) == pytest.approx(0.0)


def test_phasic_input_nan_is_zero():
    assert phasic_input(float("nan"), 0.5) == pytest.approx(0.0)


def test_phasic_input_intermediate_value():
    # (0.65 - 0.5) / (1 - 0.5) == 0.3
    assert phasic_input(0.65, 0.5) == pytest.approx(0.3, abs=1e-9)


def test_max_report_salience_returns_highest():
    events = [
        _event("topos", 0.2),
        _event("aisthesis", 0.9),
        _event("mneme", 0.6),
    ]
    assert max_report_salience(events) == pytest.approx(0.9)


def test_max_report_salience_ignores_excluded_sources():
    events = [
        _event("cycle", 1.0),
        _event("syneidesis", 1.0),
        _event("topos", 0.6),
    ]
    assert max_report_salience(events) == pytest.approx(0.6)


def test_max_report_salience_none_when_only_excluded():
    events = [_event("cycle", 1.0), _event("syneidesis", 0.8)]
    assert max_report_salience(events) is None


def test_max_report_salience_none_when_empty():
    assert max_report_salience([]) is None


def test_controller_calm_returns_resting():
    cfg = AccessRateConfig(enabled=True, baseline_arousal=0.3)
    ctrl = AccessRateController(cfg)
    drive, effective = ctrl.step(
        events=[],
        arousal=0.3,
        dt_s=0.1,
        resting_hz=3.333,
        ceiling_hz=10.0,
    )
    assert drive == pytest.approx(0.0)
    assert effective == pytest.approx(3.333)


def test_controller_full_arousal_returns_ceiling():
    cfg = AccessRateConfig(enabled=True, baseline_arousal=0.3)
    ctrl = AccessRateController(cfg)
    drive, effective = ctrl.step(
        events=[],
        arousal=1.0,
        dt_s=0.1,
        resting_hz=3.333,
        ceiling_hz=10.0,
    )
    assert drive == pytest.approx(1.0)
    assert effective == pytest.approx(10.0)


def test_controller_phasic_peak_decays():
    cfg = AccessRateConfig(enabled=True, phasic_decay_s=1.0)
    ctrl = AccessRateController(cfg)
    # Spike tick.
    ctrl.step(
        events=[_event("topos", 1.0)],
        arousal=0.3,
        dt_s=0.1,
        resting_hz=3.333,
        ceiling_hz=10.0,
    )
    assert ctrl.drive == pytest.approx(1.0)
    assert ctrl.phasic == pytest.approx(1.0)

    # Quiet ticks: phasic decays by exp(-dt/tau) per tick.
    for n in range(1, 11):
        ctrl.step(
            events=[],
            arousal=0.3,
            dt_s=0.1,
            resting_hz=3.333,
            ceiling_hz=10.0,
        )
        expected = math.exp(-0.1 * n)
        assert ctrl.phasic == pytest.approx(expected, abs=1e-9), f"failed at n={n}"
        assert ctrl.drive == pytest.approx(expected, abs=1e-9)


def test_controller_drive_is_max_not_sum():
    cfg = AccessRateConfig(enabled=True, baseline_arousal=0.3, salience_floor=0.5)
    ctrl = AccessRateController(cfg)
    # tonic ~0.4, phasic input ~0.3 -> max should be 0.4
    drive, _effective = ctrl.step(
        events=[_event("topos", 0.65)],
        arousal=0.58,
        dt_s=0.1,
        resting_hz=3.333,
        ceiling_hz=10.0,
    )
    assert drive == pytest.approx(0.4, abs=1e-9)


def test_controller_disabled_returns_zero_drive_and_resting():
    cfg = AccessRateConfig(enabled=False)
    ctrl = AccessRateController(cfg)
    ctrl.phasic = 0.9  # should be reset
    drive, effective = ctrl.step(
        events=[_event("topos", 1.0)],
        arousal=1.0,
        dt_s=0.1,
        resting_hz=3.333,
        ceiling_hz=10.0,
    )
    assert drive == pytest.approx(0.0)
    assert effective == pytest.approx(3.333)
    assert ctrl.phasic == pytest.approx(0.0)


def test_controller_resting_at_or_above_ceiling_returns_resting():
    cfg = AccessRateConfig(enabled=True)
    ctrl = AccessRateController(cfg)
    drive, effective = ctrl.step(
        events=[_event("topos", 1.0)],
        arousal=1.0,
        dt_s=0.1,
        resting_hz=12.0,
        ceiling_hz=10.0,
    )
    assert effective == pytest.approx(12.0)
    assert drive == pytest.approx(1.0)
