# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kaine.lifecycle.divergence import DivergenceAssessment
from kaine.lifecycle.fork_merge_gate import gated_merge
from kaine.lifecycle.manager import ForkManager


class FakeModule:
    def __init__(self, name: str, state: dict[str, Any] | None = None) -> None:
        self.name = name
        self._state = dict(state or {})

    def serialize(self) -> dict[str, Any]:
        return dict(self._state)

    def deserialize(self, state: dict[str, Any]) -> None:
        self._state = dict(state)


class FakeRegistry:
    def __init__(self, modules: list[FakeModule]) -> None:
        self._modules = list(modules)

    def all_modules(self):
        return iter(self._modules)


def _parent_and_fork(tmp_path: Path) -> tuple[ForkManager, str, str]:
    mgr = ForkManager(tmp_path / "forks")
    parent = mgr.snapshot(
        FakeRegistry([FakeModule("eidolon", {"name": "Kaine Doe"})]), label="parent"
    )
    fork = mgr.fork(parent.id, label="temp-being")
    return mgr, parent.id, fork.id


_NOT_DIVERGED = DivergenceAssessment(
    diverged=False, signals={"individuation_significant": False}, summary="NOT DIVERGED"
)
_DIVERGED = DivergenceAssessment(
    diverged=True, signals={"individuation_significant": True}, summary="DIVERGED"
)


def test_short_lived_not_diverged_fork_is_discarded(tmp_path: Path) -> None:
    mgr, parent_id, fork_id = _parent_and_fork(tmp_path)
    verdict = gated_merge(
        mgr,
        parent_id,
        fork_id,
        assessment=_NOT_DIVERGED,
        fork_lived_s=0.0,
    )
    assert verdict.individuated is False
    assert verdict.fork_discarded is True
    assert verdict.fork_preserved is False
    assert verdict.signals["preserved_for_lived_time"] is False


def test_min_lived_not_diverged_fork_is_preserved_for_time(tmp_path: Path) -> None:
    mgr, parent_id, fork_id = _parent_and_fork(tmp_path)
    verdict = gated_merge(
        mgr,
        parent_id,
        fork_id,
        assessment=_NOT_DIVERGED,
        fork_lived_s=1800.0,
    )
    assert verdict.individuated is True
    assert verdict.fork_preserved is True
    assert verdict.signals["preserved_for_lived_time"] is True
    assert verdict.signals["fork_lived_s"] == 1800.0
    assert verdict.signals["fork_preserve_min_lived_s"] == 1800.0


@pytest.mark.parametrize("lived", [None, float("nan")])
def test_unknown_or_non_finite_lived_time_preserves_by_default(
    tmp_path: Path, lived: float | None
) -> None:
    mgr, parent_id, fork_id = _parent_and_fork(tmp_path)
    verdict = gated_merge(
        mgr,
        parent_id,
        fork_id,
        assessment=_NOT_DIVERGED,
        fork_lived_s=lived,
    )
    assert verdict.fork_preserved is True
    assert verdict.signals["fork_lived_s"] is lived


def test_diverged_fork_preserved_not_for_lived_time(tmp_path: Path) -> None:
    mgr, parent_id, fork_id = _parent_and_fork(tmp_path)
    verdict = gated_merge(
        mgr,
        parent_id,
        fork_id,
        assessment=_DIVERGED,
        fork_lived_s=0.0,
    )
    assert verdict.individuated is True
    assert verdict.fork_preserved is True
    assert verdict.signals["preserved_for_lived_time"] is False
    assert verdict.signals["fork_lived_s"] == 0.0
