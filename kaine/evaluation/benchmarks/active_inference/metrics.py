# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Metrics + WIN/NULL/NEGATIVE verdict for the AIF-vs-RL benchmark.

Reported per task and aggregated across seeds (design.md, spec.md):

- **Decision quality:** asymptotic mean reward (greedy eval for RL; standard
  EFE policy for AIF).
- **Sample efficiency:** RL's steps-to-competence (training episodes to reach a
  fraction of optimal return) — AIF needs no learning episodes for the decision
  policy, so it is reported as competent-from-model; plus cumulative regret vs
  the env's optimal policy for both.
- **Value of epistemic action:** on epistemic tasks, each agent's probe rate and
  timing, and the epistemic-vs-exploitation decision-quality gap.

The **verdict** compares the two agents' per-seed decision-quality distributions
with a two-sided Mann–Whitney U test (scipy) plus a minimum effect size (rank-
biserial correlation): WIN if AIF is significantly higher beyond the effect-size
floor, NEGATIVE if significantly lower, NULL otherwise. NULL and NEGATIVE are
first-class, reportable outcomes — the classifier never manufactures a WIN. The
same shape of statistical instrument the individuation boundary uses, for
consistency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
from scipy import stats

# Verdict labels.
WIN = "WIN"
NULL = "NULL"
NEGATIVE = "NEGATIVE"


@dataclass(frozen=True)
class VerdictConfig:
    """Thresholds for the verdict classifier.

    ``alpha`` is the significance level of the Mann–Whitney test;
    ``min_effect`` is the minimum absolute rank-biserial correlation
    ``|r|`` required to call a significant difference a WIN/NEGATIVE rather than
    a (practically negligible) NULL.
    """

    alpha: float = 0.05
    min_effect: float = 0.3

    def as_dict(self) -> dict[str, float]:
        return {"alpha": self.alpha, "min_effect": self.min_effect}


def rank_biserial(a: np.ndarray, b: np.ndarray, u_statistic: float) -> float:
    """Rank-biserial correlation effect size from a Mann–Whitney U statistic.

    ``r = 2U/(n_a*n_b) - 1`` lies in [-1, 1]; positive means ``a`` tends to
    exceed ``b``. Robust to ties (uses the U already computed by scipy).
    """
    n_a = len(a)
    n_b = len(b)
    if n_a == 0 or n_b == 0:
        return 0.0
    return float(2.0 * u_statistic / (n_a * n_b) - 1.0)


def classify_verdict(
    aif_scores: list[float],
    rl_scores: list[float],
    config: Optional[VerdictConfig] = None,
) -> dict[str, Any]:
    """Classify AIF vs RL decision-quality distributions as WIN/NULL/NEGATIVE.

    Uses a two-sided Mann–Whitney U test. Direction is read from the
    rank-biserial effect size (AIF as group ``a``): positive ``r`` means AIF
    tends to score higher. A significant result with ``|r| >= min_effect`` is a
    WIN (r > 0) or NEGATIVE (r < 0); everything else is NULL.

    Degenerate inputs (identical constant distributions, or n < 2) are reported
    as NULL with ``p_value = 1.0`` rather than raising — a tie is a null, not a
    harness failure.
    """
    cfg = config or VerdictConfig()
    a = np.asarray(aif_scores, dtype=float)
    b = np.asarray(rl_scores, dtype=float)
    n_a, n_b = len(a), len(b)
    mean_aif = float(a.mean()) if n_a else 0.0
    mean_rl = float(b.mean()) if n_b else 0.0

    base = {
        "verdict": NULL,
        "p_value": 1.0,
        "effect_size_r": 0.0,
        "mean_aif": mean_aif,
        "mean_rl": mean_rl,
        "delta": mean_aif - mean_rl,
        "n_seeds": min(n_a, n_b),
        "config": cfg.as_dict(),
    }

    if n_a < 2 or n_b < 2:
        return base
    # All values identical across both groups -> indistinguishable -> NULL.
    if np.ptp(np.concatenate([a, b])) == 0.0:
        return base

    try:
        u_stat, p_value = stats.mannwhitneyu(a, b, alternative="two-sided")
    except ValueError:
        # scipy raises if an input is constant in a way it can't rank; NULL.
        return base
    r = rank_biserial(a, b, float(u_stat))
    base["p_value"] = float(p_value)
    base["effect_size_r"] = r

    if p_value < cfg.alpha and abs(r) >= cfg.min_effect:
        base["verdict"] = WIN if r > 0 else NEGATIVE
    else:
        base["verdict"] = NULL
    return base


