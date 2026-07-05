# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Controlled, seeded, offline runners for the passive measuring instruments.

Three of KAINE's instruments — the A/B-divergence meter, the memory-coherence
prober, and the self-model (Eidolon) accuracy scorer — normally run as PASSIVE
live sidecars (they record opportunistically while the entity runs). This package
promotes each to a CONTROLLED experiment of the same shape as the active-inference
benchmark and the oscillatory-ablation runner: it sets a fixed stimulus battery
and a seed, runs the instrument's production control seam offline (deterministic /
echo clients + an in-memory Mnemos only — no live modules, no network, no entity
boot), and emits a shared-schema ``Verdict`` plus seeded JSONL.

Each runner exposes ``run_*(config) -> dict`` (records / summary / verdict),
``write_jsonl``, and ``format_summary``; the package ``__main__`` dispatches to one
of the three by name.
"""
from __future__ import annotations

from kaine.evaluation.benchmarks.instrument_runners.ab_divergence_runner import (
    ABDivergenceConfig,
    format_summary as format_ab_summary,
    run_ab_divergence,
)
from kaine.evaluation.benchmarks.instrument_runners.memory_coherence_runner import (
    MemoryCoherenceConfig,
    format_summary as format_memory_summary,
    run_memory_coherence,
)
from kaine.evaluation.benchmarks.instrument_runners.self_model_runner import (
    SelfModelConfig,
    format_summary as format_self_model_summary,
    run_self_model,
)
from kaine.evaluation.benchmarks.instrument_runners.shared import write_jsonl

__all__ = [
    "ABDivergenceConfig",
    "run_ab_divergence",
    "format_ab_summary",
    "MemoryCoherenceConfig",
    "run_memory_coherence",
    "format_memory_summary",
    "SelfModelConfig",
    "run_self_model",
    "format_self_model_summary",
    "write_jsonl",
]
