# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Fixed rules that derive the planned test's settings from the pilot runs.

Paper Appendix A.8, "Settings from the pilot runs". Pure functions; the calibration tool
``kaine.experiment.calibrate`` applies them to the pilot logs.

Citations:
- Norman, Sloan and Wyrwich (2003); Lakens (2017) for the minimum-effect multiple.
- Lancaster, Dodd and Williamson (2004) for the number of paired pilot runs.
- Cohen (1988) for the medium effect q = 0.65 used in the sign test.
- Currie (1968) for the positive-control false and missed detection probabilities.
- Browne (1995) for the one-sided upper confidence limit on the pilot variance.
- White (1997); Hoad, Robinson and Davies (2010) for MSER-5.
- Cochran (1968) for quintile bins.
- Chernick and Liu (2002) for the saw-toothed power of exact binomial tests.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction

import numpy as np


class CalibrationError(ValueError):
    """A calibration rule could not be applied."""


C_EFF = 0.5  # minimum-effect multiple: half a standard deviation (Norman, Sloan and Wyrwich 2003; Lakens 2017)
N_CAL = 30  # paired pilot runs (Lancaster, Dodd and Williamson 2004)
Q_POW = Fraction(13, 20)  # 0.65, Cohen's (1988) medium effect for the sign test
TARGET_POWER = Fraction(9, 10)  # power of each control's WIN test
ALPHA_TEST = Fraction(1, 20)  # level of each one-sided sign test
ALPHA_PC = 0.05  # positive control: false detection probability (Currie 1968)
BETA_PC = 0.05  # positive control: missed detection probability (Currie 1968)
UCL_LEVEL = 0.8  # Browne's (1995) one-sided upper confidence limit on the pilot variance
MSER_BATCH = 5  # batch size of MSER-5 (White 1997; Hoad, Robinson and Davies 2010)
N_BINS = 5  # quintile bins (Cochran 1968)
SNR_LADDER = tuple(4.0**k for k in range(-2, 5))  # (1/16, 1/4, 1, 4, 16, 64, 256)

POWER_HORIZON = 1000
# The paper asks for the smallest n with power at least the target for every larger n.
# The search checks every n up to this horizon, which is far past the point where the
# binomial power settles (at q = 0.65 the minimum of the power over 102 <= n <= 600 is 0.9075).


def sign_test_critical_count(n: int, alpha: Fraction = ALPHA_TEST) -> int:
    """Return k_n, the critical count for a one-sided sign test.

    k_n is the smallest k in 0..n with 2^-n * sum_{i=k}^{n} C(n, i) <= alpha, computed
    with exact integer arithmetic:
    tail_count * alpha.denominator <= alpha.numerator * 2**n.

    When no k in 0..n qualifies (for example n < 5 at alpha = 0.05), the function
    returns n + 1, meaning the test can never reject.

    Raises:
        CalibrationError: if n is negative.

    Source: paper Appendix A.8, one-sided sign-test calibration.
    """
    if n < 0:
        raise CalibrationError("sign test critical count: n must be non-negative")
    threshold_num = alpha.numerator * (2**n)
    threshold_den = alpha.denominator
    tail = 0
    # Walk downward; the last k that keeps the tail within the bound is the answer.
    for k in range(n, -1, -1):
        tail += math.comb(n, k)
        if tail * threshold_den > threshold_num:
            return k + 1
    return 0


def sign_test_power(n: int, q: Fraction = Q_POW, alpha: Fraction = ALPHA_TEST) -> Fraction:
    """Return pi(n), the exact power of the one-sided sign test.

    pi(n) = sum_{i=k_n}^{n} C(n, i) q^i (1 - q)^(n - i), computed as a Fraction.
    With q = a/b, the numerator is sum C(n, i) a^i (b-a)^(n-i) and the denominator is b^n.
    Returns Fraction(0) when k_n = n + 1.

    Raises:
        CalibrationError: if q is not strictly between 0 and 1, or if n is negative.

    Source: paper Appendix A.8, sign-test power.
    """
    if n < 0:
        raise CalibrationError("sign test power: n must be non-negative")
    if not isinstance(q, Fraction) or not (0 < q < 1):
        raise CalibrationError("sign test power: q must be a Fraction strictly between 0 and 1")
    k = sign_test_critical_count(n, alpha)
    if k > n:
        return Fraction(0)
    a = q.numerator
    b = q.denominator
    term = math.comb(n, k) * pow(a, k) * pow(b - a, n - k)
    total = term
    for i in range(k, n):
        term = term * (n - i) * a // ((i + 1) * (b - a))
        total += term
    return Fraction(total, pow(b, n))


