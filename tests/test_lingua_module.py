# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.lingua import (
    EXTERNAL_STREAM,
    INTERNAL_STREAM,
    FakeChatClient,
    IntentExpressionLog,
    Lingua,
)


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
    return ("e0", Event(
        source=source,
        type=type_,
        payload=payload or {"wellness": 0.5, "alerts": []},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    ))


@pytest.mark.asyncio
async def test_invalid_construction(bus: AsyncBus):
    with pytest.raises(ValueError):
        Lingua(bus, chat_client=FakeChatClient(), baseline_salience=2.0)
    with pytest.raises(ValueError):
        Lingua(bus, chat_client=FakeChatClient(), alert_salience=-0.1)


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
    records = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
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
    records = [json.loads(l) for l in log_path.read_text().splitlines() if l.strip()]
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
async def test_custom_client_used(bus: AsyncBus, tmp_path: Path):
    client = FakeChatClient(responses=["custom"])
    lingua = Lingua(
        bus, chat_client=client,
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
    )
    out = await lingua.speak("anything")
    assert out == "custom"
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_shutdown_closes_client(bus: AsyncBus, tmp_path: Path):
    client = FakeChatClient()
    lingua = Lingua(
        bus, chat_client=client,
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
        assert "What I am aware of right now" in req.prompt
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
async def test_lingua_silent_without_intent_on_perceived_input(
    bus: AsyncBus, tmp_path: Path
):
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
                _event(source="audition", type_="audition.transcription",
                       payload={"text": "are you there?"})
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
    from kaine.modules.lingua.client import OpenAIChatClient, ChatRequest

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
        resp = await client.complete(ChatRequest(
            prompt="Say PONG in one word.",
            model=model_id,
            max_tokens=64,
            temperature=0.0,
        ))
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
