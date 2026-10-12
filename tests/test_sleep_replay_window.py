# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Integration tests for the sleep / episodic memory replay window path.

These run a real sleep against a real episodic memory module on the bus so the replay
window is exercised the same way a running system does.
"""

import asyncio
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.episodic_memory import (
    EpisodicMemory,
    EpisodicMemoryCore,
    FakeEmbedder,
    InMemoryStorage,
)
from kaine.modules.episodic_memory.replay import ReplayWindowError
from kaine.modules.sleep import FakeTrainer, Sleep, VoiceAlignmentConfig


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


async def _new_episodic_memory(bus: AsyncBus, *, capacity: int = 8, **kwargs) -> EpisodicMemory:
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    core = EpisodicMemoryCore(embedder=emb, storage=storage, short_term_capacity=capacity)
    return EpisodicMemory(bus, core=core, **kwargs)


class FakeAffect:
    """Stand-in affect module that only counts affective resets."""

    def __init__(self) -> None:
        self.resets = 0

    async def affective_reset(self) -> None:
        self.resets += 1


def _make_sleep(bus: AsyncBus, tmp_path: Path, episodic_memory: EpisodicMemory, affect: FakeAffect) -> Sleep:
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
    )


async def _drain_peer_poll(episodic_memory: EpisodicMemory, bus: AsyncBus) -> None:
    """Wait until the episodic memory module's peer poll has consumed every sleep event."""
    stream = episodic_memory._sleep_stream

    def _parse_id(raw):
        if isinstance(raw, bytes):
            raw = raw.decode()
        left, right = raw.split("-")
        return (int(left), int(right))

    deadline = asyncio.get_running_loop().time() + 2.0
    while asyncio.get_running_loop().time() < deadline:
        latest = await bus.client.xrevrange(stream, count=1)
        cursor = episodic_memory._peer_cursors.get(stream)
        if latest and cursor is not None:
            latest_id = latest[0][0]
            try:
                if _parse_id(cursor) >= _parse_id(latest_id):
                    return
            except Exception:
                # An id that does not parse yet means the poll has not caught up; keep waiting.
                pass
        await asyncio.sleep(0.02)
    pytest.fail("mnemos peer poll did not catch up")


@pytest.mark.asyncio
async def test_quick_phase_one_does_not_fail_phase_two(bus: AsyncBus, tmp_path: Path):
    """With no short-term traces phase 2 still opens and closes its replay window."""
    episodic_memory = await _new_episodic_memory(bus, replay_selection_top_k=5)
    await episodic_memory.initialize()
    try:
        sleep = _make_sleep(bus, tmp_path, episodic_memory, FakeAffect())
        summary = await sleep.enter_sleep()

        deep = next(p for p in summary["phases"] if p["phase"] == "deep_consolidation")
        assert deep["success"] is True
        assert deep["error"] is None
        assert deep["metadata"]["replay_events"] == 0
        assert summary["alert"] is False

        await _drain_peer_poll(episodic_memory, bus)
        assert not episodic_memory.replay_engine.window_active
        with pytest.raises(ReplayWindowError):
            await episodic_memory.replay_now()
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_sleep_replays_consolidated_traces_through_the_bus(bus: AsyncBus, tmp_path: Path):
    """Sleep deep consolidation replays the traces light consolidation moved."""
    episodic_memory = await _new_episodic_memory(
        bus,
        replay_selection_top_k=5,
        replay_redact_content=False,
    )
    await episodic_memory.initialize()
    try:
        for i in range(3):
            await episodic_memory.core.store(
                f"trace {i}",
                payload={"idx": i},
                affect={
                    "intensity": 0.2 * (i + 1),
                    "valence": 0.0,
                    "dominance": 0.0,
                },
                collection="short_term",
            )

        sleep = _make_sleep(bus, tmp_path, episodic_memory, FakeAffect())
        summary = await sleep.enter_sleep()

        deep = next(p for p in summary["phases"] if p["phase"] == "deep_consolidation")
        assert deep["success"] is True
        assert deep["metadata"]["replay_events"] == 3

        light = next(p for p in summary["phases"] if p["phase"] == "light_consolidation")
        assert light["metadata"]["entries_consolidated"] == 3

        assert summary["alert"] is False

        events = await bus.read("mnemos.out", last_id="0")
        replay_texts = {
            ev.payload["text"] for _, ev in events if ev.type == "mnemos.replay"
        }
        assert replay_texts == {"trace 0", "trace 1", "trace 2"}

        await _drain_peer_poll(episodic_memory, bus)
        assert not episodic_memory.replay_engine.window_active
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_sleep_ends_with_the_affective_reset(bus: AsyncBus, tmp_path: Path):
    """The final phase is affective_reset, and it invokes the affect module exactly once."""
    episodic_memory = await _new_episodic_memory(bus)
    await episodic_memory.initialize()
    try:
        affect = FakeAffect()
        sleep = _make_sleep(bus, tmp_path, episodic_memory, affect)
        summary = await sleep.enter_sleep()

        phases = [p["phase"] for p in summary["phases"]]
        assert phases == [
            "light_consolidation",
            "deep_consolidation",
            "associative_replay",
            "voice_alignment",
            "affective_reset",
        ]
        assert affect.resets == 1
    finally:
        await episodic_memory.shutdown()
