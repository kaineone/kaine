# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Cross-record corpus analysis — the field-tier statistical layer.

The mechanism-validation tier reproduces each experiment exactly from a seed. The
field tier cannot: a live entity under real, operator-chosen stimulus is not
bit-reproducible, so validity is recovered by *replicability* instead — pool many
admissible runs and estimate the effect across them. This module is that pooling
layer.

Where :func:`kaine.experiment.stability.run_multi_seed` re-runs one callable
across SEEDS in-process, :func:`run_multi_record` here pools ALREADY-RECORDED
runs: each admissible run contributes one unit to a corpus, and the headline
effect is estimated across the corpus with an interval and a pre-registered
verdict, optionally stratified by stimulus regime so an effect can be shown to
hold ACROSS regimes rather than in one (the robustness axis).

Boundary-neutral: lives in ``kaine.experiment`` and imports only the standard
library, numpy, and ``kaine.experiment`` siblings (the record loader, the
admissibility + range gates, the verdict vocabulary, the Holm–Bonferroni
correction). It never imports ``kaine.evaluation`` — the experiment-specific
extraction of a per-run metric is supplied by the caller as a ``metric_fn``,
exactly as ``run_multi_seed`` takes one, so the sidecar can drive it without
crossing the privacy boundary.

Statistical posture (honest scope). The estimators are closed-form and
dependency-light by design, matching the project's lean, offline, consumer-hardware
footprint:

* a distribution-free percentile **bootstrap** interval on the pooled effect when
  runs contribute only a point value;
* a **DerSimonian–Laird** random-effects estimate when each run supplies its own
  within-run variance (records as the random unit — the frequentist mixed-effects
  reading at the record level), which then becomes the primary interval;
* a **normal–normal conjugate** posterior with a weakly-informative prior centred
  at the null as the Bayesian robustness check.

A verdict is trusted only where the frequentist interval and the Bayesian credible
interval agree (``agree``). Full crossed random effects for operator AND stimulus
regime together (a general linear mixed model) is a heavier fit deferred to an
optional backend; at the record level, and for the operator-local corpus that
ships first, this closed-form layer is the faithful instrument. Cross-operator
pooling (the guardian corpus) adds operator as a second random factor and is the
declared extension, not built here.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence, TypeVar

import numpy as np

from kaine.experiment.run_records import (
    DEFAULT_ROOT,
    RunRecords,
    discover_run_ids,
    load_run_records,
)
from kaine.experiment.verdict import Outcome

T = TypeVar("T")

#: How a per-run metric may be reported by a ``metric_fn``: a bare float, a
#: :class:`RunMetric`, or ``None`` (the experiment did not run in that record).
MetricLike = "RunMetric | float | None"


# --------------------------------------------------------------------------- #
# Per-run metric
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class RunMetric:
    """One run's contribution to a corpus.

    ``value`` is the run's headline effect (e.g. its A/B divergence, its
    memory-retrieval advantage, its ablation selection-divergence). ``variance``
    and ``n``, when supplied, are the run's *within-run* sampling variance of that
    value and the number of within-run samples it was computed from; supplying
    them promotes the pooled estimate from a bootstrap over run-level points to a
    DerSimonian–Laird random-effects meta-analysis. ``group`` is a content-free
    stratifier — the stimulus regime label — used to check that an effect holds
    across regimes.
    """

    value: float
    variance: float | None = None
    n: int | None = None
    group: str | None = None


def _coerce_metric(m: Any) -> RunMetric | None:
    """Normalise a ``metric_fn`` return into a ``RunMetric`` (or ``None``)."""
    if m is None:
        return None
    if isinstance(m, RunMetric):
        if not math.isfinite(m.value):
            return None
        return m
    try:
        v = float(m)
    except (TypeError, ValueError):
        return None
    return RunMetric(value=v) if math.isfinite(v) else None


# --------------------------------------------------------------------------- #
# Small closed-form statistics (numpy + stdlib only)
# --------------------------------------------------------------------------- #


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via the complementary error function (stdlib)."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


