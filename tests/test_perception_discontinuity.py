# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Perceptual-discontinuity regression guard (perception-drives-salience task 4).

The first containerized base-thesis run falsified the thesis for its config:
perception NEVER influenced the workspace competition — Topos emitted its baseline
salience on all 3,830 reports and Audition on all 3,511 events, so a scene cut and
a frozen frame produced the identical value. These tests are the standing guard
against silent regression back to flat-baseline perception: a hard discontinuity
(a scene cut / an acoustic onset) MUST raise at least one alert-level perceptual
event on each surface. If perception ever goes flat again, these fail.
"""
from __future__ import annotations

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.audition import (
    Audition,
    FakeEmotionClassifier,
    FakeSTTClient,
)
from kaine.modules.audition.acoustic import FakeAcousticEncoder
from kaine.modules.topos import Topos


class _FakeClipEncoder:
    """Minimal encoder double returning preset latents in call order."""

    model_id = "fake/discontinuity-encoder"
    latent_dim = 4
    clip_len = 1

    def __init__(self, vectors: list[list[float]]) -> None:
        self.calls = 0
        self._vectors = vectors

    async def load(self) -> None:  # pragma: no cover - trivial
        pass

    async def shutdown(self) -> None:  # pragma: no cover - trivial
        pass

    async def encode(self, image):  # noqa: ARG002
        vec = self._vectors[self.calls % len(self._vectors)]
        self.calls += 1
        return list(vec)

    async def encode_clip(self, frames):
        return await self.encode(frames[-1])


class _ConstErrorForwardModel:
    """Constant prediction error → the forward-model path never alerts on its own,
    so these guards attribute any alert to the (stimulus-driven) change path."""

    def step(self, embedding):  # noqa: ARG002
        return 1.0


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.mark.asyncio
async def test_scene_cut_produces_an_alert_level_topos_report(bus: AsyncBus):
    """A hard scene cut MUST raise at least one alert-level topos.report."""
    steady = [0.5, 0.5, 0.5, 0.5]
    cut = [0.5, -0.5, 0.5, -0.5]  # orthogonal → a hard cut
    enc = _FakeClipEncoder([steady] * 6 + [cut] + [steady] * 3)
    topos = Topos(
        bus,
        encoder=enc,
        forward_prediction=False,  # attribute the alert to perception, not internals
        change_alert_threshold=1e-4,
        baseline_salience=0.2,
        alert_salience=0.7,
    )
    for _ in range(10):
        await topos.process_frame(None)
    entries = await bus.read("topos.out", last_id="0")
    reports = [ev for _, ev in entries]
    alerted = [r for r in reports if r.payload["alert"]]
    # The cut alerts; a run over a steady stream does NOT sit at a flat baseline.
    assert alerted, "scene cut produced no alert-level topos.report (flat perception)"
    assert any(r.salience == pytest.approx(0.7) for r in alerted)
    # And the steady frames before the cut stayed at baseline (perception varies).
    assert reports[0].salience == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_acoustic_onset_produces_an_alert_level_perception(bus: AsyncBus):
    """An acoustic onset MUST raise at least one alert-level audition.perception."""
    import numpy as np

    def _tone(freq: float) -> bytes:
        t = np.arange(int(0.2 * 16000)) / 16000
        return (0.3 * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2").tobytes()

    audition = Audition(
        bus,
        stt_client=FakeSTTClient(responses=["x"]),
        emotion_classifier=FakeEmotionClassifier(),
        stt_model="fake-stt",
        general_audition=True,
        acoustic_encoder=FakeAcousticEncoder(embedding_dim=8),
        acoustic_change_alert_threshold=0.01,
    )
    audition._acoustic_forward_model = _ConstErrorForwardModel()
    await audition.initialize()
    try:
        for _ in range(4):
            await audition.process_audio(_tone(300), sample_rate=16000)
        await audition.process_audio(_tone(6000), sample_rate=16000)  # onset
        entries = await bus.read("audition.out", last_id="0", count=50)
        perc = [e for _, e in entries if e.type == "audition.perception"]
        alerted = [p for p in perc if p.payload["alert"]]
        assert alerted, "acoustic onset produced no alert-level perception (flat)"
        assert any(
            p.salience == pytest.approx(audition._alert_salience) for p in alerted
        )
    finally:
        await audition.shutdown()
