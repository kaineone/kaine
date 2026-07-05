# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for FatigueAccumulator (soma/fatigue.py)."""
from __future__ import annotations

import pytest

from kaine.modules.soma.fatigue import FatigueAccumulator


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_construction_defaults():
    f = FatigueAccumulator()
    assert f.value == 0.0
    assert f.threshold > 0
    assert f.threshold_crossed is False
    assert f.faster_decay is False


def test_construction_rejects_negative_decay():
    with pytest.raises(ValueError):
        FatigueAccumulator(decay_per_s=-0.1)


def test_construction_rejects_zero_threshold():
    with pytest.raises(ValueError):
        FatigueAccumulator(maintenance_threshold=0.0)


def test_construction_rejects_low_faster_decay_factor():
    with pytest.raises(ValueError):
        FatigueAccumulator(faster_decay_factor=0.5)


# ---------------------------------------------------------------------------
# Basic accumulation
# ---------------------------------------------------------------------------

def test_first_update_initialises_timer():
    """The very first update sets the internal clock; value stays 0."""
    f = FatigueAccumulator(decay_per_s=0.0, maintenance_threshold=10.0)
    crossed = f.update(5.0, now=0.0)
    assert not crossed
    assert f.value == 0.0


def test_accumulation_increases_value():
    f = FatigueAccumulator(decay_per_s=0.0, maintenance_threshold=100.0)
    f.update(1.0, now=0.0)
    f.update(1.0, now=1.0)   # dt=1, error=1 → +1.0
    assert f.value == pytest.approx(1.0)


def test_accumulation_integrates_error_over_time():
    f = FatigueAccumulator(decay_per_s=0.0, maintenance_threshold=100.0)
    f.update(2.0, now=0.0)     # initialise
    f.update(2.0, now=5.0)     # dt=5, error=2 → +10.0
    assert f.value == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Decay
# ---------------------------------------------------------------------------

def test_decay_reduces_value():
    f = FatigueAccumulator(decay_per_s=1.0, maintenance_threshold=100.0)
    f.update(10.0, now=0.0)   # init
    f.update(10.0, now=1.0)   # +10 -1 = 9
    f.update(0.0, now=2.0)    # +0 -1 = 8
    assert f.value == pytest.approx(8.0)


def test_decay_does_not_go_below_zero():
    f = FatigueAccumulator(decay_per_s=10.0, maintenance_threshold=100.0)
    f.update(0.0, now=0.0)
    f.update(0.0, now=5.0)   # -50 but clamped at 0
    assert f.value == 0.0


def test_faster_decay_reduces_faster():
    f1 = FatigueAccumulator(decay_per_s=1.0, maintenance_threshold=100.0)
    f2 = FatigueAccumulator(decay_per_s=1.0, maintenance_threshold=100.0, faster_decay_factor=3.0)
    f2.faster_decay = True

    # Give both the same starting value.
    for f in (f1, f2):
        f.update(0.0, now=0.0)
        # Manually set value.
        f._value = 30.0

    f1.update(0.0, now=10.0)
    f2.update(0.0, now=10.0)

    assert f2.value < f1.value


# ---------------------------------------------------------------------------
# Threshold crossing
# ---------------------------------------------------------------------------

def test_threshold_crossing_emits_event():
    f = FatigueAccumulator(decay_per_s=0.0, maintenance_threshold=5.0)
    f.update(0.0, now=0.0)   # init
    crossed = f.update(10.0, now=1.0)   # +10, crosses 5
    assert crossed is True
    assert f.threshold_crossed is True


def test_threshold_not_crossed_when_below():
    f = FatigueAccumulator(decay_per_s=0.0, maintenance_threshold=100.0)
    f.update(0.0, now=0.0)
    crossed = f.update(1.0, now=1.0)   # +1, still < 100
    assert crossed is False
    assert f.threshold_crossed is False


def test_threshold_crossed_only_fires_once():
    """Crossing fires True exactly once; subsequent ticks return False."""
    f = FatigueAccumulator(decay_per_s=0.0, maintenance_threshold=5.0)
    f.update(0.0, now=0.0)
    r1 = f.update(10.0, now=1.0)   # crosses
    r2 = f.update(10.0, now=2.0)   # still above, but already crossed
    r3 = f.update(10.0, now=3.0)
    assert r1 is True
    assert r2 is False
    assert r3 is False


def test_fatigue_decays_without_error():
    """Spec: when prediction error is zero, value strictly decreases."""
    f = FatigueAccumulator(decay_per_s=1.0, maintenance_threshold=100.0)
    f.update(0.0, now=0.0)
    f._value = 20.0   # seed a non-zero value
    f.update(0.0, now=1.0)
    assert f.value < 20.0


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------

def test_reset_clears_state():
    f = FatigueAccumulator(decay_per_s=0.0, maintenance_threshold=5.0)
    f.update(0.0, now=0.0)
    f.update(10.0, now=1.0)
    assert f.value > 0
    f.reset()
    assert f.value == 0.0
    assert f.threshold_crossed is False


def test_reset_allows_recrossing():
    f = FatigueAccumulator(decay_per_s=0.0, maintenance_threshold=5.0)
    f.update(0.0, now=0.0)
    r1 = f.update(10.0, now=1.0)
    assert r1 is True
    f.reset()
    f.update(0.0, now=2.0)
    r2 = f.update(10.0, now=3.0)
    assert r2 is True


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------

def test_state_dict_roundtrip():
    f = FatigueAccumulator(decay_per_s=0.0, maintenance_threshold=100.0)
    f.update(0.0, now=0.0)
    f._value = 42.5
    sd = f.state_dict()
    f2 = FatigueAccumulator(decay_per_s=0.0, maintenance_threshold=100.0)
    f2.load_state_dict(sd)
    assert f2.value == pytest.approx(42.5)


def test_state_dict_does_not_persist_raw_buffers():
    """Only the scalar value is persisted (no raw metric data)."""
    f = FatigueAccumulator()
    sd = f.state_dict()
    assert set(sd.keys()) == {"value"}
