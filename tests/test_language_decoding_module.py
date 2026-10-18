# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for language decoding bounds: think cap, DRY repetition penalty, and sentence cut."""

from __future__ import annotations

import json
import logging
import math
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.boot.factories.language import make_language
from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.language import IntentExpressionLog, Language
from kaine.modules.language.client import ChatResponse, DryPenalty, OpenAIChatClient


def _ev(source, type_, payload):
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
        causal_parent=None,
    )


VISION = {
    "change_score": 0.0004,
    "habituation_score": 0.6116,
    "encoder_model_id": "dinov2-small",
    "normalised_error": 1.2,
}


def _snap(*events):
    pairs = [(f"e{i}", ev) for i, ev in enumerate(events)]
    return WorkspaceSnapshot(
        tick_index=1,
        selected_events=pairs,
        salience_scores={k: 0.5 for k, _ in pairs},
    )


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class _ScriptedClient:
    base_url = "http://fake/v1"

    def __init__(self, replies):
        self.replies = list(replies)
        self.requests = []

    async def complete(self, request):
        self.requests.append(request)
        text, finish = self.replies.pop(0) if self.replies else ("ok", "stop")
        return ChatResponse(text=text, model=request.model, finish_reason=finish)

    async def aclose(self):
        return None


def _lang(bus, tmp_path, replies=(), **kw):
    return Language(
        bus,
        chat_client=_ScriptedClient(replies),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
        **kw,
    )


async def _last_internal_payload(bus):
    entries = await bus.client.xrange("language.internal")
    return json.loads(entries[-1][1]["payload"])


async def _last_external_payload(bus):
    entries = await bus.client.xrange("language.external")
    return json.loads(entries[-1][1]["payload"])


def _last_intent_record(language):
    return json.loads(language.intent_log.path.read_text().splitlines()[-1])


LOOP_REPLY = (
    "I do not know how I feel. I do not know what I am thinking about. "
    "I do not know what I am thinking about. I do not know what I"
)


async def test_think_has_own_cap(bus, tmp_path):
    language = _lang(
        bus,
        tmp_path,
        replies=[("speak reply", "stop"), ("think reply", "stop")],
        max_tokens=512,
        think_max_tokens=128,
    )
    await language.initialize()
    try:
        await language.speak(
            "are you awake",
            snapshot=_snap(_ev("vision", "vision.report", VISION)),
        )
        await language.think(
            "Something in what I see stands out noticeably.",
            snapshot=_snap(_ev("vision", "vision.report", VISION)),
            about_kind="felt",
        )
        assert len(language._chat_client.requests) == 2
        assert language._chat_client.requests[0].max_tokens == 512
        assert language._chat_client.requests[1].max_tokens == 128
    finally:
        await language.shutdown()

    default = _lang(
        bus,
        tmp_path / "default",
        replies=[("a", "stop"), ("b", "stop")],
        max_tokens=512,
    )
    await default.initialize()
    try:
        await default.speak(
            "are you awake",
            snapshot=_snap(_ev("vision", "vision.report", VISION)),
        )
        await default.think(
            "Something in what I see stands out noticeably.",
            snapshot=_snap(_ev("vision", "vision.report", VISION)),
            about_kind="felt",
        )
        assert default._chat_client.requests[0].max_tokens == 512
        assert default._chat_client.requests[1].max_tokens == 512
    finally:
        await default.shutdown()


async def test_dry_penalty_on_requests(bus, tmp_path):
    language = _lang(
        bus,
        tmp_path,
        replies=[("speak reply", "stop"), ("think reply", "stop")],
        dry_multiplier=0.8,
        dry_base=1.75,
        dry_allowed_length=2,
        dry_penalty_last_n=2048,
    )
    await language.initialize()
    try:
        await language.speak(
            "are you awake",
            snapshot=_snap(_ev("vision", "vision.report", VISION)),
        )
        await language.think(
            "Something in what I see stands out noticeably.",
            snapshot=_snap(_ev("vision", "vision.report", VISION)),
            about_kind="felt",
        )
        assert len(language._chat_client.requests) == 2
        expected = DryPenalty(0.8, 1.75, 2, 2048)
        assert language._chat_client.requests[0].dry == expected
        assert language._chat_client.requests[1].dry == expected
    finally:
        await language.shutdown()

    default = _lang(
        bus,
        tmp_path / "default",
        replies=[("a", "stop"), ("b", "stop")],
    )
    await default.initialize()
    try:
        await default.speak(
            "are you awake",
            snapshot=_snap(_ev("vision", "vision.report", VISION)),
        )
        await default.think(
            "Something in what I see stands out noticeably.",
            snapshot=_snap(_ev("vision", "vision.report", VISION)),
            about_kind="felt",
        )
        assert default._chat_client.requests[0].dry is None
        assert default._chat_client.requests[1].dry is None
    finally:
        await default.shutdown()


