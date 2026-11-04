# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for workspace feedback preservation (top-down heads, blends, gains)."""

from __future__ import annotations

import math

import numpy as np
import pytest

from kaine.modules.context import CONTEXT_DIM
from kaine.modules.feedback import TopDownBlend, TopDownHead
from kaine.workspace.feedback import (
    PROCESSORS,
    FeedbackController,
    WorkspaceFeedbackSettings,
)


# ---------------------------------------------------------------------------
# Minimal mock forward model (same contract as FakeForwardModel in
# test_workspace_feedback_blend.py)
# ---------------------------------------------------------------------------


class _FakeForwardModel:
    """Minimal forward model implementing the processor contract for tests."""

    def __init__(self, *, dim: int = 8):
        self._dim = dim
        self._last_prediction = None
        self._last_null_prediction = None
        self.last_null_error = None
        self.last_scored_had_context = False
        self.last_error_defined = False
        self.last_reading_skipped = True
        self._after_skip = True
        self.suspended = False
        self.context_dim = 24
        self._state = {"marker": "inner"}

    def step(self, latent, context=None, null_context=None, **kwargs):
        if any(not math.isfinite(v) for v in latent):
            self.last_reading_skipped = True
            self.last_error_defined = False
            self._last_prediction = None
            self._last_null_prediction = None
            return 0.0

        self.last_reading_skipped = False
        self.last_error_defined = not self._after_skip
        self._after_skip = False

        prev = self._last_prediction
        if prev is None:
            prediction_error = 0.0
            self.last_scored_had_context = False
            self.last_null_error = None
        else:
            prediction_error = math.sqrt(sum((a - b) ** 2 for a, b in zip(latent, prev)))
            self.last_scored_had_context = context is not None

        self._last_prediction = [0.5 * v for v in latent]
        if null_context is not None:
            self._last_null_prediction = [0.25 * v for v in latent]
        else:
            self._last_null_prediction = None

        return prediction_error

    def state_dict(self):
        return dict(self._state)

    def load_state_dict(self, state):
        self._state = dict(state)

    def matches_state_shape(self, state):
        return "marker" in state

    def state_shape_mismatch(self, state):
        if "marker" not in state:
            return "missing marker key"
        return None


# ---------------------------------------------------------------------------
# TopDownHead round-trip
# ---------------------------------------------------------------------------


def test_top_down_head_state_round_trip():
    head = TopDownHead(output_dim=8, lr=0.05)
    ctx = [0.1] * CONTEXT_DIM
    seq = [0.2] * 24
    x = head.regressor(ctx, seq)
    target = [0.3] * 8

    # Adapt several times so weights are non-trivial.
    for _ in range(50):
        head.adapt(x, target)

    saved = head.state_dict()
    assert saved["output_dim"] == 8
    assert saved["lr"] == 0.05
    assert np.any(np.asarray(saved["weights"]) != 0.0)

    # Restore into a fresh head and verify weights match.
    head2 = TopDownHead(output_dim=8, lr=0.05)
    head2.load_state_dict(saved)
    np.testing.assert_array_equal(head2.weights, head.weights)


def test_top_down_head_rejects_shape_mismatch():
    head = TopDownHead(output_dim=8, lr=0.05)
    bad_state = {
        "weights": np.zeros((4, head.input_dim)).tolist(),
        "output_dim": 4,
        "lr": 0.05,
    }
    with pytest.raises(ValueError, match="shape mismatch"):
        head.load_state_dict(bad_state)


# ---------------------------------------------------------------------------
# TopDownBlend round-trip
# ---------------------------------------------------------------------------


def test_top_down_blend_state_round_trip():
    inner = _FakeForwardModel()
    blend = TopDownBlend(inner, window=32, lr=1e-3)

    # Run several steps to build the head and populate error windows.
    for i in range(5):
        blend.step([float(i)] * 8)

    assert blend.head is not None
    saved = blend.state_dict()

    assert "inner" in saved
    assert "head" in saved
    assert "own_errors" in saved
    assert "top_errors" in saved
    assert "blend_errors" in saved

    # Restore into a new blend wrapping a fresh inner model.
    inner2 = _FakeForwardModel()
    blend2 = TopDownBlend(inner2, window=32, lr=1e-3)
    blend2.load_state_dict(saved)

    # Head weights should match.
    assert blend2.head is not None
    np.testing.assert_array_equal(blend2.head.weights, blend.head.weights)

    # Error windows should match.
    assert list(blend2._own_errors) == list(blend._own_errors)
    assert list(blend2._top_errors) == list(blend._top_errors)
    assert list(blend2._blend_errors) == list(blend._blend_errors)

    # Inner model state should have been restored.
    assert inner2._state == inner._state


def test_top_down_blend_state_backward_compat():
    """A state_dict without the 'inner' key (legacy) still loads into the inner model."""
    inner = _FakeForwardModel()
    blend = TopDownBlend(inner, window=32, lr=1e-3)

    # Build a legacy-shaped state: just the inner model's dict at the top level.
    legacy_state = {"marker": "restored-legacy"}

    blend.load_state_dict(legacy_state)
    assert inner._state == {"marker": "restored-legacy"}
    # No head or error windows in the legacy state, so they stay at defaults.
    assert blend.head is None
    assert len(blend._own_errors) == 0


