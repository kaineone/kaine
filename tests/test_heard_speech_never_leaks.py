# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.faithful.templates import HEARD_SPEECH_PLACEHOLDER, redact_heard_speech
from kaine.modules.lingua import EXTERNAL_STREAM, FakeChatClient, IntentExpressionLog, Lingua
from kaine.modules.mnemos.module import _serialize_snapshot
from kaine.workspace.report_policy import SelfInitiatedReportPolicy
from kaine.workspace.volition import SPEAK


async def _wait_for_entries(bus: AsyncBus, stream: str, *, timeout_s: float = 2.0):
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        entries = await bus.client.xrange(stream)
        if entries:
            return entries
        await asyncio.sleep(0.02)
    return await bus.client.xrange(stream)


def _payloads(entries):
    out = []
    for _entry_id, fields in entries:
        raw = fields.get("payload")
        if isinstance(raw, str):
            out.append(json.loads(raw))
        elif raw:
            out.append(raw)
    return out


def _records(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _make_lingua(bus: AsyncBus, tmp_path: Path, responses=None) -> Lingua:
    return Lingua(
        bus,
        chat_client=FakeChatClient(responses=responses),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )


def _snapshot(events=None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=0, selected_events=events or [], inhibited=False)


async def _say(lingua, *, about, snapshot, about_kind):
    """Run one external utterance to completion, as the dispatcher would."""
    return await lingua._produce_inner(
        about=about,
        snapshot=snapshot,
        mode="external",
        stream=EXTERNAL_STREAM,
        about_kind=about_kind,
    )


def _event(source, type_, payload, salience=0.6):
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_heard_sentinel_never_leaves_lingua(bus: AsyncBus, tmp_path: Path):
    """Heard speech never reaches the bus or the log, including through
    Lingua's own earlier external_speech event coming back in a coalition."""
    sentinel = "PURPLE-HERON-4471 said this"
    lingua = _make_lingua(bus, tmp_path, responses=["First reply.", "Second reply."])
    await lingua.initialize()
    try:
        heard = _snapshot([("t1", _event("audition", "audition.transcription", {"text": sentinel}, 0.9))])
        await _say(lingua, about=sentinel, snapshot=heard, about_kind="heard")
        first_payload = _payloads(await bus.client.xrange(EXTERNAL_STREAM))[-1]

        # A later coalition holds that earlier event. Before the fix its
        # user_input and unredacted rendering carried the heard text back in.
        echo = dict(first_payload)
        echo["user_input"] = sentinel  # a legacy event that still carries it
        later = _snapshot([("l1", _event("lingua", "external_speech", echo))])
        await _say(
            lingua, about="reflecting on what just happened", snapshot=later, about_kind="event"
        )

        for payload in _payloads(await bus.client.xrange(EXTERNAL_STREAM)):
            assert sentinel not in json.dumps(payload)
        lingua_out = await bus.client.xrange("lingua.out")
        assert lingua_out
        assert sentinel not in json.dumps(lingua_out)
        records = _records(lingua.intent_log.path)
        assert len(records) == 2
        assert sentinel not in lingua.intent_log.path.read_text()
        assert HEARD_SPEECH_PLACEHOLDER in records[1]["faithful_rendering"]

        snapshot = _snapshot(_events_from_entries(await bus.client.xrange(EXTERNAL_STREAM)))
        assert sentinel not in _serialize_snapshot(snapshot)
    finally:
        await lingua.shutdown()


def test_redact_heard_speech_by_field():
    sentinel = "PURPLE-HERON-4471 said this"
    unknown = _event("somewhere", "something.happened", {"user_input": sentinel, "n": 3})
    line = redact_heard_speech(unknown)
    assert line is not None
    assert sentinel not in line
    assert HEARD_SPEECH_PLACEHOLDER in line

    transcription = _event("audition", "audition.transcription", {"text": sentinel})
    assert redact_heard_speech(transcription) == f'Speech heard: "{HEARD_SPEECH_PLACEHOLDER}".'

    # `text` is heard only on audition.transcription.
    assert redact_heard_speech(_event("vox", "vox.something", {"text": "spoken by me"})) is None


@pytest.mark.asyncio
async def test_payload_user_input_follows_the_trigger(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path, responses=["felt reply", "heard reply"])
    await lingua.initialize()
    try:
        felt = "a pull towards company"
        await _say(lingua, about=felt, snapshot=_snapshot(), about_kind="felt")
        felt_payload = _payloads(await bus.client.xrange(EXTERNAL_STREAM))[-1]
        assert felt_payload["user_input"] == felt

        sentinel = "PURPLE-HERON-4471 said this"
        heard = _snapshot([("t1", _event("audition", "audition.transcription", {"text": sentinel}, 0.9))])
        await _say(lingua, about=sentinel, snapshot=heard, about_kind="heard")
        heard_payload = _payloads(await bus.client.xrange(EXTERNAL_STREAM))[-1]
        assert "user_input" not in heard_payload
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_felt_phrase_echoed_by_lingua_stays_felt(bus: AsyncBus, tmp_path: Path):
    """Lingua's own earlier event carries a felt phrase as user_input. The same
    phrase driving the next utterance is still felt, not heard."""
    lingua = _make_lingua(bus, tmp_path, responses=["one", "two"])
    await lingua.initialize()
    try:
        felt = "a pull towards company"
        await _say(lingua, about=felt, snapshot=_snapshot(), about_kind="felt")
        first_payload = _payloads(await bus.client.xrange(EXTERNAL_STREAM))[-1]
        later = _snapshot([("l1", _event("lingua", "external_speech", first_payload))])
        await _say(lingua, about=felt, snapshot=later, about_kind="felt")
        second_payload = _payloads(await bus.client.xrange(EXTERNAL_STREAM))[-1]
        assert second_payload["user_input"] == felt
        prompt = _records(lingua.intent_log.path)[-1]["prompt"]
        assert "## What was just said to me" not in prompt
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_default_report_policy_intents_are_events(bus: AsyncBus, tmp_path: Path):
    policy = SelfInitiatedReportPolicy()
    top_event = _event("topos", "topos.surprise", {"surprise": 0.95}, 0.9)
    snapshot = WorkspaceSnapshot(
        tick_index=1,
        selected_events=[("e1", top_event)],
        inhibited=False,
        salience_scores={"e1": 0.9},
    )
    intents = policy(snapshot)
    assert intents
    for intent in intents:
        assert intent.about_kind == "event"

    speak_intent = next(i for i in intents if i.kind == SPEAK)
    lingua = _make_lingua(bus, tmp_path, responses=["report reply"])
    await lingua.initialize()
    try:
        await _say(
            lingua, about=speak_intent.about, snapshot=snapshot, about_kind=speak_intent.about_kind
        )
        prompt = _records(lingua.intent_log.path)[0]["prompt"]
        assert "## What was just said to me" not in prompt
        assert "## What moves me to speak" in prompt
    finally:
        await lingua.shutdown()


def test_every_report_policy_branch_tags_its_intent_as_an_event():
    """Speak, think and interrupt intents are all tagged, so none of them is
    framed as something said to the entity."""
    t = [0.0]
    policy = SelfInitiatedReportPolicy(
        report_threshold=0.6,
        think_threshold=0.45,
        interrupt_threshold=0.9,
        clock=lambda: t[0],
        guard_clock=lambda: t[0],
    )

    def snap(source, surprise):
        return WorkspaceSnapshot(
            tick_index=1,
            selected_events=[("e1", _event(source, f"{source}.surprise", {}, surprise))],
            inhibited=False,
            salience_scores={"e1": surprise},
        )

    think = policy(snap("soma", 0.5))
    assert [i.kind for i in think] == ["think"]
    t[0] += 10.0
    speak = policy(snap("topos", 0.7))
    assert [i.kind for i in speak] == [SPEAK] and not speak[0].interrupt
    t[0] += 1.0
    interrupt = policy(snap("audition", 0.95))
    assert interrupt and interrupt[0].interrupt
    for intent in think + speak + interrupt:
        assert intent.about_kind == "event"


@pytest.mark.asyncio
async def test_mundus_chat_never_leaves_lingua(bus: AsyncBus, tmp_path: Path):
    """Other avatars' chat and their identifiers are redacted like heard
    speech and never reach the bus or the log."""
    sentinel = "PURPLE-HERON-4471 said this"
    sender = "Avatar Two"
    lingua = _make_lingua(bus, tmp_path, responses=["First reply.", "Second reply."])
    await lingua.initialize()
    try:
        chat = _snapshot(
            [("t1", _event("mundus", "mundus.chat", {"message": sentinel, "sender": sender}, 0.9))]
        )
        await _say(lingua, about="chat event", snapshot=chat, about_kind="event")
        await _say(lingua, about=sentinel, snapshot=_snapshot(), about_kind="heard")

        for key in await bus.client.keys("*"):
            try:
                entries = await bus.client.xrange(key)
            except Exception:
                continue
            for payload in _payloads(entries):
                body = json.dumps(payload)
                assert sentinel not in body
                assert sender not in body

        records = _records(lingua.intent_log.path)
        assert len(records) == 2
        log_text = lingua.intent_log.path.read_text()
        assert sentinel not in log_text
        assert sender not in log_text
        assert HEARD_SPEECH_PLACEHOLDER in records[0]["faithful_rendering"]

        snapshot = _snapshot(_events_from_entries(await bus.client.xrange(EXTERNAL_STREAM)))
        serialized = _serialize_snapshot(snapshot)
        assert sentinel not in serialized
        assert sender not in serialized
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_nested_heard_field_never_leaves_lingua(bus: AsyncBus, tmp_path: Path):
    """Heard-speech payload fields are redacted at any nesting depth."""
    sentinel = "PURPLE-HERON-4471 nested"
    lingua = _make_lingua(bus, tmp_path, responses=["reply"])
    await lingua.initialize()
    try:
        note = _snapshot(
            [
                (
                    "n1",
                    _event(
                        "nexus",
                        "nexus.note",
                        {"x": {"user_input": sentinel}, "items": [{"heard_text": sentinel}]},
                        0.9,
                    ),
                )
            ]
        )
        await _say(lingua, about="note", snapshot=note, about_kind="event")

        for key in await bus.client.keys("*"):
            try:
                entries = await bus.client.xrange(key)
            except Exception:
                continue
            for payload in _payloads(entries):
                assert sentinel not in json.dumps(payload)

        assert sentinel not in lingua.intent_log.path.read_text()

        snapshot = _snapshot(_events_from_entries(await bus.client.xrange(EXTERNAL_STREAM)))
        assert sentinel not in _serialize_snapshot(snapshot)
    finally:
        await lingua.shutdown()


def test_redact_heard_speech_external_types_and_nesting():
    sentinel = "PURPLE-HERON-4471"

    chat = _event("mundus", "mundus.chat", {"message": sentinel, "sender": "Avatar Two"})
    line = redact_heard_speech(chat)
    assert line is not None
    assert sentinel not in line
    assert "Avatar Two" not in line
    assert HEARD_SPEECH_PLACEHOLDER in line

    nested = _event(
        "nexus",
        "nexus.note",
        {"x": {"user_input": sentinel}, "items": [{"heard_text": sentinel}]},
    )
    line = redact_heard_speech(nested)
    assert line is not None
    assert sentinel not in line
    assert HEARD_SPEECH_PLACEHOLDER in line

    plain = _event("me", "me.utterance", {"text": "I am the being"})
    assert redact_heard_speech(plain) is None

    original = {"message": sentinel, "sender": "Avatar Two"}
    chat2 = _event("mundus", "mundus.chat", original)
    redact_heard_speech(chat2)
    assert chat2.payload == original


def test_external_input_types_single_source():
    import kaine.faithful.external_input
    import kaine.modules.hypnos.ignition_audit

    assert (
        kaine.modules.hypnos.ignition_audit.EXTERNAL_INPUT_TYPES
        is kaine.faithful.external_input.EXTERNAL_INPUT_TYPES
    )


async def _assert_sentinel_nowhere(bus: AsyncBus, lingua, sentinel: str) -> None:
    for key in await bus.client.keys("*"):
        try:
            entries = await bus.client.xrange(key)
        except Exception:
            continue
        for payload in _payloads(entries):
            assert sentinel not in json.dumps(payload)
    assert sentinel not in lingua.intent_log.path.read_text()


@pytest.mark.asyncio
async def test_nested_external_input_text_makes_an_event_about_heard(
    bus: AsyncBus, tmp_path: Path
):
    """An about that repeats text nested anywhere in an external-input event is
    heard speech, even when the trigger is tagged as an event."""
    sentinel = "PURPLE-HERON-4471 nested chat"
    lingua = _make_lingua(bus, tmp_path, responses=["reply"])
    await lingua.initialize()
    try:
        chat = _snapshot(
            [("c1", _event("mundus", "mundus.chat", {"message": {"text": sentinel}}, 0.9))]
        )
        await _say(lingua, about=sentinel, snapshot=chat, about_kind="event")
        await _assert_sentinel_nowhere(bus, lingua, sentinel)
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_nested_heard_field_value_is_scrubbed_from_an_event_about(
    bus: AsyncBus, tmp_path: Path
):
    """A heard-speech field nested in any coalition event is scrubbed from the
    logged prompt even when an event-tagged about repeats it."""
    sentinel = "PURPLE-HERON-4471 nested field"
    lingua = _make_lingua(bus, tmp_path, responses=["reply"])
    await lingua.initialize()
    try:
        note = _snapshot(
            [("n1", _event("nexus", "nexus.note", {"x": {"user_input": sentinel}}, 0.9))]
        )
        await _say(lingua, about=sentinel, snapshot=note, about_kind="event")
        assert sentinel not in lingua.intent_log.path.read_text()
    finally:
        await lingua.shutdown()


def _events_from_entries(entries):
    out = []
    for entry_id, fields in entries:
        payload = fields.get("payload")
        if isinstance(payload, str):
            payload = json.loads(payload) if payload else {}
        elif payload is None:
            payload = {}
        source = fields.get("source", "lingua")
        type_ = fields.get("type", "external_speech")
        salience = fields.get("salience")
        if salience is not None:
            try:
                salience = float(salience)
            except Exception:
                salience = 0.6
        else:
            salience = 0.6
        ts_raw = fields.get("timestamp")
        if ts_raw:
            try:
                timestamp = datetime.fromisoformat(ts_raw)
            except Exception:
                timestamp = datetime.now(timezone.utc)
        else:
            timestamp = datetime.now(timezone.utc)
        out.append(
            (
                entry_id,
                Event(
                    source=source,
                    type=type_,
                    payload=payload,
                    salience=salience,
                    timestamp=timestamp,
                ),
            )
        )
    return out


def test_redact_heard_speech_list_and_dict_fields():
    s1 = "SENTINEL-LIST-001"
    s2 = "SENTINEL-DICT-002"
    s3 = "SENTINEL-TRANSCRIPT-003"

    list_event = _event(
        "somewhere", "something.happened", {"user_input": [s1, {"x": s2}]}
    )
    line = redact_heard_speech(list_event)
    assert line is not None
    assert s1 not in line
    assert s2 not in line
    assert HEARD_SPEECH_PLACEHOLDER in line

    dict_event = _event(
        "somewhere", "something.happened", {"transcription": {"text": s3}}
    )
    line = redact_heard_speech(dict_event)
    assert line is not None
    assert s3 not in line
    assert HEARD_SPEECH_PLACEHOLDER in line


@pytest.mark.asyncio
async def test_heard_list_payload_never_leaves_lingua(bus: AsyncBus, tmp_path: Path):
    sentinel = "PURPLE-HERON-LIST-4471"
    lingua = _make_lingua(bus, tmp_path, responses=["reply"])
    await lingua.initialize()
    try:
        event = _event(
            "nexus",
            "nexus.note",
            {"user_input": [sentinel]},
            0.9,
        )
        await _say(
            lingua, about="reflecting", snapshot=_snapshot([("n1", event)]), about_kind="event"
        )
        await _assert_sentinel_nowhere(bus, lingua, sentinel)
        records = _records(lingua.intent_log.path)
        assert records
        assert HEARD_SPEECH_PLACEHOLDER in records[-1]["faithful_rendering"]
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_about_matching_list_field_value_is_scrubbed(
    bus: AsyncBus, tmp_path: Path
):
    sentinel = "PURPLE-HERON-LIST-4471"
    lingua = _make_lingua(bus, tmp_path, responses=["reply"])
    await lingua.initialize()
    try:
        event = _event(
            "nexus",
            "nexus.note",
            {"user_input": [sentinel]},
            0.9,
        )
        await _say(
            lingua, about=sentinel, snapshot=_snapshot([("n1", event)]), about_kind="event"
        )
        await _assert_sentinel_nowhere(bus, lingua, sentinel)
    finally:
        await lingua.shutdown()
