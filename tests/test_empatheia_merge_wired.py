# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from typing import Any

import pytest

from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.strategies import (
    EmpatheiaMergeStrategy,
    default_strategies,
)


class FakeModule:
    def __init__(self, name: str, initial_state: dict[str, Any] | None = None) -> None:
        self.name = name
        self._state = dict(initial_state or {})

    def serialize(self) -> dict[str, Any]:
        return dict(self._state)

    def deserialize(self, state: dict[str, Any]) -> None:
        self._state = dict(state)


class FakeRegistry:
    def __init__(self, modules: list[FakeModule]) -> None:
        self._modules = list(modules)

    def all_modules(self):
        return iter(self._modules)


def _profile(
    interaction_count: int,
    emotion_histogram: dict[str, float],
    behavioral_summary: dict[str, float],
    reliability: float,
    first_seen: float,
    last_seen: float,
) -> dict[str, Any]:
    return {
        "id": "agent-1",
        "label": "x",
        "interaction_count": interaction_count,
        "emotion_histogram": emotion_histogram,
        "behavioral_summary": behavioral_summary,
        "reliability": reliability,
        "first_seen": first_seen,
        "last_seen": last_seen,
    }


def test_default_strategies_registers_empatheia():
    assert isinstance(default_strategies()["empatheia"], EmpatheiaMergeStrategy)


def test_fork_manager_merge_reconciles_empatheia(tmp_path):
    mgr = ForkManager(tmp_path)

    profile_a = _profile(
        interaction_count=5,
        emotion_histogram={"joy": 1.0},
        behavioral_summary={"approach": 1.0},
        reliability=1.0,
        first_seen=10.0,
        last_seen=50.0,
    )
    profile_b = _profile(
        interaction_count=3,
        emotion_histogram={"fear": 1.0},
        behavioral_summary={"approach": 0.0},
        reliability=0.5,
        first_seen=5.0,
        last_seen=40.0,
    )

    reg_a = FakeRegistry([FakeModule("empatheia", {"profiles": {"agent-1": profile_a}})])
    reg_b = FakeRegistry([FakeModule("empatheia", {"profiles": {"agent-1": profile_b}})])

    snap_a = mgr.snapshot(reg_a)
    snap_b = mgr.snapshot(reg_b)

    merged = mgr.merge(snap_a.id, snap_b.id)
    profile = merged.modules["empatheia"]["profiles"]["agent-1"]

    assert profile["interaction_count"] == 8
    assert profile["emotion_histogram"]["joy"] == pytest.approx(5 / 8)
    assert profile["emotion_histogram"]["fear"] == pytest.approx(3 / 8)
    assert profile["behavioral_summary"]["approach"] == pytest.approx(5 / 8)
    assert profile["reliability"] == pytest.approx((5 / 8 * 1.0) + (3 / 8 * 0.5))
    assert profile["first_seen"] == 5.0
    assert profile["last_seen"] == 50.0


def test_merge_reloads_from_disk(tmp_path):
    mgr = ForkManager(tmp_path)

    profile_a = _profile(
        interaction_count=5,
        emotion_histogram={"joy": 1.0},
        behavioral_summary={"approach": 1.0},
        reliability=1.0,
        first_seen=10.0,
        last_seen=50.0,
    )
    profile_b = _profile(
        interaction_count=3,
        emotion_histogram={"fear": 1.0},
        behavioral_summary={"approach": 0.0},
        reliability=0.5,
        first_seen=5.0,
        last_seen=40.0,
    )

    reg_a = FakeRegistry([FakeModule("empatheia", {"profiles": {"agent-1": profile_a}})])
    reg_b = FakeRegistry([FakeModule("empatheia", {"profiles": {"agent-1": profile_b}})])

    snap_a = mgr.snapshot(reg_a)
    snap_b = mgr.snapshot(reg_b)

    merged = mgr.merge(snap_a.id, snap_b.id)

    reloaded = mgr.load(merged.id)
    assert reloaded.modules["empatheia"]["profiles"]["agent-1"]["interaction_count"] == 8
