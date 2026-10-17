# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import numpy as np
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.audition import Audition, FakeEmotionClassifier, FakeSTTClient
from kaine.modules.audition.acoustic import FakeAcousticEncoder


def _tone(freq: float, seconds: float = 0.2, amp: float = 0.3, sr: int = 16000) -> bytes:
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2").tobytes()


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _make_audition(bus: AsyncBus, **overrides) -> Audition:
    # STT is deactivated by default in the module; this helper builds the full
    # pipeline (STT on) so transcription-path tests opt in explicitly.
    overrides.setdefault("transcription_enabled", True)
    return Audition(
        bus,
        stt_client=FakeSTTClient(responses=["hello world"]),
        emotion_classifier=FakeEmotionClassifier(),
        stt_model="fake-stt",
        **overrides,
    )


def _general_audition(bus: AsyncBus, **overrides) -> Audition:
    return _make_audition(
        bus,
        general_audition=True,
        acoustic_encoder=FakeAcousticEncoder(embedding_dim=8),
        **overrides,
    )


class _ConstErrorForwardModel:
    """Test double: constant prediction error, isolating the change-alert path
    from the forward-model path (normalised error stays ~1.0 -> never alerts)."""

    def step(self, embedding):  # noqa: ARG002
        return 1.0


def _prepare_audition(bus: AsyncBus) -> Audition:
    audition = _general_audition(bus, acoustic_change_alert_threshold=0.01)
    audition._acoustic_forward_model = _ConstErrorForwardModel()
    # The fake model only accepts the embedding, so bypass context arguments.
    audition._acoustic_forward_model.context_dim = 0
    return audition


@pytest.mark.asyncio
async def test_normalised_change_on_acoustic_onset(bus):
    audition = _prepare_audition(bus)
    await audition.initialize()
    try:
        for _ in range(4):
            await audition.process_audio(_tone(300), sample_rate=16000)
        await audition.process_audio(_tone(6000), sample_rate=16000)

        entries = await bus.read("audition.out", last_id="0", count=50)
        perceptions = [e for _, e in entries if e.type == "audition.perception"]
        assert len(perceptions) == 5

        change_scores = [p.payload["change_score"] for p in perceptions]
        for p in perceptions:
            assert "normalised_change" in p.payload
            assert isinstance(p.payload["normalised_change"], float)

        assert perceptions[0].payload["normalised_change"] == 0.0

        fifth = perceptions[4].payload
        mean = sum(change_scores) / len(change_scores)
        assert fifth["normalised_change"] == pytest.approx(change_scores[4] / mean)
        assert fifth["normalised_change"] >= 2.0
        assert fifth["alert"] is True
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_normalised_change_zero_on_first_window(bus):
    audition = _prepare_audition(bus)
    await audition.initialize()
    try:
        await audition.process_audio(_tone(300), sample_rate=16000)

        entries = await bus.read("audition.out", last_id="0", count=50)
        perceptions = [e for _, e in entries if e.type == "audition.perception"]
        assert len(perceptions) == 1
        assert perceptions[0].payload["normalised_change"] == 0.0
    finally:
        await audition.shutdown()
