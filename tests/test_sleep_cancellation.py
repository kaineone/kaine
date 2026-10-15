# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Sleep ends with the affective reset and reports its end on every path,
including a cancel, and the phases run in the paper's order.
"""

import asyncio

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.episodic_memory import (
    EpisodicMemory,
    EpisodicMemoryCore,
    FakeEmbedder,
    InMemoryStorage,
)
from kaine.modules.sleep import FakeTrainer, Sleep, VoiceAlignmentConfig


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class RecordingAffect:
    def __init__(
        self,
        calls: list[str] | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.calls = calls if calls is not None else []
        self.gate = gate
        self.resets = 0
        self.started = asyncio.Event()

    async def affective_reset(self) -> None:
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        self.resets += 1
        self.calls.append("reset")


class RecordingEpisodicMemory:
    def __init__(
        self,
        calls: list[str],
        hang_in: str | None = None,
    ) -> None:
        self.calls = calls
        self.hang_in = hang_in
        self.entered = asyncio.Event()

    async def consolidate_now(self) -> int:
        self.calls.append("consolidate")
        if self.hang_in == "consolidate":
            self.entered.set()
            await asyncio.Event().wait()
        return 0

    def open_replay_window(self) -> None:
        self.calls.append("open")

    def close_replay_window(self) -> None:
        self.calls.append("close")

    async def replay_now(self) -> list:
        self.calls.append("replay")
        if self.hang_in == "replay":
            self.entered.set()
            await asyncio.Event().wait()
        return []

    async def downscale(self, protect=()):
        self.calls.append("downscale")
        return {"n_new": 0, "factor": 1.0, "protected": len(protect), "total_before": 0.0, "total_after": 0.0, "silent": 0}

    async def select_cross_period_traces(
        self,
        *,
        periods: int,
        per_period: int,
    ) -> dict:
        self.calls.append("associative")
        return {}


def _make_sleep(bus, tmp_path, *, episodic_memory, affect, associative=False):
    return Sleep(
        bus,
        episodic_memory=episodic_memory,
        affect=affect,
        trainer=FakeTrainer(),
        voice_alignment_config=VoiceAlignmentConfig(
            intent_log_path=tmp_path / "intent.jsonl",
            adapter_output_dir=tmp_path / "adapters",
            enabled=False,
        ),
        perception_desired_path=tmp_path / "perception_desired.json",
        associative_replay_enabled=associative,
    )


async def _completed_events(bus) -> list[dict]:
    entries = await bus.read("sleep.out", last_id="0")
    return [e.payload for _, e in entries if e.type == "sleep.sleep.completed"]


async def _cancel_and_expect(task: asyncio.Task) -> None:
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_sleep_runs_the_phases_in_the_paper_order(bus, tmp_path):
    calls: list[str] = []
    episodic_memory = RecordingEpisodicMemory(calls)
    affect = RecordingAffect(calls)
    sleep = _make_sleep(
        bus,
        tmp_path,
        episodic_memory=episodic_memory,
        affect=affect,
        associative=True,
    )

    original_voice = sleep._run_voice_alignment

    async def _voice():
        calls.append("voice")
        return await original_voice()

    sleep._run_voice_alignment = _voice

    await sleep.enter_sleep()

    assert calls == [
        "consolidate",
        "open",
        "replay",
        "close",
        "downscale",
        "associative",
        "voice",
        "reset",
    ]


@pytest.mark.asyncio
async def test_cancel_during_voice_alignment_still_resets_and_reports(
    bus, tmp_path
):
    episodic_memory = RecordingEpisodicMemory([])
    affect = RecordingAffect()
    sleep = _make_sleep(bus, tmp_path, episodic_memory=episodic_memory, affect=affect)

    entered = asyncio.Event()

    async def _hang():
        entered.set()
        await asyncio.Event().wait()

    sleep._run_voice_alignment = _hang

    task = asyncio.create_task(sleep.enter_sleep())
    await asyncio.wait_for(entered.wait(), 5)
    await _cancel_and_expect(task)

    assert affect.resets == 1
    completed = await _completed_events(bus)
    assert len(completed) == 1
    assert completed[0]["aborted"] is True
    assert completed[0]["reason"] == "CancelledError"
    assert not sleep.is_sleeping


@pytest.mark.asyncio
async def test_cancel_in_phase_one_still_resets_and_reports(bus, tmp_path):
    episodic_memory = RecordingEpisodicMemory(calls=[], hang_in="consolidate")
    affect = RecordingAffect()
    sleep = _make_sleep(bus, tmp_path, episodic_memory=episodic_memory, affect=affect)

    task = asyncio.create_task(sleep.enter_sleep())
    await asyncio.wait_for(episodic_memory.entered.wait(), 5)
    await _cancel_and_expect(task)

    assert affect.resets == 1
    completed = await _completed_events(bus)
    assert len(completed) == 1
    assert completed[0]["aborted"] is True
    assert completed[0]["reason"] == "CancelledError"


@pytest.mark.asyncio
async def test_cancel_mid_replay_closes_the_replay_window(bus, tmp_path):
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    core = EpisodicMemoryCore(
        embedder=emb,
        storage=InMemoryStorage(latent_dim=8),
        short_term_capacity=8,
    )
    episodic_memory = EpisodicMemory(bus, core=core)
    affect = RecordingAffect()
    sleep = _make_sleep(bus, tmp_path, episodic_memory=episodic_memory, affect=affect)

    seen_open: list[bool] = []
    entered = asyncio.Event()

    async def _hang_replay():
        seen_open.append(episodic_memory.replay_engine.window_active)
        entered.set()
        await asyncio.Event().wait()

    episodic_memory.replay_now = _hang_replay

    task = asyncio.create_task(sleep.enter_sleep())
    await asyncio.wait_for(entered.wait(), 5)
    await _cancel_and_expect(task)

    assert seen_open == [True]
    assert not episodic_memory.replay_engine.window_active
    assert affect.resets == 1
    completed = await _completed_events(bus)
    assert len(completed) == 1
    assert completed[0]["aborted"] is True
    assert completed[0]["reason"] == "CancelledError"


@pytest.mark.asyncio
async def test_affective_reset_survives_a_second_cancel(bus, tmp_path):
    gate = asyncio.Event()
    affect = RecordingAffect(gate=gate)
    sleep = _make_sleep(
        bus,
        tmp_path,
        episodic_memory=RecordingEpisodicMemory([]),
        affect=affect,
    )

    entered = asyncio.Event()

    async def _hang():
        entered.set()
        await asyncio.Event().wait()

    sleep._run_voice_alignment = _hang

    task = asyncio.create_task(sleep.enter_sleep())
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    await asyncio.wait_for(affect.started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert affect.resets == 0
    gate.set()
    for _ in range(20):
        if affect.resets == 1:
            break
        await asyncio.sleep(0)
    assert affect.resets == 1
