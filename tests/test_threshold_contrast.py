# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for threshold_contrast.py on synthetic logs with a known discontinuity."""

from __future__ import annotations

import numpy as np
import pytest

from kaine.experiment.calibration_rules import Outcome
from kaine.experiment.rd_robust import rd_estimate, wls_condition
from kaine.experiment.threshold_contrast import (
    ThresholdContrastError,
    bin_observations,
    broadcast_distances,
    following_reports,
    near_threshold_ages,
    pooled_intervals,
    run_contrast,
    side_fittable,
    threshold_verdict,
)

REPORT_TYPES = ("vision.report", "audition.perception", "interoception.report")
T_LEARN_S = 50.0
THETA_BAND = 0.25
B_BAND = 0.3
AGE_EDGES = [1.0, 2.0]


def make_run(
    n: int = 120,
    *,
    seed: int = 0,
    alpha: float = 0.0,
    slope: float = 1.0,
    jump: float = 0.0,
    noise_sd: float = 0.0,
    ages=None,
) -> list[dict]:
    """Build one synthetic run's research-event records."""
    records: list[dict] = []
    rng = np.random.default_rng(seed)
    for k in range(1, n + 1):
        d = 0.6 * ((k * 0.6180339887) % 1.0) - 0.3
        s_star = 0.4 + d
        records.append(
            {
                "event_type": "workspace.broadcast",
                "tick_index": k,
                "salience_scores": {
                    "a": float(s_star),
                    "b": float(s_star - 0.05),
                },
                "access_threshold": 0.4,
            }
        )
        gain = alpha + slope * d + jump * (d >= 0)
        if noise_sd:
            gain += rng.normal(0, noise_sd)
        if ages is None:
            report_ages = [0.5, 1.5, 2.5]
        else:
            report_ages = ages(k, d)
        for idx, report_type in enumerate(REPORT_TYPES):
            records.append(
                {
                    "event_type": report_type,
                    "awake": True,
                    "context_gain": float(gain),
                    "entity_time_s": 100 + k,
                    "prediction_broadcast_tick": k,
                    "prediction_context_age_s": float(report_ages[idx]),
                }
            )
    return records


def test_run_contrast_linear_jump_is_exact():
    records = make_run(jump=0.2)
    result = run_contrast(records, T_LEARN_S, THETA_BAND, B_BAND, AGE_EDGES)
    for tau in result.per_bin.values():
        assert tau is not None
        assert abs(tau - 0.2) < 1e-10
    assert result.contrast is not None
    assert abs(result.contrast - 0.2) < 1e-10


def test_run_contrast_zero_jump_is_zero():
    records = make_run(jump=0.0)
    result = run_contrast(records, T_LEARN_S, THETA_BAND, B_BAND, AGE_EDGES)
    for tau in result.per_bin.values():
        assert tau is not None
        assert abs(tau) < 1e-10
    assert result.contrast is not None
    assert abs(result.contrast) < 1e-10


def test_excluded_reports_do_not_change_contrast():
    records = make_run(jump=0.2)
    for k in (1, 2, 3):
        records.append(
            {
                "event_type": "vision.report",
                "awake": False,
                "context_gain": 1e9,
                "entity_time_s": 100 + k,
                "prediction_broadcast_tick": k,
                "prediction_context_age_s": 0.5,
            }
        )
        records.append(
            {
                "event_type": "audition.perception",
                "awake": True,
                "context_gain": 1e9,
                "entity_time_s": 10,
                "prediction_broadcast_tick": k,
                "prediction_context_age_s": 1.5,
            }
        )
        records.append(
            {
                "event_type": "interoception.report",
                "awake": True,
                "context_gain": float("nan"),
                "entity_time_s": 100 + k,
                "prediction_broadcast_tick": k,
                "prediction_context_age_s": 2.5,
            }
        )
    result = run_contrast(records, T_LEARN_S, THETA_BAND, B_BAND, AGE_EDGES)
    assert result.contrast is not None
    assert abs(result.contrast - 0.2) < 1e-10


def test_near_threshold_ages():
    records = make_run()
    ages = near_threshold_ages(records, T_LEARN_S, 0.25)
    expected: list[float] = []
    for k in range(1, 121):
        d = 0.6 * ((k * 0.6180339887) % 1.0) - 0.3
        if abs(d) <= 0.25:
            expected.extend([0.5, 1.5, 2.5])
    assert ages == expected


def test_run_contrast_averages_only_fitted_bins():
    def ages_by_side(k, d):
        if d < 0:
            return [0.5, 1.5, 1.5]
        return [1.5, 2.5, 2.5]

    records = make_run(jump=0.2, ages=ages_by_side)
    result = run_contrast(records, T_LEARN_S, THETA_BAND, B_BAND, AGE_EDGES)
    assert result.per_bin[0] is None
    assert result.per_bin[1] is not None
    assert abs(result.per_bin[1] - 0.2) < 1e-10
    assert result.per_bin[2] is None
    assert result.contrast is not None
    assert abs(result.contrast - result.per_bin[1]) < 1e-12


