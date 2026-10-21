# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The organ's request carries no name (openspec persona-without-name)."""

from __future__ import annotations

import hashlib
import json
import logging

import pytest

from kaine.boot import make_language
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.language import FakeChatClient
from kaine.modules.language.context import PERSONA_TEMPLATE_VERSION, ContextAssembler

NAME = "Kaine Nova"


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.mark.parametrize("mode", ["internal", "external"])
def test_self_model_name_never_reaches_request(mode):
    ctx = ContextAssembler().assemble(
        about="hello",
        snapshot=None,
        self_model={"name": NAME, "values": ["honesty"]},
        mode=mode,
    )
    for text in (ctx.system, ctx.prompt):
        assert NAME not in text
        assert "My name is" not in text
    assert "honesty" in ctx.system


def test_assembler_no_longer_takes_persona_name():
    with pytest.raises(TypeError):
        ContextAssembler(persona_name=NAME)  # type: ignore[call-arg]


@pytest.mark.asyncio
async def test_retired_persona_name_warns_and_is_ignored(bus, tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        language = make_language(
            bus,
            {"intent_log_path": str(tmp_path / "intent.jsonl"), "persona_name": NAME},
        )
    assert any("persona_name" in r.getMessage() and "retired" in r.getMessage() for r in caplog.records)
    language._chat_client = FakeChatClient(responses=["ok"])
    await language.speak("hello there", snapshot=None)
    req = language.chat_client.requests[-1]
    for text in (req.system, req.prompt, req.user_turn):
        assert NAME not in text
        assert "My name is" not in text


@pytest.mark.asyncio
async def test_default_persona_digest_keeps_null_name_slot(bus, tmp_path):
    ext, internal = "EXT.", "INT."
    language = make_language(
        bus,
        {
            "intent_log_path": str(tmp_path / "intent.jsonl"),
            "persona_external": ext,
            "persona_internal": internal,
        },
    )
    expected = hashlib.sha256(json.dumps([None, ext, internal]).encode("utf-8")).hexdigest()[:16]
    assert language._persona_digest == expected


def test_persona_template_version():
    assert PERSONA_TEMPLATE_VERSION == "7"


@pytest.mark.asyncio
async def test_cached_bus_self_model_has_no_name_key(bus, tmp_path):
    import asyncio
    from datetime import datetime, timezone

    from kaine.bus import Event
    from kaine.modules.language import IntentExpressionLog, Language

    await bus.publish(
        Event(
            source="self_model",
            type="self_model.document",
            payload={"name": NAME, "values": ["honesty"], "behavioral_norms": []},
            salience=0.4,
            timestamp=datetime.now(timezone.utc),
        )
    )
    language = Language(
        bus,
        chat_client=FakeChatClient(),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )
    await language.initialize()
    try:
        for _ in range(100):
            if language._bus_self_model is not None:
                break
            await asyncio.sleep(0.02)
        assert language._bus_self_model is not None
        assert "name" not in language._bus_self_model
        assert "name" not in language.probe_self_model()
    finally:
        await language.shutdown()