def test_top_down_blend_matches_state_shape():
    inner = _FakeForwardModel()
    blend = TopDownBlend(inner, window=32, lr=1e-3)

    good_state = {"inner": {"marker": "ok"}}
    assert blend.matches_state_shape(good_state) is True
    assert blend.state_shape_mismatch(good_state) is None

    bad_state = {"inner": {"no_marker": True}}
    assert blend.matches_state_shape(bad_state) is False
    assert blend.state_shape_mismatch(bad_state) is not None


def test_top_down_blend_matches_state_shape_legacy():
    """Legacy (no 'inner' key) falls through to the inner checker."""
    inner = _FakeForwardModel()
    blend = TopDownBlend(inner, window=32, lr=1e-3)

    good_legacy = {"marker": "ok"}
    assert blend.matches_state_shape(good_legacy) is True

    bad_legacy = {"no_marker": True}
    assert blend.matches_state_shape(bad_legacy) is False


def test_top_down_blend_error_window_clipping():
    """Error windows loaded from a larger snapshot are clipped to the blend's window."""
    inner = _FakeForwardModel()
    blend = TopDownBlend(inner, window=4, lr=1e-3)

    state = {
        "inner": {"marker": "ok"},
        "own_errors": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
        "top_errors": [0.1, 0.2, 0.3, 0.4, 0.5],
        "blend_errors": [0.5, 0.6, 0.7, 0.8, 0.9],
    }
    blend.load_state_dict(state)

    # Window is 4, so only the last 4 values should be kept.
    assert list(blend._own_errors) == [3.0, 4.0, 5.0, 6.0]
    assert list(blend._top_errors) == [0.2, 0.3, 0.4, 0.5]
    assert list(blend._blend_errors) == [0.6, 0.7, 0.8, 0.9]


# ---------------------------------------------------------------------------
# FeedbackController round-trip
# ---------------------------------------------------------------------------


def test_feedback_controller_state_round_trip():
    settings = WorkspaceFeedbackSettings(arm="head_gain")
    ctrl = FeedbackController(settings)

    # Manually set gains to non-default values (within bounds).
    ctrl._gains["vision"] = 1.15
    ctrl._gains["audition"] = 0.9
    ctrl._gains["interoception"] = 0.95

    saved = ctrl.state_dict()
    assert saved["gains"]["vision"] == 1.15
    assert saved["gains"]["audition"] == 0.9
    assert saved["gains"]["interoception"] == 0.95

    # Restore into a fresh controller.
    ctrl2 = FeedbackController(settings)
    ctrl2.load_state_dict(saved)

    assert ctrl2.gains == ctrl.gains


def test_feedback_controller_rejects_invalid_gains():
    settings = WorkspaceFeedbackSettings(arm="head_gain", pi_min=0.8, pi_max=1.25)
    ctrl = FeedbackController(settings)

    # Gains outside [pi_min, pi_max] should be rejected (silently ignored).
    ctrl.load_state_dict({"gains": {"vision": 2.0}})  # above pi_max
    assert ctrl.gains["vision"] == 1.0  # unchanged

    ctrl.load_state_dict({"gains": {"vision": 0.5}})  # below pi_min
    assert ctrl.gains["vision"] == 1.0  # unchanged

    ctrl.load_state_dict({"gains": {"vision": float("nan")}})  # non-finite
    assert ctrl.gains["vision"] == 1.0  # unchanged

    ctrl.load_state_dict({"gains": {"vision": float("inf")}})  # non-finite
    assert ctrl.gains["vision"] == 1.0  # unchanged

    ctrl.load_state_dict({"gains": {"vision": True}})  # bool
    assert ctrl.gains["vision"] == 1.0  # unchanged

    # Valid value within bounds should be accepted.
    ctrl.load_state_dict({"gains": {"vision": 1.1}})
    assert ctrl.gains["vision"] == 1.1


def test_feedback_controller_rejects_non_dict():
    settings = WorkspaceFeedbackSettings(arm="head_gain")
    ctrl = FeedbackController(settings)

    # Non-dict gains should be silently ignored.
    ctrl.load_state_dict({"gains": "not a dict"})
    assert ctrl.gains == {"vision": 1.0, "audition": 1.0, "interoception": 1.0}

    ctrl.load_state_dict({})
    assert ctrl.gains == {"vision": 1.0, "audition": 1.0, "interoception": 1.0}


# ---------------------------------------------------------------------------
# Vision module integration (forward_model.state_dict captures blend state)
# ---------------------------------------------------------------------------


def test_vision_serialize_preserves_blend():
    """When vision wraps its forward model in TopDownBlend, serialize() carries the head state."""
    pytest.importorskip("torch")
    from kaine.modules.vision.forward import LatentForwardModel

    fm = LatentForwardModel(latent_dim=8, units=16, seed=3, context_dim=24)
    blend = TopDownBlend(fm, window=32, lr=1e-3)

    # Run a few steps to build the head.
    for i in range(5):
        blend.step([float(i + 1) * 0.1] * 8)

    assert blend.head is not None

    state = blend.state_dict()
    assert "inner" in state
    assert "head" in state
    assert "own_errors" in state
    assert "blend_errors" in state

    # The inner state should be what LatentForwardModel.state_dict() produces.
    inner_state = state["inner"]
    assert fm.matches_state_shape(inner_state)

    # Verify a round-trip through a fresh blend + inner model.
    fm2 = LatentForwardModel(latent_dim=8, units=16, seed=7, context_dim=24)
    blend2 = TopDownBlend(fm2, window=32, lr=1e-3)
    blend2.load_state_dict(state)

    assert blend2.head is not None
    np.testing.assert_array_equal(blend2.head.weights, blend.head.weights)
