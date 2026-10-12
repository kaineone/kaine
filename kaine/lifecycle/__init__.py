# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.lifecycle.manager import (
    AdapterMerger,
    FakeAdapterMerger,
    ForkManager,
)
from kaine.lifecycle.snapshot import ForkSnapshot
from kaine.lifecycle.strategies import (
    AffectMergeStrategy,
    EpisodicMemoryMergeStrategy,
    MergeStrategy,
    PlanningMergeStrategy,
    SelfModelMergeStrategy,
    UnionMergeStrategy,
    default_strategies,
)

__all__ = [
    "AdapterMerger",
    "SelfModelMergeStrategy",
    "FakeAdapterMerger",
    "ForkManager",
    "ForkSnapshot",
    "MergeStrategy",
    "EpisodicMemoryMergeStrategy",
    "PlanningMergeStrategy",
    "AffectMergeStrategy",
    "UnionMergeStrategy",
    "default_strategies",
]
