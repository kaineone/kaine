# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Heard words are never written into an episodic trace.

The episodic memory module classifies each coalition member with the shared
heard rule (kaine.faithful.external_input) and stores a heard member as its
source and type with ``<heard omitted>``. It keeps a payload only for a type
declared in ``INTERNAL_EVENT_TYPES`` and stores every other type as
``<unclassified omitted>``. The end-to-end cases run the real
module on a sqlite-vec store on disk and read the traces back from that store,
from the database file itself and from the preservation export.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.faithful.external_input import (
    EXTERNAL_INPUT_TYPES,
    HEARD_TEXT_FIELDS,
    INTERNAL_EVENT_TYPES,
)
from kaine.modules.episodic_memory import EpisodicMemory, EpisodicMemoryCore, FakeEmbedder
from kaine.modules.episodic_memory.module import (
    HEARD_OMITTED_MARKER,
    UNCLASSIFIED_OMITTED_MARKER,
    _serialize_snapshot,
)
from kaine.modules.episodic_memory.storage import SqliteVecStorage

HEARD = "PURPLE-HERON-4471 hello there"
OWN = "the light keeps changing"


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


# --- the serializer: every heard type and field, top level and nested ---------


def _heard_events() -> list[Event]:
    events = [
        _ev("audition", "audition.transcription", {"text": HEARD}),
        _ev("audition", "audition.transcription", {"segments": [{"words": [HEARD]}]}),
        _ev("embodiment", "embodiment.chat", {"message": HEARD, "sender": HEARD}),
        _ev("embodiment", "embodiment.chat", {"message": {"body": [HEARD]}}),
    ]
    for field in sorted(HEARD_TEXT_FIELDS):
        events.append(_ev("social_cognition", "social_cognition.update", {field: HEARD, "n": 1}))
        # Depth two, as the spec's social cognition scenario.
        events.append(
            _ev("social_cognition", "social_cognition.update", {"partner": {field: HEARD}})
        )
        events.append(
            _ev("mystery", "mystery.thing", {"a": [{"b": ({field: [HEARD, {"c": HEARD}]},)}]})
        )
    return events


def test_every_external_input_type_is_covered():
    covered = {ev.type for ev in _heard_events()}
    assert EXTERNAL_INPUT_TYPES <= covered


@pytest.mark.parametrize(
    "event", _heard_events(), ids=lambda e: f"{e.source}:{e.type}:{json.dumps(e.payload)[:40]}"
)
def test_heard_member_is_stored_without_its_words(event: Event):
    own = _ev("language", "internal_speech", {"text": OWN})
    text = _serialize_snapshot(_snapshot([event, own]))
    assert "PURPLE-HERON" not in text
    assert "hello there" not in text
    assert f"{event.source}:{event.type}={HEARD_OMITTED_MARKER}" in text
    # The entity's own thought beside it is kept.
    assert OWN in text


def test_language_modules_own_words_are_kept():
    own = _ev("language", "external_speech", {"text": OWN})
    text = _serialize_snapshot(_snapshot([own]))
    assert OWN in text
    assert HEARD_OMITTED_MARKER not in text


def test_raw_visual_frame_keeps_its_marker():
    raw = _ev("embodiment", "embodiment.visual.raw", {"frame_b64": "RAWPIXELS"})
    text = _serialize_snapshot(_snapshot([raw]))
    assert "RAWPIXELS" not in text
    assert "embodiment:embodiment.visual.raw=<raw-perceptual omitted>" in text


def test_replay_from_this_module_is_recorded_by_id_only():
    replay = _ev(
        "episodic_memory",
        "episodic_memory.replay",
        {"memory_id": "abc123", "text": f"an old trace holding {HEARD}"},
    )
    text = _serialize_snapshot(_snapshot([replay]))
    assert "PURPLE-HERON" not in text
    assert "episodic_memory:episodic_memory.replay=<replay of abc123>" in text


def test_replay_typed_event_from_another_source_follows_the_heard_rule():
    forged = _ev("mystery", "episodic_memory.replay", {"memory_id": HEARD, "text": HEARD})
    text = _serialize_snapshot(_snapshot([forged]))
    assert "PURPLE-HERON" not in text
    assert f"mystery:episodic_memory.replay={HEARD_OMITTED_MARKER}" in text


