# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""KAINE evaluation sidecar.

Observes the bus, runs controlled comparisons, writes async JSONL
logs. NO core module imports from this package — observers subscribe
to bus events and read serialize() outputs only. The single coupling
point is `kaine/cycle/__main__.py`, which constructs and starts the
SidecarRegistry when `[evaluation].enabled` is true in kaine.toml.
"""
from kaine.evaluation.config import EvaluationConfig, load_evaluation_config
from kaine.evaluation.registry import SidecarRegistry
from kaine.evaluation.sink import AsyncJsonlSink

__all__ = [
    "AsyncJsonlSink",
    "EvaluationConfig",
    "SidecarRegistry",
    "load_evaluation_config",
]
