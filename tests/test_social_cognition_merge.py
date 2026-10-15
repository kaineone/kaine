# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for SocialCognitionMergeStrategy — fork/merge semantics."""
from __future__ import annotations

import pytest

from kaine.lifecycle.strategies import SocialCognitionMergeStrategy
from kaine.modules.social_cognition.agent import AgentModel

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_model(agent_id: str, categories: list[str], n: int = 5) -> AgentModel:
    model = AgentModel(id=agent_id, label=agent_id.capitalize())
    for i in range(n):
        model.update_from_emotion(categories[i % len(categories)], confidence=0.8)
    return model


def _store_snapshot(*models: AgentModel) -> dict:
    """Build the state dict that SocialCognitionMergeStrategy.merge expects."""
    return {"profiles": {m.id: m.to_dict() for m in models}}


# ---------------------------------------------------------------------------
# Merge: interaction count
# ---------------------------------------------------------------------------


def test_merged_interaction_count_is_sum():
    strategy = SocialCognitionMergeStrategy()
    model_a = _make_model("alice", ["happy"], n=3)
    model_b = _make_model("alice", ["sad"], n=5)
    state_a = _store_snapshot(model_a)
    state_b = _store_snapshot(model_b)
    merged = strategy.merge(state_a, state_b)
    alice = merged["profiles"]["alice"]
    assert alice["interaction_count"] == 8  # 3 + 5


def test_merged_interaction_count_ge_max_of_two():
    strategy = SocialCognitionMergeStrategy()
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
    strategy = SocialCognitionMergeStrategy()
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
    strategy = SocialCognitionMergeStrategy()
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
    strategy = SocialCognitionMergeStrategy()
    model_a = _make_model("eve", ["happy"], n=5)
    state_a = _store_snapshot(model_a)
    state_b: dict = {"profiles": {}}
    merged = strategy.merge(state_a, state_b)
    assert "eve" in merged["profiles"]
    assert merged["profiles"]["eve"]["interaction_count"] == 5


def test_merge_agent_only_in_fork_b():
    strategy = SocialCognitionMergeStrategy()
    model_b = _make_model("frank", ["sad"], n=4)
    state_a: dict = {"profiles": {}}
    state_b = _store_snapshot(model_b)
    merged = strategy.merge(state_a, state_b)
    assert "frank" in merged["profiles"]
    assert merged["profiles"]["frank"]["interaction_count"] == 4


def test_merge_both_none_returns_empty():
    strategy = SocialCognitionMergeStrategy()
    merged = strategy.merge(None, None)
    assert merged == {}


def test_merge_one_none_returns_other():
    strategy = SocialCognitionMergeStrategy()
    model = _make_model("grace", ["happy"], n=3)
    state = _store_snapshot(model)
    merged_a = strategy.merge(state, None)
    assert "profiles" in merged_a
    merged_b = strategy.merge(None, state)
    assert "profiles" in merged_b


def test_merge_summary_missing_error_on_one_side_is_absent():
    strategy = SocialCognitionMergeStrategy()
    a = _make_model("x", ["happy"], n=3).to_dict()
    a["behavioral_summary"]["mean_prediction_error"] = 0.6
    b = _make_model("x", ["sad"], n=5).to_dict()
    del b["behavioral_summary"]["mean_prediction_error"]

    merged = strategy.merge(
        _store_snapshot(AgentModel(**a)), _store_snapshot(AgentModel(**b))
    )
    summary = merged["profiles"]["x"]["behavioral_summary"]
    assert summary["mean_prediction_error"] == pytest.approx(0.6)
    assert summary["mean_confidence"] == pytest.approx(0.8)


def test_merge_summary_none_error_is_absent():
    strategy = SocialCognitionMergeStrategy()
    a = _make_model("x", ["happy"], n=3).to_dict()
    a["behavioral_summary"]["mean_prediction_error"] = 0.6
    b = _make_model("x", ["sad"], n=5).to_dict()
    b["behavioral_summary"]["mean_prediction_error"] = None

    merged = strategy.merge(
        _store_snapshot(AgentModel(**a)), _store_snapshot(AgentModel(**b))
    )
    summary = merged["profiles"]["x"]["behavioral_summary"]
    assert summary["mean_prediction_error"] == pytest.approx(0.6)

    merged_swap = strategy.merge(
        _store_snapshot(AgentModel(**b)), _store_snapshot(AgentModel(**a))
    )
    assert (
        merged_swap["profiles"]["x"]["behavioral_summary"]["mean_prediction_error"]
        == pytest.approx(0.6)
    )


def test_merge_summary_error_absent_on_both_sides_stays_absent():
    strategy = SocialCognitionMergeStrategy()
    a = _make_model("x", ["happy"], n=3).to_dict()
    del a["behavioral_summary"]["mean_prediction_error"]
    b = _make_model("x", ["sad"], n=5).to_dict()
    b["behavioral_summary"]["mean_prediction_error"] = None

    merged = strategy.merge(
        _store_snapshot(AgentModel(**a)), _store_snapshot(AgentModel(**b))
    )
    assert "mean_prediction_error" not in merged["profiles"]["x"]["behavioral_summary"]


def test_merge_summary_both_defined_is_weighted():
    strategy = SocialCognitionMergeStrategy()
    a = _make_model("x", ["happy"], n=3).to_dict()
    a["behavioral_summary"]["mean_prediction_error"] = 0.2
    b = _make_model("x", ["sad"], n=5).to_dict()
    b["behavioral_summary"]["mean_prediction_error"] = 0.6

    merged = strategy.merge(
        _store_snapshot(AgentModel(**a)), _store_snapshot(AgentModel(**b))
    )
    summary = merged["profiles"]["x"]["behavioral_summary"]
    assert summary["mean_prediction_error"] == pytest.approx((3 * 0.2 + 5 * 0.6) / 8)


def test_merge_summary_zero_count_side_does_not_divide_by_zero():
    strategy = SocialCognitionMergeStrategy()
    a = _make_model("x", ["happy"], n=1).to_dict()
    a["interaction_count"] = 0
    a["behavioral_summary"]["mean_prediction_error"] = 0.4
    b = _make_model("x", ["sad"], n=5).to_dict()
    del b["behavioral_summary"]["mean_prediction_error"]

    merged = strategy.merge(
        _store_snapshot(AgentModel(**a)), _store_snapshot(AgentModel(**b))
    )
    summary = merged["profiles"]["x"]["behavioral_summary"]
    assert summary["mean_prediction_error"] == pytest.approx(0.4)
