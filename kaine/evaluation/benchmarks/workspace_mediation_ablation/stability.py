# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Multi-seed stability adapter for the workspace-mediation development harness.

Runs the ablation across several seeds and summarizes whether its headline
effect (dIG) and its WIN/NULL/NEGATIVE verdict are stable, via the boundary-
neutral :func:`kaine.experiment.stability.run_multi_seed`.

The runner is deterministic per seed, but the real forward-model trajectories
are seed-varying. An unstable report across seeds (verdicts that flip, a wide
effect spread) is a real finding: it says the minimal two-module setup's
information-gain contrast is seed-sensitive and constrains the operating
envelope. Read the report; do not assume unanimity.

This module lives under ``kaine/evaluation/`` and may import
``kaine.experiment`` (the sidecar boundary forbids CORE importing evaluation,
never the reverse).
"""
from __future__ import annotations

import asyncio
import dataclasses
import math
from typing import Sequence

from kaine.evaluation.benchmarks.workspace_mediation_ablation.runner import (
    MediationConfig,
    run_ablation,
)
from kaine.evaluation.benchmarks.workspace_mediation_ablation.stimulus import (
    COUPLED_STIMULUS,
    MediationStimulus,
)
from kaine.experiment.stability import StabilityReport, run_multi_seed

HEADLINE_METRIC = "dig"


def _effect_metric(result: dict) -> float:
    """The headline effect the verdict turns on (0.0 when undefined)."""
    delta = result["effect"].get("dig")
    return float(delta) if delta is not None and not math.isnan(delta) else 0.0


def run_mediation_stability(
    seeds: Sequence[int],
    *,
    ticks: int = 160,
    warmup_ticks: int = 40,
    tolerance: float = 1.0,
    stimulus: MediationStimulus = COUPLED_STIMULUS,
    base_config: MediationConfig | None = None,
) -> StabilityReport:
    """Run the mediation ablation across ``seeds`` and report stability.

    ``tolerance`` is the maximum coefficient of variation of dIG that still
    counts as stable. It defaults high because the information-gain effect is
    genuinely seed-varying here, and the honest headline is the verdict
    distribution, not a claim of tight reproducibility across seeds. Lower it
    only if you expect seed-robustness.
    """
    template = base_config or MediationConfig()

    def run_fn(seed: int) -> dict:
        config = dataclasses.replace(
            template,
            seed=seed,
            ticks=ticks,
            warmup_ticks=warmup_ticks,
        )
        return asyncio.run(run_ablation(config, stimulus=stimulus))

    return run_multi_seed(
        run_fn,
        seeds,
        metric_fn=_effect_metric,
        tolerance=tolerance,
    )


__all__ = ["run_mediation_stability", "HEADLINE_METRIC"]
