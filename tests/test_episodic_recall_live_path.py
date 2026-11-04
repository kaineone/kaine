# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Live-path integration test: a planted thought comes back with content on, not with it off (PR 4, task 6.1)."""

from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.episodic_memory import (
    EpisodicMemory,
    EpisodicMemoryCore,
    FakeEmbedder,
    InMemoryStorage,
)
from kaine.faithful.felt import _f_episodic_memory_recall


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


async def _new_episodic_memory(bus: AsyncBus, *, capacity: int = 4, **kwargs) -> EpisodicMemory:
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    core = EpisodicMemoryCore(embedder=emb, storage=storage, short_term_capacity=capacity)
    return EpisodicMemory(bus, core=core, **kwargs)


def _snapshot(events=None, tick_index=0) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=tick_index,
        selected_events=events or [],
        inhibited=False,
    )


def _affect_event(eid="e-affect"):
    return eid, Event(
        source="affect",
        type="affect.state",
        payload={"state": {"valence": 0.9, "arousal": 0.2}, "drives": {}, "emotion": "serenity"},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


async def _recall_events(bus: AsyncBus) -> list:
    entries = await bus.read("episodic_memory.out", last_id="0")
    return [e for _, e in entries if e.type == "episodic_memory.recall"]


@pytest.mark.asyncio
async def test_planted_thought_recalled_with_content(bus: AsyncBus):
    """A trace consolidated into the persisted collection is recalled with
    content when recall_content=True: the recall event carries members,
    an age band, and the felt rendering starts with 'I remember'."""
    em = await _new_episodic_memory(
        bus,
        capacity=4,
        recall_content=True,
        recall_cooldown_s=0.0,
        recall_exclude_recent_s=0.0,
    )
    await em.initialize()
    try:
        snapshot = _snapshot([_affect_event()])

        await em.on_workspace(snapshot)
        await em.core.consolidate_now()
        await em.on_workspace(snapshot)

        recalls = await _recall_events(bus)
        assert recalls
        last_recall = recalls[-1]

        assert last_recall.payload["count"] >= 1
        assert isinstance(last_recall.payload.get("content"), dict)
        assert isinstance(last_recall.payload["content"].get("members"), list)
        assert last_recall.payload["content"]["members"]
        assert isinstance(last_recall.payload["content"].get("age_band"), str)

        rendered = _f_episodic_memory_recall(last_recall.payload)
        assert rendered.startswith("I remember")
    finally:
        await em.shutdown()


@pytest.mark.asyncio
async def test_planted_thought_recalled_without_content(bus: AsyncBus):
    """Same setup, but recall_content=False: the recall event carries no
    content key and the felt rendering does NOT say 'I remember'."""
    em = await _new_episodic_memory(
        bus,
        capacity=4,
        recall_content=False,
        recall_cooldown_s=0.0,
        recall_exclude_recent_s=0.0,
    )
    await em.initialize()
    try:
        snapshot = _snapshot([_affect_event()])

        await em.on_workspace(snapshot)
        await em.core.consolidate_now()
        await em.on_workspace(snapshot)

        recalls = await _recall_events(bus)
        assert recalls
        last_recall = recalls[-1]

        assert last_recall.payload["count"] >= 1
        assert "content" not in last_recall.payload

        rendered = _f_episodic_memory_recall(last_recall.payload)
        assert not rendered.startswith("I remember")
    finally:
        await em.shutdown()
