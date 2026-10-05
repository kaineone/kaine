# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.hypnos.ignition_audit import classify_realizations
from kaine.modules.lingua import (
    EXTERNAL_STREAM,
    INTERNAL_STREAM,
    FakeChatClient,
    IntentExpressionLog,
    Lingua,
)
from kaine.modules.lingua.context import PERSONA_TEMPLATE_VERSION
from kaine.workspace.volition import SPEAK
from tests._fakes import wait_for


async def _publish_intent(bus: AsyncBus, kind: str, about: str) -> None:
    event = Event(
        source="volition",
        type=f"intent.{kind}",
        payload={"kind": kind, "about": about},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)


async def _wait_for_entries(bus: AsyncBus, stream: str, *, timeout_s: float = 2.0):
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        entries = await bus.client.xrange(stream)
        if entries:
            return entries
        await asyncio.sleep(0.02)
    return await bus.client.xrange(stream)


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


def _event(source="soma", type_="soma.report", payload=None) -> tuple:
    return (
        "e0",
        Event(
            source=source,
            type=type_,
            payload=payload or {"wellness": 0.5, "alerts": []},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        ),
    )


@pytest.mark.asyncio
async def test_invalid_construction(bus: AsyncBus):
    with pytest.raises(ValueError):
        Lingua(bus, chat_client=FakeChatClient(), baseline_salience=2.0)
    with pytest.raises(ValueError):
        Lingua(bus, chat_client=FakeChatClient(), alert_salience=-0.1)