def _binomial_power_for_n(
    n: int,
    alpha: Fraction,
    a: int,
    b: int,
    pa: list[int],
    pb: list[int],
    bd: list[int],
) -> Fraction:
    """Exact power for one n, reused by stable_run_count.

    Computes k_n and the binomial tail probability in one pass without calling
    math.comb repeatedly.
    """
    threshold_num = alpha.numerator * (1 << n)
    threshold_den = alpha.denominator
    tail = 0
    binom = 1
    k = n + 1
    # Walk downward; the last qualifying k is candidate + 1.
    for candidate in range(n, -1, -1):
        if candidate < n:
            binom = binom * (candidate + 1) // (n - candidate)
        tail += binom
        if tail * threshold_den > threshold_num:
            k = candidate + 1
            break
    else:
        k = 0
    if k > n:
        return Fraction(0)
    # binom currently equals C(n, k - 1); advance it to C(n, k) for the first term.
    if k:
        binom = binom * (n - k + 1) // k
    term = binom * pa[k] * pb[n - k]
    total = term
    for i in range(k, n):
        term = term * (n - i) * a // ((i + 1) * (b - a))
        total += term
    return Fraction(total, bd[n])


def stable_run_count(
    q: Fraction = Q_POW,
    target: Fraction = TARGET_POWER,
    alpha: Fraction = ALPHA_TEST,
    horizon: int = POWER_HORIZON,
) -> int:
    """Return n_exact, the stable run count for the sign test.

    n_exact is the smallest n such that sign_test_power(m) >= target for every m with
    n <= m <= horizon (Chernick and Liu 2002, the saw-toothed power of exact binomial
    tests). The search computes the power for every n from 1 to horizon once, then scans
    backward from horizon to find the last n whose power is below target; the answer is
    that n + 1.

    Raises:
        CalibrationError: if q or target are invalid, if horizon is not a positive integer,
            or if power at the horizon is below the target.

    Source: paper Appendix A.8, stable run-count search.
    """
    if not isinstance(q, Fraction) or not (0 < q < 1):
        raise CalibrationError("stable run count: q must be a Fraction strictly between 0 and 1")
    if not isinstance(target, Fraction) or not (0 < target <= 1):
        raise CalibrationError(
            "stable run count: target power must be a Fraction between 0 and 1"
        )
    if not isinstance(horizon, int) or horizon < 1:
        raise CalibrationError("stable run count: horizon must be a positive integer")
    a = q.numerator
    b = q.denominator
    pa = [1] * (horizon + 1)
    pb = [1] * (horizon + 1)
    bd = [1] * (horizon + 1)
    for i in range(1, horizon + 1):
        pa[i] = pa[i - 1] * a
        pb[i] = pb[i - 1] * (b - a)
        bd[i] = bd[i - 1] * b
    last_below = 0
    for n in range(1, horizon + 1):
        power = _binomial_power_for_n(n, alpha, a, b, pa, pb, bd)
        if power < target:
            last_below = n
    if last_below == horizon:
        raise CalibrationError(
            f"stable run count: power at horizon {horizon} is below target {float(target)}"
        )
    return last_below + 1


