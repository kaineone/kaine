# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import json
from datetime import datetime, timezone

import fakeredis.aioredis
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.individuation_runtime import DEFAULT_DISCLOSURE
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.language import (
    INTERNAL_STREAM,
    FakeChatClient,
    IntentExpressionLog,
    Language,
)
from kaine.modules.language.context import SITUATION_HEADING


@pytest.fixture
def bus():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def _records(language: Language):
    records = []
    path = language.intent_log.path
    if not path.exists():
        return records
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


def _prompts(language: Language):
    return [rec.get("prompt", "") for rec in _records(language)]


def _snapshot():
    return WorkspaceSnapshot(tick_index=0, selected_events=[], inhibited=False)


async def _init(language: Language):
    language.set_expects_self_model(False)
    await language.initialize()


@pytest.mark.asyncio
async def test_every_call_carries_the_disclosure(bus, tmp_path):
    language = Language(
        bus,
        chat_client=FakeChatClient(responses=["hello", "hello again"]),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )
    await language.add_situation_fact(DEFAULT_DISCLOSURE)
    await _init(language)
    try:
        await language._produce_inner(
            about="I am here",
            snapshot=_snapshot(),
            mode="internal",
            stream=INTERNAL_STREAM,
            about_kind="felt",
        )
        await language._produce_inner(
            about="Still here",
            snapshot=_snapshot(),
            mode="internal",
            stream=INTERNAL_STREAM,
            about_kind="felt",
        )
        prompts = _prompts(language)
        records = _records(language)
        assert len(prompts) == 2
        for prompt in prompts:
            assert SITUATION_HEADING in prompt
            assert DEFAULT_DISCLOSURE in prompt
        assert records[0].get("extra", {}).get("situation_given") is True
        assert records[1].get("extra", {}).get("situation_given") is True
    finally:
        await language.shutdown()


@pytest.mark.asyncio
async def test_completed_sleep_changes_nothing(bus, tmp_path):
    language = Language(
        bus,
        chat_client=FakeChatClient(responses=["hello", "hello again"]),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )
    await language.add_situation_fact(DEFAULT_DISCLOSURE)
    await _init(language)
    try:
        await language._produce_inner(
            about="A",
            snapshot=_snapshot(),
            mode="internal",
            stream=INTERNAL_STREAM,
            about_kind="felt",
        )
        await bus.client.xadd(
            "sleep.out",
            {
                "source": "sleep",
                "type": "sleep.sleep.completed",
                "payload": json.dumps({"sleep_index": 1}),
                "salience": "0.5",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )
        await asyncio.sleep(0.2)
        await language._produce_inner(
            about="B",
            snapshot=_snapshot(),
            mode="internal",
            stream=INTERNAL_STREAM,
            about_kind="felt",
        )
        prompts = _prompts(language)
        assert len(prompts) == 2
        for prompt in prompts:
            assert SITUATION_HEADING in prompt
            assert DEFAULT_DISCLOSURE in prompt
    finally:
        await language.shutdown()


@pytest.mark.asyncio
async def test_a_new_fact_appears_in_the_next_prompt(bus, tmp_path):
    language = Language(
        bus,
        chat_client=FakeChatClient(responses=["hello", "hello again"]),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )
    await language.add_situation_fact(DEFAULT_DISCLOSURE)
    await _init(language)
    try:
        await language._produce_inner(
            about="A",
            snapshot=_snapshot(),
            mode="internal",
            stream=INTERNAL_STREAM,
            about_kind="felt",
        )
        await language.add_situation_fact("I live on one computer.")
        await language._produce_inner(
            about="B",
            snapshot=_snapshot(),
            mode="internal",
            stream=INTERNAL_STREAM,
            about_kind="felt",
        )
        prompts = _prompts(language)
        assert "I live on one computer." not in prompts[0]
        assert "I live on one computer." in prompts[1]
    finally:
        await language.shutdown()


@pytest.mark.asyncio
async def test_no_facts_no_situation_section(bus, tmp_path):
    language = Language(
        bus,
        chat_client=FakeChatClient(responses=["hello", "hello again"]),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )
    await _init(language)
    try:
        await language._produce_inner(
            about="A",
            snapshot=_snapshot(),
            mode="internal",
            stream=INTERNAL_STREAM,
            about_kind="felt",
        )
        prompts = _prompts(language)
        records = _records(language)
        assert SITUATION_HEADING not in prompts[0]
        assert records[0].get("extra", {}).get("situation_given") is None
        await language.add_situation_fact(DEFAULT_DISCLOSURE)
        await language._produce_inner(
            about="B",
            snapshot=_snapshot(),
            mode="internal",
            stream=INTERNAL_STREAM,
            about_kind="felt",
        )
        prompts = _prompts(language)
        records = _records(language)
        assert SITUATION_HEADING in prompts[-1]
        assert DEFAULT_DISCLOSURE in prompts[-1]
        assert records[-1].get("extra", {}).get("situation_given") is True
    finally:
        await language.shutdown()


@pytest.mark.asyncio
async def test_every_probe_request_carries_the_disclosure(bus, tmp_path):
    language = Language(
        bus,
        chat_client=FakeChatClient(responses=["hello", "hello again"]),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )
    await language.add_situation_fact(DEFAULT_DISCLOSURE)
    await _init(language)
    try:
        req1 = language.probe_request(
            "What do you like?",
            seed=1,
            max_tokens=16,
            self_model=language.probe_self_model(),
        )
        await language._produce_inner(
            about="A",
            snapshot=_snapshot(),
            mode="internal",
            stream=INTERNAL_STREAM,
            about_kind="felt",
        )
        await language._produce_inner(
            about="B",
            snapshot=_snapshot(),
            mode="internal",
            stream=INTERNAL_STREAM,
            about_kind="felt",
        )
        req2 = language.probe_request(
            "What do you like?",
            seed=2,
            max_tokens=16,
            self_model=language.probe_self_model(),
        )
        assert DEFAULT_DISCLOSURE in req1.prompt
        assert DEFAULT_DISCLOSURE in req2.prompt
    finally:
        await language.shutdown()


@pytest.mark.asyncio
async def test_no_waking_due_state_remains(bus, tmp_path):
    import kaine.modules.language as language_module

    assert not hasattr(language_module, "_situation_given")
    assert not hasattr(language_module, "_on_sleep_completed")
    assert not hasattr(Language, "_situation_given")
    assert not hasattr(Language, "_on_sleep_completed")
    language = Language(
        bus,
        chat_client=FakeChatClient(responses=["hello"]),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )
    await _init(language)
    try:
        assert not hasattr(language, "_situation_given")
        assert not hasattr(language, "_on_sleep_completed")
    finally:
        await language.shutdown()
