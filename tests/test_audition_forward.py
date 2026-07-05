# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for kaine.modules.audition.forward.AuditoryForwardModel.

Covers:
- Predictor output shape
- Online step reduces error on a repeating pattern
- Unexpected tone raises salience
- Buffer is bounded
- Serialisation round-trip (weights only — no raw data)
- buffer_summary contains only numeric statistics
- Non-finite guard
- Suspend flag
"""
import math

import pytest

from kaine.modules.audition.forward import (
    AuditoryForwardModel,
    FEATURE_DIM,
    N_EMOTION_CATEGORIES,
    build_feature_vector,
)
from kaine.modules.audition.emotion import CATEGORIES


# ---------------------------------------------------------------------------
# Feature vector builder
# ---------------------------------------------------------------------------

def _neutral_scores() -> dict[str, float]:
    return {c: (1.0 if c == "neutral" else 0.0) for c in CATEGORIES}


def _happy_scores() -> dict[str, float]:
    return {c: (1.0 if c == "happy" else 0.0) for c in CATEGORIES}


def test_build_feature_vector_shape():
    scores = _neutral_scores()
    vec = build_feature_vector(scores, CATEGORIES, duration_s=0.5, mean_energy=0.3)
    assert len(vec) == FEATURE_DIM
    assert len(vec) == N_EMOTION_CATEGORIES + 2


def test_build_feature_vector_values():
    scores = _neutral_scores()
    vec = build_feature_vector(scores, CATEGORIES, duration_s=0.5, mean_energy=0.3)
    # Neutral slot should be 1.0
    neutral_idx = list(CATEGORIES).index("neutral")
    assert vec[neutral_idx] == pytest.approx(1.0)
    # duration and energy at the end
    assert vec[-2] == pytest.approx(0.5)
    assert vec[-1] == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# Construction and shape
# ---------------------------------------------------------------------------

def test_construction_defaults():
    model = AuditoryForwardModel()
    assert model.feature_dim == FEATURE_DIM
    assert model.units == 32
    assert model.auditory_buffer_size == 16


def test_invalid_construction_rejected():
    with pytest.raises(ValueError):
        AuditoryForwardModel(feature_dim=0)
    with pytest.raises(ValueError):
        AuditoryForwardModel(units=0)
    with pytest.raises(ValueError):
        AuditoryForwardModel(auditory_buffer_size=0)
    with pytest.raises(ValueError):
        AuditoryForwardModel(lr=0.0)


def test_predict_output_shape():
    model = AuditoryForwardModel(feature_dim=FEATURE_DIM, units=16, seed=0)
    vec = [0.1] * FEATURE_DIM
    pred = model.predict(vec)
    assert isinstance(pred, list)
    assert len(pred) == FEATURE_DIM
    assert all(isinstance(v, float) for v in pred)


def test_step_returns_zero_on_first_frame():
    model = AuditoryForwardModel(feature_dim=FEATURE_DIM, units=16, seed=0)
    err = model.step([0.5] * FEATURE_DIM)
    assert err == pytest.approx(0.0)


def test_step_returns_non_negative_float():
    model = AuditoryForwardModel(feature_dim=FEATURE_DIM, units=16, seed=0)
    model.step([0.5] * FEATURE_DIM)
    err = model.step([0.3] * FEATURE_DIM)
    assert isinstance(err, float)
    assert err >= 0.0


# ---------------------------------------------------------------------------
# Buffer is bounded
# ---------------------------------------------------------------------------

def test_buffer_is_bounded():
    buf_size = 4
    model = AuditoryForwardModel(feature_dim=FEATURE_DIM, units=16,
                                  auditory_buffer_size=buf_size, seed=0)
    for i in range(buf_size + 10):
        model.step([float(i) * 0.05] * FEATURE_DIM)
    assert len(model._buffer) <= buf_size


# ---------------------------------------------------------------------------
# Online learning: error should decrease on a repeating pattern
# ---------------------------------------------------------------------------

def test_online_step_reduces_error_on_repeating_pattern():
    """After many steps on a constant feature vector, prediction error decreases."""
    model = AuditoryForwardModel(
        feature_dim=FEATURE_DIM,
        units=32,
        auditory_buffer_size=4,
        lr=0.05,
        seed=42,
    )
    fixed_vec = [0.3] * FEATURE_DIM

    errors = []
    for _ in range(200):
        err = model.step(fixed_vec)
        errors.append(err)

    # Skip the first (always 0.0) frame.
    useful = errors[1:]
    early_mean = sum(useful[:20]) / 20
    late_mean = sum(useful[-20:]) / 20
    assert late_mean < early_mean, (
        f"Expected prediction error to decrease on a repeating pattern; "
        f"early={early_mean:.4f}, late={late_mean:.4f}"
    )


# ---------------------------------------------------------------------------
# Unexpected tone raises salience
# ---------------------------------------------------------------------------

def test_unexpected_emotion_raises_salience():
    """An emotion that diverges from the forward model's prediction produces
    higher salience than an equally-confident but predicted emotion.
    """
    model = AuditoryForwardModel(
        feature_dim=FEATURE_DIM,
        units=32,
        auditory_buffer_size=4,
        lr=0.1,
        seed=7,
    )
    baseline = 0.4
    alert = 0.8

    # Condition the model on many neutral steps so it strongly predicts neutral.
    neutral_vec = build_feature_vector(
        _neutral_scores(), CATEGORIES, duration_s=0.5, mean_energy=0.1
    )
    for _ in range(200):
        model.step(neutral_vec)
    # Flush error history so we test with a clean window.
    error_window: list[float] = []

    # A neutral step should have low prediction error.
    neutral_err = model.step(neutral_vec)
    error_window.append(neutral_err)
    neutral_salience = model.prediction_error_to_salience(
        neutral_err, baseline, alert, error_window=list(error_window)
    )

    # Now inject a sudden happy step — the model doesn't expect this.
    happy_vec = build_feature_vector(
        _happy_scores(), CATEGORIES, duration_s=0.5, mean_energy=0.1
    )
    happy_err = model.step(happy_vec)
    happy_salience = model.prediction_error_to_salience(
        happy_err, baseline, alert, error_window=list(error_window)
    )

    assert happy_salience >= neutral_salience, (
        f"Unexpected emotion should raise salience; "
        f"neutral={neutral_salience:.4f}, happy={happy_salience:.4f}"
    )


def test_salience_clamps_to_alert():
    model = AuditoryForwardModel(feature_dim=FEATURE_DIM, units=16, seed=0)
    # Huge error should clamp at alert_salience.
    s = model.prediction_error_to_salience(1e6, 0.4, 0.8, error_window=[0.01])
    assert s <= 0.8


def test_salience_baseline_on_zero_error():
    model = AuditoryForwardModel(feature_dim=FEATURE_DIM, units=16, seed=0)
    s = model.prediction_error_to_salience(0.0, 0.4, 0.8, error_window=[0.5])
    assert s == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# Non-finite guard
# ---------------------------------------------------------------------------

def test_non_finite_guard_skips_update(monkeypatch):
    """If the loss is non-finite, no update occurs and no exception is raised."""
    import torch

    model = AuditoryForwardModel(feature_dim=FEATURE_DIM, units=8, seed=0)
    # Seed last_prediction so the guard path can run.
    model.step([0.1] * FEATURE_DIM)

    before = model.state_dict()

    original_mean = torch.Tensor.mean
    call_count = {"n": 0}

    def patched_mean(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return torch.tensor(float("nan"))
        return original_mean(self, *args, **kwargs)

    monkeypatch.setattr(torch.Tensor, "mean", patched_mean)

    err = model._adapt_toward([0.9] * FEATURE_DIM)
    assert err == 0.0

    after = model.state_dict()
    assert before["layers"] == after["layers"]


# ---------------------------------------------------------------------------
# Serialisation: weights round-trip; no raw data; buffer summary numeric
# ---------------------------------------------------------------------------

def test_state_dict_roundtrip():
    model = AuditoryForwardModel(feature_dim=FEATURE_DIM, units=16, seed=1, lr=0.05)
    vec = [0.4] * FEATURE_DIM
    for _ in range(10):
        model.step(vec)

    snap = model.state_dict()
    fresh = AuditoryForwardModel(feature_dim=FEATURE_DIM, units=16, seed=99)
    fresh.load_state_dict(snap)

    # Compare with empty buffer so context matches.
    model._buffer.clear()
    probe = [0.3] * FEATURE_DIM
    pred_before = model.predict(probe)
    pred_after = fresh.predict(probe)
    assert pred_before == pytest.approx(pred_after, abs=1e-5)


def test_state_dict_contains_no_raw_data():
    import torch

    model = AuditoryForwardModel(feature_dim=FEATURE_DIM, units=16, seed=0)
    for _ in range(5):
        model.step([0.5] * FEATURE_DIM)

    def _find_tensors(obj, path="root"):
        if isinstance(obj, torch.Tensor):
            raise AssertionError(f"Raw tensor at {path}: {obj.shape}")
        if isinstance(obj, dict):
            for k, v in obj.items():
                _find_tensors(v, f"{path}[{k!r}]")
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                _find_tensors(v, f"{path}[{i}]")

    _find_tensors(model.state_dict())


def test_buffer_summary_numeric_only():
    import torch

    model = AuditoryForwardModel(feature_dim=FEATURE_DIM, units=16, seed=0)
    for i in range(6):
        model.step([float(i) * 0.1] * FEATURE_DIM)

    summary = model.buffer_summary()
    assert "n_utterances" in summary
    assert "mean" in summary
    assert "variance" in summary
    assert isinstance(summary["n_utterances"], int)

    def _assert_no_tensors(obj, path):
        if isinstance(obj, torch.Tensor):
            raise AssertionError(f"Raw tensor in buffer_summary at {path}")
        if isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                _assert_no_tensors(v, f"{path}[{i}]")

    _assert_no_tensors(summary["mean"], "mean")
    _assert_no_tensors(summary["variance"], "variance")

    for v in summary["mean"]:
        assert isinstance(v, float) and math.isfinite(v)
    for v in summary["variance"]:
        assert isinstance(v, float) and math.isfinite(v)


def test_buffer_summary_empty():
    model = AuditoryForwardModel(feature_dim=FEATURE_DIM, units=8, seed=0)
    summary = model.buffer_summary()
    assert summary["n_utterances"] == 0
    assert summary["mean"] == [0.0] * FEATURE_DIM
    assert summary["variance"] == [0.0] * FEATURE_DIM


# ---------------------------------------------------------------------------
# Suspend flag
# ---------------------------------------------------------------------------

def test_suspended_blocks_adaptation():
    model = AuditoryForwardModel(feature_dim=FEATURE_DIM, units=8, seed=0)
    model.step([0.1] * FEATURE_DIM)
    model.suspended = True

    before = model.state_dict()
    for _ in range(10):
        model.step([0.9] * FEATURE_DIM)
    after = model.state_dict()

    assert before["layers"] == after["layers"]