# Coefficients for Acklam's inverse-normal-CDF approximation (max abs error
# ~1.15e-9), so we get a z-quantile for any alpha without pulling in scipy.
_ACKLAM_A = (
    -3.969683028665376e01,
    2.209460984245205e02,
    -2.759285104469687e02,
    1.383577518672690e02,
    -3.066479806614716e01,
    2.506628277459239e00,
)
_ACKLAM_B = (
    -5.447609879822406e01,
    1.615858368580409e02,
    -1.556989798598866e02,
    6.680131188771972e01,
    -1.328068155288572e01,
)
_ACKLAM_C = (
    -7.784894002430293e-03,
    -3.223964580411365e-01,
    -2.400758277161838e00,
    -2.549732539343734e00,
    4.374664141464968e00,
    2.938163982698783e00,
)
_ACKLAM_D = (
    7.784695709041462e-03,
    3.224671290700398e-01,
    2.445134137142996e00,
    3.754408661907416e00,
)


def _norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (quantile) via Acklam's approximation."""
    if not (0.0 < p < 1.0):
        if p <= 0.0:
            return -math.inf
        return math.inf
    p_low, p_high = 0.02425, 1.0 - 0.02425
    if p < p_low:
        q = math.sqrt(-2.0 * math.log(p))
        return (
            (
                (
                    ((_ACKLAM_C[0] * q + _ACKLAM_C[1]) * q + _ACKLAM_C[2]) * q
                    + _ACKLAM_C[3]
                )
                * q
                + _ACKLAM_C[4]
            )
            * q
            + _ACKLAM_C[5]
        ) / (
            (((_ACKLAM_D[0] * q + _ACKLAM_D[1]) * q + _ACKLAM_D[2]) * q + _ACKLAM_D[3])
            * q
            + 1.0
        )
    if p > p_high:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(
            (
                (
                    ((_ACKLAM_C[0] * q + _ACKLAM_C[1]) * q + _ACKLAM_C[2]) * q
                    + _ACKLAM_C[3]
                )
                * q
                + _ACKLAM_C[4]
            )
            * q
            + _ACKLAM_C[5]
        ) / (
            (((_ACKLAM_D[0] * q + _ACKLAM_D[1]) * q + _ACKLAM_D[2]) * q + _ACKLAM_D[3])
            * q
            + 1.0
        )
    q = p - 0.5
    r = q * q
    return (
        (
            (
                (
                    ((_ACKLAM_A[0] * r + _ACKLAM_A[1]) * r + _ACKLAM_A[2]) * r
                    + _ACKLAM_A[3]
                )
                * r
                + _ACKLAM_A[4]
            )
            * r
            + _ACKLAM_A[5]
        )
        * q
        / (
            (
                (
                    ((_ACKLAM_B[0] * r + _ACKLAM_B[1]) * r + _ACKLAM_B[2]) * r
                    + _ACKLAM_B[3]
                )
                * r
                + _ACKLAM_B[4]
            )
            * r
            + 1.0
        )
    )


def _two_sided_p(effect: float, se: float) -> float:
    """Two-sided p-value for H0: effect == 0 under a normal approximation."""
    if se <= 0.0:
        return 1.0 if effect == 0.0 else 0.0
    z = abs(effect) / se
    return max(0.0, min(1.0, 2.0 * (1.0 - _norm_cdf(z))))


def _bootstrap_ci(
    values: np.ndarray, *, alpha: float, n_boot: int, rng: np.random.Generator
) -> tuple[float, float, float]:
    """Percentile bootstrap of the mean → (ci_lo, ci_hi, bootstrap_se).

    Distribution-free interval for the pooled (mean) effect over run-level
    values, plus the bootstrap standard error (std of the resampled means).
    """
    n = values.shape[0]
    idx = rng.integers(0, n, size=(n_boot, n))
    means = values[idx].mean(axis=1)
    lo = float(np.quantile(means, alpha / 2.0))
    hi = float(np.quantile(means, 1.0 - alpha / 2.0))
    return lo, hi, float(means.std(ddof=1)) if n_boot > 1 else 0.0


