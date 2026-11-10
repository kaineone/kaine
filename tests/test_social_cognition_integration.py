# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""End-to-end integration: all identity pipelines enabled, cross-modal merge."""
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
    }
    if source_label is not None:
        payload["source_label"] = source_label
    return Event(
        source="audition",
        type="audition.emotion",
        payload=payload,
        salience=0.4,
        timestamp=datetime.now(timezone.utc),
    )


VOICE_EMB = [0.1] * 192
FACE_EMB = [0.2] * 128


@pytest.mark.asyncio
async def test_end_to_end_identity_pipeline(bus):
    """Enable all pipelines, mint agents by voice and face, merge via co-occurrence."""
    store = InMemoryAgentStore()
    module = SocialCognition(
        bus,
        store=store,
        speaker_identification_enabled=True,
        face_identification_enabled=True,
        co_occurrence_window_s=3.0,
        binding_merge_threshold=0.75,
        p_common_prior=0.7,
    )
    await module.initialize()
    try:
        # --- Step 1: voice embedding mints a person:XXXX agent ---
        await module._handle_audition_event(_speaker_embedding_event(VOICE_EMB))
        voice_agent_id = module._identity_cache.get("live_mic")
        assert voice_agent_id is not None
        assert voice_agent_id.startswith("person:")

        voice_model = await store.get(voice_agent_id)
        assert voice_model is not None
        assert voice_model.voice_centroid is not None
        assert voice_model.face_centroid is None

        # --- Step 2: face detection mints a second agent ---
        await module._handle_face_detection(
            _face_detection_event([{"embedding": FACE_EMB, "confidence": 0.9}])
        )

        all_profiles = await store.all_profiles()
        face_agents = [
            aid for aid in all_profiles if aid != voice_agent_id and aid.startswith("person:")
        ]
        assert len(face_agents) >= 1
        face_agent_id = face_agents[0]

        face_model = await store.get(face_agent_id)
        assert face_model is not None
        assert face_model.face_centroid is not None
        assert face_model.voice_centroid is None

        # --- Step 3: repeated co-occurrences trigger binding merge ---
        for _ in range(20):
            await module._handle_audition_event(
                _speaker_embedding_event(VOICE_EMB, confidence=0.9)
            )
            await module._handle_face_detection(
                _face_detection_event([{"embedding": FACE_EMB, "confidence": 0.9}])
            )
            if module._merged_into:
                break

        assert module._merged_into, "cross-modal merge never triggered"
        gone_id, kept_id = next(iter(module._merged_into.items()))
        assert {gone_id, kept_id} == {voice_agent_id, face_agent_id}

        # The identity cache should point to the surviving agent.
        assert module._identity_cache.get("live_mic") == kept_id

        # The kept agent has both modalities.
        kept_model = await store.get(kept_id)
        assert kept_model is not None
        assert kept_model.binding_state == "bound"
        assert kept_model.voice_centroid is not None
        assert kept_model.face_centroid is not None

        # The gone agent was deleted from the store.
        assert await store.get(gone_id) is None

        # --- Step 4: familiarity increases with more observations ---
        fam_before = kept_model.familiarity()
        for _ in range(5):
            await module._handle_audition_event(
                _speaker_embedding_event(VOICE_EMB, confidence=0.9)
            )
        kept_model = await store.get(kept_id)
        fam_after = kept_model.familiarity()
        assert fam_after >= fam_before

        # --- Step 5: emotion events attributed through identity cache ---
        await module._handle_audition_event(
            _emotion_event("happy", confidence=0.8, source_label="live_mic")
        )
        kept_model = await store.get(kept_id)
        assert kept_model.interaction_count > 0
        assert kept_model.emotion_histogram.get("happy", 0.0) > 0.0

        # --- Step 6: correct event types published ---
        entries = await bus.read("social_cognition.out", last_id="0")
        events = [e for _, e in entries]
        published_types = {e.type for e in events}
        assert "social_cognition.agent_model" in published_types
        assert "social_cognition.identity_update" in published_types

        identity_updates = [e for e in events if e.type == "social_cognition.identity_update"]
        assert any(e.payload.get("agent_id") == kept_id for e in identity_updates)
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_familiarity_monotonically_increases_during_identity_pipeline(bus):
    """Familiarity should grow as voice observations accumulate."""
    store = InMemoryAgentStore()
    module = SocialCognition(
        bus,
        store=store,
        speaker_identification_enabled=True,
        face_identification_enabled=False,
    )
    await module.initialize()
    try:
        await module._handle_audition_event(_speaker_embedding_event(VOICE_EMB))
        agent_id = module._identity_cache["live_mic"]
        model = await store.get(agent_id)
        fam_1 = model.familiarity()

        for _ in range(20):
            await module._handle_audition_event(_speaker_embedding_event(VOICE_EMB))

        model = await store.get(agent_id)
        fam_20 = model.familiarity()
        assert fam_20 > fam_1
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_published_events_carry_correct_payloads(bus):
    """agent_model and identity_update events have the expected payload fields."""
    store = InMemoryAgentStore()
    module = SocialCognition(
        bus,
        store=store,
        speaker_identification_enabled=True,
        face_identification_enabled=True,
    )
    await module.initialize()
    try:
        await module._handle_audition_event(_speaker_embedding_event(VOICE_EMB))
        await module._handle_face_detection(
            _face_detection_event([{"embedding": FACE_EMB, "confidence": 0.9}])
        )
        await module._handle_audition_event(_emotion_event("happy", source_label="live_mic"))

        entries = await bus.read("social_cognition.out", last_id="0")
        events = [e for _, e in entries]

        for e in events:
            if e.type == "social_cognition.identity_update":
                assert "agent_id" in e.payload
                assert "modality" in e.payload
                assert "confidence" in e.payload
                assert "is_new" in e.payload
                assert "binding_confidence" in e.payload
            elif e.type == "social_cognition.agent_model":
                assert "agent_id" in e.payload
                assert "familiarity" in e.payload
                assert "reliability" in e.payload
                assert "interaction_count" in e.payload
    finally:
        await module.shutdown()
