# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests that Hypnos no longer fires a standalone NARS belief-revision burst.

NARS is retired; Nous is pymdp now. A full maintenance cycle must NOT call
``nous_process.step(...)`` — replayed traces reach Nous via the NORMAL
cognitive-cycle path (re-injection -> syneidesis broadcast -> Nous pymdp
update), not a special step-burst.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.hypnos import FakeTrainer, Hypnos, VoiceAlignmentConfig
from kaine.modules.hypnos.voice_alignment import OPERATOR_APPROVED_ENV


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


class FakeMnemos:
    def __init__(self) -> None:
        self.replay_calls = 0

    async def consolidate_now(self) -> int:
        return 0

    def downscale_activations(self, factor: float) -> int:
        return 0

    async def replay_now(self) -> list:
        self.replay_calls += 1
        return []


class FakeThymos:
    async def affective_reset(self) -> None:
        return None


class StepSpyNous:
    """Records every call to step(); a non-zero count means a NARS-style
    belief-revision burst was fired during maintenance (regression)."""

    def __init__(self) -> None:
        self.step_calls: list[int] = []

    @property
    def running(self) -> bool:
        return True

    async def step(self, n: int) -> list[str]:
        self.step_calls.append(n)
        return ["belief"]


@pytest.mark.asyncio
async def test_no_nar_burst_during_full_maintenance_cycle(bus: AsyncBus, tmp_path: Path):
    nous = StepSpyNous()
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
    )
    hypnos = Hypnos(
        bus,
        mnemos=FakeMnemos(),
        nous_process=nous,
        thymos=FakeThymos(),
        trainer=FakeTrainer(),
        voice_alignment_config=config,
    )

    summary = await hypnos.enter_sleep()

    # All five phases ran.
    assert len(summary["phases"]) == 5
    # The load-bearing assertion: no NARS step-burst was invoked.
    assert nous.step_calls == [], (
        f"NARS step-burst fired during maintenance: {nous.step_calls}"
    )
    # No phase is named for belief revision in the active pipeline.
    phase_names = {p["phase"] for p in summary["phases"]}
    assert "belief_revision" not in phase_names


@pytest.mark.asyncio
async def test_replay_reaches_workspace_not_via_burst(bus: AsyncBus, tmp_path: Path):
    """Replay drives the normal path (mnemos.replay_now invoked during the
    window); belief revision happens via the cognitive cycle, never a burst."""
    mnemos = FakeMnemos()
    nous = StepSpyNous()
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
    )
    hypnos = Hypnos(
        bus,
        mnemos=mnemos,
        nous_process=nous,
        thymos=FakeThymos(),
        trainer=FakeTrainer(),
        voice_alignment_config=config,
    )
    await hypnos.enter_sleep()
    # Replay ran through the normal deep-consolidation window path.
    assert mnemos.replay_calls == 1
    # And still no special burst.
    assert nous.step_calls == []
