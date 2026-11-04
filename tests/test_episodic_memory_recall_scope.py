# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

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


def _snapshot(events=None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=events or [],
        inhibited=False,
    )


def _event(source="interoception", type_="wellness.update", salience=0.5, eid="e1"):
    return eid, Event(
        source=source,
        type=type_,
        payload={"x": 1},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


async def _recall_events(bus: AsyncBus) -> list:
    entries = await bus.read("episodic_memory.out", last_id="0")
    return [e for _, e in entries if e.type == "episodic_memory.recall"]


@pytest.mark.asyncio
async def test_earlier_wake_trace_recalled(bus: AsyncBus):
    """A trace consolidated into the persisted episodic collection during a
    prior wake is found by the spontaneous on_workspace recall."""
    em = await _new_episodic_memory(
        bus, capacity=2, recall_cooldown_s=0.0, recall_exclude_recent_s=0.0,
    )
    await em.initialize()
    try:
        # Store two traces so the buffer is full, then consolidate to simulate
        # a sleep cycle moving entries to the persisted collection.
        await em.on_workspace(_snapshot([_event(eid="e0")]))
        await em.on_workspace(_snapshot([_event(eid="e1")]))
        assert em.core.short_term_size == 2
        moved = await em.core.consolidate_now()
        assert moved == 2
        assert em.core.short_term_size == 0
        episodic_coll = em.core.collection_name("episodic")
        assert await em.core.storage.count(episodic_coll) == 2

        # New wake: a fresh tick triggers recall over the persisted collection.
        await em.on_workspace(_snapshot([_event(eid="e2")]))
        recalls = await _recall_events(bus)
        # Filter to only the recall from the third tick (the first two ticks
        # also fire recalls since cooldown=0).
        last_recall = recalls[-1]
        assert last_recall.payload["collection"] == "episodic"
        assert last_recall.payload["count"] >= 1
        assert last_recall.payload["top_similarity"] > 0.0
    finally:
        await em.shutdown()


@pytest.mark.asyncio
async def test_recent_short_term_excluded(bus: AsyncBus):
    """With a large recall_exclude_recent_s, all short-term entries are too
    recent and the recall finds nothing from the short-term buffer. The
    persisted collection is also empty, so count is 0."""
    em = await _new_episodic_memory(
        bus, capacity=128, recall_cooldown_s=0.0, recall_exclude_recent_s=9999.0,
    )
    await em.initialize()
    try:
        for i in range(5):
            await em.on_workspace(_snapshot([_event(eid=f"e{i}")]))
        assert em.core.short_term_size == 5

        recalls = await _recall_events(bus)
        assert len(recalls) == 5
        for r in recalls:
            assert r.payload["count"] == 0
            assert r.payload["collection"] == "episodic"
    finally:
        await em.shutdown()


@pytest.mark.asyncio
async def test_schema_node_yields_no_content(bus: AsyncBus):
    """When recall_content is True but there are no results (empty store),
    the recall event carries top_similarity == 0.0 and no 'content' key."""
    em = await _new_episodic_memory(
        bus, capacity=128, recall_cooldown_s=0.0,
        recall_exclude_recent_s=9999.0, recall_content=True,
    )
    await em.initialize()
    try:
        await em.on_workspace(_snapshot([_event(eid="e0")]))
        recalls = await _recall_events(bus)
        assert len(recalls) == 1
        r = recalls[0]
        assert r.payload["top_similarity"] == 0.0
        assert "content" not in r.payload
    finally:
        await em.shutdown()