def test_pooled_intervals_clustered_standard_error():
    # Thirty runs: a clustered variance with very few clusters is biased far
    # downward, and the live test has about a hundred runs.
    runs = {f"run_{r}": make_run(seed=r, jump=0.2, noise_sd=0.1) for r in range(30)}
    results = pooled_intervals(runs, T_LEARN_S, THETA_BAND, B_BAND, AGE_EDGES)
    for a, estimate in results.items():
        assert estimate is not None
        # A 95 percent interval misses one bin in twenty, so check the estimate
        # within four standard errors instead of inside the interval.
        assert abs(estimate.tau_bias_corrected - 0.2) <= 4 * estimate.se_robust
        assert estimate.ci_robust[0] < estimate.tau_bias_corrected < estimate.ci_robust[1]
        xs, ys, labels = [], [], []
        for run_id, records in runs.items():
            bins = bin_observations(records, T_LEARN_S, AGE_EDGES)
            run_xs, run_ys = bins.get(a, ([], []))
            xs.extend(run_xs)
            ys.extend(run_ys)
            labels.extend([run_id] * len(run_xs))
        direct = rd_estimate(xs, ys, THETA_BAND, B_BAND, vce="hc0", cluster=labels)
        assert abs(direct.se_robust - estimate.se_robust) < 1e-12


def test_threshold_verdict_win():
    result = threshold_verdict([0.3] * 10, 0.1)
    assert result.outcome == Outcome.WIN


def test_malformed_repeated_broadcast_tick():
    records = make_run(n=5)
    records.insert(
        0,
        {
            "event_type": "workspace.broadcast",
            "tick_index": 1,
            "salience_scores": {"a": 0.5},
            "access_threshold": 0.4,
        },
    )
    with pytest.raises(ThresholdContrastError):
        broadcast_distances(records)


def test_malformed_non_finite_score():
    records = make_run(n=5)
    for record in records:
        if record.get("event_type") == "workspace.broadcast":
            record["salience_scores"] = {"a": float("inf")}
            break
    with pytest.raises(ThresholdContrastError):
        broadcast_distances(records)


def test_malformed_missing_prediction_tick():
    records = make_run(n=5)
    for record in records:
        if record.get("event_type") == "vision.report":
            del record["prediction_broadcast_tick"]
            break
    with pytest.raises(ThresholdContrastError):
        following_reports(records, T_LEARN_S)



def _make_fittable_run(n_left: int, n_right: int) -> list[dict]:
    """Return records where one side has a controlled distinct score count."""
    records: list[dict] = []
    # Scores spread evenly over each side of the threshold, all within both
    # bandwidths, so only their number decides whether a side can be fitted.
    for k in range(1, n_left + 1):
        d = -(0.01 + 0.19 * (k - 1) / max(n_left - 1, 1))
        records.append(
            {
                "event_type": "workspace.broadcast",
                "tick_index": k,
                "salience_scores": {"a": float(0.4 + d), "b": float(0.35 + d)},
                "access_threshold": 0.4,
            }
        )
        gain = 0.1 if d < 0 else 0.3
        for report_type in REPORT_TYPES:
            records.append(
                {
                    "event_type": report_type,
                    "awake": True,
                    "context_gain": float(gain),
                    "entity_time_s": 100 + k,
                    "prediction_broadcast_tick": k,
                    "prediction_context_age_s": 1.5,
                }
            )
    for k in range(1, n_right + 1):
        d = 0.01 + 0.19 * (k - 1) / max(n_right - 1, 1)
        tick = 1000 + k
        records.append(
            {
                "event_type": "workspace.broadcast",
                "tick_index": tick,
                "salience_scores": {"a": float(0.4 + d), "b": float(0.35 + d)},
                "access_threshold": 0.4,
            }
        )
        gain = 0.1 if d < 0 else 0.3
        for report_type in REPORT_TYPES:
            records.append(
                {
                    "event_type": report_type,
                    "awake": True,
                    "context_gain": float(gain),
                    "entity_time_s": 100 + tick,
                    "prediction_broadcast_tick": tick,
                    "prediction_context_age_s": 1.5,
                }
            )
    return records


def test_bin_not_fitted_with_nine_distinct_scores_on_a_side():
    records = _make_fittable_run(n_left=20, n_right=9)
    result = run_contrast(records, T_LEARN_S, THETA_BAND, B_BAND, AGE_EDGES)
    # Every report has age 1.5, so only bin 1 has observations.
    assert result.per_bin[1] is None
    assert result.contrast is None


def test_bin_fitted_with_ten_distinct_scores_on_a_side():
    records = _make_fittable_run(n_left=20, n_right=10)
    result = run_contrast(records, T_LEARN_S, THETA_BAND, B_BAND, AGE_EDGES)
    # Every report has age 1.5, so only bin 1 has observations; the gain is a
    # step of 0.2 at the threshold.
    assert result.per_bin[1] == pytest.approx(0.2, abs=1e-10)
    assert result.contrast == pytest.approx(0.2, abs=1e-10)


def test_side_not_fittable_when_scores_are_nearly_coincident():
    x_side = 0.1 + np.linspace(0, 1e-9, 10)
    assert np.unique(x_side).size == 10
    assert wls_condition(x_side, B_BAND, 2) > 1e8
    assert not side_fittable(x_side, THETA_BAND, B_BAND)


@pytest.mark.parametrize("bad_time", [float("nan"), float("inf"), None])
def test_report_with_non_finite_time_raises(bad_time):
    records = make_run(jump=0.2)
    records.append(
        {
            "event_type": "vision.report",
            "awake": True,
            "context_gain": 0.1,
            "entity_time_s": bad_time,
            "prediction_broadcast_tick": 1,
            "prediction_context_age_s": 0.5,
        }
    )
    with pytest.raises(ThresholdContrastError):
        following_reports(records, T_LEARN_S)
