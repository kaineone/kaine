# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""History readers fall back to the streams' names from before the keys rename."""

import json

import pytest

from kaine import legacy_aliases
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.dashboard.conversation import read_conversation_history
from kaine.modules.language import FakeChatClient, IntentExpressionLog, Language

OLD_SLEEP = legacy_aliases.old_stream_name("sleep.out")
OLD_EXTERNAL = legacy_aliases.old_stream_name("language.external")


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _fields(source: str, type_: str, payload: dict) -> dict:
    return {
        "source": source,
        "type": type_,
        "salience": "0.1",
        "timestamp": "2026-10-13T00:00:00+00:00",
        "causal_parent": "",
        "payload": json.dumps(payload),
    }


def test_old_stream_names_come_from_the_table():
    """The helper names each renamed stream's old name and nothing for an unrenamed one."""
    assert OLD_SLEEP is not None and OLD_SLEEP != "sleep.out"
    assert OLD_EXTERNAL is not None and OLD_EXTERNAL != "language.external"
    assert legacy_aliases.old_stream_name("cycle.out") is None


async def test_sleep_index_backfills_from_the_old_stream(bus, tmp_path):
    """With no sleep event on the new stream, the language module takes the last one from the old stream."""
    old_source = OLD_SLEEP.removesuffix(".out")
    await bus.client.xadd(OLD_SLEEP, _fields(old_source, f"{old_source}.sleep.completed", {"sleep_index": 7}))
    language = Language(
        bus,
        chat_client=FakeChatClient(),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )
    await language.initialize()
    try:
        assert language._sleep_index == 7
    finally:
        await language.shutdown()


async def test_sleep_index_prefers_the_new_stream(bus, tmp_path):
    """A sleep event on the new stream wins over the old stream."""
    old_source = OLD_SLEEP.removesuffix(".out")
    await bus.client.xadd(OLD_SLEEP, _fields(old_source, f"{old_source}.sleep.completed", {"sleep_index": 7}))
    await bus.client.xadd("sleep.out", _fields("sleep", "sleep.sleep.completed", {"sleep_index": 9}))
    language = Language(
        bus,
        chat_client=FakeChatClient(),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )
    await language.initialize()
    try:
        assert language._sleep_index == 9
    finally:
        await language.shutdown()


async def test_conversation_history_merges_old_then_new(bus):
    """Dashboard history reads the old stream and the new one in id order, with old events under the new names."""
    old_source = OLD_EXTERNAL.split(".", 1)[0]
    await bus.client.xadd(OLD_EXTERNAL, _fields(old_source, OLD_EXTERNAL, {"text": "before"}), id="1000-0")
    await bus.client.xadd("language.external", _fields("language", "language.external", {"text": "after"}), id="2000-0")
    await bus.client.xadd(OLD_EXTERNAL, _fields(old_source, OLD_EXTERNAL, {"text": "between"}), id="1500-0")

    history = await read_conversation_history(bus, 10)

    assert [event.payload["text"] for _, event in history] == ["before", "between", "after"]
    assert {event.source for _, event in history} == {"language"}
    assert {event.type for _, event in history} == {"language.external"}


async def test_conversation_history_without_the_old_stream(bus):
    """Once the cleanup has removed the old stream, history reads the new stream alone."""
    await bus.client.xadd("language.external", _fields("language", "language.external", {"text": "only"}))
    history = await read_conversation_history(bus, 10)
    assert [event.payload["text"] for _, event in history] == ["only"]
