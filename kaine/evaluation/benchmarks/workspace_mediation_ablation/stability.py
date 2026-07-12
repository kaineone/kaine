# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Multi-seed stability adapter for the workspace-mediation ablation.

Runs the ablation across several seeds and summarizes whether its headline effect
(``coupling_delta``) and its WIN/NULL/NEGATIVE verdict are stable, via the
boundary-neutral :func:`kaine.experiment.stability.run_multi_seed`.

The runner is deterministic *per seed*, but — unlike the fully-scripted
oscillatory ablation — the effect here depends on real forward-model trajectories
whose relationship to Soma's error is genuinely seed-varying. So an *unstable*
report across seeds (verdicts that flip, a wide effect spread) is a real finding:
it says the minimal two-module setup's coupling is seed-sensitive and constrains
the operating envelope, exactly the multi-seed caution the methodology calls for.
Read the report; do not assume unanimity.

This module lives under ``kaine/evaluation/`` and may import ``kaine.experiment``
(the sidecar boundary forbids CORE importing evaluation, never the reverse).
"""
from __future__ import annotations

import asyncio
import math
from typing import Sequence

from kaine.evaluation.benchmarks.workspace_mediation_ablation.runner import (
    MediationConfig,
    run_ablation,
)
from kaine.evaluation.benchmarks.workspace_mediation_ablation.stimulus import (
    SOMA_SALIENT_STIMULUS,
    MediationStimulus,
)
from kaine.experiment.stability import StabilityReport, run_multi_seed

HEADLINE_METRIC = "coupling_delta"


def _effect_metric(result: dict) -> float:
    """The headline effect the verdict turns on (0.0 when undefined/underpowered)."""
    delta = result["effect"].get("coupling_delta")
    return float(delta) if delta is not None and not math.isnan(delta) else 0.0


def run_mediation_stability(
    seeds: Sequence[int],
    *,
    ticks: int = 24,
    tolerance: float = 1.0,
    stimulus: MediationStimulus = SOMA_SALIENT_STIMULUS,
    base_config: MediationConfig | None = None,
) -> StabilityReport:
    """Run the mediation ablation across ``seeds`` and report stability.

    ``tolerance`` is the maximum coefficient of variation of ``coupling_delta``
    that still counts as stable. It defaults high (1.0) because — unlike a
    scripted ablation — the coupling effect is genuinely seed-varying here, and
    the honest headline is the verdict distribution, not a claim of tight
    reproducibility across seeds. Lower it only if you expect seed-robustness.
    """
    template = base_config or MediationConfig()

    def run_fn(seed: int) -> dict:
        config = MediationConfig(
            seed=seed,
            ticks=ticks,
            top_k=template.top_k,
            publication_threshold=template.publication_threshold,
            window=template.window,
            min_effect=template.min_effect,
            soma_units=template.soma_units,
            chronos_units=template.chronos_units,
            max_events=template.max_events,
            char_budget=template.char_budget,
        )
        return asyncio.run(run_ablation(config, stimulus=stimulus))

    return run_multi_seed(
        run_fn,
        seeds,
        metric_fn=_effect_metric,
        tolerance=tolerance,
    )


__all__ = ["run_mediation_stability", "HEADLINE_METRIC"]
