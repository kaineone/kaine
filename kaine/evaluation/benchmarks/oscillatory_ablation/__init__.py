# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Controlled offline oscillatory-ablation runner (oscillatory-binding).

Runs the cognitive cycle layer-enabled vs layer-disabled under the same seed and
the same fixed scripted input in deterministic mode, and emits a verdict for the
measured effect of precision modulation on selection. The determinism keystone
(``CognitiveCycle(deterministic=True)`` over a scripted bus) makes a run
bit-for-bit reproducible, so the ONLY difference between the two arms is the
coherence layer — any trajectory difference is attributable to it alone.

Offline: drives only the engine + Syneidesis over a scripted in-memory bus. No
live modules, no entity boot, no network.
"""
from __future__ import annotations

from kaine.evaluation.benchmarks.oscillatory_ablation.runner import (
    AblationConfig,
    format_summary,
    run_ablation,
    write_jsonl,
)

__all__ = [
    "AblationConfig",
    "run_ablation",
    "format_summary",
    "write_jsonl",
]
