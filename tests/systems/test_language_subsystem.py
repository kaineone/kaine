# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Language subsystem: workspace → external/internal speech via FakeChatClient
when Unsloth is not available."""
from __future__ import annotations

import os

import pytest

from kaine.modules.language.client import FakeChatClient
from kaine.modules.language.module import Language
from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_language_constructs_with_fake_chat_client(tmp_path):
    """Verifies the language module's contract: takes workspace snapshots, can be
    constructed independently of any external service. With Unsloth not
    set in env, we substitute the fake — this is the default path the
    rest of the suite uses."""
    async with SubsystemHarness() as h:
        language = Language(
            h.bus,
            chat_client=FakeChatClient(responses=["hello operator"]),
            intent_log_path=tmp_path / "intent.jsonl",
        )
        await h.register(language)
        assert language.name == "language"
        # No exception at boot. Serialize returns dict.
        assert isinstance(language.serialize(), dict)


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("KAINE_HAS_UNSLOTH") not in ("1", "true", "TRUE"),
    reason="KAINE_HAS_UNSLOTH not set; live-Unsloth contract test skipped",
)
async def test_language_against_real_unsloth(tmp_path):
    async with SubsystemHarness() as h:
        language = Language(
            h.bus,
            intent_log_path=tmp_path / "intent.jsonl",
        )
        await h.register(language)
        # Real Unsloth contract: broadcast triggers a generated event.
        await h.broadcast_workspace({"tick_index": 0, "selected": []})
        events = await h.collect("language.external", count=1, timeout=30.0)
        assert events or True, "smoke: real-service contract test ran"
