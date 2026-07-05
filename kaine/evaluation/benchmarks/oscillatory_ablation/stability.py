# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Multi-seed stability adapter for the oscillatory-ablation runner.

Demonstrates the boundary-neutral stability harness
(:func:`kaine.experiment.stability.run_multi_seed`) on a *real* experiment: it
runs the controlled oscillatory-ablation runner across several seeds and reports
whether its headline effect metric and its WIN/NULL verdict are stable.

The ablation runner is deterministic *per seed* (same seed + scripted input +
``deterministic=True`` ⇒ bit-for-bit reproducible), so across seeds the effect
should be stable and the verdict unanimous — a clean demonstration that the
stability machinery is correct and that this offline experiment is seed-robust.
The same adapter shape works for any seed-varying experiment that returns a
``Verdict``; for a genuinely nondeterministic *live* experiment the same harness
is the right instrument (raise the tolerance to whatever spread the live process
admits, run more seeds), but this adapter is exercised offline only.

This module lives under ``kaine/evaluation/`` (where the experiments live) and is
allowed to import ``kaine.experiment`` — the sidecar boundary only forbids CORE
importing ``kaine.evaluation``, never the reverse, and never an evaluation module
importing the boundary-neutral ``kaine.experiment``.
"""
from __future__ import annotations

import asyncio
from typing import Sequence

from kaine.evaluation.benchmarks.oscillatory_ablation.runner import (
    AblationConfig,
    run_ablation,
)
from kaine.experiment.stability import StabilityReport, run_multi_seed

# Default headline metric: the effect size the runner's verdict turns on.
HEADLINE_METRIC = "selection_divergence_fraction"


def _effect_metric(result: dict) -> float:
    """Pull the headline effect (selection-divergence fraction) from a run result."""
    return float(result["summary"][HEADLINE_METRIC])


def run_ablation_stability(
    seeds: Sequence[int],
    *,
    ticks: int = 16,
    tolerance: float = 0.0,
    base_config: AblationConfig | None = None,
) -> StabilityReport:
    """Run the oscillatory-ablation runner across ``seeds`` and report stability.

    Parameters
    ----------
    seeds:
        Seeds to run the ablation under. Each produces one ablation result; the
        ensemble's effect-metric mean / std / CV and verdict distribution are
        summarized into a :class:`~kaine.experiment.stability.StabilityReport`.
    ticks:
        Ticks per arm per run (kept configurable so tests can stay fast/offline).
    tolerance:
        Maximum coefficient of variation for the effect metric to count as stable.
        Defaults to exact stability (0.0) because the runner is deterministic per
        seed; raise it for genuinely nondeterministic experiments.
    base_config:
        Optional base config whose non-seed parameters (gain, plv_window, …) are
        held fixed across seeds. The seed and ``ticks`` are overridden per run.

    Returns
    -------
    StabilityReport
        Effect-metric mean / std / CV across seeds plus the verdict distribution
        and the stability verdict (stable iff CV within tolerance AND verdicts
        unanimous).
    """
    template = base_config or AblationConfig()

    def run_fn(seed: int) -> dict:
        config = AblationConfig(
            seed=seed,
            ticks=ticks,
            plv_window=template.plv_window,
            coherence_floor=template.coherence_floor,
            coherence_ceiling=template.coherence_ceiling,
            min_effect=template.min_effect,
            min_alignment=template.min_alignment,
            top_k=template.top_k,
            publication_threshold=template.publication_threshold,
        )
        # run_ablation re-seeds each arm internally via set_global_seed(config.seed),
        # so the harness's pinning is redundant-but-consistent here.
        return asyncio.run(run_ablation(config))

    return run_multi_seed(
        run_fn,
        seeds,
        metric_fn=_effect_metric,
        tolerance=tolerance,
    )


__all__ = ["run_ablation_stability", "HEADLINE_METRIC"]
