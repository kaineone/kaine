# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for kaine.modules.vision.forward.LatentForwardModel.

Covers:
- Predictor output shape
- Online step reduces error on a repeating latent sequence
- Non-finite guard (loss / gradient)
- Buffer bounds
- Serialisation round-trip (weights only — no raw tensors)
"""
import math

import pytest

from kaine.modules.vision.forward import LatentForwardModel

# ---------------------------------------------------------------------------
# Construction and shape
# ---------------------------------------------------------------------------

def test_construction_defaults():
    model = LatentForwardModel(latent_dim=8)
    assert model.latent_dim == 8
    assert model.units == 128
    assert model.visual_buffer_size == 16


def test_invalid_construction_rejected():
    with pytest.raises(ValueError):
        LatentForwardModel(latent_dim=0)
    with pytest.raises(ValueError):
        LatentForwardModel(latent_dim=8, units=0)
    with pytest.raises(ValueError):
        LatentForwardModel(latent_dim=8, visual_buffer_size=0)
    with pytest.raises(ValueError):
        LatentForwardModel(latent_dim=8, lr=0.0)


def test_predict_output_shape():
    """predict() returns a list of length latent_dim."""
    model = LatentForwardModel(latent_dim=16, units=32, seed=0)
    latent = [0.1] * 16
    pred = model.predict(latent)
    assert isinstance(pred, list)
    assert len(pred) == 16
    assert all(isinstance(v, float) for v in pred)


def test_step_returns_zero_on_first_frame():
    """First step has no prior prediction — error must be 0.0."""
    model = LatentForwardModel(latent_dim=8, units=16, seed=0)
    err = model.step([0.5] * 8)
    assert err == pytest.approx(0.0)


def test_step_returns_float_error():
    """step() returns a non-negative float."""
    model = LatentForwardModel(latent_dim=8, units=16, seed=0)
    model.step([0.5] * 8)
    err = model.step([0.3] * 8)
    assert isinstance(err, float)
    assert err >= 0.0


# ---------------------------------------------------------------------------
# Buffer is bounded
# ---------------------------------------------------------------------------

def test_buffer_is_bounded():
    """Buffer must never exceed visual_buffer_size entries."""
    buf_size = 4
    model = LatentForwardModel(latent_dim=8, units=16, visual_buffer_size=buf_size, seed=0)
    for i in range(buf_size + 10):
        model.step([float(i)] * 8)
    assert len(model._buffer) <= buf_size


# ---------------------------------------------------------------------------
# Online learning: error should decrease on a repeating latent sequence
# ---------------------------------------------------------------------------

def test_online_step_reduces_error_on_repeating_sequence():
    """After many steps on a constant latent, prediction error should decrease.

    This mirrors test_forward_prediction_head_error_drops_on_regular_cadence
    in test_sequence_network.py.
    """
    latent_dim = 8
    model = LatentForwardModel(
        latent_dim=latent_dim,
        units=32,
        visual_buffer_size=4,
        lr=0.05,
        seed=42,
    )
    fixed_latent = [0.5] * latent_dim
    errors = []
    # Warm up enough that the model has had many adaptation steps.
    for _ in range(200):
        err = model.step(fixed_latent)
        errors.append(err)

    # Skip the very first (always 0.0) and warm-up frames.
    useful = errors[1:]  # first real errors start at index 1
    early_mean = sum(useful[:20]) / 20
    late_mean = sum(useful[-20:]) / 20
    assert late_mean < early_mean, (
        f"Expected prediction error to decrease with adaptation on a repeating "
        f"sequence; early={early_mean:.4f}, late={late_mean:.4f}"
    )


# ---------------------------------------------------------------------------
# Non-finite guard
# ---------------------------------------------------------------------------

def test_non_finite_guard_skips_update(monkeypatch):
    """If the loss is non-finite, no update occurs and no exception is raised."""
    import torch

    model = LatentForwardModel(latent_dim=4, units=8, seed=0)
    # Seed last_prediction so the guard path can run.
    model.step([0.1] * 4)

    # Record weights before the poisoned step.
    before = model.state_dict()

    # Monkeypatch: make torch.Tensor.mean() return NaN after first call inside adapt.
    original_mean = torch.Tensor.mean

    call_count = {"n": 0}

    def patched_mean(self, *args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return torch.tensor(float("nan"))
        return original_mean(self, *args, **kwargs)

    monkeypatch.setattr(torch.Tensor, "mean", patched_mean)

    # Should not raise; guard must absorb the NaN.
    err = model._adapt_toward([0.9] * 4)
    assert err == 0.0

    after = model.state_dict()
    # Weights must be unchanged.
    assert before["layers"] == after["layers"]


# ---------------------------------------------------------------------------
# Serialisation: weights round-trip; no raw tensors
# ---------------------------------------------------------------------------

def test_state_dict_roundtrip():
    """state_dict() / load_state_dict() reproduce predictions exactly.

    Because predict() uses the internal buffer context, we clear both buffers
    before comparing — the serialised state only covers MLP weights (not raw
    latents), so a restored model correctly starts with an empty buffer.
    """
    model = LatentForwardModel(latent_dim=8, units=16, seed=1, lr=0.05)
    latent = [0.4] * 8
    # Adapt a few steps to move weights away from init.
    for _ in range(10):
        model.step(latent)

    snap = model.state_dict()

    fresh = LatentForwardModel(latent_dim=8, units=16, seed=99)
    fresh.load_state_dict(snap)

    # Compare with empty buffer on both models so the buffer context matches.
    model._buffer.clear()
    probe = [0.3] * 8
    pred_before = model.predict(probe)
    pred_after = fresh.predict(probe)

    assert pred_before == pytest.approx(pred_after, abs=1e-5)


def test_state_dict_contains_no_raw_latents():
    """state_dict() must not contain any torch.Tensor values."""
    import torch

    model = LatentForwardModel(latent_dim=8, units=16, seed=0)
    for _ in range(5):
        model.step([0.5] * 8)

    def _find_tensors(obj, path="root"):
        if isinstance(obj, torch.Tensor):
            raise AssertionError(
                f"Raw tensor found at {path}: {obj.shape}"
            )
        if isinstance(obj, dict):
            for k, v in obj.items():
                _find_tensors(v, f"{path}[{k!r}]")
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                _find_tensors(v, f"{path}[{i}]")

    snap = model.state_dict()
    _find_tensors(snap)  # must not raise


def test_buffer_summary_contains_only_numeric_summaries():
    """buffer_summary() holds three content-free scalars and no per-dimension
    statistic of the buffered latents (the latent rule)."""
    import numpy as np

    model = LatentForwardModel(latent_dim=8, units=16, seed=0)
    vectors = [[0.1 * i + 0.03 * j * (-1) ** i for j in range(8)] for i in range(6)]
    for vec in vectors:
        model.step(vec)

    summary = model.buffer_summary()
    assert set(summary) == {"n_frames", "mean_norm", "mean_variance"}
    assert type(summary["n_frames"]) is int and summary["n_frames"] == 6
    assert type(summary["mean_norm"]) is float
    assert type(summary["mean_variance"]) is float
    arr = np.asarray(vectors)
    assert summary["mean_norm"] == pytest.approx(float(np.linalg.norm(arr, axis=1).mean()))
    assert summary["mean_variance"] == pytest.approx(float(arr.var(axis=0).mean()))
    assert summary["mean_variance"] > 0.0
    for v in summary.values():
        assert math.isfinite(v)


def test_buffer_summary_empty():
    """buffer_summary() on a fresh model returns a zeroed descriptor."""
    model = LatentForwardModel(latent_dim=4, units=8, seed=0)
    assert model.buffer_summary() == {"n_frames": 0, "mean_norm": 0.0, "mean_variance": 0.0}


def test_buffer_summary_one_frame_has_zero_variance():
    model = LatentForwardModel(latent_dim=4, units=8, seed=0)
    model.step([3.0, 4.0, 0.0, 0.0])
    assert model.buffer_summary() == {"n_frames": 1, "mean_norm": 5.0, "mean_variance": 0.0}


# ---------------------------------------------------------------------------
# Suspend flag
# ---------------------------------------------------------------------------

def test_suspended_blocks_adaptation():
    """With suspended=True, weights must not change across step() calls."""
    model = LatentForwardModel(latent_dim=4, units=8, seed=0)
    # Seed one frame so subsequent steps have a prior prediction.
    model.step([0.1] * 4)
    model.suspended = True

    before = model.state_dict()
    for _ in range(10):
        model.step([0.9] * 4)
    after = model.state_dict()

    assert before["layers"] == after["layers"]
