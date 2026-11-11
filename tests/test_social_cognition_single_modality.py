# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Single-modality tests: voice-only and face-only identity pipelines."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.modules.social_cognition.agent import EMOTION_CATEGORIES
from kaine.modules.social_cognition.module import SocialCognition
from kaine.modules.social_cognition.store import InMemoryAgentStore


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _speaker_embedding_event(
    embedding: list[float], confidence: float = 0.9, source_label: str = "live_mic"
) -> Event:
    return Event(
        source="audition",
        type="audition.speaker_embedding",
        payload={"embedding": embedding, "confidence": confidence, "source_label": source_label},
        salience=0.4,
        timestamp=datetime.now(timezone.utc),
    )


def _face_detection_event(faces: list[dict]) -> Event:
    return Event(
        source="vision",
        type="vision.face_detection",
        payload={"faces": faces},
        salience=0.4,
        timestamp=datetime.now(timezone.utc),
    )


def _emotion_event(
    category: str = "happy",
    confidence: float = 0.8,
    source_label: str = "live_mic",
) -> Event:
    payload = {
        "category": category,
        "confidence": confidence,
        "scores": {c: (1.0 if c == category else 0.0) for c in EMOTION_CATEGORIES},
        "model": "emotion2vec/emotion2vec_plus_base",
        "latency_ms": 50.0,
        "prediction_error": 0.0,
        "source_label": source_label,
    }
    return Event(
        source="audition",
        type="audition.emotion",
        payload=payload,
        salience=0.4,
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Voice-only (speaker_identification_enabled=True, face_identification_enabled=False)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_only_mints_agent_with_voice_data(bus):
    store = InMemoryAgentStore()
    module = SocialCognition(
        bus,
        store=store,
        speaker_identification_enabled=True,
        face_identification_enabled=False,
    )
    await module.initialize()
    try:
        await module._handle_audition_event(_speaker_embedding_event([0.1] * 192))

        assert "live_mic" in module._identity_cache
        agent_id = module._identity_cache["live_mic"]
        assert agent_id.startswith("person:")

        model = await store.get(agent_id)
        assert model is not None
        assert model.voice_centroid is not None
        assert model.face_centroid is None
        assert model.binding_state == "voice_only"
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_voice_only_no_vision_consumer_task(bus):
    store = InMemoryAgentStore()
    module = SocialCognition(
        bus,
        store=store,
        speaker_identification_enabled=True,
        face_identification_enabled=False,
    )
    await module.initialize()
    try:
        task_names = [t.get_name() for t in module._tasks]
        assert "social-cognition-audition-consumer" in task_names
        assert "social-cognition-vision-consumer" not in task_names
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_voice_only_speaker_embedding_ignored_when_disabled(bus):
    store = InMemoryAgentStore()
    module = SocialCognition(
        bus,
        store=store,
        speaker_identification_enabled=False,
        face_identification_enabled=False,
    )
    await module.initialize()
    try:
        await module._handle_audition_event(_speaker_embedding_event([0.1] * 192))
        assert not module._identity_cache
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_voice_only_emotion_uses_identity_cache(bus):
    store = InMemoryAgentStore()
    module = SocialCognition(
        bus,
        store=store,
        speaker_identification_enabled=True,
        face_identification_enabled=False,
    )
    await module.initialize()
    try:
        await module._handle_audition_event(_speaker_embedding_event([0.1] * 192))
        agent_id = module._identity_cache["live_mic"]

        await module._handle_audition_event(_emotion_event("happy", source_label="live_mic"))

        model = await store.get(agent_id)
        assert model is not None
        assert model.interaction_count >= 1
        assert model.emotion_histogram.get("happy", 0.0) > 0.0
    finally:
        await module.shutdown()


# ---------------------------------------------------------------------------
# Face-only (speaker_identification_enabled=False, face_identification_enabled=True)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_face_only_mints_agent_with_face_data(bus):
    store = InMemoryAgentStore()
    module = SocialCognition(
        bus,
        store=store,
        speaker_identification_enabled=False,
        face_identification_enabled=True,
    )
    await module.initialize()
    try:
        await module._handle_face_detection(
            _face_detection_event([{"embedding": [0.2] * 128, "confidence": 0.9}])
        )

        all_profiles = await store.all_profiles()
        person_agents = [
            aid for aid in all_profiles if aid.startswith("person:")
        ]
        assert len(person_agents) >= 1

        model = await store.get(person_agents[0])
        assert model is not None
        assert model.face_centroid is not None
        assert model.voice_centroid is None
        assert model.binding_state == "face_only"
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_face_only_has_vision_consumer_task(bus):
    store = InMemoryAgentStore()
    module = SocialCognition(
        bus,
        store=store,
        speaker_identification_enabled=False,
        face_identification_enabled=True,
    )
    await module.initialize()
    try:
        task_names = [t.get_name() for t in module._tasks]
        assert "social-cognition-audition-consumer" in task_names
        assert "social-cognition-vision-consumer" in task_names
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_face_only_speaker_embedding_ignored(bus):
    store = InMemoryAgentStore()
    module = SocialCognition(
        bus,
        store=store,
        speaker_identification_enabled=False,
        face_identification_enabled=True,
    )
    await module.initialize()
    try:
        await module._handle_audition_event(_speaker_embedding_event([0.1] * 192))
        assert not module._identity_cache
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_face_only_emotion_defaults_to_operator(bus):
    store = InMemoryAgentStore()
    module = SocialCognition(
        bus,
        store=store,
        speaker_identification_enabled=False,
        face_identification_enabled=True,
    )
    await module.initialize()
    try:
        await module._handle_audition_event(_emotion_event("happy", source_label="live_mic"))

        model = await store.get("operator")
        assert model is not None
        assert model.interaction_count >= 1

        all_profiles = await store.all_profiles()
        person_agents = [aid for aid in all_profiles if aid.startswith("person:")]
        assert len(person_agents) == 0
    finally:
        await module.shutdown()
