# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Module factories thread the device-pinning keys correctly.

These tests don't need a real GPU — they assert the kwargs flow from
TOML through boot.py to the module/encoder constructors.
"""
from __future__ import annotations

import pytest

from kaine.boot import make_audition, make_mnemos, make_topos
from kaine.modules.audition.module import Audition
from kaine.modules.hypnos.voice_alignment import VoiceAlignmentConfig
from kaine.modules.mnemos.module import Mnemos
from kaine.modules.topos.module import Topos

from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_topos_factory_forwards_cuda_index():
    async with SubsystemHarness() as h:
        topos = make_topos(
            h.bus,
            {
                "encoder_backend": "dinov2",
                "encoder_model_id": "facebook/dinov2-small",
                "device": "cuda:1",
                "change_alert_threshold": 0.5,
                "baseline_salience": 0.2,
                "alert_salience": 0.7,
            },
        )
        assert isinstance(topos, Topos)
        # Encoder hasn't loaded — but the preference is stored.
        assert topos._encoder._device_preference == "cuda:1"


@pytest.mark.asyncio
async def test_mnemos_factory_forwards_device_to_embedder():
    async with SubsystemHarness() as h:
        mnemos = make_mnemos(
            h.bus,
            {
                "backend": "inmemory",
                "collection_prefix": "mnemos_",
                "short_term_capacity": 8,
                "recall_top_k": 3,
                "device": "cpu",
                "embedder_model_id": "sentence-transformers/all-MiniLM-L6-v2",
            },
        )
        assert isinstance(mnemos, Mnemos)
        # Embedder is the default SentenceTransformerEmbedder; its
        # preference is set but the model hasn't loaded.
        assert mnemos._core._embedder._device_preference == "cpu"


@pytest.mark.asyncio
async def test_audition_factory_forwards_emotion_device():
    async with SubsystemHarness() as h:
        ai = make_audition(
            h.bus,
            {
                "speaches_url": "http://127.0.0.1:8000",
                "stt_model": "x",
                "emotion_model_id": "y",
                "emotion_device": "cpu",
                "request_timeout_s": 60.0,
            },
        )
        assert isinstance(ai, Audition)
        assert ai._emotion_device == "cpu"


def test_voice_alignment_config_carries_training_device():
    cfg = VoiceAlignmentConfig(
        intent_log_path="state/lingua/x.jsonl",
        adapter_output_dir="state/hypnos/adapters",
        training_device="cuda:0",
    )
    assert cfg.training_device == "cuda:0"


def test_voice_alignment_config_default_training_device():
    cfg = VoiceAlignmentConfig(
        intent_log_path="x", adapter_output_dir="y"
    )
    assert cfg.training_device == "cuda:0"


def test_topos_factory_rejects_unknown_device_key():
    """Unknown TOML keys still trip the allowlist."""
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    import fakeredis.aioredis

    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    with pytest.raises(ValueError, match="unknown config keys"):
        make_topos(
            bus,
            {
                "device": "cuda:1",
                "bogus_extra": "nope",
            },
        )