def _dersimonian_laird(
    effects: np.ndarray, variances: np.ndarray
) -> tuple[float, float, float]:
    """DerSimonian–Laird random-effects pooled estimate → (mu, se, tau2).

    The classic moment estimator: a between-study variance ``tau2`` is estimated
    from the weighted residual heterogeneity (Q) and added to each within-study
    variance, so the pooled mean incorporates heterogeneity rather than assuming a
    single common effect.
    """
    k = effects.shape[0]
    variances = np.maximum(variances, 1e-12)
    w = 1.0 / variances
    fixed_mean = float((w * effects).sum() / w.sum())
    q = float((w * (effects - fixed_mean) ** 2).sum())
    if k > 1:
        c = float(w.sum() - (w**2).sum() / w.sum())
        tau2 = max(0.0, (q - (k - 1)) / c) if c > 0 else 0.0
    else:
        tau2 = 0.0
    w_star = 1.0 / (variances + tau2)
    mu = float((w_star * effects).sum() / w_star.sum())
    se = float(math.sqrt(1.0 / w_star.sum()))
    return mu, se, tau2


def _normal_normal(values: np.ndarray, *, alpha: float) -> tuple[float, float, float]:
    """Normal–normal conjugate posterior for the mean → (post_mean, lo, hi).

    Weakly-informative prior centred at the null (mean 0, sd = 10× the data sd)
    so the posterior shrinks negligibly toward zero — a conservative Bayesian
    robustness check on the frequentist verdict. With a diffuse prior this
    reproduces the sampling interval; the mild shrinkage is deliberate.
    """
    n = values.shape[0]
    xbar = float(values.mean())
    s2 = float(values.var(ddof=1)) if n > 1 else 0.0
    if s2 <= 0.0 or n < 2:
        return xbar, xbar, xbar
    data_prec = n / s2
    prior_sd = 10.0 * math.sqrt(s2)
    prior_prec = 1.0 / (prior_sd**2)
    post_prec = data_prec + prior_prec
    post_mean = (data_prec * xbar) / post_prec  # prior mean 0 drops out
    post_sd = math.sqrt(1.0 / post_prec)
    z = _norm_ppf(1.0 - alpha / 2.0)
    return post_mean, post_mean - z * post_sd, post_mean + z * post_sd


def _decide(lo: float, hi: float, *, min_effect: float, direction: str) -> Outcome:
    """Map an interval to a verdict against a pre-registered ``min_effect``.

    ``two_sided``: WIN if the interval is entirely above ``+min_effect``,
    NEGATIVE if entirely below ``-min_effect``, else NULL. ``greater``: WIN if the
    interval is entirely above ``+min_effect``, else NULL (no NEGATIVE surface).
    """
    if lo > min_effect:
        return Outcome.WIN
    if direction == "two_sided" and hi < -min_effect:
        return Outcome.NEGATIVE
    return Outcome.NULL


# --------------------------------------------------------------------------- #
# Estimate + report
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CorpusEstimate:
    """Pooled estimate of one effect over a corpus (or one regime of it)."""

    n_runs: int
    effect: float
    ci_lo: float
    ci_hi: float
    se: float
    method: str  # "dersimonian_laird" | "bootstrap" | "insufficient"
    p_value: float
    verdict: str  # frequentist verdict (Outcome value)
    bayes_mean: float
    bayes_lo: float
    bayes_hi: float
    bayes_verdict: str
    agree: bool
    min_effect: float
    alpha: float
    tau2: float | None = None

    def reasons(self) -> list[str]:
        out = [
            f"n={self.n_runs} runs; effect={self.effect:.6g} "
            f"[{self.ci_lo:.6g}, {self.ci_hi:.6g}] ({self.method}); "
            f"verdict={self.verdict} (p={self.p_value:.4g})",
            f"bayes mean={self.bayes_mean:.6g} "
            f"[{self.bayes_lo:.6g}, {self.bayes_hi:.6g}]; verdict={self.bayes_verdict}",
        ]
        out.append(
            "frequentist and Bayesian verdicts AGREE"
            if self.agree
            else "frequentist and Bayesian verdicts DISAGREE — verdict not trusted"
        )
        if self.tau2 is not None:
            out.append(f"between-run variance tau2={self.tau2:.6g}")
        return out

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "n_runs": self.n_runs,
            "effect": self.effect,
            "ci": [self.ci_lo, self.ci_hi],
            "se": self.se,
            "method": self.method,
            "p_value": self.p_value,
            "verdict": self.verdict,
            "bayes": {
                "mean": self.bayes_mean,
                "ci": [self.bayes_lo, self.bayes_hi],
                "verdict": self.bayes_verdict,
            },
            "agree": self.agree,
            "min_effect": self.min_effect,
            "alpha": self.alpha,
            "reasons": self.reasons(),
        }
        if self.tau2 is not None:
            d["tau2"] = self.tau2
        return d