def decision_quality(eval_returns: list[float]) -> dict[str, float]:
    """Asymptotic decision quality summary from greedy/standard eval returns."""
    arr = np.asarray(eval_returns, dtype=float)
    if arr.size == 0:
        return {"mean": 0.0, "std": 0.0}
    return {"mean": float(arr.mean()), "std": float(arr.std())}


def steps_to_competence(
    train_returns: list[float],
    optimal_return: float,
    *,
    fraction: float = 0.8,
    window: int = 20,
) -> Optional[int]:
    """Training episodes until a moving-average return reaches ``fraction`` of
    optimal. ``None`` if never reached (a real, reportable outcome).

    AIF needs no training episodes for its decision policy, so for the AIF agent
    this is reported as 0 (competent from the model) by the runner; here it is
    the RL learning-curve measure.
    """
    arr = np.asarray(train_returns, dtype=float)
    if arr.size == 0:
        return None
    threshold = fraction * optimal_return
    w = max(1, min(window, arr.size))
    moving = np.convolve(arr, np.ones(w) / w, mode="valid")
    hits = np.flatnonzero(moving >= threshold)
    if hits.size == 0:
        return None
    return int(hits[0] + w - 1)


def cumulative_regret(returns: list[float], optimal_return: float) -> float:
    """Total regret = sum over episodes of (optimal - achieved) return."""
    arr = np.asarray(returns, dtype=float)
    return float(np.sum(optimal_return - arr))


def epistemic_value(
    *,
    aif_probe_rate: float,
    rl_probe_rate: float,
    aif_mean_probe_step: Optional[float],
    rl_mean_probe_step: Optional[float],
) -> dict[str, Any]:
    """Value-of-epistemic-action summary on an epistemic task.

    The headline is the *probe-rate gap* (AIF minus RL): a positive gap means the
    AIF agent info-seeks more than the no-/low-exploration baseline, which is the
    behaviour the paper's hypothesis predicts. Timing (mean step at which the
    probe first occurs) is reported when available; earlier is better.
    """
    return {
        "aif_probe_rate": float(aif_probe_rate),
        "rl_probe_rate": float(rl_probe_rate),
        "probe_rate_gap": float(aif_probe_rate - rl_probe_rate),
        "aif_mean_probe_step": aif_mean_probe_step,
        "rl_mean_probe_step": rl_mean_probe_step,
    }


def aggregate_verdict(per_task_verdicts: list[str]) -> str:
    """Suite-level verdict over per-task verdicts.

    Conservative aggregation that surfaces a mixed picture honestly:
    - any NEGATIVE present and no WIN -> NEGATIVE;
    - all WIN -> WIN;
    - a mix of WIN and NEGATIVE -> NULL (mixed: the suite as a whole does not
      support a clean win, which is itself the reportable finding);
    - otherwise (WIN/NULL mix, or all NULL) -> WIN if any WIN and no NEGATIVE
      else NULL.
    """
    has_win = WIN in per_task_verdicts
    has_neg = NEGATIVE in per_task_verdicts
    if has_win and has_neg:
        return NULL
    if has_neg:
        return NEGATIVE
    if has_win:
        return WIN
    return NULL


__all__ = [
    "WIN",
    "NULL",
    "NEGATIVE",
    "VerdictConfig",
    "classify_verdict",
    "rank_biserial",
    "decision_quality",
    "steps_to_competence",
    "cumulative_regret",
    "epistemic_value",
    "aggregate_verdict",
]
