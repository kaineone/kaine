# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests that the sleep module's deep consolidation replays the batch light consolidation moved."""

from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.episodic_memory import (
    EpisodicMemory,
    EpisodicMemoryCore,
    FakeEmbedder,
    InMemoryStorage,
)
from kaine.modules.sleep.phases import deep_consolidation, light_consolidation


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


@pytest.mark.asyncio
async def test_phase_two_replays_what_phase_one_consolidated(bus: AsyncBus):
    """Phase 2 must replay the traces phase 1 moved to episodic."""
    episodic_memory = await _new_episodic_memory(
        bus,
        capacity=8,
        replay_selection_top_k=5,
        replay_redact_content=False,
    )
    await episodic_memory.initialize()
    try:
        # Seed short_term with three traces.
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

        # Open the window by hand; in a sleep, phase 2 opens it through open_replay_window().
        episodic_memory.replay_engine.open_window()

        # Phase 1 consolidates the batch; phase 2 should replay it.
        p1 = await light_consolidation(episodic_memory)
        p2 = await deep_consolidation(episodic_memory)

        assert p1.success
        assert p1.metadata["entries_consolidated"] == 3

        assert p2.success
        assert p2.metadata["replay_events"] == 3

        # Gather replay events emitted on the bus.
        bus_entries = await bus.read("episodic_memory.out", last_id="0")
        replay_events = [e for _, e in bus_entries if e.type == "episodic_memory.replay"]

        assert {ev.payload["text"] for ev in replay_events} == {
            "trace 0",
            "trace 1",
            "trace 2",
        }

        episodic_ids = {
            str(p["id"])
            for p in episodic_memory.core.storage._collections[
                episodic_memory.core.collection_name("episodic")
            ]
        }
        assert {ev.payload["memory_id"] for ev in replay_events} == episodic_ids
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_later_consolidation_does_not_replay_an_earlier_batch(bus: AsyncBus):
    """After the wake ends, the earlier batch is no longer in the replay pool."""
    episodic_memory = await _new_episodic_memory(
        bus,
        capacity=8,
        replay_selection_top_k=5,
        replay_redact_content=False,
    )
    await episodic_memory.initialize()
    try:
        for i in range(2):
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

        episodic_memory.replay_engine.open_window()

        # First consolidation moves the batch and ends that wake.
        assert await episodic_memory.consolidate_now() == 2
        await episodic_memory.downscale()

        # Second consolidation sees an empty buffer.
        assert await episodic_memory.consolidate_now() == 0

        events = await episodic_memory.replay_now()
        assert events == []

        bus_entries = await bus.read("episodic_memory.out", last_id="0")
        assert not any(e.type == "episodic_memory.replay" for _, e in bus_entries)
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_sleep_completed_drops_the_consolidated_batch(bus: AsyncBus):
    """sleep.sleep.completed closes the window; the wake ends at downscale."""
    episodic_memory = await _new_episodic_memory(
        bus,
        capacity=8,
        replay_selection_top_k=5,
        replay_redact_content=False,
    )
    await episodic_memory.initialize()
    try:
        for i in range(2):
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

        await episodic_memory.consolidate_now()

        # Simulate the peer consumer loop delivering sleep completion.
        episodic_memory._handle_peer_event(
            episodic_memory._sleep_stream,
            Event(
                source="sleep",
                type="sleep.sleep.completed",
                payload={},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            ),
        )

        assert not episodic_memory.replay_engine.window_active

        # Downscale ends the wake; the consolidated batch is no longer in the replay pool.
        await episodic_memory.downscale()
        episodic_memory.replay_engine.open_window()
        assert await episodic_memory.replay_now() == []
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_entry_stored_after_phase_one_is_replayed_with_the_batch(bus: AsyncBus):
    """A trace that lands in short-term after phase 1 is still replayed in phase 2."""
    episodic_memory = await _new_episodic_memory(
        bus,
        capacity=8,
        replay_selection_top_k=5,
        replay_redact_content=False,
    )
    await episodic_memory.initialize()
    try:
        for i in range(2):
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

        episodic_memory.replay_engine.open_window()

        p1 = await light_consolidation(episodic_memory)
        assert p1.success

        await episodic_memory.core.store(
            "late trace",
            payload={"idx": 2},
            affect={
                "intensity": 0.5,
                "valence": 0.0,
                "dominance": 0.0,
            },
            collection="short_term",
        )

        p2 = await deep_consolidation(episodic_memory)
        assert p2.success
        assert p2.metadata["replay_events"] == 3

        bus_entries = await bus.read("episodic_memory.out", last_id="0")
        replay_events = [e for _, e in bus_entries if e.type == "episodic_memory.replay"]

        texts = sorted(ev.payload["text"] for ev in replay_events)
        assert texts == ["late trace", "trace 0", "trace 1"]

        memory_ids = {ev.payload["memory_id"] for ev in replay_events}
        assert len(memory_ids) == 3

        episodic_ids = {
            str(p["id"])
            for p in episodic_memory.core.storage._collections[
                episodic_memory.core.collection_name("episodic")
            ]
        }
        assert memory_ids == episodic_ids | {"short_term:0"}
    finally:
        await episodic_memory.shutdown()
