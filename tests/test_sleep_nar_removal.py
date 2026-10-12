# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The sleep module fires no belief-revision burst and takes no planning module collaborator.

NARS is retired; the planning module is pymdp now. Replayed traces reach the planning module via the NORMAL
cognitive-cycle path (re-injection -> workspace broadcast -> planning module pymdp
update), so the sleep module has no planning module argument and no step-burst setting.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.sleep import FakeTrainer, Sleep, VoiceAlignmentConfig
from kaine.modules.sleep.voice_alignment import OPERATOR_APPROVED_ENV


@pytest.fixture(autouse=True)
def _voice_alignment_opt_in(monkeypatch):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class FakeEpisodicMemory:
    def __init__(self) -> None:
        self.replay_calls = 0

    async def consolidate_now(self) -> int:
        return 0

    async def downscale(self, protect=()):
        return {"n_new": 0, "factor": 1.0, "protected": len(list(protect)), "total_before": 0.0, "total_after": 0.0, "silent": 0}

    async def replay_now(self) -> list:
        self.replay_calls += 1
        return []


class FakeAffect:
    async def affective_reset(self) -> None:
        return None


def test_sleep_takes_no_nous_collaborator():
    params = inspect.signature(Sleep.__init__).parameters
    assert "nous_process" not in params
    assert "nous_step_burst" not in params


@pytest.mark.asyncio
async def test_no_nar_burst_during_full_maintenance_cycle(bus: AsyncBus, tmp_path: Path):
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
    )
    sleep = Sleep(
        bus,
        episodic_memory=FakeEpisodicMemory(),
        affect=FakeAffect(),
        trainer=FakeTrainer(),
        voice_alignment_config=config,
    )

    summary = await sleep.enter_sleep()

    # All five phases ran.
    assert len(summary["phases"]) == 5
    # No phase is named for belief revision in the active pipeline.
    phase_names = {p["phase"] for p in summary["phases"]}
    assert "belief_revision" not in phase_names


@pytest.mark.asyncio
async def test_replay_reaches_workspace_not_via_burst(bus: AsyncBus, tmp_path: Path):
    """Replay drives the normal path (mnemos.replay_now invoked during the window)."""
    episodic_memory = FakeEpisodicMemory()
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
    )
    sleep = Sleep(
        bus,
        episodic_memory=episodic_memory,
        affect=FakeAffect(),
        trainer=FakeTrainer(),
        voice_alignment_config=config,
    )
    await sleep.enter_sleep()
    # Replay ran through the normal deep-consolidation window path.
    assert episodic_memory.replay_calls == 1
