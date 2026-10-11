# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests that Hypnos deep consolidation replays the batch light consolidation moved."""

from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.hypnos.phases import deep_consolidation, light_consolidation
from kaine.modules.mnemos import FakeEmbedder, InMemoryStorage, Mnemos, MnemosCore


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


async def _new_mnemos(bus: AsyncBus, *, capacity: int = 8, **kwargs) -> Mnemos:
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    core = MnemosCore(embedder=emb, storage=storage, short_term_capacity=capacity)
    return Mnemos(bus, core=core, **kwargs)


@pytest.mark.asyncio
async def test_phase_two_replays_what_phase_one_consolidated(bus: AsyncBus):
    """Phase 2 must replay the traces phase 1 moved to episodic."""
    mnemos = await _new_mnemos(
        bus,
        capacity=8,
        replay_selection_top_k=5,
        replay_redact_content=False,
    )
    await mnemos.initialize()
    try:
        # Seed short_term with three traces.
        for i in range(3):
            await mnemos.core.store(
                f"trace {i}",
                payload={"idx": i},
                affect={
                    "intensity": 0.2 * (i + 1),
                    "valence": 0.0,
                    "dominance": 0.0,
                },
                collection="short_term",
            )

        # Open the Hypnos window manually; in production sleep.started does this.
        mnemos.replay_engine.open_window()

        # Phase 1 consolidates the batch; phase 2 should replay it.
        p1 = await light_consolidation(mnemos)
        p2 = await deep_consolidation(mnemos)

        assert p1.success
        assert p1.metadata["entries_consolidated"] == 3

        assert p2.success
        assert p2.metadata["replay_events"] == 3

        # Gather replay events emitted on the bus.
        bus_entries = await bus.read("mnemos.out", last_id="0")
        replay_events = [e for _, e in bus_entries if e.type == "mnemos.replay"]

        assert {ev.payload["text"] for ev in replay_events} == {
            "trace 0",
            "trace 1",
            "trace 2",
        }

        episodic_ids = {
            str(p["id"])
            for p in mnemos.core.storage._collections[
                mnemos.core.collection_name("episodic")
            ]
        }
        assert {ev.payload["memory_id"] for ev in replay_events} == episodic_ids
    finally:
        await mnemos.shutdown()


@pytest.mark.asyncio
async def test_later_consolidation_does_not_replay_an_earlier_batch(bus: AsyncBus):
    """Replaying after a second empty consolidation must not emit old traces."""
    mnemos = await _new_mnemos(
        bus,
        capacity=8,
        replay_selection_top_k=5,
        replay_redact_content=False,
    )
    await mnemos.initialize()
    try:
        for i in range(2):
            await mnemos.core.store(
                f"trace {i}",
                payload={"idx": i},
                affect={
                    "intensity": 0.2 * (i + 1),
                    "valence": 0.0,
                    "dominance": 0.0,
                },
                collection="short_term",
            )

        mnemos.replay_engine.open_window()

        # First consolidation moves the batch; second sees an empty buffer.
        assert await mnemos.consolidate_now() == 2
        assert await mnemos.consolidate_now() == 0

        events = await mnemos.replay_now()
        assert events == []

        bus_entries = await bus.read("mnemos.out", last_id="0")
        assert not any(e.type == "mnemos.replay" for _, e in bus_entries)
    finally:
        await mnemos.shutdown()


@pytest.mark.asyncio
async def test_sleep_completed_drops_the_consolidated_batch(bus: AsyncBus):
    """hypnos.sleep.completed closes the window and drops the consolidated batch."""
    mnemos = await _new_mnemos(
        bus,
        capacity=8,
        replay_selection_top_k=5,
        replay_redact_content=False,
    )
    await mnemos.initialize()
    try:
        for i in range(2):
            await mnemos.core.store(
                f"trace {i}",
                payload={"idx": i},
                affect={
                    "intensity": 0.2 * (i + 1),
                    "valence": 0.0,
                    "dominance": 0.0,
                },
                collection="short_term",
            )

        await mnemos.consolidate_now()

        # Simulate the peer consumer loop delivering sleep completion.
        mnemos._handle_peer_event(
            mnemos._hypnos_stream,
            Event(
                source="hypnos",
                type="hypnos.sleep.completed",
                payload={},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            ),
        )

        assert not mnemos.replay_engine.window_active

        # Reopening the window must not resurrect the already-completed batch.
        mnemos.replay_engine.open_window()
        assert await mnemos.replay_now() == []
    finally:
        await mnemos.shutdown()


@pytest.mark.asyncio
async def test_entry_stored_after_phase_one_is_replayed_with_the_batch(bus: AsyncBus):
    """A trace that lands in short-term after phase 1 is still replayed in phase 2."""
    mnemos = await _new_mnemos(
        bus,
        capacity=8,
        replay_selection_top_k=5,
        replay_redact_content=False,
    )
    await mnemos.initialize()
    try:
        for i in range(2):
            await mnemos.core.store(
                f"trace {i}",
                payload={"idx": i},
                affect={
                    "intensity": 0.2 * (i + 1),
                    "valence": 0.0,
                    "dominance": 0.0,
                },
                collection="short_term",
            )

        mnemos.replay_engine.open_window()

        p1 = await light_consolidation(mnemos)
        assert p1.success

        await mnemos.core.store(
            "late trace",
            payload={"idx": 2},
            affect={
                "intensity": 0.5,
                "valence": 0.0,
                "dominance": 0.0,
            },
            collection="short_term",
        )

        p2 = await deep_consolidation(mnemos)
        assert p2.success
        assert p2.metadata["replay_events"] == 3

        bus_entries = await bus.read("mnemos.out", last_id="0")
        replay_events = [e for _, e in bus_entries if e.type == "mnemos.replay"]

        texts = sorted(ev.payload["text"] for ev in replay_events)
        assert texts == ["late trace", "trace 0", "trace 1"]

        memory_ids = {ev.payload["memory_id"] for ev in replay_events}
        assert len(memory_ids) == 3

        episodic_ids = {
            str(p["id"])
            for p in mnemos.core.storage._collections[
                mnemos.core.collection_name("episodic")
            ]
        }
        assert memory_ids == episodic_ids | {"short_term:0"}
    finally:
        await mnemos.shutdown()
