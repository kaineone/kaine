# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Contrast at threshold for the on-arm broadcast access regression discontinuity.

Paper Appendix A.8, "Contrast at threshold": a broadcast is accessed exactly when
S*_k >= theta, so the contrast at threshold is a sharp regression discontinuity
with running variable S*_k and cutoff theta. For broadcast k and age bin a,
tau_{r,a} is the jump of the mean report gain at S*_k = theta, estimated with a
local-linear fit on each side and a local-quadratic bias correction (Calonico,
Cattaneo, and Titiunik 2014). The run contrast is the mean of the fitted bins,
and across runs the contrasts enter a one-sided sign test.

Only numpy and the Python standard library are required.
"""

from __future__ import annotations

import bisect
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from kaine.experiment.calibration_rules import SignTestResult, sign_test_verdict
from kaine.experiment.rd_robust import RDError, RDEstimate, rd_estimate, wls_condition


class ThresholdContrastError(ValueError):
    """A threshold-contrast input record was malformed."""


REPORT_TYPES = ("vision.report", "audition.perception", "interoception.report")
BROADCAST_EVENT_TYPE = "workspace.broadcast"

MIN_DISTINCT_PER_SIDE = 10  # Paper A.8, Table A1
MAX_CONDITION = 1e8  # Paper A.8, Table A1


def _is_number(value):
    """True for non-bool ints and floats (finiteness is checked separately)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_finite_number(value):
    """True for finite non-bool ints and floats."""
    return _is_number(value) and math.isfinite(value)


def broadcast_distances(records) -> dict[int, float]:
    """Map broadcast tick to S*_k - theta for broadcasts with candidates."""
    distances: dict[int, float] = {}
    for record in records:
        if record.get("event_type") != BROADCAST_EVENT_TYPE:
            continue
        tick = record.get("tick_index")
        if not isinstance(tick, int) or isinstance(tick, bool):
            raise ThresholdContrastError("broadcast tick_index must be an int")
        salience = record.get("salience_scores")
        if not isinstance(salience, dict):
            raise ThresholdContrastError("broadcast salience_scores must be a dict")
        if not salience:
            continue
        threshold = record.get("access_threshold")
        if not _is_finite_number(threshold):
            raise ThresholdContrastError(
                "broadcast access_threshold must be finite when it has candidates"
            )
        scores = list(salience.values())
        if not all(_is_finite_number(score) for score in scores):
            raise ThresholdContrastError("salience_scores must contain finite numbers")
        max_score = max(scores)
        distance = float(max_score - threshold)
        if tick in distances:
            raise ThresholdContrastError(f"broadcast tick {tick} is repeated")
        distances[tick] = distance
    return distances


@dataclass(frozen=True)
class FollowingReport:
    """One included report that follows a broadcast."""

    tick: int
    age_s: float
    gain: float


def following_reports(records, t_learn_s: float) -> list[FollowingReport]:
    """Return included reports in record order."""
    reports: list[FollowingReport] = []
    for record in records:
        if record.get("event_type") not in REPORT_TYPES:
            continue
        awake = record.get("awake")
        if not isinstance(awake, bool):
            raise ThresholdContrastError("report awake must be a bool")
        gain = record.get("context_gain")
        if not _is_finite_number(gain) or not awake:
            continue
        entity_time = record.get("entity_time_s")
        # A NaN would compare as after the learning period, so a report with a
        # defined gain must carry a finite time, as the calibration tool requires.
        if not _is_finite_number(entity_time):
            raise ThresholdContrastError("included report entity_time_s must be finite")
        if entity_time <= t_learn_s:
            continue
        tick = record.get("prediction_broadcast_tick")
        if not isinstance(tick, int) or isinstance(tick, bool):
            raise ThresholdContrastError(
                "included report prediction_broadcast_tick must be an int"
            )
        age = record.get("prediction_context_age_s")
        if not _is_number(age) or not math.isfinite(age) or age < 0:
            raise ThresholdContrastError(
                "included report prediction_context_age_s must be a finite non-negative number"
            )
        reports.append(
            FollowingReport(tick=int(tick), age_s=float(age), gain=float(gain))
        )
    return reports


def _mean(values: Sequence[float]) -> float:
    return float(np.mean(values))


def bandwidth_observations(records, t_learn_s) -> tuple[list[float], list[float]]:
    """Return (x, y) observations for MSE bandwidth selection, ordered by tick."""
    records_list = list(records)
    distances = broadcast_distances(records_list)
    reports = following_reports(records_list, t_learn_s)
    by_tick: dict[int, list[float]] = {}
    for report in reports:
        by_tick.setdefault(report.tick, []).append(report.gain)
    xs: list[float] = []
    ys: list[float] = []
    for tick in sorted(distances):
        gains = by_tick.get(tick, [])
        if not gains:
            continue
        xs.append(distances[tick])
        ys.append(_mean(gains))
    return xs, ys


def near_threshold_ages(records, t_learn_s, theta_band) -> list[float]:
    """Return ages of reports following broadcasts near the threshold."""
    records_list = list(records)
    distances = broadcast_distances(records_list)
    reports = following_reports(records_list, t_learn_s)
    return [
        report.age_s
        for report in reports
        if report.tick in distances and abs(distances[report.tick]) <= theta_band
    ]


