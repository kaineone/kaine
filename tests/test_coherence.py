# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for PLV computation and the bounded coherence factor (oscillatory-layer).

Uses no snnTorch — PLV and the coherence factor operate purely on phase
sequences, so these run unconditionally.
"""
from __future__ import annotations

import math
import random

import pytest

from kaine.workspace.coherence import (
    CoherenceScorer,
    mean_pairwise_plv,
    phase_locking_value,
)


def test_plv_locked_phases_near_one():
    # Two oscillators with a constant phase offset are perfectly locked.
    base = [i * 0.3 for i in range(20)]
    other = [p + 0.7 for p in base]
    assert phase_locking_value(base, other) >= 0.95


def test_plv_identical_phases_is_one():
    base = [i * 0.3 for i in range(20)]
    assert phase_locking_value(base, list(base)) == pytest.approx(1.0)


def test_plv_independent_phases_near_zero():
    rng = random.Random(1234)
    a = [rng.uniform(0, 2 * math.pi) for _ in range(400)]
    b = [rng.uniform(0, 2 * math.pi) for _ in range(400)]
    assert phase_locking_value(a, b) <= 0.2


def test_plv_within_unit_interval():
    rng = random.Random(7)
    for _ in range(10):
        a = [rng.uniform(0, 2 * math.pi) for _ in range(30)]
        b = [rng.uniform(0, 2 * math.pi) for _ in range(30)]
        plv = phase_locking_value(a, b)
        assert 0.0 <= plv <= 1.0


def test_plv_empty_is_zero():
    assert phase_locking_value([], []) == 0.0


def test_mean_pairwise_single_window_is_one():
    assert mean_pairwise_plv([[0.1, 0.2, 0.3]]) == 1.0


# --------------------------------------------------------------------------
# CoherenceScorer
# --------------------------------------------------------------------------

def _scorer(floor=0.8, ceiling=1.25, window=10):
    return CoherenceScorer(
        plv_window=window, coherence_floor=floor, coherence_ceiling=ceiling
    )


def test_min_window_enforced():
    with pytest.raises(ValueError):
        CoherenceScorer(plv_window=5, coherence_floor=0.8, coherence_ceiling=1.25)


def test_invalid_bounds_rejected():
    with pytest.raises(ValueError):
        CoherenceScorer(plv_window=10, coherence_floor=1.5, coherence_ceiling=1.0)


def test_factor_bounded_in_floor_ceiling():
    s = _scorer(floor=0.8, ceiling=1.25)
    for plv in (0.0, 0.25, 0.5, 0.75, 1.0):
        f = s.factor_from_plv(plv)
        assert 0.8 <= f <= 1.25
    assert s.factor_from_plv(0.0) == pytest.approx(0.8)
    assert s.factor_from_plv(1.0) == pytest.approx(1.25)


def test_factor_clamps_out_of_range_plv():
    s = _scorer(floor=0.8, ceiling=1.25)
    assert s.factor_from_plv(-5.0) == pytest.approx(0.8)
    assert s.factor_from_plv(5.0) == pytest.approx(1.25)


def test_locked_modules_get_higher_factor_than_desync():
    s = _scorer(window=12)
    # Feed phases over several ticks: a and b locked (same phase),
    # c random (desynchronized from both).
    rng = random.Random(3)
    for k in range(12):
        ph = k * 0.4
        s.observe({"a": ph, "b": ph, "c": rng.uniform(0, 2 * math.pi)})
    factor_locked = s.factor_for_source("a", ["a", "b"])
    factor_desync = s.factor_for_source("c", ["a", "b", "c"])
    assert factor_locked > factor_desync


def test_single_source_cohort_maps_from_full_plv():
    s = _scorer(floor=0.8, ceiling=1.25)
    s.observe({"a": 0.5})
    # Alone in the cohort → never penalised: maps from PLV 1.0 → ceiling.
    assert s.factor_for_source("a", ["a"]) == pytest.approx(1.25)
