# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import math
import statistics
from fractions import Fraction

import numpy as np
import pytest

from kaine.experiment.calibration_rules import (
    ALPHA_TEST,
    SNR_LADDER,
    CalibrationError,
    browne_ucl_factor,
    control_min_reports,
    detection_z,
    ensemble_average,
    interpolate_snr,
    minimum_effect,
    mser_truncation,
    planned_run_count,
    quintile_edges,
    runs_still_needed,
    sample_sd,
    sign_test_critical_count,
    sign_test_power,
    stable_run_count,
)


def test_stable_run_count_paper_values() -> None:
    assert stable_run_count() == 102
    # The loader compares records with this constant.
    from kaine.experiment.calibration_rules import N_EXACT

    assert N_EXACT == stable_run_count()
    assert sign_test_critical_count(102) == 60
    assert float(sign_test_power(102)) == pytest.approx(0.9197, abs=5e-5)
    assert stable_run_count(target=Fraction(4, 5)) == 76
    assert stable_run_count(q=Fraction(3, 4)) == 35


def test_power_saw_tooth() -> None:
    assert float(sign_test_power(98)) > 0.9
    assert float(sign_test_power(99)) < 0.9
    assert float(sign_test_power(100)) > 0.9
    first = next(n for n in range(1, 101) if sign_test_power(n) >= Fraction(9, 10))
    assert first == 93
    assert stable_run_count(target=Fraction(9, 10)) == 102


def test_attained_level_at_102() -> None:
    k = sign_test_critical_count(102)
    assert k == 60
    level = Fraction(1, 2**102) * sum(Fraction(math.comb(102, i)) for i in range(k, 103))
    assert level <= ALPHA_TEST
    level_59 = Fraction(1, 2**102) * sum(Fraction(math.comb(102, i)) for i in range(59, 103))
    assert level_59 > ALPHA_TEST


def test_sign_test_can_never_reject_for_small_n() -> None:
    assert sign_test_critical_count(4) == 5
    assert sign_test_power(4) == Fraction(0)
    assert sign_test_critical_count(0) == 1
    assert sign_test_power(0) == Fraction(0)


def test_planned_run_count() -> None:
    assert planned_run_count(102, 0, 30) == 102
    assert planned_run_count(102, 3, 33) == 113
    with pytest.raises(CalibrationError):
        planned_run_count(102, 1, 0)
    with pytest.raises(CalibrationError):
        planned_run_count(102, 5, 5)


def test_runs_still_needed() -> None:
    assert runs_still_needed({"matched": 100, "pooled": 103}, 102) == 2
    assert runs_still_needed({"matched": 102, "pooled": 110}, 102) == 0
    with pytest.raises(CalibrationError):
        runs_still_needed({}, 102)


def test_sample_sd() -> None:
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    assert sample_sd(values) == pytest.approx(statistics.stdev(values))
    with pytest.raises(CalibrationError):
        sample_sd([1.0])
    with pytest.raises(CalibrationError):
        sample_sd([1.0, float("nan")])


def test_minimum_effect() -> None:
    assert minimum_effect(0.4) == 0.2
    with pytest.raises(CalibrationError):
        minimum_effect(0.0)
    with pytest.raises(CalibrationError):
        minimum_effect(float("nan"))


def test_mser_constants() -> None:
    from kaine.experiment.calibration_rules import MSER_IGNORE_END, MSER_MIN_BATCHES
    assert MSER_IGNORE_END == 5
    assert MSER_MIN_BATCHES == 10


def test_mser_recovers_short_transient() -> None:
    rng = np.random.default_rng(7)
    t = np.arange(400)
    noise = rng.normal(0.0, 0.05, size=400)
    values = (1.0 + 3.0 * np.exp(-t / 15.0) + noise).tolist()
    result = mser_truncation(values, ignore_end=5)
    assert result.first_half is True
    assert result.long_enough is True
    assert 30 <= result.truncated_report <= 120
    degenerate = mser_truncation(values, ignore_end=1)
    assert degenerate.d_star == degenerate.n_batches - 1
    assert degenerate.first_half is False


