# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for the pure gestation marker functions."""

from __future__ import annotations

import numpy as np
import pytest

from kaine.cycle.gestation import (
    hrv_cv,
    phase_locking_value,
    recovery_seconds,
    self_sustains,
)


def test_plv_identical_phases():
    phases = [0.0, np.pi / 2, np.pi, 3 * np.pi / 2]
    assert phase_locking_value(phases, phases) == pytest.approx(1.0)


def test_plv_independent_uniform_phases():
    rng = np.random.default_rng(0)
    a = rng.uniform(0, 2 * np.pi, size=10_000)
    b = rng.uniform(0, 2 * np.pi, size=10_000)
    plv = phase_locking_value(list(a), list(b))
    assert plv is not None
    assert plv < 0.05


def test_plv_different_lengths():
    assert phase_locking_value([0.0, 1.0], [0.0]) is None


def test_plv_too_few_samples():
    assert phase_locking_value([0.0], [0.0]) is None


def test_self_sustains_true_boundary():
    assert self_sustains([1.0, 1.0], [0.5, 0.5]) is True


def test_self_sustains_false_below_half():
    assert self_sustains([1.0, 1.0], [0.49, 0.49]) is False


def test_self_sustains_zero_withdrawn():
    assert self_sustains([1.0, 1.0], [0.0, 0.0]) is False


def test_self_sustains_empty_none():
    assert self_sustains([], [1.0]) is None
    assert self_sustains([1.0], []) is None


def test_hrv_cv_regular_sawtooth():
    sample_hz = 100.0
    n_wraps = 10
    period = 1.0
    total_time = n_wraps * period
    times = np.linspace(0, total_time, int(total_time * sample_hz) + 1)
    phases = (2 * np.pi * (times % period)) / period
    cv = hrv_cv(list(times), list(phases))
    assert cv == pytest.approx(0.0, abs=1e-9)


def test_hrv_cv_jittered_intervals():
    rng = np.random.default_rng(1)
    intervals = rng.normal(1.0, 0.1, size=20)
    wrap_times = np.cumsum(intervals)
    times = []
    phases = []
    for wt in wrap_times:
        times.extend([wt - 0.05, wt + 0.05])
        phases.extend([3.0, -3.0])
    cv = hrv_cv(times, phases)
    # N wraps bound N-1 intervals; the first generated interval precedes the
    # first wrap and is not observable.
    observed = np.diff(wrap_times)
    expected = float(np.std(observed, ddof=0) / np.mean(observed))
    assert cv == pytest.approx(expected, rel=1e-2)


def test_hrv_cv_insufficient_intervals():
    times = [0.0, 0.5, 1.0]
    phases = [0.0, 3.0, -3.0]
    assert hrv_cv(times, phases) is None


def test_recovery_seconds_synthetic():
    # Baseline = 1.0, perturbation lasts 5 s, then settles.
    times = list(np.arange(0, 25, 1.0))
    values = [1.0] * 10 + [3.0] * 6 + [1.0] * 9
    result = recovery_seconds(
        times,
        values,
        perturbation_start=10.0,
        perturbation_end=15.0,
        tolerance=0.25,
        cap=300.0,
    )
    # At t=19 the last 5 s (t=14..19) hold [3, 3, 1, 1, 1, 1]: median 1 <= 1.25.
    # At t=18 they hold [3, 3, 3, 1, 1, 1]: median 2. So recovery is 4 s.
    assert result == pytest.approx(4.0)


def test_recovery_window_never_reaches_before_a_short_perturbation():
    # A 2 s perturbation: a plain [t-5, t] window at its end would include 3 s
    # of pre-perturbation baseline and report instant recovery.
    times = list(np.arange(0, 30, 1.0))
    values = [1.0] * 10 + [3.0] * 8 + [1.0] * 12
    result = recovery_seconds(
        times, values, perturbation_start=10.0, perturbation_end=12.0,
        tolerance=0.25, cap=300.0,
    )
    assert result is not None and result > 0.0


def test_recovery_seconds_cap():
    # Data must reach perturbation_end + cap (310) for "never recovered" to be known.
    times = list(np.arange(0, 311, 1.0))
    values = [1.0] * 10 + [3.0] * 301
    result = recovery_seconds(
        times,
        values,
        perturbation_start=10.0,
        perturbation_end=10.0,
        tolerance=0.25,
        cap=300.0,
    )
    assert result == pytest.approx(300.0)


def test_recovery_seconds_data_ends_early():
    times = list(np.arange(0, 100, 1.0))
    values = [1.0] * 10 + [3.0] * 90
    result = recovery_seconds(
        times,
        values,
        perturbation_start=10.0,
        perturbation_end=10.0,
        tolerance=0.25,
        cap=300.0,
    )
    assert result is None


def test_recovery_seconds_no_baseline():
    times = list(np.arange(10, 20, 1.0))
    values = [1.0] * 10
    result = recovery_seconds(
        times,
        values,
        perturbation_start=20.0,
        perturbation_end=20.0,
        tolerance=0.25,
        cap=300.0,
    )
    assert result is None
