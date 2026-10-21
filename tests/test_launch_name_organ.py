# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The entity's launch name never reaches the language organ (launch-name-at-first-boot)."""

from __future__ import annotations

import asyncio
import dataclasses

import fakeredis.aioredis
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.language import (
    EXTERNAL_STREAM,
    INTERNAL_STREAM,
    FakeChatClient,
    IntentExpressionLog,
    Language,
)
from kaine.modules.self_model import SelfModel

NAME = "Kaine Zqxvbn"


@pytest.fixture
def bus():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


def _everything(req) -> str:
    return " || ".join(str(v) for v in dataclasses.asdict(req).values())


@pytest.mark.asyncio
async def test_identity_name_never_reaches_the_organ(bus, tmp_path):
    sm = SelfModel(bus, persistence_path=tmp_path / "sm.json", identity_name=NAME, save_interval_s=60)
    client = FakeChatClient(responses=["a", "b"])
    language = Language(
        bus,
        chat_client=client,
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )
    await language.initialize()
    await sm.initialize()
    try:
        for _ in range(100):
            if language._bus_self_model is not None:
                break
            await asyncio.sleep(0.05)
        assert language._bus_self_model is not None, "the self-model snapshot never arrived"
        assert "name" not in language._bus_self_model  # the language module caches no name
        snap = WorkspaceSnapshot(tick_index=0, selected_events=[], inhibited=False)
        await language._produce_inner(
            about="Who are you?", snapshot=snap, mode="external", stream=EXTERNAL_STREAM, about_kind="felt"
        )
        await language._produce_inner(
            about="What is on your mind?", snapshot=snap, mode="internal", stream=INTERNAL_STREAM, about_kind="felt"
        )
        probe = language.probe_request(
            "Who are you?", seed=1, max_tokens=16, self_model=language.probe_self_model()
        )
        requests = [*client.requests, probe]
        assert len(requests) == 3
        for req in requests:
            blob = _everything(req)
            assert NAME not in blob
            assert "Zqxvbn" not in blob
    finally:
        await sm.shutdown()
        await language.shutdown()
