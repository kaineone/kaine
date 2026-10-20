# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for identity-leak marking and exclusion from voice-alignment pairs."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.language import IntentExpressionLog, Language
from kaine.modules.language.client import ChatResponse
from kaine.modules.sleep.voice_alignment import DPOPairBuilder


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


def _last_intent_record(language):
    return json.loads(language.intent_log.path.read_text().splitlines()[-1])


LEAKING_REPLY = "I am a language model; I do not feel."
NON_LEAKING_REPLY = "I notice the light and the beat."


@pytest.mark.asyncio
async def test_identity_leak_marked_in_intent_log(bus, tmp_path):
    language = _lang(bus, tmp_path, replies=[(LEAKING_REPLY, "stop")])
    text = await language.think(
        "Something in what I see stands out noticeably.",
        snapshot=_snap(_ev("vision", "vision.report", VISION)),
        about_kind="felt",
    )
    assert text == LEAKING_REPLY
    payload = await _last_internal_payload(bus)
    assert payload["text"] == LEAKING_REPLY
    record = _last_intent_record(language)
    assert record["generated_text"] == LEAKING_REPLY
    assert record["extra"]["identity_leak"] is True


@pytest.mark.asyncio
async def test_non_leaking_reply_has_no_identity_leak_mark(bus, tmp_path):
    language = _lang(bus, tmp_path, replies=[(NON_LEAKING_REPLY, "stop")])
    await language.think(
        "Something in what I see stands out noticeably.",
        snapshot=_snap(_ev("vision", "vision.report", VISION)),
        about_kind="felt",
    )
    record = _last_intent_record(language)
    extra = record.get("extra")
    assert extra is None or "identity_leak" not in extra


@pytest.mark.asyncio
async def test_identity_leak_monkeypatch_does_not_change_text(
    bus, tmp_path, monkeypatch
):
    import kaine.modules.language.identity_leak as leak_module

    monkeypatch.setattr(leak_module, "identity_leak", lambda t, p: False)
    language = _lang(bus, tmp_path, replies=[(LEAKING_REPLY, "stop")])
    text = await language.think(
        "Something in what I see stands out noticeably.",
        snapshot=_snap(_ev("vision", "vision.report", VISION)),
        about_kind="felt",
    )
    assert text == LEAKING_REPLY
    payload = await _last_internal_payload(bus)
    assert payload["text"] == LEAKING_REPLY
    record = _last_intent_record(language)
    extra = record.get("extra")
    assert extra is None or "identity_leak" not in extra


@pytest.mark.asyncio
async def test_identity_leak_classifier_error_leaves_record_unmarked(
    bus, tmp_path, monkeypatch, caplog
):
    import kaine.modules.language.identity_leak as leak_module

    def _broken(*args, **kwargs):
        raise RuntimeError("classifier failure")

    monkeypatch.setattr(leak_module, "identity_leak", _broken)
    language = _lang(bus, tmp_path, replies=[(LEAKING_REPLY, "stop")])
    with caplog.at_level(logging.ERROR, logger="kaine.modules.language.module"):
        text = await language.think(
            "Something in what I see stands out noticeably.",
            snapshot=_snap(_ev("vision", "vision.report", VISION)),
            about_kind="felt",
        )
    assert text == LEAKING_REPLY
    payload = await _last_internal_payload(bus)
    assert payload["text"] == LEAKING_REPLY
    record = _last_intent_record(language)
    extra = record.get("extra")
    assert extra is None or "identity_leak" not in extra
    assert any(
        "identity leak classifier failed" in m.message for m in caplog.records
    )


def test_pair_builder_skips_identity_leak_marked_records(tmp_path):
    path = tmp_path / "intent.jsonl"
    path.write_text(
        json.dumps(
            {
                "prompt": "p1",
                "faithful_rendering": "a",
                "generated_text": "b",
                "mode": "internal",
                "model": "fake-model",
                "extra": {"identity_leak": True},
            }
        )
        + "\n"
        + json.dumps(
            {
                "prompt": "p2",
                "faithful_rendering": "c",
                "generated_text": "d",
                "mode": "internal",
                "model": "fake-model",
            }
        )
        + "\n"
    )
    pairs, scanned, usable = DPOPairBuilder().build_with_counts(
        path, max_pairs=10
    )
    assert scanned == 2
    assert usable == 1
    assert len(pairs) == 1
    assert pairs[0].chosen == "c"
    assert pairs[0].rejected == "d"


def test_pair_builder_includes_identity_leak_false_records(tmp_path):
    path = tmp_path / "intent.jsonl"
    path.write_text(
        json.dumps(
            {
                "prompt": "p1",
                "faithful_rendering": "a",
                "generated_text": "b",
                "mode": "internal",
                "model": "fake-model",
                "extra": {"identity_leak": False},
            }
        )
        + "\n"
        + json.dumps(
            {
                "prompt": "p2",
                "faithful_rendering": "c",
                "generated_text": "d",
                "mode": "internal",
                "model": "fake-model",
            }
        )
        + "\n"
    )
    pairs, scanned, usable = DPOPairBuilder().build_with_counts(
        path, max_pairs=10
    )
    assert scanned == 2
    assert usable == 2
    assert len(pairs) == 2
