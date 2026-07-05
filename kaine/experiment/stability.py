# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Multi-seed stability harness — the longitudinal / multi-run control.

When determinism is NOT enforced (the live / longitudinal case), there is no
bit-for-bit seed-determinism guarantee to lean on. The methodological control is
the multi-seed analog: run the SAME configuration under several seeds and assert
that the SUMMARY STATISTICS are stable across them. If they are, nondeterminism
has washed out — N is large enough that the headline number and the verdict are
robust to the seed. If they are not, the experiment is under-powered or genuinely
unstable, which is itself a reportable finding (not a harness failure).

This module is boundary-neutral. Like the rest of ``kaine/experiment/`` it carries
NO dependency on ``kaine.evaluation``: it takes a *callable* ``run_fn(seed)`` and a
``metric_fn``, so both the core cycle and the evaluation sidecar may use it without
crossing the sidecar privacy boundary. It depends only on the standard library and
``kaine.experiment`` siblings (``set_global_seed``, the ``Verdict`` schema).

Statistical posture mirrors ``kaine.evaluation.individuation`` (mean / std across a
seeded ensemble), but here the ensemble is over *experiment runs* rather than
permutation samples, and the headline summary adds a coefficient of variation and a
verdict-distribution count.

Scope (honest): this harness is the right instrument for genuinely
nondeterministic live experiments. As exercised in this codebase it runs *offline*
runners that are deterministic per seed, so it proves the stability *machinery* is
correct and demonstrates those offline experiments are seed-robust. It does not
itself collect weeks-long live longitudinal data — that is the operator's job once
an entity is running; this is the analysis instrument waiting for that data.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from kaine.experiment.seeding import set_global_seed
from kaine.experiment.verdict import Outcome, Verdict