@pytest.mark.asyncio
async def test_think_intent_origin_copied_to_internal_speech(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path, responses=["inner thought"])
    event = Event(
        source="volition",
        type="intent.think",
        payload={"kind": "think", "about": "origin test", "origin": "nous"},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await lingua._dispatch_intent(event)
    entries = await _wait_for_entries(bus, INTERNAL_STREAM)
    assert entries
    payload_json = entries[0][1].get("payload") or entries[0][1]["payload"]
    payload = json.loads(payload_json)
    assert payload.get("origin") == "nous"


@pytest.mark.asyncio
async def test_speak_publishes_only_to_external(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path, responses=["spoken text"])
    out = await lingua.speak("hello")
    assert out == "spoken text"
    ext = await bus.client.xrange(EXTERNAL_STREAM)
    inn = await bus.client.xrange(INTERNAL_STREAM)
    assert len(ext) == 1
    assert len(inn) == 0


@pytest.mark.asyncio
async def test_think_publishes_only_to_internal(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path, responses=["internal thought"])
    out = await lingua.think("ponder")
    assert out == "internal thought"
    ext = await bus.client.xrange(EXTERNAL_STREAM)
    inn = await bus.client.xrange(INTERNAL_STREAM)
    assert len(ext) == 0
    assert len(inn) == 1


@pytest.mark.asyncio
async def test_speech_published_with_semantic_event_types(bus: AsyncBus, tmp_path: Path):
    """Producer contract: external speech is type 'external_speech', internal is
    'internal_speech' — the semantic types the conversation router and the
    evaluation observers (ab_divergence/proactive_audit/affect_correlation) and
    the volition guards filter on. Exercises the real producer, not a hand-built
    event, which is the gap that let the producer emit the stream name as type."""
    lingua = _make_lingua(bus, tmp_path, responses=["spoken", "thought"])
    await lingua.speak("hello")
    await lingua.think("ponder")
    ext = await bus.client.xrange(EXTERNAL_STREAM)
    inn = await bus.client.xrange(INTERNAL_STREAM)
    assert ext and ext[0][1]["type"] == "external_speech"
    assert inn and inn[0][1]["type"] == "internal_speech"


@pytest.mark.asyncio
async def test_intent_log_records_both_modes(bus: AsyncBus, tmp_path: Path):
    log_path = tmp_path / "intent.jsonl"
    lingua = Lingua(
        bus,
        chat_client=FakeChatClient(responses=["a", "b"]),
        intent_log=IntentExpressionLog(log_path),
        model_id="m",
    )
    await lingua.speak("p1")
    await lingua.think("p2")
    records = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    assert len(records) == 2
    modes = [r["mode"] for r in records]
    assert "external" in modes
    assert "internal" in modes


@pytest.mark.asyncio
async def test_intent_log_includes_faithful_rendering(bus: AsyncBus, tmp_path: Path):
    log_path = tmp_path / "intent.jsonl"
    lingua = Lingua(
        bus,
        chat_client=FakeChatClient(responses=["spoken"]),
        intent_log=IntentExpressionLog(log_path),
        model_id="m",
    )
    snap = _snapshot([_event()])
    await lingua.speak("hi", snapshot=snap)
    records = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    assert records[0]["faithful_rendering"]
    assert "Soma" in records[0]["faithful_rendering"]  # template starts with "Soma reports"


@pytest.mark.asyncio
async def test_bus_event_payload_shape(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path, responses=["spoken"])
    await lingua.speak("hi", snapshot=_snapshot([_event()]))
    entries = await bus.client.xrange(EXTERNAL_STREAM)
    _, fields = entries[0]
    payload = json.loads(fields["payload"])
    assert set(payload.keys()) >= {"text", "mode", "model", "prompt_length", "latency_ms"}
    assert payload["mode"] == "external"
    assert payload["text"] == "spoken"


@pytest.mark.asyncio
async def test_aggregate_lingua_out_mirrors_mode_specific_stream(bus: AsyncBus, tmp_path: Path):
    """Every utterance is also published to the canonical lingua.out stream."""
    lingua = _make_lingua(bus, tmp_path, responses=["spoken"])
    await lingua.speak("hi", snapshot=_snapshot([_event()]))
    await lingua.think("quiet", snapshot=_snapshot([_event()]))

    external = await bus.client.xrange(EXTERNAL_STREAM)
    internal = await bus.client.xrange(INTERNAL_STREAM)
    aggregate = await bus.client.xrange("lingua.out")
    assert len(aggregate) == 2
    assert (
        json.loads(external[0][1]["payload"])["text"]
        == json.loads(aggregate[0][1]["payload"])["text"]
    )
    assert (
        json.loads(internal[0][1]["payload"])["text"]
        == json.loads(aggregate[1][1]["payload"])["text"]
    )


@pytest.mark.asyncio
async def test_custom_client_used(bus: AsyncBus, tmp_path: Path):
    client = FakeChatClient(responses=["custom"])
    lingua = Lingua(
        bus,
        chat_client=client,
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
    )
    out = await lingua.speak("anything")
    assert out == "custom"
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_shutdown_closes_client(bus: AsyncBus, tmp_path: Path):
    client = FakeChatClient()
    lingua = Lingua(
        bus,
        chat_client=client,
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
    )
    await lingua.initialize()
    await lingua.shutdown()
    assert client.closed is True


@pytest.mark.asyncio
async def test_lingua_realizes_speak_intent(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path, responses=["a reply"])
    # Intent published BEFORE initialize would be skipped (cursor seeks to
    # latest), so initialize first, then publish.
    await lingua.initialize()
    try:
        await _publish_intent(bus, "speak", "how are you?")
        entries = await _wait_for_entries(bus, EXTERNAL_STREAM)
        assert len(entries) == 1
        _, fields = entries[0]
        payload = json.loads(fields["payload"])
        assert payload["text"] == "a reply"
        assert payload["mode"] == "external"
        # The triggering utterance is embedded in the assembled prompt, which now
        # also carries the conscious-workspace awareness block and a persona
        # system prompt (the language organ is conditioned, not a bare chatbot).
        req = lingua.chat_client.requests[-1]
        assert "how are you?" in req.prompt
        assert "How I feel and what I notice" in req.prompt
        assert req.system  # persona is set (was None before conditioning)
        # External speech carries the user input for the A/B divergence observer.
        assert payload["user_input"] == "how are you?"
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_lingua_realizes_think_intent_to_internal(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path, responses=["a thought"])
    await lingua.initialize()
    try:
        await _publish_intent(bus, "think", "ponder this")
        entries = await _wait_for_entries(bus, INTERNAL_STREAM)
        assert len(entries) == 1
        ext = await bus.client.xrange(EXTERNAL_STREAM)
        assert len(ext) == 0
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_lingua_silent_without_intent_on_perceived_input(bus: AsyncBus, tmp_path: Path):
    """No speak intent → no external speech, even though a user transcription
    is broadcast. Lingua must NOT self-trigger on perceived input."""
    lingua = _make_lingua(bus, tmp_path, responses=["should not be spoken"])
    await lingua.initialize()
    try:
        # Simulate a broadcast containing a user transcription, but issue NO
        # intent (e.g. the snapshot was inhibited).
        snap = WorkspaceSnapshot(
            tick_index=0,
            selected_events=[
                _event(
                    source="audition",
                    type_="audition.transcription",
                    payload={"text": "are you there?"},
                )
            ],
            inhibited=False,
            is_experiential=True,
        )
        await lingua.on_workspace(snap)
        # Give any (incorrect) reflex a chance to fire.
        await asyncio.sleep(0.1)
        ext = await bus.client.xrange(EXTERNAL_STREAM)
        assert len(ext) == 0
        assert len(lingua.chat_client.requests) == 0
    finally:
        await lingua.shutdown()


def test_lingua_does_not_override_on_workspace():
    """Structural guard: Lingua must not introduce a self-trigger reflex via
    on_workspace. It inherits BaseModule's no-op."""
    from kaine.modules.base import BaseModule

    assert Lingua.on_workspace is BaseModule.on_workspace


REAL_CHAT_ENV = "KAINE_LINGUA_RUN_REAL_CHAT"


@pytest.mark.skipif(
    os.environ.get(REAL_CHAT_ENV) != "1",
    reason=f"set {REAL_CHAT_ENV}=1 to hit live Unsloth Studio",
)
@pytest.mark.asyncio
async def test_real_chat_returns_text(bus: AsyncBus, tmp_path: Path):
    """Hits the actual Unsloth Studio chat API at 127.0.0.1:11434.

    Picks a small model from the served list. Skipped unless the env var
    is set (so this isn't run by default in CI).
    """
    from kaine.modules.lingua.client import ChatRequest, OpenAIChatClient

    client = OpenAIChatClient()
    try:
        # Discover an available model rather than hardcoding (which served
        # ids exist depends on what the operator has loaded in Unsloth).
        models_resp = await client._ensure_client().get("/models")
        models_resp.raise_for_status()
        served = [m["id"] for m in models_resp.json().get("data", [])]
        assert served, "Unsloth Studio reports no models"
        # Prefer a smallish Qwen / Gemma if present; else first available.
        preferred = [m for m in served if "qwen3" in m.lower() or "gemma4" in m.lower()]
        model_id = (preferred or served)[0]
        resp = await client.complete(
            ChatRequest(
                prompt="Say PONG in one word.",
                model=model_id,
                max_tokens=64,
                temperature=0.0,
            )
        )
        # Thinking models may put text in `reasoning` instead of `content`;
        # the client handles that fallback, so any non-empty text counts.
        assert resp.text.strip(), f"empty response from {model_id}: {resp.raw}"
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_speak_payload_carries_user_input(bus: AsyncBus, tmp_path: Path):
    """External speech embeds user_input so ABDivergenceObserver can build its
    bare baseline without an early return."""
    lingua = _make_lingua(bus, tmp_path, responses=["answer"])
    await lingua.speak("what time is it?")
    entries = await bus.client.xrange(EXTERNAL_STREAM)
    payload = json.loads(entries[0][1]["payload"])
    assert payload.get("user_input") == "what time is it?"


@pytest.mark.asyncio
async def test_think_payload_excludes_user_input(bus: AsyncBus, tmp_path: Path):
    """Internal speech must NOT carry user_input — that field is the A/B
    observer's trigger and belongs only on external_speech events."""
    lingua = _make_lingua(bus, tmp_path, responses=["a thought"])
    await lingua.think("something internal")
    entries = await bus.client.xrange(INTERNAL_STREAM)
    payload = json.loads(entries[0][1]["payload"])
    assert "user_input" not in payload


# --- interruptible / preemptable generation (interruptible-utterance) ---------


class _GatedChatClient:
    """Chat client whose ``complete`` blocks until released, so a test can hold
    a generation 'in flight' and assert a preemption really cancels it.

    Test double — lives only in tests/ (the real client hits the LLM server).
    ``started`` is set when a completion begins; ``release`` lets a completion
    finish. ``cancelled`` counts completions aborted mid-flight.
    """

    def __init__(self, responses=None):
        from kaine.modules.lingua.client import ChatResponse  # noqa: F401

        self._responses = list(responses or [])
        self.requests = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.completed = 0
        self.cancelled = 0
        self.closed = False

    @property
    def base_url(self) -> str:
        return "http://fake/v1"

    async def complete(self, request):
        from kaine.modules.lingua.client import ChatResponse

        self.requests.append(request)
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        text = self._responses.pop(0) if self._responses else "done"
        self.completed += 1
        return ChatResponse(
            text=text,
            model=request.model,
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1.0,
            raw={},
        )

    async def aclose(self) -> None:
        self.closed = True


async def _publish_speak(bus: AsyncBus, about: str, *, interrupt: bool = False) -> None:
    payload = {"kind": "speak", "about": about}
    if interrupt:
        payload["interrupt"] = True
    event = Event(
        source="volition",
        type="intent.speak",
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)


@pytest.mark.asyncio
async def test_uninterrupted_generation_completes_via_loop(bus: AsyncBus, tmp_path: Path):
    """With no interrupt, a generation driven through the intent loop completes
    and publishes exactly as before this change."""
    client = _GatedChatClient(responses=["a full reply"])
    lingua = Lingua(
        bus,
        chat_client=client,
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="m",
    )
    await lingua.initialize()
    try:
        await _publish_speak(bus, "hello")
        await asyncio.wait_for(client.started.wait(), timeout=2.0)
        client.release.set()  # let it finish
        entries = await _wait_for_entries(bus, EXTERNAL_STREAM)
        assert len(entries) == 1
        assert json.loads(entries[0][1]["payload"])["text"] == "a full reply"
        assert client.completed == 1
        assert client.cancelled == 0
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_interrupt_aborts_and_redirects(bus: AsyncBus, tmp_path: Path):
    """An interrupt-marked speak arriving mid-generation cancels the in-flight
    generation and redirects to the new one; the aborted line is never published
    and a content-free preemption record is written."""
    log_path = tmp_path / "intent.jsonl"
    client = _GatedChatClient(responses=["redirected reply"])
    lingua = Lingua(
        bus,
        chat_client=client,
        intent_log=IntentExpressionLog(log_path),
        model_id="m",
    )
    await lingua.initialize()
    try:
        # First (ordinary) speak begins and blocks in flight.
        await _publish_speak(bus, "the first thing")
        await asyncio.wait_for(client.started.wait(), timeout=2.0)
        client.started.clear()
        # An urgent interrupt arrives while the first is still generating.
        await _publish_speak(bus, "something more important", interrupt=True)
        # The redirect begins only after the first is aborted.
        await asyncio.wait_for(client.started.wait(), timeout=2.0)
        assert client.cancelled == 1  # the first generation was really cancelled
        client.release.set()
        entries = await _wait_for_entries(bus, EXTERNAL_STREAM)
        # Exactly the redirect is published — the aborted first was never emitted.
        assert len(entries) == 1
        assert json.loads(entries[0][1]["payload"])["text"] == "redirected reply"
        # A content-free preemption record notes the abort (no cognitive text).
        records = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
        preemptions = [r for r in records if r.get("event") == "preempted"]
        assert len(preemptions) == 1
        assert "generated_text" not in preemptions[0]
        assert "prompt" not in preemptions[0]
        assert preemptions[0]["mode"] == "external"
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_already_emitted_utterance_is_not_unsaid(bus: AsyncBus, tmp_path: Path):
    """A generation that already completed and published before an interrupt
    arrives stays published — only an in-flight remainder is dropped."""
    client = _GatedChatClient(responses=["first said", "second said"])
    lingua = Lingua(
        bus,
        chat_client=client,
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="m",
    )
    await lingua.initialize()
    try:
        await _publish_speak(bus, "first")
        await asyncio.wait_for(client.started.wait(), timeout=2.0)
        client.started.clear()
        client.release.set()  # let the first fully complete + publish
        first_entries = await _wait_for_entries(bus, EXTERNAL_STREAM)
        assert len(first_entries) == 1
        # Now an interrupt arrives — the first is already done, so nothing to
        # cancel; the second is generated. The first utterance remains on-stream.
        client.release.clear()
        await _publish_speak(bus, "urgent", interrupt=True)
        await asyncio.wait_for(client.started.wait(), timeout=2.0)
        client.release.set()
        deadline = asyncio.get_event_loop().time() + 2.0
        while asyncio.get_event_loop().time() < deadline:
            entries = await bus.client.xrange(EXTERNAL_STREAM)
            if len(entries) >= 2:
                break
            await asyncio.sleep(0.02)
        entries = await bus.client.xrange(EXTERNAL_STREAM)
        texts = [json.loads(e[1]["payload"])["text"] for e in entries]
        assert "first said" in texts  # not un-said
        assert client.cancelled == 0  # first had finished; nothing was aborted
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_shutdown_cancels_in_flight_generation(bus: AsyncBus, tmp_path: Path):
    """Shutting down while a generation is in flight cancels it cleanly — no
    leaked task, no publish of the aborted utterance."""
    client = _GatedChatClient(responses=["never emitted"])
    lingua = Lingua(
        bus,
        chat_client=client,
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="m",
    )
    await lingua.initialize()
    await _publish_speak(bus, "hanging")
    await asyncio.wait_for(client.started.wait(), timeout=2.0)
    await lingua.shutdown()  # must not hang or leak
    assert client.cancelled == 1
    assert client.closed is True
    entries = await bus.client.xrange(EXTERNAL_STREAM)
    assert entries == []


# --- failed-generation audit path ---------------------------------------------


class _FailingChatClient:
    """Chat client whose ``complete`` always raises, for testing the failure
    audit path that must emit a content-free realization_failed record.
    """

    async def complete(self, request):
        raise ConnectionError("organ down")

    async def aclose(self) -> None:
        pass


def _make_failing_lingua(bus: AsyncBus, tmp_path: Path) -> Lingua:
    return Lingua(
        bus,
        chat_client=_FailingChatClient(),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )


@pytest.mark.asyncio
async def test_failed_speak_writes_content_free_realization_failed_record(
    bus: AsyncBus, tmp_path: Path
):
    lingua = _make_failing_lingua(bus, tmp_path)
    await lingua._realize_intent(SPEAK, "hello secret")

    entries = await bus.client.xrange(INTERNAL_STREAM)
    assert len(entries) == 1
    _entry_id, fields = entries[0]

    assert fields["type"] == "realization_failed"
    payload = json.loads(fields["payload"])
    assert payload == {"mode": SPEAK, "reason_class": "ConnectionError"}

    # Content-free: the sensitive input and exception message must never appear
    # in any stored field (prompt/input/text/reason string are all excluded).
    stored_text = " ".join(str(v) for v in fields.values())
    assert "hello secret" not in stored_text
    assert "organ down" not in stored_text

    ext = await bus.client.xrange(EXTERNAL_STREAM)
    assert len(ext) == 0


@pytest.mark.asyncio
async def test_realization_failed_record_is_counted_by_ignition_audit(
    bus: AsyncBus, tmp_path: Path
):
    lingua = _make_failing_lingua(bus, tmp_path)
    await lingua._realize_intent(SPEAK, "hello secret")

    entries = await bus.client.xrange(INTERNAL_STREAM)
    assert len(entries) == 1
    entry_id, fields = entries[0]

    record = {
        "stream": INTERNAL_STREAM,
        "type": fields["type"],
        "source": fields.get("source", lingua.name),
        "payload": json.loads(fields["payload"]),
        "entry_id": entry_id,
    }

    report = classify_realizations([], [], [record])
    assert report.realization_failed_count == 1


# --- intent-expression log: redaction and new record fields -------------------


def _records(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


async def _wait_for_entry_count(bus: AsyncBus, stream: str, n: int, *, timeout_s: float = 2.0):
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        entries = await bus.client.xrange(stream)
        if len(entries) >= n:
            return entries
        await asyncio.sleep(0.02)
    return await bus.client.xrange(stream)


@pytest.mark.asyncio
async def test_heard_speech_redacted_when_about_kind_is_heard(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path, responses=["reply"])
    await lingua.initialize()
    try:
        marker = "UNIQUE_MARKER_HEARD_123"
        snap = WorkspaceSnapshot(
            tick_index=1,
            selected_events=[
                (
                    "aud1",
                    Event(
                        source="audition",
                        type="audition.transcription",
                        payload={"text": marker},
                        salience=0.9,
                        timestamp=datetime.now(timezone.utc),
                    ),
                )
            ],
            inhibited=False,
            is_experiential=True,
        )
        lingua._latest_snapshot = snap
        event = Event(
            source="volition",
            type="intent.speak",
            payload={
                "kind": "speak",
                "about": marker,
                "entry_id": "e1",
                "about_kind": "heard",
            },
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
        await lingua._dispatch_intent(event)
        entries = await _wait_for_entries(bus, EXTERNAL_STREAM)
        assert entries
        rec = _records(lingua.intent_log.path)[0]
        whole = json.dumps(rec)
        assert marker not in whole
        assert "[heard speech]" in whole
        assert rec["intent_entry_id"] == "e1"
        assert rec["intent_origin"] is None
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_heard_speech_redacted_when_about_kind_missing(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path, responses=["reply"])
    await lingua.initialize()
    try:
        marker = "UNIQUE_MARKER_UNMARKED_456"
        event = Event(
            source="volition",
            type="intent.speak",
            payload={"kind": "speak", "about": marker, "entry_id": "e2"},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
        await lingua._dispatch_intent(event)
        await _wait_for_entries(bus, EXTERNAL_STREAM)
        rec = _records(lingua.intent_log.path)[0]
        whole = json.dumps(rec)
        assert marker not in whole
        assert "[heard speech]" in whole
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_felt_about_logged_verbatim(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path, responses=["reply"])
    await lingua.initialize()
    try:
        about = "I feel curious."
        event = Event(
            source="volition",
            type="intent.speak",
            payload={
                "kind": "speak",
                "about": about,
                "entry_id": "e3",
                "about_kind": "felt",
                "origin": "nous",
            },
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
        await lingua._dispatch_intent(event)
        await _wait_for_entries(bus, EXTERNAL_STREAM)
        rec = _records(lingua.intent_log.path)[0]
        assert about in rec["prompt"]
        assert "[heard speech]" not in rec["prompt"]
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_intent_log_record_has_all_required_fields(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path, responses=["generated"])
    await lingua.initialize()
    try:
        event = Event(
            source="volition",
            type="intent.speak",
            payload={
                "kind": "speak",
                "about": "hi",
                "entry_id": "e4",
                "origin": "nous",
                "about_kind": "felt",
            },
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
        await lingua._dispatch_intent(event)
        await _wait_for_entries(bus, EXTERNAL_STREAM)
        rec = _records(lingua.intent_log.path)[0]
        assert len(rec["record_id"]) == 32
        assert all(c in "0123456789abcdef" for c in rec["record_id"])
        assert rec["intent_entry_id"] == "e4"
        assert rec["intent_origin"] == "nous"
        assert "sleep_index" in rec
        assert len(rec["system_digest"]) == 64
        assert all(c in "0123456789abcdef" for c in rec["system_digest"])
        req = lingua.chat_client.requests[-1]
        expected = hashlib.sha256(req.system.encode("utf-8")).hexdigest()
        assert rec["system_digest"] == expected
        assert "seed" in rec
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_bus_payload_carries_record_id(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path, responses=["generated"])
    await lingua.initialize()
    try:
        event = Event(
            source="volition",
            type="intent.speak",
            payload={"kind": "speak", "about": "hello", "entry_id": "e5"},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
        await lingua._dispatch_intent(event)
        entries = await _wait_for_entries(bus, EXTERNAL_STREAM)
        payload = json.loads(entries[0][1]["payload"])
        rec = _records(lingua.intent_log.path)[0]
        assert payload["record_id"] == rec["record_id"]
    finally:
        await lingua.shutdown()


def test_probe_conditions_reports_persona_template_version(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path)
    conditions = lingua.probe_conditions()
    assert conditions["persona_template_version"] == PERSONA_TEMPLATE_VERSION


@pytest.mark.asyncio
async def test_sleep_index_read_from_hypnos_out(bus: AsyncBus, tmp_path: Path):
    lingua = _make_lingua(bus, tmp_path, responses=["first", "second"])
    await lingua.initialize()
    try:
        # Before any hypnos event, sleep_index is unknown (None).
        await _publish_intent(bus, "speak", "first")
        await _wait_for_entries(bus, EXTERNAL_STREAM)
        recs = _records(lingua.intent_log.path)
        assert recs[0]["sleep_index"] is None

        # Hypnos publishes a completed sleep with index 3.
        await bus.publish(
            Event(
                source="hypnos",
                type="hypnos.consolidation_divergence",
                payload={"sleep_index": 3, "records_scanned": 0},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        )
        await wait_for(lambda: lingua._sleep_index == 3, timeout_s=2.0)

        # The next utterance records that sleep index.
        await _publish_intent(bus, "speak", "second")
        await _wait_for_entry_count(bus, EXTERNAL_STREAM, 2)
        recs = _records(lingua.intent_log.path)
        second_rec = [r for r in recs if r["generated_text"] == "second"][0]
        assert second_rec["sleep_index"] == 3
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_sleep_index_backfilled_at_initialize_takes_the_latest(bus: AsyncBus, tmp_path: Path):
    """Sleeps published before Lingua starts are picked up at initialize, and
    the latest value wins over a larger earlier one (a restarted Hypnos counts
    from zero again)."""
    for idx in (5, 1):
        await bus.publish(
            Event(
                source="hypnos",
                type="hypnos.consolidation_divergence",
                payload={"sleep_index": idx, "records_scanned": 0},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        )
    lingua = _make_lingua(bus, tmp_path, responses=["only"])
    await lingua.initialize()
    try:
        assert lingua._sleep_index == 1
    finally:
        await lingua.shutdown()


@pytest.mark.asyncio
async def test_heard_about_redacted_even_when_coalition_has_moved_on(bus: AsyncBus, tmp_path: Path):
    """The heard text may no longer be in the snapshot Lingua uses when it
    speaks; the intent's about_kind alone must keep it out of the log."""
    lingua = _make_lingua(bus, tmp_path, responses=["reply"])
    await lingua.initialize()
    try:
        marker = "UNIQUE_MARKER_MOVED_ON_789"
        lingua._latest_snapshot = WorkspaceSnapshot(
            tick_index=2,
            selected_events=[
                (
                    "soma1",
                    Event(
                        source="soma",
                        type="soma.report",
                        payload={"wellness": 0.8, "alerts": []},
                        salience=0.5,
                        timestamp=datetime.now(timezone.utc),
                    ),
                )
            ],
            inhibited=False,
            is_experiential=True,
        )
        event = Event(
            source="volition",
            type="intent.speak",
            payload={"kind": "speak", "about": marker, "about_kind": "heard"},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
        await lingua._dispatch_intent(event)
        await _wait_for_entries(bus, EXTERNAL_STREAM)
        whole = json.dumps(_records(lingua.intent_log.path)[0])
        assert marker not in whole
        assert "[heard speech]" in whole
    finally:
        await lingua.shutdown()
