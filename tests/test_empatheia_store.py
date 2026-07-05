# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for AgentStore — InMemoryAgentStore, serialize/deserialize, protocol."""
from __future__ import annotations

import json

import pytest

from kaine.modules.empatheia.agent import AgentModel, EMOTION_CATEGORIES
from kaine.modules.empatheia.store import AgentStore, InMemoryAgentStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model(agent_id: str = "alice", n_observations: int = 5) -> AgentModel:
    model = AgentModel(id=agent_id, label=agent_id.capitalize())
    cats = list(EMOTION_CATEGORIES)
    for i in range(n_observations):
        model.update_from_emotion(cats[i % len(cats)], confidence=0.7)
    return model


# ---------------------------------------------------------------------------
# InMemoryAgentStore roundtrip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_put_then_get_returns_same_model():
    store = InMemoryAgentStore()
    await store.initialize()
    model = _make_model("alice")
    await store.put(model)
    recovered = await store.get("alice")
    assert recovered is not None
    assert recovered.id == "alice"
    assert recovered.interaction_count == model.interaction_count


@pytest.mark.asyncio
async def test_get_missing_returns_none():
    store = InMemoryAgentStore()
    await store.initialize()
    assert await store.get("nobody") is None


@pytest.mark.asyncio
async def test_all_ids_reflects_stored_agents():
    store = InMemoryAgentStore()
    await store.initialize()
    for agent_id in ["alice", "bob", "carol"]:
        await store.put(_make_model(agent_id))
    ids = await store.all_ids()
    assert set(ids) == {"alice", "bob", "carol"}


@pytest.mark.asyncio
async def test_put_overwrites_existing():
    store = InMemoryAgentStore()
    await store.initialize()
    model = _make_model("alice", n_observations=3)
    await store.put(model)
    model.update_from_emotion("happy", confidence=0.9)
    await store.put(model)
    recovered = await store.get("alice")
    assert recovered is not None
    assert recovered.interaction_count == 4


# ---------------------------------------------------------------------------
# Serialize / deserialize round-trip (lossless)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serialize_deserialize_lossless():
    store = InMemoryAgentStore()
    await store.initialize()
    model = _make_model("alice", n_observations=10)
    await store.put(model)

    data = store.serialize()
    assert isinstance(data, bytes)

    new_store = InMemoryAgentStore()
    new_store.deserialize(data)

    recovered = await new_store.get("alice")
    assert recovered is not None
    assert recovered.id == model.id
    assert recovered.interaction_count == model.interaction_count
    assert recovered.reliability == pytest.approx(model.reliability)
    for cat in EMOTION_CATEGORIES:
        assert recovered.emotion_histogram.get(cat, 0.0) == pytest.approx(
            model.emotion_histogram.get(cat, 0.0), abs=1e-9
        )


@pytest.mark.asyncio
async def test_serialize_deserialize_multiple_agents():
    store = InMemoryAgentStore()
    await store.initialize()
    for agent_id in ["alice", "bob", "carol"]:
        await store.put(_make_model(agent_id))

    data = store.serialize()
    new_store = InMemoryAgentStore()
    new_store.deserialize(data)

    ids = await new_store.all_ids()
    assert set(ids) == {"alice", "bob", "carol"}
    for agent_id in ["alice", "bob", "carol"]:
        recovered = await new_store.get(agent_id)
        assert recovered is not None


@pytest.mark.asyncio
async def test_serialize_empty_store():
    store = InMemoryAgentStore()
    await store.initialize()
    data = store.serialize()
    assert json.loads(data.decode()) == {}


@pytest.mark.asyncio
async def test_deserialize_empty_bytes():
    store = InMemoryAgentStore()
    await store.initialize()
    store.deserialize(b"{}")
    ids = await store.all_ids()
    assert ids == []


# ---------------------------------------------------------------------------
# Protocol satisfaction
# ---------------------------------------------------------------------------


def test_inmemory_store_satisfies_protocol():
    store = InMemoryAgentStore()
    assert isinstance(store, AgentStore)


def test_protocol_requires_serialize():
    assert hasattr(InMemoryAgentStore, "serialize")
    assert hasattr(InMemoryAgentStore, "deserialize")
