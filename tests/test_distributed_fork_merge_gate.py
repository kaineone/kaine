# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from kaine.distributed.fork_being import (
    build_forked_being_job,
    forked_being_gate,
)
from kaine.distributed.job import ArtifactKind, JobKind
from kaine.lifecycle.divergence import DivergenceAssessment
from kaine.lifecycle.fork_merge_gate import (
    WelfareSignals,
    assess_fork,
    gated_merge,
)
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


# --------------------------------------------------------------------------- #
# Fork-merge welfare gate
# --------------------------------------------------------------------------- #
def test_instrument_fork_is_merged_and_discarded(tmp_path):
    mgr, parent_id, fork_id = _parent_and_fork(tmp_path)
    surfaced: list[dict] = []
    verdict = gated_merge(
        mgr, parent_id, fork_id, assessment=_NOT_DIVERGED, surface=surfaced.append
    )
    assert verdict.individuated is False
    assert verdict.fork_discarded is True
    assert verdict.fork_preserved is False
    assert verdict.requires_operator_decommission is False
    # Knowledge was still assimilated (a real merge produced a snapshot).
    assert verdict.merged_snapshot_id is not None
    assert surfaced and surfaced[0]["fork_discarded"] is True


def test_individuated_fork_is_preserved_not_terminated(tmp_path):
    mgr, parent_id, fork_id = _parent_and_fork(tmp_path)
    preserved: list[str] = []
    verdict = gated_merge(
        mgr,
        parent_id,
        fork_id,
        assessment=_DIVERGED,
        preserve_fn=preserved.append,
    )
    assert verdict.individuated is True
    # Parent took the knowledge one-directionally...
    assert verdict.merged_snapshot_id is not None
    # ...but the fork is preserved, NOT terminated by the merge.
    assert verdict.fork_preserved is True
    assert verdict.fork_discarded is False
    assert verdict.requires_operator_decommission is True
    assert preserved == [fork_id]


def test_welfare_signal_alone_marks_individuation(tmp_path):
    mgr, parent_id, fork_id = _parent_and_fork(tmp_path)
    verdict = gated_merge(
        mgr,
        parent_id,
        fork_id,
        assessment=_NOT_DIVERGED,
        welfare=WelfareSignals(prefers_to_continue=True),
    )
    # Even with divergence below threshold, a welfare interest in continuing
    # triggers the preserve path.
    assert verdict.individuated is True
    assert verdict.fork_preserved is True


def test_assess_fork_reads_consolidation_divergence(tmp_path):
    # A fork whose organ-level consolidation divergence crossed threshold reads
    # as individuated via the SAME divergence gate used by decommission.
    state_root = tmp_path / "fork_state"
    (state_root / "hypnos").mkdir(parents=True)
    (state_root / "hypnos" / "consolidation_divergence.json").write_text(
        json.dumps({"divergence_rate": 0.9, "divergence_magnitude": 0.6})
    )
    assessment = assess_fork(
        fork_state_root=state_root, eval_root=tmp_path / "eval"
    )
    assert assessment.diverged is True


def test_assess_fork_empty_state_is_not_diverged(tmp_path):
    assessment = assess_fork(
        fork_state_root=tmp_path / "empty", eval_root=tmp_path / "eval"
    )
    assert assessment.diverged is False


# --------------------------------------------------------------------------- #
# Forked-being job kind
# --------------------------------------------------------------------------- #
def test_build_forked_being_job_carries_fork_directive_and_time_scale():
    job = build_forked_being_job(
        "snap-123", "explore the corpus", time_scale=2.0
    )
    assert job.kind is JobKind.FORKED_BEING
    assert job.fork_snapshot_id == "snap-123"
    assert job.directive == "explore the corpus"
    assert job.time_scale == 2.0
    assert job.is_entity_bearing is True
    assert job.expected_artifact.kind is ArtifactKind.FORK_SNAPSHOT
    # The timing profile is packed into inputs (per-fork dilation).
    assert job.inputs["timing"]["time_scale"] == 2.0


def test_build_forked_being_job_rejects_bad_time_scale():
    with pytest.raises(Exception):
        build_forked_being_job("snap-1", "do a thing", time_scale=0.0)


def test_build_forked_being_job_requires_directive():
    with pytest.raises(ValueError):
        build_forked_being_job("snap-1", "   ")


def test_forked_being_gate_accepts_wellformed_snapshot(tmp_path):
    job = build_forked_being_job("snap-1", "run")
    snap = tmp_path / "post_run.json"
    snap.write_text(json.dumps({"id": "x", "modules": {"eidolon": {"name": "K"}}}))
    outcome = forked_being_gate(job, snap)
    assert outcome.passed is True


def test_forked_being_gate_rejects_empty_snapshot(tmp_path):
    job = build_forked_being_job("snap-1", "run")
    snap = tmp_path / "post_run.json"
    snap.write_text(json.dumps({"id": "x", "modules": {}}))
    outcome = forked_being_gate(job, snap)
    assert outcome.passed is False


def test_forked_being_gate_rejects_missing_snapshot(tmp_path):
    job = build_forked_being_job("snap-1", "run")
    outcome = forked_being_gate(job, tmp_path / "nope.json")
    assert outcome.passed is False


def test_verification_gate_routes_forked_being_through_fork_gate(tmp_path):
    from kaine.distributed.gate import VerificationGate

    job = build_forked_being_job("snap-1", "run")
    snap = tmp_path / "post_run.json"
    snap.write_text(json.dumps({"id": "x", "modules": {"eidolon": {}}}))
    gate = VerificationGate(fork_gate=forked_being_gate)
    result = gate.verify(job, snap)
    assert result.promotable is True
    assert result.fork is not None and result.fork.passed is True
