# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for episodic memory replay selection, re-injection, and window guard.

Scenarios verified:
- Selection ranks high-affect/recent traces first.
- replay() emits mnemos.replay events with trace content inside a window.
- replay() raises ReplayWindowError and emits nothing outside a window.
"""
from __future__ import annotations

import time

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.episodic_memory import (
    EpisodicMemory,
    EpisodicMemoryCore,
    FakeEmbedder,
    InMemoryStorage,
    ReplayWindowError,
)

# ---------------------------------------------------------------------------
# Pure unit tests — no bus needed
# ---------------------------------------------------------------------------
from kaine.modules.episodic_memory.replay import ReplayEngine, ReplayEntry, select_traces


def _entry(
    point_id: str,
    *,
    intensity: float,
    timestamp: float,
    text: str = "memory text",
) -> ReplayEntry:
    return ReplayEntry(
        point_id=point_id,
        text=text,
        affect_intensity=intensity,
        timestamp=timestamp,
        payload={},
        affect={"intensity": intensity},
    )


class TestSelectTraces:
    """Scenario: emotionally significant, recent traces rank first."""

    def test_high_affect_recent_ranks_above_low_affect_old(self):
        now = time.time()
        high_recent = _entry("hi", intensity=0.9, timestamp=now)
        low_old = _entry("lo", intensity=0.1, timestamp=now - 3600)
        ranked = select_traces(
            [low_old, high_recent],
            affect_weight=0.7,
            recency_weight=0.3,
            top_k=2,
        )
        assert ranked[0].point_id == "hi"
        assert ranked[1].point_id == "lo"

    def test_top_k_limits_results(self):
        now = time.time()
        candidates = [_entry(f"m{i}", intensity=float(i) / 10, timestamp=now + i) for i in range(10)]
        ranked = select_traces(candidates, affect_weight=0.7, recency_weight=0.3, top_k=3)
        assert len(ranked) == 3

    def test_empty_candidates_returns_empty(self):
        result = select_traces([], affect_weight=0.7, recency_weight=0.3, top_k=5)
        assert result == []

    def test_single_candidate_always_selected(self):
        now = time.time()
        entry = _entry("only", intensity=0.5, timestamp=now)
        result = select_traces([entry], affect_weight=0.5, recency_weight=0.5, top_k=1)
        assert len(result) == 1
        assert result[0].point_id == "only"

    def test_all_same_timestamp_ordered_by_affect(self):
        now = time.time()
        entries = [_entry(f"m{i}", intensity=float(i) / 10, timestamp=now) for i in range(5)]
        ranked = select_traces(entries, affect_weight=1.0, recency_weight=0.0, top_k=5)
        intensities = [e.affect_intensity for e in ranked]
        assert intensities == sorted(intensities, reverse=True)


class TestReplayEngineGuard:
    """Scenario: guard fires when replay() called outside a window."""

    def test_replay_outside_window_raises(self):
        engine = ReplayEngine()
        assert not engine.window_active
        with pytest.raises(ReplayWindowError):
            engine.replay([])

    def test_replay_outside_window_with_candidates_raises(self):
        engine = ReplayEngine()
        now = time.time()
        candidates = [_entry("x", intensity=0.8, timestamp=now)]
        with pytest.raises(ReplayWindowError):
            engine.replay(candidates)

    def test_open_close_window(self):
        engine = ReplayEngine()
        engine.open_window()
        assert engine.window_active
        engine.close_window()
        assert not engine.window_active

    def test_replay_inside_window_returns_events(self):
        engine = ReplayEngine(selection_top_k=2)
        engine.open_window()
        now = time.time()
        candidates = [
            _entry("a", intensity=0.9, timestamp=now, text="alpha memory"),
            _entry("b", intensity=0.3, timestamp=now - 100, text="beta memory"),
        ]
        events = engine.replay(candidates)
        assert len(events) == 2
        # Top result should be the high-affect one.
        assert events[0].point_id == "a"

    def test_replay_inside_window_loop_payload_has_text(self):
        engine = ReplayEngine(selection_top_k=5, redact_content=False)
        engine.open_window()
        now = time.time()
        candidates = [_entry("z", intensity=0.5, timestamp=now, text="test content")]
        events = engine.replay(candidates)
        assert len(events) == 1
        assert events[0].loop_payload["text"] == "test content"
        assert events[0].loop_payload["memory_id"] == "z"


# ---------------------------------------------------------------------------
# Integration tests — bus required
# ---------------------------------------------------------------------------

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
async def test_replay_emits_events_with_content_inside_window(bus: AsyncBus):
    """Scenario: replay() inside a window emits mnemos.replay with trace content."""
    episodic_memory = await _new_episodic_memory(
        bus,
        capacity=8,
        replay_selection_top_k=3,
        replay_redact_content=False,
    )
    await episodic_memory.initialize()
    try:
        # Store some memories via core so they land in short_term with affect.
        for i in range(3):
            await episodic_memory.core.store(
                f"memory trace {i}",
                payload={"idx": i},
                affect={"intensity": float(i + 1) / 3, "valence": 0.0, "dominance": 0.0},
                collection="short_term",
            )

        # Open the maintenance window and trigger replay.
        episodic_memory.replay_engine.open_window()
        events = await episodic_memory.replay_now()

        assert len(events) > 0

        # Check that bus received mnemos.replay events.
        bus_entries = await bus.read("mnemos.out", last_id="0")
        replay_events = [e for _, e in bus_entries if e.type == "mnemos.replay"]
        assert len(replay_events) == len(events)

        # Each event must carry text content (redact_content=False).
        for _, ev in (e for e in bus_entries if e[1].type == "mnemos.replay"):
            assert "text" in ev.payload
            assert "memory_id" in ev.payload
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_replay_raises_outside_window_and_emits_nothing(bus: AsyncBus):
    """Scenario: replay() outside a window raises and emits nothing."""
    episodic_memory = await _new_episodic_memory(bus, capacity=8)
    await episodic_memory.initialize()
    try:
        await episodic_memory.core.store(
            "some memory",
            payload={},
            affect={"intensity": 0.5},
            collection="short_term",
        )

        # Window is closed by default — replay must raise.
        assert not episodic_memory.replay_engine.window_active
        with pytest.raises(ReplayWindowError):
            await episodic_memory.replay_now()

        # No mnemos.replay events should have been emitted.
        bus_entries = await bus.read("mnemos.out", last_id="0")
        replay_events = [e for _, e in bus_entries if e.type == "mnemos.replay"]
        assert replay_events == []
    finally:
        await episodic_memory.shutdown()


@pytest.mark.asyncio
async def test_replay_selection_ranks_high_affect_first(bus: AsyncBus):
    """Verify selection ordering: high-affect recent trace scores above low-affect old."""
    import time as _time

    now = _time.time()
    episodic_memory = await _new_episodic_memory(
        bus,
        capacity=16,
        replay_selection_top_k=2,
        replay_affect_weight=0.7,
        replay_recency_weight=0.3,
        replay_redact_content=False,
    )
    await episodic_memory.initialize()
    try:
        # Manually plant two entries in short-term with controlled timestamps.
        from collections import deque

        from kaine.modules.episodic_memory.memory import StoredMemory

        episodic_memory.core._short_term = deque()
        episodic_memory.core._short_term.append(
            StoredMemory(
                text="low affect old memory",
                payload={"timestamp": now - 3600},
                affect={"intensity": 0.1, "valence": 0.0, "dominance": 0.0},
                timestamp=now - 3600,
            )
        )
        episodic_memory.core._short_term.append(
            StoredMemory(
                text="high affect recent memory",
                payload={"timestamp": now},
                affect={"intensity": 0.9, "valence": 0.5, "dominance": 0.2},
                timestamp=now,
            )
        )

        episodic_memory.replay_engine.open_window()
        events = await episodic_memory.replay_now()

        assert len(events) == 2
        # Top-ranked event must be the high-affect one.
        assert events[0].loop_payload["text"] == "high affect recent memory"
    finally:
        await episodic_memory.shutdown()
