# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""An external-input event's metadata is never quoted to the organ as heard speech.

A transcription carries the words heard under ``text`` and, beside them, its
channel (``source_label``), the STT model id (``model``), the backend name
(``backend``) and, on a failed transcription, an ``error`` message. Only the
words are heard: the heard turn quotes ``heard_words`` (the values under a
``HEARD_TEXT_FIELDS`` key), while redaction and storage keep using every text
leaf (``heard_texts``), so they still fail closed.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.faithful.external_input import (
    EXTERNAL_INPUT_TYPES,
    HEARD_TEXT_FIELDS,
    heard_texts,
    heard_words,
    is_heard_event,
)
from kaine.modules.language import (
    EXTERNAL_STREAM,
    FakeChatClient,
    IntentExpressionLog,
    Language,
)
from kaine.modules.language.client import ChatRequest, chat_messages
from kaine.modules.language.context import (
    AWARENESS_RENDERINGS,
    HEARD_ATTRIBUTION_SAID,
    HEARD_ATTRIBUTION_WROTE,
    HEARD_POINTER_LINE,
    ContextAssembler,
)

WORDS = "please feed the cat"
SOURCE_LABEL = "mic-LABEL-7Q3Z-unique"
MODEL_ID = "stt-MODEL-K9W2-unique/faster-whisper-medium.en"
BACKEND = "backend-BKND-X5V8-unique"
ERROR = "RuntimeError: ERR-M4T6-unique decoder failed"
SENDER = "Avatar SNDR-P2L7-unique"
METADATA = (SOURCE_LABEL, MODEL_ID, BACKEND)


def _ev(source: str, type_: str, payload: dict) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.9,
        timestamp=datetime.now(timezone.utc),
    )


def _transcription(text: str = WORDS, **extra) -> Event:
    payload = {
        "text": text,
        "source_label": SOURCE_LABEL,
        "model": MODEL_ID,
        "sample_rate": 16000,
        "audio_bytes_length": 32000,
        "latency_ms": 3.0,
        "prediction_error": None,
        "backend": BACKEND,
    }
    payload.update(extra)
    return _ev("audition", "audition.transcription", payload)


def _snap(*events: Event) -> WorkspaceSnapshot:
    pairs = [(f"e{i}", ev) for i, ev in enumerate(events)]
    return WorkspaceSnapshot(
        tick_index=1,
        selected_events=pairs,
        salience_scores={k: 0.9 for k, _ in pairs},
    )


def _organ_messages(ctx) -> str:
    """Everything the organ receives for this request, as one string."""
    messages = chat_messages(
        ChatRequest(
            prompt=ctx.prompt,
            model="m",
            system=ctx.system,
            own_turn=True,
            user_turn=ctx.heard_turn,
        )
    )
    return json.dumps(messages, ensure_ascii=False)


def _sent_to_organ(ctx) -> list[str]:
    return [ctx.system, ctx.prompt, ctx.working_memory, ctx.heard_turn or "", _organ_messages(ctx)]


# --- the rule -----------------------------------------------------------------


def test_heard_words_are_the_text_field_only():
    event = _transcription()
    assert heard_words(event) == [WORDS]
    # Redaction and storage still see every text leaf.
    assert set(heard_texts(event)) == {WORDS, *METADATA}
    assert is_heard_event(event)


def test_failed_transcription_has_no_heard_words():
    event = _transcription(text="", error=ERROR, alert=True)
    assert heard_words(event) == []
    assert ERROR in heard_texts(event)
    assert is_heard_event(event)


def test_heard_words_use_the_heard_rules_field_set():
    for type_ in sorted(EXTERNAL_INPUT_TYPES):
        for field in sorted(HEARD_TEXT_FIELDS):
            event = _ev(type_.split(".")[0], type_, {field: WORDS, "source_label": SOURCE_LABEL})
            assert heard_words(event) == [WORDS]
            nested = _ev(type_.split(".")[0], type_, {"segments": [{field: WORDS}], "model": MODEL_ID})
            assert heard_words(nested) == [WORDS]


