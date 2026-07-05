# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for EmpatheiaMergeStrategy — fork/merge semantics."""
from __future__ import annotations

import pytest

from kaine.modules.empatheia.agent import AgentModel, EMOTION_CATEGORIES
from kaine.modules.empatheia.store import (
    EmpatheiaMergeStrategy,
    InMemoryAgentStore,
    apply_merged_state,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model(agent_id: str, categories: list[str], n: int = 5) -> AgentModel:
    model = AgentModel(id=agent_id, label=agent_id.capitalize())
    for i in range(n):
        model.update_from_emotion(categories[i % len(categories)], confidence=0.8)
    return model


def _store_snapshot(*models: AgentModel) -> dict:
    """Build the state dict that EmpatheiaMergeStrategy.merge expects."""
    return {"profiles": {m.id: m.to_dict() for m in models}}


# ---------------------------------------------------------------------------
# Merge: interaction count
# ---------------------------------------------------------------------------


def test_merged_interaction_count_is_sum():
    strategy = EmpatheiaMergeStrategy()
    model_a = _make_model("alice", ["happy"], n=3)
    model_b = _make_model("alice", ["sad"], n=5)
    state_a = _store_snapshot(model_a)
    state_b = _store_snapshot(model_b)
    merged = strategy.merge(state_a, state_b)
    alice = merged["profiles"]["alice"]
    assert alice["interaction_count"] == 8  # 3 + 5


def test_merged_interaction_count_ge_max_of_two():
    strategy = EmpatheiaMergeStrategy()
    for n_a, n_b in [(1, 10), (10, 1), (7, 7)]:
        model_a = _make_model("bob", ["neutral"], n=n_a)
        model_b = _make_model("bob", ["neutral"], n=n_b)
        state_a = _store_snapshot(model_a)
        state_b = _store_snapshot(model_b)
        merged = strategy.merge(state_a, state_b)
        count = merged["profiles"]["bob"]["interaction_count"]
        assert count >= max(n_a, n_b), f"n_a={n_a} n_b={n_b} merged={count}"


# ---------------------------------------------------------------------------
# Merge: histogram weighted average
# ---------------------------------------------------------------------------


def test_merged_histogram_is_weighted_average():
    strategy = EmpatheiaMergeStrategy()
    # Fork A: only "happy" (3 observations).
    model_a = _make_model("carol", ["happy"], n=3)
    # Fork B: only "sad" (6 observations).
    model_b = _make_model("carol", ["sad"], n=6)
    state_a = _store_snapshot(model_a)
    state_b = _store_snapshot(model_b)
    merged = strategy.merge(state_a, state_b)
    hist = merged["profiles"]["carol"]["emotion_histogram"]

    # Weights: w_a = 3/9 = 1/3, w_b = 6/9 = 2/3.
    # Expected "happy" ≈ w_a * model_a.emotion_histogram["happy"] + w_b * 0
    expected_happy = (
        (3 / 9) * model_a.emotion_histogram.get("happy", 0.0)
        + (6 / 9) * model_b.emotion_histogram.get("happy", 0.0)
    )
    expected_sad = (
        (3 / 9) * model_a.emotion_histogram.get("sad", 0.0)
        + (6 / 9) * model_b.emotion_histogram.get("sad", 0.0)
    )
    assert hist.get("happy", 0.0) == pytest.approx(expected_happy, abs=1e-9)
    assert hist.get("sad", 0.0) == pytest.approx(expected_sad, abs=1e-9)


def test_histogram_values_non_negative_after_merge():
    strategy = EmpatheiaMergeStrategy()
    model_a = _make_model("dave", ["angry", "fearful"], n=4)
    model_b = _make_model("dave", ["happy", "neutral"], n=6)
    merged = strategy.merge(_store_snapshot(model_a), _store_snapshot(model_b))
    hist = merged["profiles"]["dave"]["emotion_histogram"]
    for val in hist.values():
        assert val >= 0.0


# ---------------------------------------------------------------------------
# Merge: one-sided (agent only in one fork)
# ---------------------------------------------------------------------------


def test_merge_agent_only_in_fork_a():
    strategy = EmpatheiaMergeStrategy()
    model_a = _make_model("eve", ["happy"], n=5)
    state_a = _store_snapshot(model_a)
    state_b: dict = {"profiles": {}}
    merged = strategy.merge(state_a, state_b)
    assert "eve" in merged["profiles"]
    assert merged["profiles"]["eve"]["interaction_count"] == 5


def test_merge_agent_only_in_fork_b():
    strategy = EmpatheiaMergeStrategy()
    model_b = _make_model("frank", ["sad"], n=4)
    state_a: dict = {"profiles": {}}
    state_b = _store_snapshot(model_b)
    merged = strategy.merge(state_a, state_b)
    assert "frank" in merged["profiles"]
    assert merged["profiles"]["frank"]["interaction_count"] == 4


def test_merge_both_none_returns_empty():
    strategy = EmpatheiaMergeStrategy()
    merged = strategy.merge(None, None)
    assert merged == {}


def test_merge_one_none_returns_other():
    strategy = EmpatheiaMergeStrategy()
    model = _make_model("grace", ["happy"], n=3)
    state = _store_snapshot(model)
    merged_a = strategy.merge(state, None)
    assert "profiles" in merged_a
    merged_b = strategy.merge(None, state)
    assert "profiles" in merged_b


# ---------------------------------------------------------------------------
# Persist merged profiles to store
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_merged_profile_persisted_to_store():
    strategy = EmpatheiaMergeStrategy()
    model_a = _make_model("henry", ["happy"], n=3)
    model_b = _make_model("henry", ["sad"], n=7)
    merged_state = strategy.merge(_store_snapshot(model_a), _store_snapshot(model_b))

    store = InMemoryAgentStore()
    await store.initialize()
    await apply_merged_state(store, merged_state)

    recovered = await store.get("henry")
    assert recovered is not None
    assert recovered.interaction_count == 10  # 3 + 7


@pytest.mark.asyncio
async def test_all_agents_persisted_after_merge():
    strategy = EmpatheiaMergeStrategy()
    # Fork A has "alice"; fork B has "bob"; both have "carol".
    carol_a = _make_model("carol", ["happy"], n=2)
    carol_b = _make_model("carol", ["sad"], n=3)
    state_a = _store_snapshot(_make_model("alice", ["happy"], n=4), carol_a)
    state_b = _store_snapshot(_make_model("bob", ["sad"], n=6), carol_b)
    merged_state = strategy.merge(state_a, state_b)

    store = InMemoryAgentStore()
    await store.initialize()
    await apply_merged_state(store, merged_state)

    ids = await store.all_ids()
    assert set(ids) == {"alice", "bob", "carol"}
    carol = await store.get("carol")
    assert carol is not None
    assert carol.interaction_count == 5  # 2 + 3
