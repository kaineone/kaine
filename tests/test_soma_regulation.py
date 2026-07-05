# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for RegulationDetector (soma/regulation.py)."""
from __future__ import annotations

import pytest

from kaine.modules.soma.regulation import RegulationDetector


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

def test_construction_defaults():
    r = RegulationDetector()
    assert r.threshold > 0
    assert r.sustain_window_s > 0
    assert r.is_stressed is False


def test_construction_rejects_negative_threshold():
    with pytest.raises(ValueError):
        RegulationDetector(threshold=-0.1)


def test_construction_rejects_zero_window():
    with pytest.raises(ValueError):
        RegulationDetector(sustain_window_s=0.0)


# ---------------------------------------------------------------------------
# Transient stress does NOT emit advisory
# ---------------------------------------------------------------------------

def test_transient_stress_no_advisory():
    """Error briefly above threshold, less than one window → no event."""
    r = RegulationDetector(threshold=0.5, sustain_window_s=10.0)
    # Error above threshold but only for 5 s (< 10 s window).
    r.update(1.0, now=0.0)   # episode starts
    result = r.update(1.0, now=5.0)   # 5 s elapsed < 10 s window
    assert result is None


def test_below_threshold_no_advisory():
    r = RegulationDetector(threshold=0.5, sustain_window_s=10.0)
    result = r.update(0.1, now=0.0)
    assert result is None
    result = r.update(0.3, now=100.0)
    assert result is None


# ---------------------------------------------------------------------------
# Sustained stress emits advisory
# ---------------------------------------------------------------------------

def test_sustained_stress_emits_advisory():
    """Error above threshold for > one window → advisory emitted."""
    r = RegulationDetector(threshold=0.5, sustain_window_s=10.0)
    r.update(1.0, now=0.0)    # episode starts
    result = r.update(1.0, now=11.0)   # 11 s > 10 s window
    assert result is not None
    assert result["action"] in ("reduce_rate", "shed_module", "request_maintenance")
    assert "reason" in result
    assert "severity" in result


def test_advisory_has_valid_action():
    r = RegulationDetector(threshold=0.0, sustain_window_s=5.0)
    r.update(1.0, now=0.0)
    result = r.update(1.0, now=6.0)
    assert result is not None
    assert result["action"] in ("reduce_rate", "shed_module", "request_maintenance")


def test_advisory_severity_is_positive_int():
    r = RegulationDetector(threshold=0.0, sustain_window_s=5.0)
    r.update(1.0, now=0.0)
    result = r.update(1.0, now=6.0)
    assert result is not None
    assert isinstance(result["severity"], int)
    assert result["severity"] > 0


# ---------------------------------------------------------------------------
# Escalation ladder
# ---------------------------------------------------------------------------

def test_escalation_ladder():
    """Three consecutive windows should produce three escalating actions."""
    r = RegulationDetector(threshold=0.0, sustain_window_s=10.0)
    r.update(1.0, now=0.0)
    r1 = r.update(1.0, now=11.0)   # first window
    r2 = r.update(1.0, now=21.0)   # second window
    r3 = r.update(1.0, now=31.0)   # third window

    assert r1 is not None
    assert r2 is not None
    assert r3 is not None

    assert r1["action"] == "reduce_rate"
    assert r2["action"] == "shed_module"
    assert r3["action"] == "request_maintenance"

    assert r1["severity"] < r2["severity"] <= r3["severity"]


# ---------------------------------------------------------------------------
# Episode reset when error drops
# ---------------------------------------------------------------------------

def test_episode_resets_on_low_error():
    r = RegulationDetector(threshold=0.5, sustain_window_s=10.0)
    r.update(1.0, now=0.0)   # episode starts
    r.update(0.1, now=5.0)   # drops below threshold → reset
    assert r.is_stressed is False
    # Restarting should not immediately fire.
    result = r.update(1.0, now=6.0)   # new episode start
    assert result is None
    result = r.update(1.0, now=11.0)  # half-window later, no event yet
    assert result is None
    result = r.update(1.0, now=17.0)  # first full window since restart
    assert result is not None


# ---------------------------------------------------------------------------
# reset() method
# ---------------------------------------------------------------------------

def test_reset_clears_episode():
    r = RegulationDetector(threshold=0.0, sustain_window_s=5.0)
    r.update(1.0, now=0.0)
    r.update(1.0, now=6.0)
    assert r.is_stressed
    r.reset()
    assert r.is_stressed is False


def test_reset_then_advisory_fires_afresh():
    r = RegulationDetector(threshold=0.0, sustain_window_s=5.0)
    r.update(1.0, now=0.0)
    r.update(1.0, now=6.0)   # first advisory
    r.reset()
    # New episode.
    r.update(1.0, now=7.0)
    result = r.update(1.0, now=13.0)   # one window from episode restart
    assert result is not None
    assert result["action"] == "reduce_rate"


# ---------------------------------------------------------------------------
# is_stressed property
# ---------------------------------------------------------------------------

def test_is_stressed_false_initially():
    r = RegulationDetector(threshold=0.5, sustain_window_s=10.0)
    assert r.is_stressed is False


def test_is_stressed_true_after_high_error():
    r = RegulationDetector(threshold=0.5, sustain_window_s=10.0)
    r.update(1.0, now=0.0)
    assert r.is_stressed is True


def test_is_stressed_clears_after_low_error():
    r = RegulationDetector(threshold=0.5, sustain_window_s=10.0)
    r.update(1.0, now=0.0)
    r.update(0.1, now=1.0)
    assert r.is_stressed is False
