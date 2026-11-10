# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Backwards compatibility: deserialize agent profiles from before identity-binding fields existed."""
from __future__ import annotations

import json

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.social_cognition.agent import AgentModel, EMOTION_CATEGORIES
from kaine.modules.social_cognition.module import SocialCognition
from kaine.modules.social_cognition.store import InMemoryAgentStore


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _legacy_profile(agent_id: str = "legacy-agent", **overrides) -> dict:
    profile = {
        "id": agent_id,
        "label": "Legacy Agent",
        "emotion_histogram": {"happy": 0.6, "sad": 0.4},
        "behavioral_summary": {"mean_confidence": 0.42},
        "reliability": 0.75,
        "interaction_count": 5,
        "first_seen": 100.0,
        "last_seen": 200.0,
    }
    profile.update(overrides)
    return profile


def _identity_profile(agent_id: str = "identity-agent") -> dict:
    profile = _legacy_profile(agent_id=agent_id, label="Identity Agent")
    profile.update(
        {
            "voice_centroid": [0.1] * 192,
            "face_centroid": [0.2] * 128,
            "voice_exemplars": [
                {"embedding": [0.1] * 192, "timestamp": 100.0},
                {"embedding": [0.15] * 192, "timestamp": 110.0},
            ],
            "face_exemplars": [
                {"embedding": [0.2] * 128, "timestamp": 105.0},
            ],
            "voice_sample_count": 3,
            "face_sample_count": 2,
            "binding_state": "bound",
            "binding_confidence": 0.87,
            "voice_reliability": 0.91,
            "face_reliability": 0.83,
            "voice_acoustic_embedding": [0.7] * 192,
        }
    )
    return profile


def _assert_legacy_defaults(model: AgentModel) -> None:
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
    assert model.voice_acoustic_embedding is None


# ---------------------------------------------------------------------------
# AgentModel.from_dict with legacy data
# ---------------------------------------------------------------------------


def test_agentmodel_from_dict_legacy_defaults():
    model = AgentModel.from_dict(_legacy_profile())

    assert model.id == "legacy-agent"
    assert model.label == "Legacy Agent"
    assert model.emotion_histogram == {"happy": 0.6, "sad": 0.4}
    assert model.behavioral_summary == {"mean_confidence": 0.42}
    assert model.reliability == 0.75
    assert model.interaction_count == 5
    assert model.first_seen == 100.0
    assert model.last_seen == 200.0

    _assert_legacy_defaults(model)


def test_agentmodel_legacy_functions_and_roundtrip():
    model = AgentModel.from_dict(_legacy_profile())

    model.update_from_emotion("happy", confidence=0.8)

    familiarity = model.familiarity()
    assert isinstance(familiarity, float)
    assert 0.0 <= familiarity <= 1.0

    rebuilt = AgentModel.from_dict(model.to_dict())
    assert rebuilt.id == model.id
    assert rebuilt.label == model.label
    assert rebuilt.interaction_count == model.interaction_count
    assert rebuilt.reliability == pytest.approx(model.reliability)
    _assert_legacy_defaults(rebuilt)


# ---------------------------------------------------------------------------
# InMemoryAgentStore deserialization of legacy JSON
# ---------------------------------------------------------------------------


def test_inmemory_store_deserializes_legacy_json():
    store = InMemoryAgentStore()
    payload = {"legacy-agent": _legacy_profile()}
    store.deserialize(json.dumps(payload).encode("utf-8"))

    assert "legacy-agent" in store._profiles
    model = store._profiles["legacy-agent"]
    assert model.id == "legacy-agent"
    _assert_legacy_defaults(model)


def test_inmemory_store_mixed_legacy_and_identity_profiles():
    store = InMemoryAgentStore()
    payload = {
        "legacy-agent": _legacy_profile(),
        "identity-agent": _identity_profile(),
    }
    store.deserialize(json.dumps(payload).encode("utf-8"))

    assert set(store._profiles) == {"legacy-agent", "identity-agent"}

    _assert_legacy_defaults(store._profiles["legacy-agent"])

    identity_model = store._profiles["identity-agent"]
    assert identity_model.voice_centroid == [0.1] * 192
    assert identity_model.face_centroid == [0.2] * 128
    assert identity_model.voice_sample_count == 3
    assert identity_model.face_sample_count == 2
    assert identity_model.binding_state == "bound"
    assert identity_model.binding_confidence == 0.87
    assert identity_model.voice_reliability == 0.91
    assert identity_model.face_reliability == 0.83
    assert identity_model.voice_acoustic_embedding == [0.7] * 192


# ---------------------------------------------------------------------------
# SocialCognition.import_preservation_state with legacy profiles
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_import_preservation_state_legacy(bus):
    store = InMemoryAgentStore()
    sc = SocialCognition(bus, store=store)
    await sc.initialize()
    try:
        state = {"profiles": {"legacy-agent": _legacy_profile()}}
        count = await sc.import_preservation_state(state)

        assert count == 1
        model = await store.get("legacy-agent")
        assert model is not None
        assert model.id == "legacy-agent"
        _assert_legacy_defaults(model)
    finally:
        await sc.shutdown()


@pytest.mark.asyncio
async def test_import_preservation_state_mixed(bus):
    store = InMemoryAgentStore()
    sc = SocialCognition(bus, store=store)
    await sc.initialize()
    try:
        state = {
            "profiles": {
                "legacy-agent": _legacy_profile(),
                "identity-agent": _identity_profile(),
            }
        }
        count = await sc.import_preservation_state(state)

        assert count == 2
        legacy = await store.get("legacy-agent")
        assert legacy is not None
        _assert_legacy_defaults(legacy)
        identity = await store.get("identity-agent")
        assert identity is not None
        assert identity.binding_state == "bound"
    finally:
        await sc.shutdown()