# --------------------------------------------------------------------------- #
# Pure summary statistics (stdlib only). These are the single canonical
# definitions; kaine.evaluation.individuation imports them from here so the two
# never drift (this module is boundary-neutral and may not import evaluation).
# --------------------------------------------------------------------------- #


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _std(values: Sequence[float]) -> float:
    """Population standard deviation (the canonical definition shared with
    kaine.evaluation.individuation)."""
    if len(values) < 2:
        return 0.0
    m = _mean(values)
    variance = sum((v - m) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def _coefficient_of_variation(mean: float, std: float) -> float:
    """std / |mean| when mean != 0.

    The CV is the scale-free dispersion the stability verdict turns on. When the
    mean is exactly zero the CV is undefined; we report 0.0 iff the std is also
    zero (a degenerate all-zero ensemble is perfectly stable) and ``inf``
    otherwise (non-zero spread around a zero mean is maximally unstable in
    relative terms, and the absolute spread is then judged by ``std`` against the
    tolerance — see ``run_multi_seed``).
    """
    if mean != 0.0:
        return std / abs(mean)
    return 0.0 if std == 0.0 else math.inf


# --------------------------------------------------------------------------- #
# Report
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class StabilityReport:
    """Summary of one experiment's behaviour across several seeds.

    Fields
    ------
    seeds:
        The seeds run, in the order supplied.
    values:
        The per-seed headline metric (one float per seed, aligned with ``seeds``).
    mean / std:
        Mean and population standard deviation of ``values``.
    cv:
        Coefficient of variation = ``std / |mean|`` (0.0 for an all-equal
        ensemble; ``inf`` for non-zero spread around a zero mean).
    verdict_counts:
        Distribution of verdict outcomes across seeds, e.g. ``{"WIN": 5}``. Empty
        when ``metric_fn`` returned no verdict (metric-only ensembles).
    tolerance:
        The CV tolerance the stability verdict was evaluated against.
    stable:
        True iff the ensemble is stable under the documented criterion (see
        ``run_multi_seed``): CV within tolerance AND verdicts unanimous (when
        verdicts are present).
    """

    seeds: tuple[int, ...]
    values: tuple[float, ...]
    mean: float
    std: float
    cv: float
    verdict_counts: dict[str, int] = field(default_factory=dict)
    tolerance: float = 0.0
    stable: bool = False

    # ------------------------------------------------------------------ #
    @property
    def verdict_unanimous(self) -> bool:
        """True iff at most one distinct verdict outcome appears across seeds.

        An empty ``verdict_counts`` (metric-only ensemble) is vacuously
        unanimous — there is no disagreement to find.
        """
        return len(self.verdict_counts) <= 1

    def reasons(self) -> list[str]:
        """Human-readable explanation of the stability verdict.

        Always lists every factor (CV vs tolerance, verdict unanimity) so the
        report explains *why* it is stable or unstable, not just the boolean.
        """
        out: list[str] = []
        if math.isinf(self.cv):
            out.append(
                f"cv is infinite (std={self.std:.6g} around a zero mean) "
                f"> tolerance={self.tolerance:.6g}: UNSTABLE spread"
            )
        elif self.cv <= self.tolerance:
            out.append(
                f"cv={self.cv:.6g} <= tolerance={self.tolerance:.6g}: "
                f"metric is stable across seeds"
            )
        else:
            out.append(
                f"cv={self.cv:.6g} > tolerance={self.tolerance:.6g}: "
                f"metric varies too much across seeds"
            )
        if not self.verdict_counts:
            out.append("no verdicts collected (metric-only ensemble)")
        elif self.verdict_unanimous:
            only = next(iter(self.verdict_counts))
            out.append(f"verdicts unanimous: {only} across all {len(self.seeds)} seeds")
        else:
            out.append(f"verdicts disagree across seeds: {dict(self.verdict_counts)}")
        return out

    def to_dict(self) -> dict[str, Any]:
        """Stable serialization for a JSONL record / manifest."""
        return {
            "seeds": list(self.seeds),
            "values": list(self.values),
            "mean": self.mean,
            "std": self.std,
            "cv": (None if math.isinf(self.cv) else self.cv),
            "cv_is_infinite": math.isinf(self.cv),
            "verdict_counts": dict(self.verdict_counts),
            "verdict_unanimous": self.verdict_unanimous,
            "tolerance": self.tolerance,
            "stable": self.stable,
            "reasons": self.reasons(),
        }


# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #


def _extract_verdict_outcome(result: Any) -> str | None:
    """Best-effort pull of a verdict outcome string out of a run result.

    Recognizes a ``Verdict``/``Outcome`` directly, a result dict carrying a
    ``"verdict"`` (either a ``Verdict`` or its ``to_dict`` form), or a result
    object exposing a ``.verdict`` attribute. Returns ``None`` when no verdict is
    present — metric-only ensembles are first-class.
    """
    candidate: Any = result
    if isinstance(result, dict) and "verdict" in result:
        candidate = result["verdict"]
    elif hasattr(result, "verdict"):
        candidate = getattr(result, "verdict")

    if isinstance(candidate, Verdict):
        return candidate.outcome.value
    if isinstance(candidate, Outcome):
        return candidate.value
    if isinstance(candidate, dict) and "outcome" in candidate:
        outcome = candidate["outcome"]
        return outcome.value if isinstance(outcome, Outcome) else str(outcome)
    return None


def run_multi_seed(
    run_fn: Callable[[int], Any],
    seeds: Sequence[int],
    *,
    metric_fn: Callable[[Any], float],
    tolerance: float = 0.0,
    pin_global_seed: bool = True,
) -> StabilityReport:
    """Run ``run_fn`` once per seed and report stability of its headline metric.

    Parameters
    ----------
    run_fn:
        ``run_fn(seed) -> result``. Called once per seed. If ``pin_global_seed``
        is True (default), ``set_global_seed(seed)`` is called immediately before
        each invocation so the legacy global RNGs are pinned even when ``run_fn``
        does not pin them itself. (Runners that already call ``set_global_seed``
        internally are unaffected — re-pinning to the same seed is idempotent.)
    seeds:
        The seeds to run. Must be non-empty.
    metric_fn:
        ``metric_fn(result) -> float`` — extracts the per-seed headline metric
        (the number whose stability is asserted) from a run result.
    tolerance:
        Maximum coefficient of variation for the ensemble to count as stable.
        Defaults to 0.0 (exact stability — the right default for per-seed
        deterministic offline runners, where the metric should not move at all).
    pin_global_seed:
        Whether to call ``set_global_seed(seed)`` before each ``run_fn`` call.

    Returns
    -------
    StabilityReport
        Summary statistics + stability verdict.

    Stability criterion
    -------------------
    The ensemble is ``stable`` iff:
      1. the coefficient of variation of the headline metric is within
         ``tolerance`` (``cv <= tolerance``; an infinite CV — non-zero spread
         around a zero mean — is never within a finite tolerance), AND
      2. the verdict is unanimous across seeds (when verdicts are present; a
         metric-only ensemble has no verdict to disagree on and is vacuously
         unanimous).
    Both conditions must hold. Verdict disagreement makes the ensemble unstable
    even when the metric CV is within tolerance, because a flipped WIN/NULL is a
    qualitative instability the scalar dispersion would otherwise hide.
    """
    seed_list = [int(s) for s in seeds]
    if not seed_list:
        raise ValueError("run_multi_seed requires at least one seed.")
    if tolerance < 0.0:
        raise ValueError("tolerance must be >= 0.")

    values: list[float] = []
    verdict_counts: dict[str, int] = {}
    for seed in seed_list:
        if pin_global_seed:
            set_global_seed(seed)
        result = run_fn(seed)
        values.append(float(metric_fn(result)))
        outcome = _extract_verdict_outcome(result)
        if outcome is not None:
            verdict_counts[outcome] = verdict_counts.get(outcome, 0) + 1

    mean = _mean(values)
    std = _std(values)
    cv = _coefficient_of_variation(mean, std)
    unanimous = len(verdict_counts) <= 1
    stable = (cv <= tolerance) and unanimous

    return StabilityReport(
        seeds=tuple(seed_list),
        values=tuple(values),
        mean=mean,
        std=std,
        cv=cv,
        verdict_counts=dict(verdict_counts),
        tolerance=float(tolerance),
        stable=stable,
    )


class StabilityError(AssertionError):
    """Raised by ``assert_stable`` when an ensemble is not stable."""

    def __init__(self, report: StabilityReport) -> None:
        self.report = report
        super().__init__(
            "experiment is not stable across seeds: " + "; ".join(report.reasons())
        )


def assert_stable(
    run_fn: Callable[[int], Any],
    seeds: Sequence[int],
    *,
    metric_fn: Callable[[Any], float],
    tolerance: float = 0.0,
    pin_global_seed: bool = True,
) -> StabilityReport:
    """Run the multi-seed ensemble and raise ``StabilityError`` unless stable.

    Returns the ``StabilityReport`` on success so callers can still read the
    summary statistics. The error message carries ``report.reasons()`` so a
    failure is self-explaining (honest failure over a fake pass).
    """
    report = run_multi_seed(
        run_fn,
        seeds,
        metric_fn=metric_fn,
        tolerance=tolerance,
        pin_global_seed=pin_global_seed,
    )
    if not report.stable:
        raise StabilityError(report)
    return report


__all__ = [
    "StabilityReport",
    "StabilityError",
    "run_multi_seed",
    "assert_stable",
]