def bin_observations(
    records, t_learn_s, age_edges
) -> dict[int, tuple[list[float], list[float]]]:
    """Return per-bin (x, y) observations keyed by bin index."""
    records_list = list(records)
    distances = broadcast_distances(records_list)
    reports = following_reports(records_list, t_learn_s)
    edges = list(age_edges)
    by_tick_bin: dict[tuple[int, int], list[float]] = {}
    for report in reports:
        if report.tick not in distances:
            continue
        bin_index = bisect.bisect_right(edges, report.age_s)
        by_tick_bin.setdefault((report.tick, bin_index), []).append(report.gain)
    bins: dict[int, tuple[list[float], list[float]]] = {}
    for (tick, bin_index), gains in by_tick_bin.items():
        xs, ys = bins.setdefault(bin_index, ([], []))
        xs.append(distances[tick])
        ys.append(_mean(gains))
    return bins


@dataclass(frozen=True)
class RunContrast:
    """Per-bin tau estimates and the run's overall contrast."""

    per_bin: dict[int, float | None]
    contrast: float | None


def side_fittable(x_side, theta_band, b_band) -> bool:
    """True when a side has enough distinct, well-conditioned units.

    Paper A.8: at least MIN_DISTINCT_PER_SIDE distinct scores with |x| < theta_band
    and with |x| < b_band, and the local-linear and local-quadratic weighted
    least-squares problems are well conditioned.
    """
    x_side = np.asarray(x_side, dtype=float)
    if x_side.ndim != 1:
        raise ThresholdContrastError("x_side must be one-dimensional")
    near_theta = x_side[np.abs(x_side) < theta_band]
    near_b = x_side[np.abs(x_side) < b_band]
    if np.unique(near_theta).size < MIN_DISTINCT_PER_SIDE:
        return False
    if np.unique(near_b).size < MIN_DISTINCT_PER_SIDE:
        return False
    if wls_condition(x_side, theta_band, 1) > MAX_CONDITION:
        return False
    return wls_condition(x_side, b_band, 2) <= MAX_CONDITION


def bin_fittable(xs, theta_band, b_band) -> bool:
    """True when both sides of the cutoff have fittable units."""
    xs = np.asarray(xs, dtype=float)
    return side_fittable(xs[xs >= 0], theta_band, b_band) and side_fittable(
        xs[xs < 0], theta_band, b_band
    )


def run_contrast(records, t_learn_s, theta_band, b_band, age_edges) -> RunContrast:
    """Estimate tau_{r,a} per bin and the mean contrast across fitted bins."""
    bins = bin_observations(records, t_learn_s, age_edges)
    n_bins = len(list(age_edges)) + 1
    per_bin: dict[int, float | None] = {}
    defined: list[float] = []
    for a in range(n_bins):
        xs, ys = bins.get(a, ([], []))
        if not xs or not bin_fittable(xs, theta_band, b_band):
            per_bin[a] = None
            continue
        try:
            # Only the point estimate is used, so the cheaper plug-in variance is enough.
            estimate = rd_estimate(xs, ys, theta_band, b_band, vce="hc0")
            per_bin[a] = estimate.tau_bias_corrected
            defined.append(estimate.tau_bias_corrected)
        except RDError:
            per_bin[a] = None
    if not defined:
        return RunContrast(per_bin=per_bin, contrast=None)
    return RunContrast(per_bin=per_bin, contrast=float(np.mean(defined)))


def pooled_intervals(
    runs: Mapping[str, Iterable[Mapping]],
    t_learn_s,
    theta_band,
    b_band,
    age_edges,
    level=0.95,
) -> dict[int, RDEstimate | None]:
    """Return a robust RD estimate per bin pooled over runs, clustered by run."""
    run_bins: dict[str, dict[int, tuple[list[float], list[float]]]] = {}
    for run_id, records in runs.items():
        run_bins[run_id] = bin_observations(records, t_learn_s, age_edges)
    n_bins = len(list(age_edges)) + 1
    results: dict[int, RDEstimate | None] = {}
    for a in range(n_bins):
        xs: list[float] = []
        ys: list[float] = []
        labels: list[str] = []
        for run_id, bins in run_bins.items():
            run_xs, run_ys = bins.get(a, ([], []))
            xs.extend(run_xs)
            ys.extend(run_ys)
            labels.extend([run_id] * len(run_xs))
        if not xs or not bin_fittable(xs, theta_band, b_band):
            results[a] = None
            continue
        try:
            results[a] = rd_estimate(
                xs, ys, theta_band, b_band, vce="hc0", cluster=labels, level=level
            )
        except RDError:
            results[a] = None
    return results


def threshold_verdict(contrasts, min_effect) -> SignTestResult:
    """One-sided sign-test verdict for run contrasts minus a minimum effect."""
    return sign_test_verdict(contrasts, min_effect)


__all__ = [
    "ThresholdContrastError",
    "REPORT_TYPES",
    "MIN_DISTINCT_PER_SIDE",
    "MAX_CONDITION",
    "FollowingReport",
    "RunContrast",
    "broadcast_distances",
    "following_reports",
    "bandwidth_observations",
    "near_threshold_ages",
    "bin_observations",
    "side_fittable",
    "bin_fittable",
    "run_contrast",
    "pooled_intervals",
    "threshold_verdict",
]