@dataclass(frozen=True)
class CorpusReport:
    """One experiment's field-tier verdict, pooled over a corpus of records."""

    experiment: str
    overall: CorpusEstimate
    by_group: dict[str, CorpusEstimate] = field(default_factory=dict)
    holds_across_groups: bool = True
    n_dropped: int = 0  # records for which metric_fn returned None

    @property
    def verdict(self) -> str:
        return self.overall.verdict

    @property
    def trusted(self) -> bool:
        """A verdict is trusted only when freq & Bayes agree AND, where the corpus
        spans more than one regime, no regime contradicts the overall direction."""
        return self.overall.agree and self.holds_across_groups

    def reasons(self) -> list[str]:
        out = [f"[{self.experiment}] overall: " + "; ".join(self.overall.reasons())]
        for g, est in sorted(self.by_group.items()):
            out.append(f"  regime {g!r}: {est.verdict} (n={est.n_runs})")
        if self.by_group:
            out.append(
                "effect holds across all regimes"
                if self.holds_across_groups
                else "effect does NOT hold across all regimes"
            )
        if self.n_dropped:
            out.append(f"{self.n_dropped} record(s) contributed no metric (dropped)")
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "experiment": self.experiment,
            "overall": self.overall.to_dict(),
            "by_group": {g: e.to_dict() for g, e in self.by_group.items()},
            "holds_across_groups": self.holds_across_groups,
            "trusted": self.trusted,
            "n_dropped": self.n_dropped,
            "reasons": self.reasons(),
        }


def _estimate(
    metrics: Sequence[RunMetric],
    *,
    min_effect: float,
    alpha: float,
    direction: str,
    n_boot: int,
    rng: np.random.Generator,
) -> CorpusEstimate:
    """Pool a set of per-run metrics into one estimate + verdict."""
    n = len(metrics)
    values = np.array([m.value for m in metrics], dtype=float)

    def _empty(reason_method: str) -> CorpusEstimate:
        pt = float(values.mean()) if n else 0.0
        return CorpusEstimate(
            n_runs=n,
            effect=pt,
            ci_lo=pt,
            ci_hi=pt,
            se=0.0,
            method=reason_method,
            p_value=1.0,
            verdict=Outcome.NULL.value,
            bayes_mean=pt,
            bayes_lo=pt,
            bayes_hi=pt,
            bayes_verdict=Outcome.NULL.value,
            agree=True,
            min_effect=min_effect,
            alpha=alpha,
        )

    if n < 2:
        # A single run (or none) cannot establish a pooled effect: report the
        # point but resolve to NULL rather than fake certainty from one unit.
        return _empty("insufficient")

    have_var = all(m.variance is not None and m.variance >= 0.0 for m in metrics)
    tau2: float | None = None
    if have_var:
        variances = np.array([float(m.variance) for m in metrics], dtype=float)
        effect, se, tau2 = _dersimonian_laird(values, variances)
        z = _norm_ppf(1.0 - alpha / 2.0)
        ci_lo, ci_hi = effect - z * se, effect + z * se
        method = "dersimonian_laird"
    else:
        ci_lo, ci_hi, boot_se = _bootstrap_ci(
            values, alpha=alpha, n_boot=n_boot, rng=rng
        )
        effect = float(values.mean())
        se = boot_se
        method = "bootstrap"

    p_value = _two_sided_p(effect, se)
    verdict = _decide(ci_lo, ci_hi, min_effect=min_effect, direction=direction)

    b_mean, b_lo, b_hi = _normal_normal(values, alpha=alpha)
    b_verdict = _decide(b_lo, b_hi, min_effect=min_effect, direction=direction)

    return CorpusEstimate(
        n_runs=n,
        effect=effect,
        ci_lo=ci_lo,
        ci_hi=ci_hi,
        se=se,
        method=method,
        p_value=p_value,
        verdict=verdict.value,
        bayes_mean=b_mean,
        bayes_lo=b_lo,
        bayes_hi=b_hi,
        bayes_verdict=b_verdict.value,
        agree=(verdict == b_verdict),
        min_effect=min_effect,
        alpha=alpha,
        tau2=tau2,
    )


