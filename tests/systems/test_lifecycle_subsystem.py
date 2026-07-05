# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Lifecycle subsystem: snapshot/restore round-trip + fork + merge."""
from __future__ import annotations

import pytest

from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.strategies import (
    EidolonMergeStrategy,
    MnemosMergeStrategy,
    UnionMergeStrategy,
)


class FakeModule:
    def __init__(self, name, state):
        self.name = name
        self._state = state

    def serialize(self):
        return dict(self._state)

    def deserialize(self, state):
        self._state = dict(state)


class FakeRegistry:
    def __init__(self, modules):
        self._modules = list(modules)

    def all_modules(self):
        return iter(self._modules)


def test_snapshot_restore_round_trip(tmp_path):
    fm = ForkManager(tmp_path)
    src = [FakeModule("soma", {"v": 1}), FakeModule("chronos", {"t": 7})]
    snap = fm.snapshot(FakeRegistry(src), label="root")
    fresh = [FakeModule("soma", {}), FakeModule("chronos", {})]
    fm.restore(snap.id, FakeRegistry(fresh))
    assert fresh[0].serialize() == {"v": 1}
    assert fresh[1].serialize() == {"t": 7}


def test_fork_with_shed(tmp_path):
    fm = ForkManager(tmp_path)
    parent = fm.snapshot(
        FakeRegistry(
            [FakeModule("soma", {"a": 1}), FakeModule("topos", {"b": 2})]
        )
    )
    child = fm.fork(parent.id, label="no-topos", shed=["topos"])
    assert "topos" not in child.modules
    assert "soma" in child.modules


def test_merge_applies_default_strategy(tmp_path):
    fm = ForkManager(tmp_path)
    a = fm.snapshot(FakeRegistry([FakeModule("custom", {"x": 1, "y": 2})]))
    b = fm.snapshot(FakeRegistry([FakeModule("custom", {"y": 99, "z": 3})]))
    merged = fm.merge(a.id, b.id)
    assert merged.modules["custom"] == {"x": 1, "y": 99, "z": 3}


def test_merge_invokes_specialized_strategies(tmp_path):
    fm = ForkManager(tmp_path)
    a = fm.snapshot(
        FakeRegistry([FakeModule("mnemos", {"short_term_size": 3, "collection_prefix": "mnemos_"})])
    )
    b = fm.snapshot(
        FakeRegistry([FakeModule("mnemos", {"short_term_size": 5, "collection_prefix": "mnemos_"})])
    )
    merged = fm.merge(a.id, b.id)
    assert merged.modules["mnemos"]["short_term_size"] == 8
