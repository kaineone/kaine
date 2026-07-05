# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for AgentModel — familiarity, histogram updates, and update rules."""
from __future__ import annotations

import math

import pytest

from kaine.modules.empatheia.agent import AgentModel, EMOTION_CATEGORIES


# ---------------------------------------------------------------------------
# Familiarity
# ---------------------------------------------------------------------------


def test_familiarity_zero_on_fresh_model():
    model = AgentModel(id="alice", label="Alice")
    assert model.familiarity() == pytest.approx(0.0)


def test_familiarity_rises_with_interaction_count():
    model = AgentModel(id="alice", label="Alice")
    fam_before = model.familiarity()
    model.update_from_emotion("happy", confidence=0.8)
    fam_after_one = model.familiarity()
    assert fam_after_one > fam_before

    for _ in range(50):
        model.update_from_emotion("happy", confidence=0.8)
    fam_after_many = model.familiarity()
    assert fam_after_many > fam_after_one


def test_familiarity_is_monotonically_non_decreasing_with_interactions():
    model = AgentModel(id="bob", label="Bob")
    previous = 0.0
    for _ in range(100):
        model.update_from_emotion("neutral", confidence=0.5)
        current = model.familiarity()
        assert current >= previous
        previous = current


def test_familiarity_in_range():
    model = AgentModel(id="carol", label="Carol")
    for _ in range(500):
        model.update_from_emotion("happy", confidence=1.0)
    fam = model.familiarity()
    assert 0.0 <= fam <= 1.0


def test_familiarity_grows_with_category_coverage():
    """Observing more distinct emotion categories increases model coverage."""
    model_narrow = AgentModel(id="d1", label="D1")
    model_broad = AgentModel(id="d2", label="D2")
    # Same interaction count, different category coverage.
    for _ in range(10):
        model_narrow.update_from_emotion("happy", confidence=0.9)
    for cat in EMOTION_CATEGORIES:
        model_broad.update_from_emotion(cat, confidence=0.9)
    # model_broad has more category coverage → higher familiarity.
    assert model_broad.familiarity() > model_narrow.familiarity()


# ---------------------------------------------------------------------------
# Histogram updates
# ---------------------------------------------------------------------------


def test_first_emotion_sets_histogram_entry():
    model = AgentModel(id="eve", label="Eve")
    model.update_from_emotion("happy", confidence=0.9)
    assert model.emotion_histogram.get("happy", 0.0) > 0.0


def test_histogram_covers_all_categories_after_update():
    model = AgentModel(id="frank", label="Frank")
    model.update_from_emotion("sad", confidence=0.7)
    # After one update every category should have a key (EMA initialises all).
    for cat in EMOTION_CATEGORIES:
        assert cat in model.emotion_histogram


def test_repeated_same_category_raises_its_histogram_value():
    model = AgentModel(id="grace", label="Grace")
    for _ in range(20):
        model.update_from_emotion("angry", confidence=0.9)
    assert model.emotion_histogram["angry"] > model.emotion_histogram.get("happy", 0.0)


def test_histogram_values_are_non_negative():
    model = AgentModel(id="henry", label="Henry")
    for cat in ["happy", "sad", "angry", "neutral", "fearful"]:
        model.update_from_emotion(cat, confidence=0.5)
    for val in model.emotion_histogram.values():
        assert val >= 0.0


# ---------------------------------------------------------------------------
# Behavioral summary / reliability
# ---------------------------------------------------------------------------


def test_behavioral_summary_populated_after_update():
    model = AgentModel(id="iris", label="Iris")
    model.update_from_emotion("happy", confidence=0.8, prediction_error=0.1)
    assert "mean_confidence" in model.behavioral_summary
    assert "mean_prediction_error" in model.behavioral_summary


def test_interaction_count_increments():
    model = AgentModel(id="jack", label="Jack")
    assert model.interaction_count == 0
    model.update_from_emotion("neutral", confidence=0.5)
    assert model.interaction_count == 1
    model.update_from_emotion("happy", confidence=0.5)
    assert model.interaction_count == 2


def test_reliability_starts_at_one():
    model = AgentModel(id="kate", label="Kate")
    assert model.reliability == pytest.approx(1.0)


def test_large_deviation_decays_reliability():
    model = AgentModel(id="liam", label="Liam")
    # Build up a "neutral" model first.
    for _ in range(10):
        model.update_from_emotion("neutral", confidence=1.0)
    reliability_before = model.reliability
    # Suddenly observe an extreme out-of-character emotion with high confidence.
    for _ in range(10):
        model.update_from_emotion("angry", confidence=1.0, deviation_threshold=0.1)
    assert model.reliability < reliability_before


# ---------------------------------------------------------------------------
# Serialization roundtrip
# ---------------------------------------------------------------------------


def test_to_dict_from_dict_roundtrip():
    model = AgentModel(id="mia", label="Mia")
    for cat in ["happy", "neutral", "sad"]:
        model.update_from_emotion(cat, confidence=0.7, prediction_error=0.05)
    d = model.to_dict()
    recovered = AgentModel.from_dict(d)
    assert recovered.id == model.id
    assert recovered.label == model.label
    assert recovered.interaction_count == model.interaction_count
    assert recovered.reliability == pytest.approx(model.reliability)
    for cat in EMOTION_CATEGORIES:
        assert recovered.emotion_histogram.get(cat, 0.0) == pytest.approx(
            model.emotion_histogram.get(cat, 0.0)
        )