def planned_run_count(n_exact: int, n_not_exercised: int, n_attempted: int) -> int:
    """Return n_run = ceil(n_exact / (1 - r_NE)) with r_NE = n_not_exercised / n_attempted.

    The calculation is exact: r is a Fraction and the ceiling is computed with integer
    arithmetic.

    Raises:
        CalibrationError: if n_attempted < 1, n_not_exercised < 0, or
            n_not_exercised >= n_attempted.

    Source: paper Appendix A.8, attrition adjustment.
    """
    if n_attempted < 1:
        raise CalibrationError("planned run count: n_attempted must be at least 1")
    if n_not_exercised < 0:
        raise CalibrationError("planned run count: n_not_exercised must be non-negative")
    if n_not_exercised >= n_attempted:
        raise CalibrationError("planned run count: n_not_exercised must be less than n_attempted")
    r = Fraction(n_not_exercised, n_attempted)
    value = Fraction(n_exact) / (Fraction(1, 1) - r)
    return -((-value.numerator) // value.denominator)


def runs_still_needed(entered: Mapping[str, int], n_exact: int) -> int:
    """Return the attrition rule's remaining runs.

    Runs are added until at least n_exact runs enter each control's test. The result is
    max(0, n_exact - min(entered.values())).

    Raises:
        CalibrationError: if entered is empty or any count is negative.

    Source: paper Appendix A.8, attrition rule.
    """
    if not entered:
        raise CalibrationError("runs still needed: entered must not be empty")
    for name, count in entered.items():
        if count < 0:
            raise CalibrationError(f"runs still needed: count for {name} is negative")
    return max(0, n_exact - min(entered.values()))


def sample_sd(values: Sequence[float]) -> float:
    """Return the sample standard deviation with divisor n - 1.

    Raises:
        CalibrationError: when there are fewer than 2 values or any value is not finite.

    Source: paper Appendix A.8, pilot standard deviation.
    """
    n = len(values)
    if n < 2:
        raise CalibrationError("sample sd: need at least 2 values")
    for v in values:
        if not math.isfinite(v):
            raise CalibrationError("sample sd: all values must be finite")
    mean = sum(values) / n
    sq = sum((v - mean) ** 2 for v in values)
    return math.sqrt(sq / (n - 1))


def minimum_effect(s_cal: float) -> float:
    """Return the minimum effect theta = C_EFF * s_cal.

    Raises:
        CalibrationError: if s_cal is not finite or is not positive.

    Source: Norman, Sloan and Wyrwich (2003); Lakens (2017).
    """
    if not math.isfinite(s_cal) or s_cal <= 0:
        raise CalibrationError("minimum effect: s_cal must be finite and positive")
    return C_EFF * s_cal


def ensemble_average(series: Sequence[Sequence[float]], batch: int = MSER_BATCH) -> list[float]:
    """Return the replication average of Welch's procedure.

    The mean across runs is computed at each report number, truncated to the smallest
    length any run reached.

    Raises:
        CalibrationError: if there is no run, if any value is not finite, or if the
            shortest series has fewer than 2 * batch values.

    Source: paper Appendix A.8, ensemble average for MSER-5.
    """
    if not series:
        raise CalibrationError("ensemble average: need at least one run")
    shortest = min(len(run) for run in series)
    if shortest < 2 * batch:
        raise CalibrationError("ensemble average: shortest run is too short for the batch size")
    for run in series:
        for v in run:
            if not math.isfinite(v):
                raise CalibrationError("ensemble average: all values must be finite")
    n = len(series)
    return [sum(run[i] for run in series) / n for i in range(shortest)]


@dataclass(frozen=True)
class MserResult:
    """Outcome of the MSER-5 truncation search."""

    n_values: int  # values used (whole batches only)
    n_batches: int  # b
    d_star: int  # truncation point in batches
    truncated_report: int  # batch * d_star, the last report removed (0 when nothing is removed)
    first_half: bool  # True when 2 * d_star <= n_batches


def mser_truncation(
    values: Sequence[float],
    *,
    ignore_end: int,
    batch: int = MSER_BATCH,
) -> MserResult:
    """Return the MSER-5 truncation point.

    MSER-5 (White 1997, with the batching of Hoad, Robinson and Davies 2010) groups the
    values in consecutive batches of ``batch``, dropping an incomplete last batch, giving
    batch means Y_1..Y_b. For each d in the search range, it computes

        MSER(d) = (1 / (b - d)^2) * sum_{i=d+1}^{b} (Y_i - Ybar_d)^2,

    and takes d* as the d with the smallest value (the smallest d on a tie).

    The search range is 0 <= d < b - ignore_end. ``ignore_end`` is keyword-only with no
    default: the paper writes the range as 0 <= d < b, but at d = b - 1 the statistic is
    0 for every series, so the literal range always returns the last batch. The caller
    must choose how many final batches to leave out of the search, and passing 0
    reproduces the literal range.

    Raises:
        CalibrationError: if ignore_end is not a non-negative integer, if b < 2, if
            b - ignore_end < 1, or if any value is not finite.

    Source: White (1997); Hoad, Robinson and Davies (2010).
    """
    if not isinstance(ignore_end, int) or isinstance(ignore_end, bool) or ignore_end < 0:
        raise CalibrationError("mser truncation: ignore_end must be a non-negative integer")
    n = len(values)
    b = n // batch
    if b < 2:
        raise CalibrationError("mser truncation: need at least two whole batches")
    if b - ignore_end < 1:
        raise CalibrationError("mser truncation: ignore_end leaves no batches for the search")
    for v in values:
        if not math.isfinite(v):
            raise CalibrationError("mser truncation: values must be finite")
    means = [sum(values[i * batch : (i + 1) * batch]) / batch for i in range(b)]
    min_ms = float("inf")
    d_star = 0
    for d in range(b - ignore_end):
        window = means[d:]
        m = sum(window) / len(window)
        ms = sum((y - m) ** 2 for y in window) / (len(window) ** 2)
        if ms < min_ms:
            min_ms = ms
            d_star = d
    return MserResult(
        n_values=b * batch,
        n_batches=b,
        d_star=d_star,
        truncated_report=batch * d_star,
        first_half=2 * d_star <= b,
    )


def browne_ucl_factor(n_cal: int = N_CAL, level: float = UCL_LEVEL) -> float:
    """Return Browne's one-sided upper confidence limit factor on a pilot variance.

    (n_cal - 1) / chi2.ppf(1 - level, n_cal - 1). At n_cal = 30 this is about 1.2903.

    Raises:
        CalibrationError: if n_cal < 2 or level is not in (0, 1).

    Source: Browne (1995).
    """
    if n_cal < 2:
        raise CalibrationError("browne ucl factor: n_cal must be at least 2")
    if not (0.0 < level < 1.0):
        raise CalibrationError("browne ucl factor: level must be between 0 and 1")
    # Imported here so that importing the rules (the positive control does, for
    # the SNR ladder) never needs scipy.
    from scipy.stats import chi2

    return (n_cal - 1) / chi2.ppf(1.0 - level, n_cal - 1)


def detection_z(alpha: float = ALPHA_PC) -> float:
    """Return z_{1-alpha} = norm.ppf(1 - alpha).

    At alpha = 0.05 this is about 1.6449.

    Raises:
        CalibrationError: if alpha is not in (0, 1).

    Source: Currie (1968).
    """
    if not (0.0 < alpha < 1.0):
        raise CalibrationError("detection z: alpha must be between 0 and 1")
    from scipy.stats import norm

    return float(norm.ppf(1.0 - alpha))


def control_min_reports(
    n_bar: float,
    s2: float,
    theta_pc: float,
    *,
    n_cal: int = N_CAL,
    alpha: float = ALPHA_PC,
    beta: float = BETA_PC,
    level: float = UCL_LEVEL,
) -> int:
    """Return one processor's term of the paper's n_PC formula.

    ceil( (z_{1-alpha} + z_{1-beta})^2 * n_bar * s2 / theta_pc^2 * browne_ucl_factor )

    At alpha = beta = 0.05 the first factor is Currie's (1968) detection limit:
    (2 * 1.6449)^2 = 10.822.

    Raises:
        CalibrationError: if n_bar <= 0, s2 < 0, theta_pc <= 0, or any input is not finite.

    Source: Currie (1968); Browne (1995); paper Appendix A.8.
    """
    for name, val in (
        ("n_bar", n_bar),
        ("s2", s2),
        ("theta_pc", theta_pc),
        ("alpha", alpha),
        ("beta", beta),
        ("level", level),
    ):
        if not math.isfinite(val):
            raise CalibrationError(f"control min reports: {name} must be finite")
    if n_bar <= 0:
        raise CalibrationError("control min reports: n_bar must be positive")
    if s2 < 0:
        raise CalibrationError("control min reports: s2 must be non-negative")
    if theta_pc <= 0:
        raise CalibrationError("control min reports: theta_pc must be positive")
    z_alpha = detection_z(alpha)
    z_beta = detection_z(beta)
    factor = (z_alpha + z_beta) ** 2 * n_bar * s2 / (theta_pc**2) * browne_ucl_factor(n_cal, level)
    return max(1, math.ceil(factor))


@dataclass(frozen=True)
class SnrChoice:
    """Interpolated SNR and the bracketing ladder indices."""

    snr: float
    lower_index: int  # ladder index of the rung below (the value interpolated from)
    upper_index: int  # ladder index of the first rung whose mean effect reaches the target


def interpolate_snr(
    ladder: Sequence[float],
    mean_effects: Sequence[float],
    target: float,
) -> SnrChoice:
    """Return the interpolated SNR at which the mean effect reaches the target.

    SNR_j is the smallest ladder value at which the informative component's mean effect
    reaches theta_PC, interpolated linearly in log SNR from the value below it. Let i be
    the first index with mean_effects[i] >= target and lo = i - 1. Then

        log(snr) = log(ladder[lo])
            + (target - mean_effects[lo]) / (mean_effects[i] - mean_effects[lo])
            * (log(ladder[i]) - log(ladder[lo])).

    Raises:
        CalibrationError: if the lengths differ or are below 2; if the ladder is not
            strictly increasing or has a value <= 0; if any value is not finite; if
            target <= 0; if no rung reaches the target; or if the first rung already
            reaches the target.

    Source: paper Appendix A.8, SNR ladder interpolation.
    """
    if len(ladder) != len(mean_effects):
        raise CalibrationError("interpolate snr: ladder and mean_effects must have the same length")
    if len(ladder) < 2:
        raise CalibrationError("interpolate snr: need at least two ladder rungs")
    if target <= 0:
        raise CalibrationError("interpolate snr: target must be positive")
    for value in ladder:
        if not math.isfinite(value) or value <= 0:
            raise CalibrationError("interpolate snr: ladder values must be finite and positive")
    for value in mean_effects:
        if not math.isfinite(value):
            raise CalibrationError("interpolate snr: mean effects must be finite")
    for i in range(1, len(ladder)):
        if ladder[i] <= ladder[i - 1]:
            raise CalibrationError("interpolate snr: ladder must be strictly increasing")
    i = None
    for idx, effect in enumerate(mean_effects):
        if effect >= target:
            i = idx
            break
    if i is None:
        raise CalibrationError(
            f"interpolate snr: the effect stays below theta_PC at the largest SNR ({ladder[-1]}), "
            "so the measure cannot be shown to register an effect of the minimum size "
            "and the live test does not run"
        )
    if i == 0:
        raise CalibrationError(
            "interpolate snr: the first rung already reaches the target, "
            "so the ladder does not bracket theta_PC"
        )
    lo = i - 1
    if mean_effects[i] <= mean_effects[lo]:
        raise CalibrationError(
            "interpolate snr: effect is not strictly increasing across the bracket"
        )
    log_snr = math.log(ladder[lo]) + (
        (target - mean_effects[lo]) / (mean_effects[i] - mean_effects[lo])
    ) * (math.log(ladder[i]) - math.log(ladder[lo]))
    return SnrChoice(snr=math.exp(log_snr), lower_index=lo, upper_index=i)


def quintile_edges(values: Sequence[float], n_bins: int = N_BINS) -> list[float]:
    """Return the n_bins - 1 interior edges at quantiles k / n_bins.

    Uses numpy.quantile with the default linear method.

    Raises:
        CalibrationError: if there are fewer than n_bins values, or if any value is
            not finite.

    Source: Cochran (1968).
    """
    if len(values) < n_bins:
        raise CalibrationError("quintile edges: need at least n_bins values")
    for v in values:
        if not math.isfinite(v):
            raise CalibrationError("quintile edges: values must be finite")
    quantiles = [k / n_bins for k in range(1, n_bins)]
    edges = np.quantile(values, quantiles)
    return [float(x) for x in edges]


__all__ = [
    "ALPHA_PC",
    "ALPHA_TEST",
    "BETA_PC",
    "C_EFF",
    "MSER_BATCH",
    "N_BINS",
    "N_CAL",
    "POWER_HORIZON",
    "Q_POW",
    "SNR_LADDER",
    "TARGET_POWER",
    "UCL_LEVEL",
    "CalibrationError",
    "MserResult",
    "SnrChoice",
    "browne_ucl_factor",
    "control_min_reports",
    "detection_z",
    "ensemble_average",
    "interpolate_snr",
    "minimum_effect",
    "mser_truncation",
    "planned_run_count",
    "quintile_edges",
    "runs_still_needed",
    "sample_sd",
    "sign_test_critical_count",
    "sign_test_power",
    "stable_run_count",
]