async def test_off_is_unchanged(bus, tmp_path):
    reply = ("I am here. I am here now. I am here now.", "length")
    default = _lang(
        bus,
        tmp_path / "default",
        replies=[reply, reply],
    )
    explicit = _lang(
        bus,
        tmp_path / "explicit",
        replies=[reply, reply],
        think_max_tokens=None,
        dry_multiplier=0.0,
        sentence_cut=False,
    )
    for language in (default, explicit):
        await language.initialize()
        try:
            speak_text = await language.speak(
                "are you awake",
                snapshot=_snap(_ev("vision", "vision.report", VISION)),
            )
            think_text = await language.think(
                "Something in what I see stands out noticeably.",
                snapshot=_snap(_ev("vision", "vision.report", VISION)),
                about_kind="felt",
            )
            assert speak_text == reply[0]
            assert think_text == reply[0]
        finally:
            await language.shutdown()

    assert default._chat_client.requests[0] == explicit._chat_client.requests[0]
    assert default._chat_client.requests[1] == explicit._chat_client.requests[1]

    for req in default._chat_client.requests:
        body = OpenAIChatClient()._body(req, think=False)
        assert not any(k.startswith("dry_") for k in body)

    assert (await _last_external_payload(bus))["text"] == reply[0]


async def test_loop_is_cut(bus, tmp_path):
    language = _lang(
        bus,
        tmp_path,
        replies=[(LOOP_REPLY, "length")],
        sentence_cut=True,
    )
    await language.initialize()
    try:
        text = await language.think(
            "Something in what I see stands out noticeably.",
            snapshot=_snap(_ev("vision", "vision.report", VISION)),
            about_kind="felt",
        )
        expected = (
            "I do not know how I feel. I do not know what I am thinking about."
        )
        assert text == expected

        record = _last_intent_record(language)
        assert record["generated_text"] == expected
        assert record["extra"]["text_cut"] == {
            "reason": "repeated_sentence",
            "generated_chars": len(LOOP_REPLY),
        }

        payload = await _last_internal_payload(bus)
        assert payload["text"] == expected
    finally:
        await language.shutdown()


async def test_cap_fragment_is_cut(bus, tmp_path):
    language = _lang(
        bus,
        tmp_path,
        replies=[("I am here. I feel the", "length")],
        sentence_cut=True,
    )
    await language.initialize()
    try:
        text = await language.think(
            "Something in what I see stands out noticeably.",
            snapshot=_snap(_ev("vision", "vision.report", VISION)),
            about_kind="felt",
        )
        assert text == "I am here."
        record = _last_intent_record(language)
        assert record["extra"]["text_cut"]["reason"] == "token_cap"
    finally:
        await language.shutdown()

    language = _lang(
        bus,
        tmp_path / "stop",
        replies=[("I am here. I feel the", "stop")],
        sentence_cut=True,
    )
    await language.initialize()
    try:
        text = await language.think(
            "Something in what I see stands out noticeably.",
            snapshot=_snap(_ev("vision", "vision.report", VISION)),
            about_kind="felt",
        )
        assert text == "I am here. I feel the"
        record = _last_intent_record(language)
        assert "extra" not in record
    finally:
        await language.shutdown()


async def test_cut_log_line_has_no_content(caplog, bus, tmp_path):
    language = _lang(
        bus,
        tmp_path,
        replies=[(LOOP_REPLY, "length")],
        sentence_cut=True,
    )
    await language.initialize()
    try:
        with caplog.at_level(logging.INFO, logger="kaine.modules.language.module"):
            await language.think(
                "Something in what I see stands out noticeably.",
                snapshot=_snap(_ev("vision", "vision.report", VISION)),
                about_kind="felt",
            )
        assert any("repeated_sentence" in r.message for r in caplog.records)
        assert not any("thinking about" in r.message for r in caplog.records)
    finally:
        await language.shutdown()


