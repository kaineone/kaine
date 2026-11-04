# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the familiarity grading logic (PR 3, task 5.4)."""

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
from kaine.modules.episodic_memory.replay import ReplayEntry, build_replay_events


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


async def _new_em(bus: AsyncBus, *, capacity: int = 4, **kwargs) -> EpisodicMemory:
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


# -- Unit tests: _familiarity_grade ------------------------------------------


@pytest.mark.asyncio
async def test_familiarity_before_ten_recalls(bus: AsyncBus):
    em = await _new_em(bus, capacity=2, recall_cooldown_s=0.0, recall_content=False)
    await em.initialize()
    try:
        for i in range(8):
            await em.on_workspace(_snapshot([_event(eid=f"e{i}")], tick_index=i))
        recalls = await _recall_events(bus)
        for r in recalls:
            if "familiarity" in r.payload:
                assert r.payload["familiarity"] == "somewhat_familiar"
    finally:
        await em.shutdown()


@pytest.mark.asyncio
async def test_familiarity_in_payload(bus: AsyncBus):
    em = await _new_em(bus, capacity=2, recall_cooldown_s=0.0, recall_content=False)
    await em.initialize()
    try:
        for i in range(20):
            await em.on_workspace(_snapshot([_event(eid=f"e{i}")], tick_index=i))
        recalls = await _recall_events(bus)
        with_fam = [r for r in recalls if "familiarity" in r.payload]
        assert len(with_fam) > 0
        for r in with_fam:
            assert r.payload["familiarity"] in ("faintly_familiar", "somewhat_familiar", "familiar")
    finally:
        await em.shutdown()


@pytest.mark.asyncio
async def test_familiarity_not_in_zero_count(bus: AsyncBus):
    em = await _new_em(bus, capacity=2, recall_cooldown_s=0.0, recall_content=False)
    await em.initialize()
    try:
        await em.on_workspace(_snapshot([_event(eid="e0")], tick_index=0))
        recalls = await _recall_events(bus)
        zero_count = [r for r in recalls if r.payload.get("count") == 0]
        for r in zero_count:
            assert "familiarity" not in r.payload
    finally:
        await em.shutdown()


# -- Unit tests: _familiarity_grade method directly --------------------------


@pytest.mark.asyncio
async def test_familiarity_grade_low(bus: AsyncBus):
    em = await _new_em(bus, capacity=2, recall_cooldown_s=0.0, familiarity_window=20)
    await em.initialize()
    try:
        for i in range(15):
            em._similarity_history.append(0.8 + i * 0.01)
        grade = em._familiarity_grade(0.5)
        assert grade == "faintly_familiar"
    finally:
        await em.shutdown()


@pytest.mark.asyncio
async def test_familiarity_grade_high(bus: AsyncBus):
    em = await _new_em(bus, capacity=2, recall_cooldown_s=0.0, familiarity_window=20)
    await em.initialize()
    try:
        for i in range(15):
            em._similarity_history.append(0.3 + i * 0.01)
        grade = em._familiarity_grade(0.95)
        assert grade == "familiar"
    finally:
        await em.shutdown()


@pytest.mark.asyncio
async def test_familiarity_window_bounded(bus: AsyncBus):
    em = await _new_em(bus, capacity=2, recall_cooldown_s=0.0, familiarity_window=10)
    await em.initialize()
    try:
        for i in range(20):
            em._familiarity_grade(0.5)
        assert len(em._similarity_history) == 10
    finally:
        await em.shutdown()


# -- Replay: members in loop_payload ----------------------------------------


def test_replay_members_in_payload():
    members = [{"source": "affect", "type": "affect.state"}]
    entry = ReplayEntry(
        point_id="pt-1",
        text="some text",
        affect=None,
        affect_intensity=0.0,
        timestamp=1234567890.0,
        payload={"members": members},
        collection="short_term",
    )
    events = build_replay_events([entry], redact_content=False)
    assert len(events) == 1
    assert events[0].loop_payload.get("members") == members


def test_replay_no_members_in_payload():
    entry = ReplayEntry(
        point_id="pt-1",
        text="some text",
        affect=None,
        affect_intensity=0.0,
        timestamp=1234567890.0,
        payload={},
        collection="short_term",
    )
    events = build_replay_events([entry], redact_content=False)
    assert len(events) == 1
    assert "members" not in events[0].loop_payload
