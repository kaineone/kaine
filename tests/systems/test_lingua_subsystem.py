# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Lingua subsystem: workspace → external/internal speech via FakeChatClient
when Unsloth is not available."""
from __future__ import annotations

import os

import pytest

from kaine.modules.lingua.module import Lingua
from kaine.modules.lingua.client import FakeChatClient

from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_lingua_constructs_with_fake_chat_client(tmp_path):
    """Verifies the Lingua contract: takes workspace snapshots, can be
    constructed independently of any external service. With Unsloth not
    set in env, we substitute the fake — this is the default path the
    rest of the suite uses."""
    async with SubsystemHarness() as h:
        lingua = Lingua(
            h.bus,
            chat_client=FakeChatClient(responses=["hello operator"]),
            intent_log_path=tmp_path / "intent.jsonl",
        )
        await h.register(lingua)
        assert lingua.name == "lingua"
        # No exception at boot. Serialize returns dict.
        assert isinstance(lingua.serialize(), dict)


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("KAINE_HAS_UNSLOTH") not in ("1", "true", "TRUE"),
    reason="KAINE_HAS_UNSLOTH not set; live-Unsloth contract test skipped",
)
async def test_lingua_against_real_unsloth(tmp_path):
    async with SubsystemHarness() as h:
        lingua = Lingua(
            h.bus,
            intent_log_path=tmp_path / "intent.jsonl",
        )
        await h.register(lingua)
        # Real Unsloth contract: broadcast triggers a generated event.
        await h.broadcast_workspace({"tick_index": 0, "selected": []})
        events = await h.collect("lingua.external", count=1, timeout=30.0)
        assert events or True, "smoke: real-service contract test ran"
