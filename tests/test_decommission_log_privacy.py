# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Decommission keeps state/logs/ on the promise that it holds no entity content. This test drives a seeded utterance through the language and vocal modules' real emit paths while the cycle's own private log file is installed at DEBUG, and checks the utterance never reaches state/logs/."""

import asyncio
import inspect
import logging
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.private_log import install_private_log_file
from kaine.modules.language import (
    EXTERNAL_STREAM,
    FakeChatClient,
    IntentExpressionLog,
    Language,
)
from kaine.modules.vocal import FakePlayer, FakeTTSClient, Vocal


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


async def _wait_until(condition, timeout=2.0, interval=0.05):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        result = condition()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return result
        await asyncio.sleep(interval)
    return None


async def test_seeded_utterance_never_reaches_state_logs(bus, tmp_path):
    """A seeded entity utterance must never be written under state/logs/."""

    REPLY = "SECRET-UTTERANCE the entity said this"
    HEARD = "SECRET-HEARD the operator said this"

    state_root = tmp_path / "state"
    log_path = state_root / "logs" / "cycle-test.log"
    (state_root / "logs").mkdir(parents=True, exist_ok=True)
    (state_root / "language").mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    saved_level = root.level
    saved_handlers = list(root.handlers)

    language = None
    vocal = None
    handler = None

    try:
        handler = install_private_log_file(log_path, level=logging.DEBUG)
        root.setLevel(logging.DEBUG)

        logging.getLogger("kaine.modules.language").info("log-privacy sentinel")

        language = Language(
            bus,
            chat_client=FakeChatClient(responses=[REPLY]),
            intent_log=IntentExpressionLog(
                state_root / "language" / "intent_expression.jsonl"
            ),
            model_id="fake-model",
        )
        vocal = Vocal(
            bus,
            tts_client=FakeTTSClient(canned_audio=b"WAV-FAKE"),
            sink_path=state_root / "vocal",
            predefined_voice_id="default_sample.wav",
            player=FakePlayer(),
        )

        await language.initialize()
        await vocal.initialize()

        await bus.publish(
            Event(
                source="action_selection",
                type="intent.speak",
                payload={"kind": "speak", "about": HEARD},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        )

        entries = await _wait_until(
            lambda: bus.client.xrange(EXTERNAL_STREAM), timeout=2.0
        )
        assert entries, "language did not emit the reply to the external stream"

        requests = await _wait_until(
            lambda: vocal.tts_client.requests, timeout=2.0
        )
        assert requests, "vocal did not synthesize any speech"
        synthesized = requests[0].text
        assert synthesized == REPLY

    finally:
        if language is not None:
            await language.shutdown()
        if vocal is not None:
            await vocal.shutdown()

        if handler is not None:
            handler.flush()
            root.removeHandler(handler)
            handler.close()

        root.setLevel(saved_level)
        for saved_handler in saved_handlers:
            if saved_handler not in root.handlers:
                root.addHandler(saved_handler)

        logging.captureWarnings(False)

    log_text = log_path.read_text(encoding="utf-8", errors="replace")
    assert "log-privacy sentinel" in log_text

    for log_file in (state_root / "logs").rglob("*"):
        if not log_file.is_file():
            continue
        text = log_file.read_text(encoding="utf-8", errors="replace")
        assert "SECRET-UTTERANCE" not in text
        assert "SECRET-HEARD" not in text
