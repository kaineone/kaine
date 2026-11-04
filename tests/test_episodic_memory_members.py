# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Coalition members on new episodic traces.

Task 4.1 of episodic-recall-content: FELT_FIELDS declares the payload fields
each felt template reads; new traces store their coalition members with those
fields; heard members carry ``heard: True`` and no payload.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.faithful.felt import FELT_FIELDS, FELT_TEMPLATES
from kaine.modules.episodic_memory import (
    EpisodicMemory,
    EpisodicMemoryCore,
    FakeEmbedder,
    InMemoryStorage,
)
from kaine.modules.episodic_memory.module import _build_members


def _ev(source: str, type_: str, payload: dict[str, Any]) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.6,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(events: list[Event], tick: int = 0) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=tick,
        selected_events=[(f"e{tick}-{i}", ev) for i, ev in enumerate(events)],
        inhibited=False,
    )


# --- Part 1: FELT_FIELDS declaration -----------------------------------------


def test_felt_fields_covers_all_templates():
    assert set(FELT_FIELDS) == set(FELT_TEMPLATES)


def test_felt_fields_are_frozen():
    for key, fields in FELT_FIELDS.items():
        assert isinstance(fields, frozenset), f"{key} is {type(fields)}, not frozenset"


def test_felt_fields_subset_of_payload_reads():
    for key, fields in FELT_FIELDS.items():
        template = FELT_TEMPLATES[key]
        payload_with_fields = {f: 0.5 for f in fields}
        result = template(payload_with_fields)
        assert isinstance(result, str), f"{key} with fields did not return str"
        result_empty = template({})
        assert isinstance(result_empty, str), f"{key} with empty payload did not return str"


# --- Part 2: _build_members --------------------------------------------------


def test_members_on_new_trace():
    events = [
        _ev("affect", "affect.state", {
            "state": {"valence": 0.3, "arousal": 0.5},
            "drives": {"curiosity": 0.7},
            "emotion": "joy",
            "extra_field": "should not appear",
        }),
        _ev("vision", "vision.report", {
            "change_score": 0.15,
            "habituation_score": 0.8,
            "normalised_error": 1.2,
        }),
    ]
    snap = _snapshot(events)
    members = _build_members(snap)
    assert len(members) == 2

    affect_member = members[0]
    assert affect_member["source"] == "affect"
    assert affect_member["type"] == "affect.state"
    felt = affect_member["felt_fields"]
    assert set(felt.keys()) == {"state", "drives", "emotion"}
    assert "extra_field" not in felt

    vision_member = members[1]
    assert vision_member["source"] == "vision"
    assert vision_member["type"] == "vision.report"
    felt_v = vision_member["felt_fields"]
    assert set(felt_v.keys()) == {"change_score", "habituation_score", "normalised_error"}


def test_heard_member_has_no_payload():
    events = [
        _ev("embodiment", "embodiment.chat", {"text": "hello there", "sender": "avatar"}),
    ]
    snap = _snapshot(events)
    members = _build_members(snap)
    assert len(members) == 1
    m = members[0]
    assert m == {"source": "embodiment", "type": "embodiment.chat", "heard": True}
    assert "felt_fields" not in m


def test_unclassified_member_has_no_payload():
    events = [
        _ev("mystery", "mystery.event", {"data": "something"}),
    ]
    snap = _snapshot(events)
    members = _build_members(snap)
    assert len(members) == 1
    m = members[0]
    assert m == {"source": "mystery", "type": "mystery.event"}
    assert "felt_fields" not in m
    assert "heard" not in m


def test_replay_member_has_no_payload():
    events = [
        _ev("episodic_memory", "episodic_memory.replay", {
            "memory_id": "abc123",
            "text": "old trace text",
        }),
    ]
    snap = _snapshot(events)
    members = _build_members(snap)
    assert len(members) == 1
    m = members[0]
    assert m == {"source": "episodic_memory", "type": "episodic_memory.replay"}
    assert "felt_fields" not in m


def test_raw_perceptual_event_excluded_from_members():
    events = [
        _ev("embodiment", "embodiment.visual.raw", {"frame_b64": "RAWPIXELS"}),
    ]
    snap = _snapshot(events)
    members = _build_members(snap)
    assert len(members) == 0


def test_own_content_member_without_felt_fields_has_no_felt_fields_key():
    events = [
        _ev("cycle", "cycle.tick", {"tick_index": 42}),
    ]
    snap = _snapshot(events)
    members = _build_members(snap)
    assert len(members) == 1
    m = members[0]
    assert m == {"source": "cycle", "type": "cycle.tick"}
    assert "felt_fields" not in m


# --- Part 3: integration with on_workspace -----------------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


async def _new_episodic_memory(bus: AsyncBus, *, capacity: int = 4) -> EpisodicMemory:
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    core = EpisodicMemoryCore(embedder=emb, storage=storage, short_term_capacity=capacity)
    return EpisodicMemory(bus, core=core)


@pytest.mark.asyncio
async def test_members_stored_in_trace_payload(bus: AsyncBus):
    module = await _new_episodic_memory(bus)
    await module.initialize()
    try:
        events = [
            _ev("affect", "affect.state", {
                "state": {"valence": 0.3},
                "drives": {},
                "emotion": "joy",
            }),
            _ev("vision", "vision.report", {"change_score": 0.15}),
        ]
        await module.on_workspace(_snapshot(events))
        assert module.core.short_term_size == 1
        stored = module.core._short_term[0]
        assert "members" in stored.payload
        members = stored.payload["members"]
        assert len(members) == 2
        assert members[0]["source"] == "affect"
        assert members[1]["source"] == "vision"
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_legacy_traces_untouched(bus: AsyncBus):
    module = await _new_episodic_memory(bus)
    await module.initialize()
    try:
        await module.core.store(
            "active | interoception:interoception.report={'wellness': 0.9}",
            payload={"tick_index": 0, "inhibited": False, "selected_count": 1},
            collection="short_term",
        )
        assert module.core.short_term_size == 1
        stored = module.core._short_term[0]
        assert "members" not in stored.payload
        assert stored.text == "active | interoception:interoception.report={'wellness': 0.9}"
    finally:
        await module.shutdown()
