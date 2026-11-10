# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Preservation round-trip for social cognition agent profiles with embeddings."""
from __future__ import annotations

import pytest

from kaine.modules.social_cognition.agent import AgentModel
from kaine.modules.social_cognition.store import InMemoryAgentStore


def _make_agent_with_embeddings() -> AgentModel:
    """Create an agent with voice and face embeddings for testing."""
    model = AgentModel(id="test-agent", label="Test Agent")
    model.voice_centroid = [0.1] * 192
    model.face_centroid = [0.2] * 128
    model.voice_exemplars = [
        {"embedding": [0.11] * 192, "timestamp": 1000.0},
        {"embedding": [0.12] * 192, "timestamp": 1001.0},
    ]
    model.face_exemplars = [
        {"embedding": [0.21] * 128, "timestamp": 1000.0},
    ]
    model.voice_sample_count = 2
    model.face_sample_count = 1
    model.binding_state = "voice_only"
    model.binding_confidence = 0.75
    model.voice_reliability = 0.9
    model.face_reliability = 0.8
    model.interaction_count = 10
    model.emotion_histogram = {"happy": 0.4, "neutral": 0.6}
    return model


def _make_legacy_agent() -> dict:
    """Agent profile dict from before identity binding (no embedding fields)."""
    return {
        "id": "legacy-agent",
        "label": "Legacy Agent",
        "emotion_histogram": {"neutral": 1.0},
        "behavioral_summary": {"mean_confidence": 0.5},
        "reliability": 0.95,
        "interaction_count": 50,
        "first_seen": 1000.0,
        "last_seen": 2000.0,
    }


def test_agent_model_round_trip_with_embeddings():
    """to_dict/from_dict preserves all embedding fields."""
    original = _make_agent_with_embeddings()
    restored = AgentModel.from_dict(original.to_dict())

    assert restored.id == original.id
    assert restored.voice_centroid == original.voice_centroid
    assert restored.face_centroid == original.face_centroid
    assert len(restored.voice_exemplars) == len(original.voice_exemplars)
    assert len(restored.face_exemplars) == len(original.face_exemplars)
    assert restored.voice_sample_count == original.voice_sample_count
    assert restored.face_sample_count == original.face_sample_count
    assert restored.binding_state == original.binding_state
    assert restored.binding_confidence == original.binding_confidence
    assert restored.voice_reliability == original.voice_reliability
    assert restored.face_reliability == original.face_reliability


def test_legacy_agent_deserializes_with_defaults():
    """Agent profiles from before this change load with absent defaults."""
    model = AgentModel.from_dict(_make_legacy_agent())

    assert model.id == "legacy-agent"
    assert model.interaction_count == 50
    assert model.voice_centroid is None
    assert model.face_centroid is None
    assert model.voice_exemplars == []
    assert model.face_exemplars == []
    assert model.voice_sample_count == 0
    assert model.face_sample_count == 0
    assert model.binding_state == "unbound"
    assert model.binding_confidence is None
    assert model.voice_reliability is None
    assert model.face_reliability is None


@pytest.mark.asyncio
async def test_preservation_round_trip_with_embeddings():
    """Store-level export/import preserves embeddings."""
    store = InMemoryAgentStore()
    await store.initialize()

    original = _make_agent_with_embeddings()
    await store.put(original)

    profiles = await store.all_profiles()
    state = {"profiles": {aid: m.to_dict() for aid, m in profiles.items()}}

    store2 = InMemoryAgentStore()
    await store2.initialize()
    models = [AgentModel.from_dict(d) for d in state["profiles"].values()]
    await store2.replace_all(models)

    restored = await store2.get("test-agent")
    assert restored is not None
    assert restored.voice_centroid == original.voice_centroid
    assert restored.face_centroid == original.face_centroid
    assert len(restored.voice_exemplars) == 2
    assert len(restored.face_exemplars) == 1
    assert restored.binding_state == "voice_only"
    assert restored.binding_confidence == 0.75
    assert restored.voice_reliability == 0.9
    assert restored.face_reliability == 0.8
    assert restored.familiarity() > 0.0
