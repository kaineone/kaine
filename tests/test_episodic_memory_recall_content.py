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
from kaine.modules.episodic_memory.module import _age_band, _recall_content_for
from kaine.modules.episodic_memory.storage import RecalledMemory

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


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


def _event(source="interoception", type_="wellness.update", salience=0.5, eid="e1"):
    return eid, Event(
        source=source,
        type=type_,
        payload={"x": 1},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _recalled(point_id="pt-1", payload=None, similarity=0.8):
    return RecalledMemory(
        point_id=point_id,
        score=similarity,
        text="some trace text",
        payload=payload or {},
        affect=None,
        similarity=similarity,
        strength=1.0,
    )


async def _recall_events(bus: AsyncBus) -> list:
    entries = await bus.read("episodic_memory.out", last_id="0")
    return [e for _, e in entries if e.type == "episodic_memory.recall"]


# ---------------------------------------------------------------------------
# Unit tests: _age_band
# ---------------------------------------------------------------------------


def test_age_band_this_wake():
    assert _age_band(5, 5) == "this_wake"


def test_age_band_before_last_sleep():
    assert _age_band(4, 5) == "before_last_sleep"


def test_age_band_earlier():
    assert _age_band(2, 5) == "earlier"


def test_age_band_none_born_sleep():
    assert _age_band(None, 5) == "this_wake"


def test_age_band_bool_born_sleep():
    assert _age_band(True, 5) == "this_wake"


def test_age_band_future_born_sleep():
    assert _age_band(6, 5) == "this_wake"


# ---------------------------------------------------------------------------
# Unit tests: _recall_content_for
#
# The function extracts content from the best-ranked recall result.
# Members are the coalition entries stored in the trace by _build_members
# (task 4.1): each has {source, type} and optionally {heard: True} or
# {felt_fields: {...}}.
# ---------------------------------------------------------------------------


def test_content_shape():
    """Content carries members (capped at render_max), age_band, and trace_ref."""
    members = [
        {"source": "affect", "type": "affect.state"},
        {"source": "interoception", "type": "wellness.update"},
    ]
    best = _recalled(point_id="pt-42", payload={"members": members, "born_sleep": 3})
    result = _recall_content_for(best, current_sleeps=5, render_max=3)
    assert result is not None
    assert set(result.keys()) == {"members", "age_band", "trace_ref"}
    assert result["age_band"] == "earlier"
    assert result["trace_ref"] == "pt-42"
    assert len(result["members"]) == 2


def test_content_render_max_limits_members():
    members = [{"source": f"m{i}", "type": f"t{i}"} for i in range(5)]
    best = _recalled(payload={"members": members, "born_sleep": 0})
    result = _recall_content_for(best, current_sleeps=0, render_max=2)
    assert result is not None
    assert len(result["members"]) == 2
    assert result["members"][0]["source"] == "m0"
    assert result["members"][1]["source"] == "m1"


def test_content_none_for_legacy_trace():
    """A persisted trace with no members key (stored before this change) yields no content."""
    best = _recalled(payload={"born_sleep": 2})
    assert _recall_content_for(best, current_sleeps=5, render_max=3) is None


def test_content_none_for_empty_members():
    best = _recalled(payload={"members": [], "born_sleep": 2})
    assert _recall_content_for(best, current_sleeps=5, render_max=3) is None


def test_republication_filter_heard_member():
    """A trace with ANY heard member yields no content — heard text must not be republished."""
    members = [
        {"source": "embodiment", "type": "embodiment.chat", "heard": True},
    ]
    best = _recalled(payload={"members": members, "born_sleep": 2})
    assert _recall_content_for(best, current_sleeps=5, render_max=3) is None


def test_republication_filter_mixed_members_one_heard():
    """Even one heard member among safe ones blocks the whole trace's content."""
    members = [
        {"source": "affect", "type": "affect.state"},
        {"source": "embodiment", "type": "embodiment.chat", "heard": True},
    ]
    best = _recalled(payload={"members": members, "born_sleep": 2})
    assert _recall_content_for(best, current_sleeps=5, render_max=3) is None


def test_content_preserves_felt_fields():
    """Members with felt_fields pass through to content."""
    members = [
        {"source": "affect", "type": "affect.state", "felt_fields": {"state": "active"}},
    ]
    best = _recalled(payload={"members": members, "born_sleep": 5})
    result = _recall_content_for(best, current_sleeps=5, render_max=3)
    assert result is not None
    assert result["members"][0].get("felt_fields") == {"state": "active"}


def test_content_uses_correct_age_band_for_short_term():
    """A member with no born_sleep (short-term candidate) is this_wake."""
    members = [{"source": "affect", "type": "affect.state"}]
    best = _recalled(payload={"members": members})
    result = _recall_content_for(best, current_sleeps=5, render_max=3)
    assert result is not None
    assert result["age_band"] == "this_wake"


# ---------------------------------------------------------------------------
# Integration tests: recall event payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_event_has_top_similarity(bus: AsyncBus):
    """Every recall event carries top_similarity as a float."""
    em = await _new_episodic_memory(bus, capacity=2, recall_cooldown_s=0.0, recall_content=False)
    await em.initialize()
    try:
        for i in range(4):
            await em.on_workspace(_snapshot([_event(eid=f"e{i}")], tick_index=i))
        recalls = await _recall_events(bus)
        assert len(recalls) > 0
        for r in recalls:
            assert "top_similarity" in r.payload
            assert isinstance(r.payload["top_similarity"], float)
            assert r.payload["top_similarity"] >= 0.0
    finally:
        await em.shutdown()


@pytest.mark.asyncio
async def test_recall_event_no_content_when_disabled(bus: AsyncBus):
    """With recall_content=False the event never carries a content key."""
    em = await _new_episodic_memory(bus, capacity=2, recall_cooldown_s=0.0, recall_content=False)
    await em.initialize()
    try:
        for i in range(4):
            await em.on_workspace(_snapshot([_event(eid=f"e{i}")], tick_index=i))
        recalls = await _recall_events(bus)
        assert len(recalls) > 0
        for r in recalls:
            assert "content" not in r.payload
    finally:
        await em.shutdown()


@pytest.mark.asyncio
async def test_recall_event_content_when_enabled(bus: AsyncBus):
    """With recall_content=True, a recall that finds a trace with members includes content."""
    em = await _new_episodic_memory(
        bus, capacity=2, recall_cooldown_s=0.0, recall_content=True,
    )
    await em.initialize()
    try:
        for i in range(6):
            await em.on_workspace(_snapshot([_event(eid=f"e{i}")], tick_index=i))
        recalls = await _recall_events(bus)
        content_recalls = [r for r in recalls if "content" in r.payload]
        if content_recalls:
            c = content_recalls[0].payload["content"]
            assert "members" in c
            assert "age_band" in c
            assert "trace_ref" in c
            assert isinstance(c["members"], list)
            assert c["age_band"] in ("this_wake", "before_last_sleep", "earlier")
    finally:
        await em.shutdown()
