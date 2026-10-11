# SPDX-License-Identifier: LicenseRef-CAL-0.4
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
    # a and b advance together so every sample after the first is fresh and
    # the two series stay perfectly locked. c advances independently.
    for k in range(12):
        ph = 0.3 * k
        s.observe({"a": ph, "b": ph, "c": (1.7 * k * k) % (2 * math.pi)})
    factor_locked = s.factor_for_source("a", ["a", "b"])
    factor_desync = s.factor_for_source("c", ["a", "b", "c"])
    assert factor_locked > factor_desync


def test_single_source_cohort_gets_exact_unit_factor():
    s = _scorer(floor=0.8, ceiling=1.25)
    s.observe({"a": 0.5})
    # A source alone in the cohort returns the neutral unit-gain factor, not
    # the ceiling.
    assert s.factor_for_source("a", ["a"]) == pytest.approx(1.0)
    assert s.factor_for_source("a", ["a"]) != pytest.approx(1.25)


def test_constant_phases_yield_neutral_factor_not_ceiling():
    # Frozen phases are never fresh, so the pair has no jointly fresh
    # observations and must fall back to the neutral PLV (factor 1.0).
    s = _scorer(window=12)
    for _ in range(12):
        s.observe({"a": 0.5, "b": 0.5})
    assert s.factor(["a", "b"]) == pytest.approx(1.0)
    assert s.factor(["a", "b"]) != pytest.approx(1.25)
    assert s.factor_for_source("a", ["a", "b"]) == pytest.approx(1.0)


def test_neutral_plv_maps_to_unit_factor():
    s = _scorer(floor=0.8, ceiling=1.25)
    assert s.factor_from_plv(s.neutral_plv()) == pytest.approx(1.0)


def test_pair_with_two_fresh_samples_uses_neutral_plv():
    # Only two jointly fresh observations -> below MIN_FRESH_SAMPLES -> the
    # pair must contribute neutral_plv, giving factor 1.0 rather than 1.25.
    s = _scorer(window=10)
    s.observe({"a": 0.0, "b": 0.0})
    s.observe({"a": 0.0, "b": 0.0})
    s.observe({"a": 1.0, "b": 1.0})
    s.observe({"a": 2.0, "b": 2.0})
    f = s.factor_for_source("a", ["a", "b"])
    assert f == pytest.approx(1.0)
    assert f != pytest.approx(1.25)


def test_first_sample_is_not_fresh():
    s = _scorer()
    s.observe({"a": 0.5})
    assert s._buffers["a"][0][0] == pytest.approx(0.5)
    assert s._buffers["a"][0][1] is False

    s.observe({"a": 0.5})
    assert s._buffers["a"][1][1] is False

    s.observe({"a": 0.6})
    assert s._buffers["a"][2][1] is True


def test_null_control_floor_equals_ceiling():
    # When coherence_floor == coherence_ceiling, every factor must equal that
    # value, including a lone source and a perfectly coherent frozen pair.
    s = CoherenceScorer(plv_window=10, coherence_floor=0.9, coherence_ceiling=0.9)
    assert s.factor_for_source("a", ["a"]) == pytest.approx(0.9)

    for value in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0):
        s.observe({"a": value, "b": value})
    assert s.factor_for_source("a", ["a", "b"]) == pytest.approx(0.9)
