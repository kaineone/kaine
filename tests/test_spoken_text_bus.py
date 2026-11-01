# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Heard and spoken words travel only on the never-persisted bus (change
``heard-text-volatile-bus``)."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.faithful.external_input import (
    SPOKEN_TEXT_METADATA_KEYS,
    SPOKEN_TEXT_RULE_VERSION,
    split_spoken_text,
    spoken_counts,
    words_unavailable,
)
from tests._companion import attach_test_volatile

HEARD = "come and see this right now"
OWN = "I can see the light moving on the wall"


def _ev(source, type_, payload, salience=0.5) -> Event:
    return Event(
        source=source, type=type_, payload=payload, salience=salience,
        timestamp=datetime(2026, 11, 1, tzinfo=timezone.utc),
    )


def _transcription(text=HEARD, **extra):
    payload = {
        "text": text, "source_label": "live_mic", "model": "fake-stt", "backend": "fake",
        "latency_ms": 12.5, "audio_bytes_length": 1024, "prediction_error": 0.3,
    }
    payload.update(extra)
    return _ev("audition", "audition.transcription", payload)


def _utterance(mode="external", text=OWN):
    return _ev("language", f"{mode}_speech", {
        "text": text, "mode": mode, "model": "fake-organ", "prompt_length": 40,
        "latency_ms": 9.0, "record_id": "r-1", "user_input": "[heard speech] and more",
        "faithful_rendering": "- What I see is barely changing.",
    })


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    b = AsyncBus(BusConfig(password="x", audit_required=False), client=fakeredis.FakeRedis(decode_responses=True))
    yield b
    await b.close()


def _spoken_declared(bus):
    return attach_test_volatile(
        bus,
        ("audition.out", "spoken_text"),
        ("language.external", "spoken_text"),
        ("language.internal", "spoken_text"),
        ("language.out", "spoken_text"),
        ("embodiment.out", "spoken_text"),
        ("episodic_memory.out", "spoken_text"),
    )


async def _raw(bus, stream):
    return [dict(f) for _eid, f in await bus.client.xrange(stream)]


def _no_words(text: str) -> None:
    for words in (HEARD, OWN, "[heard speech] and more", "barely changing"):
        assert words not in text


def test_rule_version_and_metadata_keys():
    assert SPOKEN_TEXT_RULE_VERSION == 1
    assert SPOKEN_TEXT_METADATA_KEYS == {"source_label", "model", "backend"}


def test_split_transcription():
    main, diverted = split_spoken_text(_transcription())
    assert [(p, v) for p, v, _i in diverted] == [(("text",), HEARD)]
    assert main == {
        "source_label": "live_mic", "model": "fake-stt", "backend": "fake", "latency_ms": 12.5,
        "audio_bytes_length": 1024, "prediction_error": 0.3, "text_chars": 27, "text_words": 6,
    }


def test_split_error_transcription():
    main, diverted = split_spoken_text(_transcription(text="", error="decode failed near 'come'"))
    assert {p for p, _v, _i in diverted} == {("text",), ("error",)}
    assert "error" not in main and main["text_chars"] == 0 and main["text_words"] == 0


def test_split_chat_unknown_string_diverted():
    event = _ev("embodiment", "embodiment.chat", {
        "speaker_name": "Ada", "message": HEARD, "channel": 0, "meta": {"note": "hello"},
        "tags": ["greeting"], "source_label": "world",
    })
    main, diverted = split_spoken_text(event)
    assert {p for p, _v, _i in diverted} == {("speaker_name",), ("message",), ("meta", "note"), ("tags",)}
    assert main == {"channel": 0, "meta": {}, "source_label": "world"}


def test_split_language_event_all_three_fields():
    for mode in ("external", "internal"):
        main, diverted = split_spoken_text(_utterance(mode))
        assert {p for p, _v, _i in diverted} == {("text",), ("user_input",), ("faithful_rendering",)}
        _no_words(json.dumps(main))
        assert main["text_chars"] == len(OWN) and main["text_words"] == 9


def test_split_replay_text():
    event = _ev("episodic_memory", "episodic_memory.replay", {"memory_id": "m-1", "text": OWN, "affect_intensity": 0.2})
    main, diverted = split_spoken_text(event)
    assert [p for p, _v, _i in diverted] == [("text",)]
    assert main == {"memory_id": "m-1", "affect_intensity": 0.2, "text_chars": len(OWN), "text_words": 9}


def test_nested_heard_field_on_another_event():
    event = _ev("planning", "planning.proposal", {"x": 1, "context": [{"user_text": HEARD}]})
    main, diverted = split_spoken_text(event)
    assert [p for p, _v, _i in diverted] == [("context", 0, "user_text")]
    assert main == {"x": 1, "context": [{}]}  # no counts: the diverted text is not top-level


def test_event_without_words_unchanged():
    event = _ev("affect", "affect.state", {"valence": 0.1, "arousal": 0.4, "label": "calm"})
    main, diverted = split_spoken_text(event)
    assert main is event.payload and diverted == []


def test_counts():
    assert spoken_counts({"text": "come and see this"}) == (17, 4)
    assert spoken_counts({"text_chars": 17, "text_words": 4}) == (17, 4)
    assert spoken_counts({"text_chars": True}) == (0, 0)
    assert words_unavailable({"text_chars": 5, "text_words": 1})
    assert not words_unavailable({"text_chars": 0})
    assert not words_unavailable({"text": "x", "text_chars": 1})