def run_multi_record(
    records: Sequence[T],
    *,
    metric_fn: Callable[[T], Any],
    experiment: str,
    min_effect: float = 0.0,
    alpha: float = 0.05,
    direction: str = "two_sided",
    n_boot: int = 2000,
    analysis_seed: int = 0,
    group_fn: Callable[[T], str | None] | None = None,
    min_group_runs: int = 3,
) -> CorpusReport:
    """Pool an effect across ALREADY-RECORDED runs and resolve a field-tier verdict.

    Parameters
    ----------
    records:
        The runs to pool — typically :class:`RunRecords` from :func:`load_corpus`,
        but any sequence works (the metric extractor is the only coupling).
    metric_fn:
        ``metric_fn(record) -> RunMetric | float | None``. ``None`` drops the
        record (the experiment did not run in it). A ``RunMetric`` may carry a
        within-run ``variance`` (promotes pooling to DerSimonian–Laird) and a
        ``group`` (stimulus regime).
    experiment:
        Label for the report.
    min_effect:
        The pre-registered smallest effect that counts. WIN requires the interval
        to clear ``+min_effect``; NEGATIVE (two-sided) requires it below
        ``-min_effect``.
    alpha:
        Interval / credible-interval level (two-sided).
    direction:
        ``"two_sided"`` (WIN / NULL / NEGATIVE) or ``"greater"`` (WIN / NULL).
    n_boot:
        Bootstrap resamples for the distribution-free interval (used when runs
        carry no within-run variance).
    analysis_seed:
        Seed for the bootstrap RNG, so the post-hoc analysis is itself
        reproducible.
    group_fn:
        Optional ``group_fn(record) -> regime label``; overrides any group on the
        ``RunMetric``. Regimes with at least ``min_group_runs`` records are
        estimated separately and checked for cross-regime robustness.
    min_group_runs:
        Minimum records for a regime to get its own estimate and to count toward
        the cross-regime robustness check.

    Returns
    -------
    CorpusReport
        The overall pooled estimate, per-regime estimates, and whether the effect
        holds across regimes. A verdict is ``trusted`` only when the frequentist
        and Bayesian intervals agree AND no regime contradicts the overall.
    """
    if direction not in ("two_sided", "greater"):
        raise ValueError("direction must be 'two_sided' or 'greater'.")
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha must be in (0, 1).")

    rng = np.random.default_rng(analysis_seed)

    metrics: list[RunMetric] = []
    groups: list[str | None] = []
    dropped = 0
    for rec in records:
        m = _coerce_metric(metric_fn(rec))
        if m is None:
            dropped += 1
            continue
        grp = group_fn(rec) if group_fn is not None else m.group
        metrics.append(
            m if group_fn is None else RunMetric(m.value, m.variance, m.n, grp)
        )
        groups.append(grp)

    overall = _estimate(
        metrics,
        min_effect=min_effect,
        alpha=alpha,
        direction=direction,
        n_boot=n_boot,
        rng=rng,
    )

    # Per-regime estimates (only regimes with enough records).
    by_group: dict[str, CorpusEstimate] = {}
    labelled = [(g, m) for g, m in zip(groups, metrics) if g is not None]
    distinct = sorted({g for g, _ in labelled})
    for g in distinct:
        grp_metrics = [m for gg, m in labelled if gg == g]
        if len(grp_metrics) >= min_group_runs:
            by_group[g] = _estimate(
                grp_metrics,
                min_effect=min_effect,
                alpha=alpha,
                direction=direction,
                n_boot=n_boot,
                rng=rng,
            )

    # The effect "holds across regimes" when the overall is a directional verdict
    # (WIN/NEGATIVE) and no estimated regime resolves to the OPPOSITE direction.
    # A NULL overall makes cross-regime robustness vacuous (nothing to hold).
    holds = True
    if (
        overall.verdict in (Outcome.WIN.value, Outcome.NEGATIVE.value)
        and len(by_group) > 1
    ):
        opposite = (
            Outcome.NEGATIVE.value
            if overall.verdict == Outcome.WIN.value
            else Outcome.WIN.value
        )
        holds = not any(est.verdict == opposite for est in by_group.values())

    return CorpusReport(
        experiment=experiment,
        overall=overall,
        by_group=by_group,
        holds_across_groups=holds,
        n_dropped=dropped,
    )