async def test_cut_and_heard_turn_both_recorded(bus, tmp_path):
    heard = "are you there"
    language = _lang(
        bus,
        tmp_path,
        replies=[(LOOP_REPLY, "length")],
        sentence_cut=True,
    )
    await language.initialize()
    try:
        await language.speak(
            heard,
            snapshot=_snap(_ev("audition", "audition.transcription", {"text": heard})),
        )
        record = _last_intent_record(language)
        assert "heard_turn" in record["extra"]
        assert record["extra"]["text_cut"]["reason"] == "repeated_sentence"
        assert record["generated_text"] == (
            "I do not know how I feel. I do not know what I am thinking about."
        )

        payload = await _last_external_payload(bus)
        assert payload["text"] == record["generated_text"]
    finally:
        await language.shutdown()


async def test_sentence_cut_off_keeps_loop(bus, tmp_path):
    language = _lang(
        bus,
        tmp_path,
        replies=[(LOOP_REPLY, "length")],
        sentence_cut=False,
    )
    await language.initialize()
    try:
        text = await language.think(
            "Something in what I see stands out noticeably.",
            snapshot=_snap(_ev("vision", "vision.report", VISION)),
            about_kind="felt",
        )
        assert text == LOOP_REPLY
        record = _last_intent_record(language)
        assert "extra" not in record

        payload = await _last_internal_payload(bus)
        assert payload["text"] == LOOP_REPLY
    finally:
        await language.shutdown()


def test_probe_unaffected(bus, tmp_path):
    bounded = _lang(
        bus,
        tmp_path / "bounded",
        think_max_tokens=128,
        dry_multiplier=0.8,
        dry_penalty_last_n=2048,
        sentence_cut=True,
    )
    default = _lang(bus, tmp_path / "default")

    bounded_req = bounded.probe_request(
        "What do you enjoy?", seed=3, max_tokens=40, self_model={}
    )
    default_req = default.probe_request(
        "What do you enjoy?", seed=3, max_tokens=40, self_model={}
    )
    assert bounded_req == default_req
    assert bounded_req.dry is None
    assert bounded_req.max_tokens == 40

    assert bounded.probe_conditions() == default.probe_conditions()


@pytest.mark.parametrize(
    "key, value",
    [
        ("think_max_tokens", 0),
        ("think_max_tokens", True),
        ("think_max_tokens", 1.5),
        ("dry_multiplier", -0.1),
        ("dry_multiplier", math.nan),
        ("dry_multiplier", True),
        ("dry_base", 0.5),
        ("dry_base", math.inf),
        ("dry_allowed_length", 0),
        ("dry_allowed_length", 2.0),
        ("dry_penalty_last_n", 0),
        ("dry_penalty_last_n", -1),
        ("sentence_cut", "yes"),
    ],
)
def test_invalid_values_rejected(key, value, bus, tmp_path):
    with pytest.raises(ValueError):
        _lang(bus, tmp_path, **{key: value})


def test_factory_passes_keys(bus, tmp_path):
    module = make_language(
        bus,
        {
            "chat_url": "http://127.0.0.1:1/v1",
            "intent_log_path": str(tmp_path / "i.jsonl"),
            "think_max_tokens": 128,
            "dry_multiplier": 0.8,
            "dry_base": 1.75,
            "dry_allowed_length": 2,
            "dry_penalty_last_n": 2048,
            "sentence_cut": True,
        },
    )
    assert module._think_max_tokens == 128
    assert module._dry == DryPenalty(0.8, 1.75, 2, 2048)
    assert module._sentence_cut is True


def test_shipped_config_values():
    config_path = Path(__file__).resolve().parents[1] / "config" / "kaine.toml"
    section = tomllib.loads(config_path.read_text())["language"]
    assert section["think_max_tokens"] == 128
    assert section["dry_multiplier"] == 0.8
    assert section["dry_base"] == 1.75
    assert section["dry_allowed_length"] == 2
    assert section["dry_penalty_last_n"] == 2048
    assert section["sentence_cut"] is True
    assert section["max_tokens"] == 512
    assert section["temperature"] == 0.7