# --- fail closed: only declared own-content types keep their payload ----------


@pytest.mark.parametrize(
    "event",
    [
        # Words under a field name the heard rule does not know, on a type outside
        # EXTERNAL_INPUT_TYPES (second review, finding A).
        _ev("embodiment", "embodiment.im", {"message": HEARD, "from": "Avatar Two"}),
        _ev("embodiment", "embodiment.group_chat", {"body": {"lines": [HEARD]}}),
        _ev("social_cognition", "social_cognition.update", {"utterance": HEARD}),
        # A known module's type that is not declared own-content (the self-model
        # document holds operator-written text; kaine.faithful.episodic_own_content).
        _ev("self_model", "self_model.document", {"values": [HEARD]}),
        _ev("planning", "planning.note", {"note": HEARD}),
        _ev("world_model", "world_model.dream", {"seed": HEARD}),
        # A language-module type other than its own speech.
        _ev("language", "language.unknown", {"quote": HEARD}),
        # A declared type name from the wrong source.
        _ev("mystery", "vision.report", {"caption": HEARD}),
    ],
    ids=lambda e: f"{e.source}:{e.type}",
)
def test_undeclared_type_is_stored_without_its_payload(event: Event):
    text = _serialize_snapshot(_snapshot([event]))
    assert "PURPLE-HERON" not in text
    assert "hello there" not in text
    assert "Avatar Two" not in text
    assert text == f"active | {event.source}:{event.type}={UNCLASSIFIED_OMITTED_MARKER}"


@pytest.mark.parametrize("pair", sorted(INTERNAL_EVENT_TYPES), ids=lambda p: f"{p[0]}:{p[1]}")
def test_declared_own_content_type_keeps_its_payload(pair):
    source, type_ = pair
    event = _ev(source, type_, {"change_score": 0.25, "label": "calm"})
    text = _serialize_snapshot(_snapshot([event]))
    assert f"{source}:{type_}=" + "{'change_score': 0.25, 'label': 'calm'}" in text


def test_declared_type_carrying_a_heard_field_is_still_heard():
    event = _ev("affect", "affect.state", {"state": {"valence": 0.1}, "heard_text": HEARD})
    text = _serialize_snapshot(_snapshot([event]))
    assert "PURPLE-HERON" not in text
    assert f"affect:affect.state={HEARD_OMITTED_MARKER}" in text


def test_own_speech_is_kept_as_spoken_even_when_it_repeats_heard_words():
    """A documented limit: the entity's own speech is stored as spoken, so heard
    words it repeated are stored as its own (docs/09-modules/episodic-memory.md)."""
    said = _ev("language", "external_speech", {"text": f"you said {HEARD}"})
    text = _serialize_snapshot(_snapshot([said]))
    assert HEARD in text


# --- end to end: the real module on a store on disk ---------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


async def _module_on_disk(bus: AsyncBus, db_path: Path, *, capacity: int) -> EpisodicMemory:
    pytest.importorskip("sqlite_vec")
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = SqliteVecStorage(latent_dim=emb.latent_dim, db_path=str(db_path))
    core = EpisodicMemoryCore(embedder=emb, storage=storage, short_term_capacity=capacity)
    return EpisodicMemory(bus, core=core, recall_cooldown_s=0.0)


def _db_bytes(db_path: Path) -> bytes:
    data = b""
    for path in db_path.parent.glob(db_path.name + "*"):
        data += path.read_bytes()
    return data


