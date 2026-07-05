# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Audio Input subsystem: STT + emotion via fakes when Speaches absent."""
from __future__ import annotations

import os

import pytest

from kaine.modules.audition.module import Audition
from kaine.modules.audition.stt_client import FakeSTTClient
from kaine.modules.audition.emotion import FakeEmotionClassifier

from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_audition_constructs_with_fakes():
    async with SubsystemHarness() as h:
        ai = Audition(
            h.bus,
            stt_client=FakeSTTClient(responses=["hello"]),
            emotion_classifier=FakeEmotionClassifier(),
        )
        await h.register(ai)
        assert ai.name == "audition"


@pytest.mark.asyncio
async def test_audition_serializes_state():
    async with SubsystemHarness() as h:
        ai = Audition(
            h.bus,
            stt_client=FakeSTTClient(responses=[]),
            emotion_classifier=FakeEmotionClassifier(),
        )
        await h.register(ai)
        state = ai.serialize()
        assert isinstance(state, dict)


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("KAINE_HAS_SPEACHES") not in ("1", "true", "TRUE"),
    reason="KAINE_HAS_SPEACHES not set; live-Speaches contract test skipped",
)
async def test_audition_against_real_speaches():
    async with SubsystemHarness() as h:
        ai = Audition(h.bus)
        await h.register(ai)
        # Smoke only — no real audio bytes to inject.
        assert ai.name == "audition"
