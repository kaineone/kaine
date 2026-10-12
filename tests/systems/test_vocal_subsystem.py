# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Vocal subsystem: TTS request observed by Fake client when
Chatterbox is absent."""
from __future__ import annotations

import os

import pytest

from kaine.modules.vocal.client import FakeTTSClient
from kaine.modules.vocal.module import Vocal
from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_vocal_constructs_with_fake_tts(tmp_path):
    async with SubsystemHarness() as h:
        ao = Vocal(
            h.bus,
            tts_client=FakeTTSClient(),
            sink_path=tmp_path / "audio",
        )
        await h.register(ao)
        assert ao.name == "vox"


@pytest.mark.asyncio
async def test_vocal_renders_on_language_external(tmp_path):
    fake = FakeTTSClient()
    async with SubsystemHarness() as h:
        ao = Vocal(
            h.bus,
            tts_client=fake,
            sink_path=tmp_path / "audio",
        )
        await h.register(ao)
        # Inject a language module external_speech event into the lingua.external
        # stream specifically (not lingua.out, which is what the default
        # publish() path would target).
        await h.inject_to_stream(
            "lingua.external",
            source="lingua",
            type="external_speech",
            payload={"text": "hello"},
        )
        # Wait briefly for the consumer task to drain.
        events = await h.collect("vox.out", count=1, timeout=1.5)
        # Either an event was published or the fake was invoked.
        assert events or fake.requests


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("KAINE_HAS_CHATTERBOX") not in ("1", "true", "TRUE"),
    reason="KAINE_HAS_CHATTERBOX not set; live-Chatterbox contract test skipped",
)
async def test_vocal_against_real_chatterbox(tmp_path):
    async with SubsystemHarness() as h:
        ao = Vocal(h.bus, sink_path=tmp_path / "audio")
        await h.register(ao)
        # Smoke only.
        assert ao.name == "vox"
