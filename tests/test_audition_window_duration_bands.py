# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import math

import numpy as np
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.audition import Audition, FakeEmotionClassifier, FakeSTTClient
from kaine.modules.audition.acoustic import (
    SpectralAcousticEncoder,
    _decode_audio,
    _log_spaced_edges,
    attend_recent,
)


def _make_audition(bus: AsyncBus, **overrides) -> Audition:
    overrides.setdefault("stt_client", FakeSTTClient(responses=["hello world"]))
    overrides.setdefault("emotion_classifier", FakeEmotionClassifier())
    overrides.setdefault("stt_model", "fake-stt")
    overrides.setdefault("transcription_enabled", True)
    return Audition(bus, **overrides)


async def _close_module(module: Audition) -> None:
    await module.shutdown()
    for task in list(getattr(module, "_tasks", [])):
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # Expected: the task was just cancelled during teardown.
                pass


@pytest.fixture
async def redis_bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def test_attend_recent_keeps_recent_tail():
    sample_rate = 16000
    duration = 2
    n = sample_rate * duration
    rng = np.random.default_rng(0)
    ints = rng.integers(-32768, 32767, size=n, dtype=np.int16)
    samples = (ints.astype(np.float32) / 32768.0).astype(np.float32)
    pcm = ints.astype("<i2").tobytes()

    kept, seconds = attend_recent(pcm, 1.0, sample_rate)
    decoded = _decode_audio(kept)
    assert decoded.size == n
    assert seconds == pytest.approx(n / sample_rate)
    assert np.allclose(decoded, samples, atol=1 / 32768)

    fraction = 0.15
    kept, seconds = attend_recent(pcm, fraction, sample_rate)
    decoded = _decode_audio(kept)
    expected_k = math.ceil(fraction * n)
    assert decoded.size == expected_k
    assert np.allclose(decoded, samples[-expected_k:], atol=1 / 32768)

    kept, seconds = attend_recent(pcm, 0.0001, sample_rate)
    decoded = _decode_audio(kept)
    assert decoded.size >= math.ceil(0.025 * sample_rate)
    assert decoded.size <= n


def test_log_spaced_edges_valid():
    edges = _log_spaced_edges(32, 16000, 201)
    assert edges[0] >= 1
    assert edges[-1] <= 200
    diffs = np.diff(edges)
    assert np.all(diffs >= 1)
    pairs = set()
    for b in range(32):
        a = int(edges[b])
        c = int(edges[b + 1])
        assert c > a
        pairs.add((a, c))
    assert len(pairs) == 32


def test_log_spaced_edges_too_small_raises():
    with pytest.raises(ValueError):
        _log_spaced_edges(32, 16000, 20)


def test_spectral_encoder_model_id_and_noise_embedding():
    encoder = SpectralAcousticEncoder()
    assert encoder.model_id.endswith("-v2")

    sample_rate = 16000
    rng = np.random.default_rng(1)
    samples = (rng.random(sample_rate, dtype=np.float32) * 2.0 - 1.0).astype(np.float32)
    pcm = (samples * 32767.0).astype(np.int16).tobytes()
    embedding = encoder.embed(pcm, sample_rate)
    assert len(embedding) == 64
    assert all(np.isfinite(embedding))


@pytest.mark.asyncio
async def test_audition_serialize_utterance_duration_feature(redis_bus):
    audition = _make_audition(redis_bus)
    await audition.initialize()
    try:
        state = audition.serialize()
        assert state.get("forward_model_features") == "utterance_duration_v2"

        original_state = audition._forward_model.state_dict()
        old_checkpoint = {"forward_model": original_state}
        audition.deserialize(old_checkpoint)
        assert audition._forward_model.state_dict() == original_state
    finally:
        await _close_module(audition)
