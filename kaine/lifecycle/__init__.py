# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.lifecycle.manager import (
    AdapterMerger,
    FakeAdapterMerger,
    ForkManager,
)
from kaine.lifecycle.snapshot import ForkSnapshot
from kaine.lifecycle.strategies import (
    EidolonMergeStrategy,
    MergeStrategy,
    MnemosMergeStrategy,
    NousMergeStrategy,
    ThymosMergeStrategy,
    UnionMergeStrategy,
    default_strategies,
)

__all__ = [
    "AdapterMerger",
    "EidolonMergeStrategy",
    "FakeAdapterMerger",
    "ForkManager",
    "ForkSnapshot",
    "MergeStrategy",
    "MnemosMergeStrategy",
    "NousMergeStrategy",
    "ThymosMergeStrategy",
    "UnionMergeStrategy",
    "default_strategies",
]