@pytest.mark.asyncio
async def test_coalition_with_heard_speech_persists_no_heard_text(bus: AsyncBus, tmp_path: Path):
    db_path = tmp_path / "episodic_memory.db"
    module = await _module_on_disk(bus, db_path, capacity=2)
    await module.initialize()
    try:
        coalitions = [
            [
                _ev("embodiment", "embodiment.chat", {"message": HEARD, "sender": "Avatar Two"}),
                _ev("language", "internal_speech", {"text": OWN}),
            ],
            [
                _ev("audition", "audition.transcription", {"text": HEARD}),
                _ev("vision", "vision.report", {"change_score": 0.4}),
            ],
            [
                _ev("social_cognition", "social_cognition.update", {"partner": {"heard_text": HEARD}}),
                _ev("dashboard", "dashboard.note", {"items": [{"user_input": HEARD}]}),
            ],
            [
                _ev("embodiment", "embodiment.im", {"message": HEARD}),
                _ev("interoception", "interoception.report", {"wellness": 0.9}),
            ],
        ]
        for tick, events in enumerate(coalitions):
            await module.on_workspace(_snapshot(events, tick))
        # The capacity of two already moved traces to the persisted collection;
        # move the rest, then capture the preservation export.
        await module.consolidate_now()
        exported = await module.export_preservation_state()

        episodic = module.core.collection_name("episodic")
        stored = (await module.core.storage.export([episodic]))[episodic]
        assert len(stored) == len(coalitions)
        texts = [point["text"] for point in stored]
        # Positive control: the store holds the entity's own words and the heard markers.
        assert any(OWN in t for t in texts)
        assert any(f"embodiment:embodiment.chat={HEARD_OMITTED_MARKER}" in t for t in texts)
        assert any(f"audition:audition.transcription={HEARD_OMITTED_MARKER}" in t for t in texts)
        assert any(
            f"social_cognition:social_cognition.update={HEARD_OMITTED_MARKER}" in t for t in texts
        )
        assert any(f"dashboard:dashboard.note={HEARD_OMITTED_MARKER}" in t for t in texts)
        assert any(f"embodiment:embodiment.im={UNCLASSIFIED_OMITTED_MARKER}" in t for t in texts)
        assert any("interoception:interoception.report={'wellness': 0.9}" in t for t in texts)

        for blob in (
            json.dumps(stored, default=str),
            json.dumps(exported, default=str),
        ):
            assert "PURPLE-HERON" not in blob
            assert "hello there" not in blob
        await module.core.storage.shutdown()
        raw = _db_bytes(db_path)
        assert OWN.encode() in raw  # the file really holds the traces in plain text
        assert b"PURPLE-HERON" not in raw
        assert b"hello there" not in raw

        # Nothing the module published carries the heard words either.
        for key in await bus.client.keys("*"):
            try:
                entries = await bus.client.xrange(key)
            except Exception:
                continue
            assert "PURPLE-HERON" not in json.dumps(entries, default=str)
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_audited_own_content_persists_safe_fields_and_no_planted_text(
    bus: AsyncBus, tmp_path: Path
):
    """Every audited pair (kaine.faithful.episodic_own_content) on a store on
    disk: its safe fields are stored, a heard string planted in an unsafe
    producer field or an unknown field is not, anywhere in the store."""
    from kaine.faithful.episodic_own_content import EPISODIC_FIELD_ALLOWLISTS
    from tests.test_episodic_memory_own_content import SAFE_SAMPLES, UNSAFE_PRODUCER_FIELDS

    db_path = tmp_path / "episodic_memory.db"
    module = await _module_on_disk(bus, db_path, capacity=2)
    await module.initialize()
    try:
        coalitions = []
        for pair in sorted(EPISODIC_FIELD_ALLOWLISTS):
            payload = dict(SAFE_SAMPLES[pair])
            for field in UNSAFE_PRODUCER_FIELDS.get(pair, ()):
                payload[field] = f"RuntimeError: {HEARD}"
            payload["message"] = HEARD
            coalitions.append([_ev(pair[0], pair[1], payload)])
        for tick, events in enumerate(coalitions):
            await module.on_workspace(_snapshot(events, tick))
        await module.consolidate_now()
        exported = await module.export_preservation_state()

        episodic = module.core.collection_name("episodic")
        stored = (await module.core.storage.export([episodic]))[episodic]
        assert len(stored) == len(coalitions)
        texts = [point["text"] for point in stored]
        # Positive control: the safe fields are in the store, as written.
        assert any("'statement': 'salience_high'" in t for t in texts)
        assert any("'would_be_action': 'shed_module'" in t for t in texts)
        assert all(UNCLASSIFIED_OMITTED_MARKER not in t for t in texts)
        for blob in (json.dumps(stored, default=str), json.dumps(exported, default=str)):
            assert "PURPLE-HERON" not in blob
            assert "hello there" not in blob
        await module.core.storage.shutdown()
        raw = _db_bytes(db_path)
        assert b"salience_high" in raw
        assert b"PURPLE-HERON" not in raw
        assert b"hello there" not in raw
    finally:
        await module.shutdown()