def test_mser_degenerate_end_no_longer_wins() -> None:
    rng = np.random.default_rng(3)
    values = rng.normal(0.0, 1.0, size=200).tolist()
    # Make the last batch means equal by pinning the final 15 values.
    values[-15:] = [0.0] * 15
    n_batches = len(values) // 5
    degenerate = mser_truncation(values, ignore_end=1)
    assert degenerate.d_star >= n_batches - 3
    fixed = mser_truncation(values, ignore_end=5)
    assert fixed.d_star <= n_batches - 5
    assert fixed.first_half is True


def test_mser_fails_closed_on_long_transient() -> None:
    rng = np.random.default_rng(3)
    t = np.arange(200)
    noise = rng.normal(0.0, 1e-4, size=200)
    values = (np.exp(-t / 200.0) + noise).tolist()
    result = mser_truncation(values, ignore_end=5)
    assert result.first_half is False


def test_mser_short_series_is_not_long_enough() -> None:
    result = mser_truncation([1.0] * 45, ignore_end=5)
    assert result.n_batches == 9
    assert result.long_enough is False
    result = mser_truncation([1.0] * 50, ignore_end=5)
    assert result.n_batches == 10
    assert result.long_enough is True


def test_mser_rejects_invalid_inputs() -> None:
    with pytest.raises(CalibrationError):
        mser_truncation([1.0] * 20, ignore_end=0)
    with pytest.raises(CalibrationError):
        mser_truncation([1.0] * 20, ignore_end=5)
    with pytest.raises(CalibrationError):
        mser_truncation([1.0, 2.0, float("nan")], ignore_end=1)


def test_ensemble_average() -> None:
    run1 = list(range(1, 13))
    run2 = list(range(3, 14))
    expected = [2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 11.0, 12.0]
    assert ensemble_average([run1, run2]) == expected
    with pytest.raises(CalibrationError):
        ensemble_average([list(range(9)), list(range(11))])


def test_browne_and_detection_constants() -> None:
    assert browne_ucl_factor() == pytest.approx(1.2903, abs=1e-4)
    assert detection_z() == pytest.approx(1.6449, abs=1e-4)


def test_control_min_reports() -> None:
    value = control_min_reports(1000.0, 0.0001, 0.01, n_cal=30)
    expected = math.ceil(
        (2 * detection_z()) ** 2 * 1000.0 * 0.0001 / 0.01**2 * browne_ucl_factor()
    )
    assert value == expected
    assert value == pytest.approx(13964, abs=1)
    with pytest.raises(CalibrationError):
        control_min_reports(1000.0, 0.0001, 0.0, n_cal=30)


def test_interpolate_snr_brackets() -> None:
    ladder = [1 / 16, 1 / 4, 1.0, 4.0, 16.0, 64.0, 256.0]
    effects = [0.0, 0.001, 0.004, 0.01, 0.02, 0.03, 0.04]
    choice = interpolate_snr(ladder, effects, 0.007)
    # Target 0.007 lies between effects[2] (SNR 1.0) and effects[3] (SNR 4.0).
    expected = math.exp(
        math.log(1.0) + 0.5 * (math.log(4.0) - math.log(1.0))
    )
    assert choice.snr == pytest.approx(expected)
    assert choice.lower_index == 2
    assert choice.upper_index == 3


def test_interpolate_snr_fails_closed() -> None:
    ladder = [1 / 16, 1 / 4, 1.0, 4.0, 16.0, 64.0, 256.0]
    with pytest.raises(CalibrationError, match="largest SNR"):
        interpolate_snr(ladder, [0.0] * len(ladder), 0.001)
    with pytest.raises(CalibrationError, match="first rung"):
        interpolate_snr(ladder, [0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07], 0.005)
    with pytest.raises(CalibrationError, match="strictly increasing"):
        interpolate_snr([4.0, 1.0, 16.0], [0.0, 0.01, 0.02], 0.015)


def test_quintile_edges() -> None:
    values = list(range(1, 101))
    edges = quintile_edges(values)
    expected = np.quantile(values, [0.2, 0.4, 0.6, 0.8]).tolist()
    assert edges == pytest.approx(expected)
    with pytest.raises(CalibrationError):
        quintile_edges([1.0, 2.0, 3.0, 4.0])


def test_snr_ladder_constant() -> None:
    assert SNR_LADDER == (1 / 16, 1 / 4, 1.0, 4.0, 16.0, 64.0, 256.0)