@pytest.mark.asyncio
async def test_main_publish_holds_no_words(bus):
    volatile = _spoken_declared(bus)
    await bus.publish(_transcription())
    from kaine.bus.schema import validate_event

    u = _utterance()
    await bus.publish_on("language.external", u)
    await bus.publish(validate_event(source="language", type=u.type, payload=u.payload, salience=0.2, timestamp=u.timestamp))
    for stream in ("audition.out", "language.external", "language.out"):
        (fields,) = await _raw(bus, stream)
        _no_words(json.dumps(fields))
        assert fields["companion"].startswith(stream + ".companion:")
    (fields,) = await _raw(bus, "audition.out")
    assert json.loads(fields["payload"])["text_chars"] == 27
    # The words are on the volatile instance only, and the join restores the
    # event exactly (no counts left, key order as published).
    ((_eid, event),) = await bus.read("audition.out")
    joined, ok = await bus.join_companion(event)
    assert ok and json.dumps(joined.payload) == json.dumps(_transcription().payload)
    assert HEARD in json.dumps([await volatile.client.xrange(s) for s in await volatile.client.keys("*")])


@pytest.mark.asyncio
async def test_undeclared_words_never_stay_on_the_main_bus(bus):
    await bus.publish(_transcription())
    (fields,) = await _raw(bus, "audition.out")
    _no_words(json.dumps(fields))
    assert "companion" not in fields


@pytest.mark.asyncio
async def test_publish_without_words_byte_identical(bus):
    from kaine.bus.client import _encode_event

    _spoken_declared(bus)
    event = _ev("affect", "affect.state", {"valence": 0.1, "label": "calm"})
    await bus.publish(event)
    (fields,) = await _raw(bus, "affect.out")
    assert fields == _encode_event(event)


def test_broadcast_member_references_not_copies():
    from tests.test_latent_content_privacy import _cycle

    cycle = _cycle()
    t = _transcription().model_copy(update={"companion": "audition.out.companion:7-0"})
    plain = _ev("affect", "affect.state", {"valence": 0.1})
    from kaine.cycle.types import WorkspaceSnapshot

    payload = cycle._snapshot_to_payload(
        WorkspaceSnapshot(tick_index=1, selected_events=[("1-0", t), ("2-0", plain)]), True
    )
    assert payload["selected"][0]["companion"] == "audition.out.companion:7-0"
    assert "companion" not in payload["selected"][1]


@pytest.mark.asyncio
async def test_broadcast_members_hold_no_words_on_the_bus(bus):
    volatile = _spoken_declared(bus)
    snapshot = {"tick_index": 1, "selected": [
        {"entry_id": "1-0", "source": "audition", "type": "audition.transcription", "salience": 0.8,
         "payload": dict(_transcription().payload), "companion": "audition.out.companion:7-0"},
        {"entry_id": "2-0", "source": "language", "type": "external_speech", "salience": 0.5,
         "payload": dict(_utterance().payload)},
    ], "metadata": {}}
    await bus.publish_workspace(snapshot)
    (fields,) = await _raw(bus, "workspace.broadcast")
    _no_words(fields["snapshot"])
    stored = json.loads(fields["snapshot"])
    assert stored["selected"][0]["companion"] == "audition.out.companion:7-0"
    assert await volatile.client.keys("*") == []  # no second copy


class _Plain:
    pass


@pytest.mark.asyncio
async def test_decoder_joins_only_declaring_modules(bus):
    from kaine.modules.base import BaseModule

    _spoken_declared(bus)
    await bus.publish(_transcription())
    ((eid, event),) = await bus.read("audition.out")
    payload = {"tick_index": 1, "selected": [{
        "entry_id": eid, "source": event.source, "type": event.type, "salience": event.salience,
        "payload": event.payload, "timestamp": event.timestamp.isoformat(), "companion": event.companion,
    }]}

    class Reader(BaseModule):
        name = "reader"
        reads_spoken_text = True

    class Other(BaseModule):
        name = "other"

    joined = await Reader(bus)._decode_broadcast(payload)
    plain = await Other(bus)._decode_broadcast(payload)
    assert joined.selected_events[0][1].payload["text"] == HEARD
    assert "text" not in plain.selected_events[0][1].payload
    assert plain.selected_events[0][1].payload["text_chars"] == 27
    # A gone companion: the reader gets the main-bus copy, no error.
    await bus.volatile.flush()
    gone = await Reader(bus)._decode_broadcast(payload)
    assert words_unavailable(gone.selected_events[0][1].payload)


def test_declarations():
    from kaine.modules.audition.module import Audition
    from kaine.modules.embodiment.module import Embodiment
    from kaine.modules.episodic_memory.module import EpisodicMemory
    from kaine.modules.language.module import Language

    assert {d.stream for d in Language.companion_declarations({})} == {
        "language.external", "language.internal", "language.out"}
    assert Audition.companion_declarations({}) == []
    assert [d.stream for d in Audition.companion_declarations({"transcription_enabled": True})] == ["audition.out"]
    assert [d.stream for d in Embodiment.companion_declarations({})] == ["embodiment.out"]
    assert [d.stream for d in EpisodicMemory.companion_declarations({})] == ["episodic_memory.out"]
    for cls in (Language, Audition, Embodiment, EpisodicMemory):
        assert all(d.field_set == "spoken_text" for d in cls.companion_declarations({"transcription_enabled": True}))
    assert Language.reads_spoken_text and EpisodicMemory.reads_spoken_text
    assert not Audition.reads_spoken_text


@pytest.mark.asyncio
async def test_boot_refused_without_volatile_instance_when_language_on(bus):
    from kaine.boot.companions import config_declarations, declare_and_check
    from kaine.modules.language.module import Language

    class _LanguageStub:
        name = "language"

    _LanguageStub.companion_declarations = Language.companion_declarations
    (reason,) = await declare_and_check(bus, [_LanguageStub()], {})
    assert "language" in reason and "volatile bus" in reason
    assert {d.stream for d in config_declarations({"modules": {"language": True}})} == {
        "language.external", "language.internal", "language.out"}