# --------------------------------------------------------------------------- #
# Corpus loading (admissibility-gated)
# --------------------------------------------------------------------------- #


@dataclass
class CorpusLoad:
    """The outcome of assembling a corpus from an eval-log tree.

    ``admitted`` holds one :class:`RunRecords` per admissible run (each gated by
    the completeness + range checks before it may enter). ``excluded`` maps an
    inadmissible run_id to the reasons it was dropped, so exclusion is never
    silent. ``unreadable_lines`` mirrors :func:`discover_run_ids`: a non-zero
    count means some log lines could not be decrypted/parsed (usually a
    wrong/absent state key), and the caller should treat the corpus as
    untrustworthy rather than merely thin.
    """

    admitted: list[RunRecords] = field(default_factory=list)
    excluded: dict[str, list[str]] = field(default_factory=dict)
    unreadable_lines: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "n_admitted": len(self.admitted),
            "admitted_run_ids": [r.run_id for r in self.admitted],
            "excluded": self.excluded,
            "unreadable_lines": self.unreadable_lines,
        }


def load_corpus(
    root: Path | str = DEFAULT_ROOT,
    *,
    expected_streams: Sequence[str] = (),
    require_admissible: bool = True,
) -> CorpusLoad:
    """Assemble an admissibility-gated corpus of runs from an eval-log tree.

    Discovers every distinct ``run_id`` under ``root`` (:func:`discover_run_ids`),
    loads each (:func:`load_run_records`), and — when ``require_admissible`` —
    gates each with the SAME two offline checks a single run passes before
    analysis: the completeness gate (contiguous ticks + per-sink ``seq``, all
    ``expected_streams`` present, no parse errors, no restart signature) and the
    log-range sweep (every logged number within its declared range). A run that
    fails either is recorded in ``excluded`` with its reasons and kept OUT of the
    pool, so an incomplete or physically-implausible run cannot silently dilute a
    pooled estimate.

    Unlike the single-run bundle builder, this deliberately admits MANY runs: the
    field tier's whole premise is pooling across runs, so a multi-run tree is the
    normal case here, not a restart signal.
    """
    from kaine.experiment.admissibility import scan_run
    from kaine.experiment.log_schema import sweep_run

    root = Path(root)
    discovery = discover_run_ids(root)
    load = CorpusLoad(unreadable_lines=discovery.unreadable_lines)

    for run_id in discovery.run_ids:
        records = load_run_records(run_id, root=root)
        if not require_admissible:
            load.admitted.append(records)
            continue
        reasons: list[str] = []
        report = scan_run(run_id, root=root, expected_streams=list(expected_streams))
        if not report.admissible:
            reasons.extend(report.reasons())
        violations = sweep_run(run_id, root=root)
        if violations:
            reasons.append(f"range violations: {len(violations)}")
        if reasons:
            load.excluded[run_id] = reasons
        else:
            load.admitted.append(records)

    return load


__all__ = [
    "RunMetric",
    "CorpusEstimate",
    "CorpusReport",
    "CorpusLoad",
    "run_multi_record",
    "load_corpus",
]