def test_heard_words_match_heard_texts_off_external_input():
    cases = [
        _ev("social_cognition", "social_cognition.update", {"partner": {"heard_text": WORDS}, "label": SOURCE_LABEL}),
        _ev("mystery", "mystery.thing", {"text": WORDS, "model": MODEL_ID}),
        _ev("language", "external_speech", {"text": WORDS, "user_input": WORDS}),
        _ev("vision", "vision.report", {"change_score": 0.4, "encoder_model_id": MODEL_ID}),
    ]
    for event in cases:
        assert heard_words(event) == heard_texts(event)


# --- the organ's request --------------------------------------------------------


@pytest.mark.parametrize("rendering", AWARENESS_RENDERINGS)
@pytest.mark.parametrize("about_is_heard", [True, False])
def test_transcription_metadata_never_reaches_the_organ(rendering, about_is_heard):
    ctx = ContextAssembler(awareness_rendering=rendering).assemble(
        about=WORDS if about_is_heard else "Something I hear stands out.",
        snapshot=_snap(_transcription()),
        self_model={},
        mode="external",
        about_is_heard=about_is_heard,
    )
    for part in _sent_to_organ(ctx):
        for value in METADATA:
            assert value not in part
    assert ctx.heard_turn is not None
    heard_lines = ctx.heard_turn.splitlines()
    assert heard_lines[0] == HEARD_ATTRIBUTION_SAID + '"' + WORDS + '".'
    # One quoted line for the event, plus the heard trigger.
    assert len(heard_lines) == (2 if about_is_heard else 1)
    assert WORDS not in ctx.prompt
    assert WORDS not in ctx.system


@pytest.mark.parametrize("rendering", AWARENESS_RENDERINGS)
def test_failed_transcription_error_is_not_quoted(rendering):
    ctx = ContextAssembler(awareness_rendering=rendering).assemble(
        about="Something I hear stands out.",
        snapshot=_snap(_transcription(text="", error=ERROR, alert=True)),
        self_model={},
        mode="external",
        about_is_heard=False,
    )
    for part in _sent_to_organ(ctx):
        for value in (*METADATA, "ERR-M4T6-unique"):
            assert value not in part
    assert ctx.heard_turn is None
    # Still heard: the notes say someone spoke.
    assert ctx.prompt.count(HEARD_POINTER_LINE) == 1


@pytest.mark.parametrize("rendering", AWARENESS_RENDERINGS)
def test_chat_sender_is_not_quoted(rendering):
    ctx = ContextAssembler(awareness_rendering=rendering).assemble(
        about="Something stands out.",
        snapshot=_snap(_ev("embodiment", "embodiment.chat", {"text": WORDS, "sender": SENDER})),
        self_model={},
        mode="external",
        about_is_heard=False,
    )
    for part in _sent_to_organ(ctx):
        assert SENDER not in part
    assert ctx.heard_turn == HEARD_ATTRIBUTION_WROTE + '"' + WORDS + '".'


# --- end to end through the language module --------------------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("rendering", AWARENESS_RENDERINGS)
async def test_language_module_sends_only_the_words(bus: AsyncBus, tmp_path: Path, rendering):
    chat_client = FakeChatClient(responses=["I will feed it."])
    language = Language(
        bus,
        chat_client=chat_client,
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
        awareness_rendering=rendering,
    )
    await language.initialize()
    try:
        await language._produce_inner(
            about=WORDS,
            snapshot=WorkspaceSnapshot(
                tick_index=0,
                selected_events=[("t1", _transcription())],
                salience_scores={"t1": 0.9},
            ),
            mode="external",
            stream=EXTERNAL_STREAM,
            about_kind="heard",
        )
        assert len(chat_client.requests) == 1
        request = chat_client.requests[0]
        sent = json.dumps(chat_messages(request), ensure_ascii=False)
        for value in METADATA:
            assert value not in sent
        assert request.user_turn is not None
        assert '"' + WORDS + '"' in request.user_turn
        # The log stays redacted as before.
        assert WORDS not in language.intent_log.path.read_text()
    finally:
        await language.shutdown()
