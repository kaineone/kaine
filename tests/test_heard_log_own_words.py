# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.faithful.templates import HEARD_SPEECH_PLACEHOLDER
from kaine.modules.language import EXTERNAL_STREAM, FakeChatClient, IntentExpressionLog, Language


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


def _make_language(bus: AsyncBus, tmp_path: Path, responses=None) -> Language:
    return Language(
        bus,
        chat_client=FakeChatClient(responses=responses),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
        # The felt rendering, as the first configuration ships it: the numeric
        # rendering redacts every heard-named field of each event on its own.
        awareness_rendering="felt",
    )


def _snapshot(events=None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=0, selected_events=events or [], inhibited=False)


async def _say(language, *, about, snapshot, about_kind):
    """Run one external utterance to completion, as the dispatcher would."""
    return await language._produce_inner(
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
async def test_own_felt_phrase_recurring_stays_in_the_log(bus: AsyncBus, tmp_path: Path, caplog):
    felt = "Something in what I hear stands out noticeably."
    language = _make_language(bus, tmp_path, responses=["one", "two"])
    await language.initialize()
    try:
        caplog.set_level(logging.WARNING, logger="kaine.modules.language.module")
        await _say(language, about=felt, snapshot=_snapshot(), about_kind="felt")
        first_payload = _payloads(await bus.client.xrange(EXTERNAL_STREAM))[-1]

        own = _snapshot([("l1", _event("language", "external_speech", first_payload))])
        await _say(language, about=felt, snapshot=own, about_kind="felt")

        last = _records(language.intent_log.path)[-1]
        assert felt in last["prompt"]
        assert HEARD_SPEECH_PLACEHOLDER not in last["prompt"]
        assert not any("residual text in log" in m for m in caplog.messages)
    finally:
        await language.shutdown()


@pytest.mark.asyncio
async def test_own_rendering_line_recurring_stays_in_the_log(bus: AsyncBus, tmp_path: Path, caplog):
    language = _make_language(bus, tmp_path, responses=["one", "two"])
    await language.initialize()
    try:
        caplog.set_level(logging.WARNING, logger="kaine.modules.language.module")

        about = "something in what I see"
        vision = _event(
            "vision",
            "vision.report",
            {"change_score": 0.2, "normalised_change": 0.2, "normalised_error": 0.5},
        )
        await _say(
            language,
            about=about,
            snapshot=_snapshot([("v1", vision)]),
            about_kind="event",
        )

        first = _records(language.intent_log.path)[-1]
        line = first["faithful_rendering"].strip().lstrip("-").strip()

        own_payload = {"text": "I spoke.", "mode": "external", "faithful_rendering": line}
        await _say(
            language,
            about=about,
            snapshot=_snapshot([("v1", vision), ("l1", _event("language", "external_speech", own_payload))]),
            about_kind="event",
        )

        second = _records(language.intent_log.path)[-1]
        assert line in second["faithful_rendering"]
        assert HEARD_SPEECH_PLACEHOLDER not in second["faithful_rendering"]
        assert HEARD_SPEECH_PLACEHOLDER not in second["prompt"]
        assert not any("residual text in log" in m for m in caplog.messages)
    finally:
        await language.shutdown()


@pytest.mark.asyncio
async def test_foreign_heard_field_is_still_replaced(bus: AsyncBus, tmp_path: Path):
    sentinel = "PURPLE-HERON-4471 foreign field"
    language = _make_language(bus, tmp_path, responses=["one"])
    await language.initialize()
    try:
        event = _event(
            "dashboard",
            "dashboard.note",
            {"user_text": sentinel},
            salience=0.9,
        )
        await _say(
            language,
            about=sentinel,
            snapshot=_snapshot([("d1", event)]),
            about_kind="event",
        )

        log_text = language.intent_log.path.read_text()
        assert sentinel not in log_text
        last = _records(language.intent_log.path)[-1]
        assert HEARD_SPEECH_PLACEHOLDER in last["prompt"]
    finally:
        await language.shutdown()
