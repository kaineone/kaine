# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the workspace feedback blend processor and its helpers."""

from __future__ import annotations

import copy
import math
import random

import numpy as np
import pytest

from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.context import CONTEXT_DIM
from kaine.modules.feedback import (
    FeedbackChannel,
    TopDownBlend,
    TopDownHead,
    blend_weights,
)
from kaine.workspace.feedback import FEEDBACK_KEY, SEQUENCE_PREDICTION_DIM


def _l2(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _mean(seq):
    return sum(seq) / len(seq) if seq else 0.0


class FakeForwardModel:
    """Minimal forward model implementing the processor contract."""

    def __init__(self):
        self._last_prediction = None
        self._last_null_prediction = None
        self._last_input_context = None
        self.last_null_error = None
        self.last_scored_had_context = False
        self.last_error_defined = False
        self.last_reading_skipped = True
        self._after_skip = True
        self.suspended = False
        self.context_dim = 24
        self.marker = "inner"
        self._buffer = []

    def _predict_next(self, latent):
        return [0.5 * v for v in latent]

    def _predict_null(self, latent):
        return [0.25 * v for v in latent]

    def _adapt_toward(self, latent, context):
        pass

    def step(self, latent, context=None, null_context=None):
        if any(not math.isfinite(v) for v in latent):
            self.last_null_error = None
            self.last_scored_had_context = False
            self._last_prediction = None
            self._last_null_prediction = None
            self._last_input_context = None
            self.last_error_defined = False
            self._after_skip = True
            self.last_reading_skipped = True
            return 0.0

        self.last_reading_skipped = False
        self.last_error_defined = not self._after_skip
        self._after_skip = False

        if self._last_prediction is None:
            prediction_error = 0.0
            self.last_scored_had_context = False
            self.last_null_error = None
        else:
            diffs = [(a - b) ** 2 for a, b in zip(latent, self._last_prediction)]
            prediction_error = math.sqrt(sum(diffs))
            self.last_scored_had_context = self._last_input_context is not None
            if self._last_null_prediction is not None:
                null_diffs = [(a - b) ** 2 for a, b in zip(latent, self._last_null_prediction)]
                self.last_null_error = math.sqrt(sum(null_diffs))
            else:
                self.last_null_error = None

        if not self.suspended and self._last_prediction is not None:
            self._adapt_toward(latent, self._last_input_context)

        self._buffer.append(list(latent))
        self._last_prediction = self._predict_next(latent)
        self._last_input_context = context

        if null_context is not None and self.context_dim > 0:
            self._last_null_prediction = self._predict_null(latent)
        else:
            self._last_null_prediction = None

        return prediction_error


def test_blend_weights():
    w_own, w_top = blend_weights(1.0, 2.0)
    assert w_own == pytest.approx(0.8, rel=1e-12)
    assert w_top == pytest.approx(0.2, rel=1e-12)
    assert blend_weights(1.0, None) == (1.0, 0.0)
    assert blend_weights(0.0, 1.0) == (1.0, 0.0)
    assert blend_weights(1.0, 0.0) == (0.0, 1.0)


def test_top_down_head():
    head = TopDownHead(output_dim=8, lr=0.05)

    assert head.output_dim == 8
    assert head.input_dim == CONTEXT_DIM + SEQUENCE_PREDICTION_DIM + 1
    assert (head.weights == 0).all()
    assert head.predict(head.regressor(None, None)) == [0.0] * 8

    ctx = [0.1] * CONTEXT_DIM
    seq = [0.2] * SEQUENCE_PREDICTION_DIM
    x = head.regressor(ctx, seq)
    assert len(x) == head.input_dim
    assert x[-1] == 1.0
    assert (x[:CONTEXT_DIM] == 0.1).all()
    assert (x[CONTEXT_DIM:-1] == 0.2).all()

    with pytest.raises(ValueError):
        head.regressor([0.0] * (CONTEXT_DIM - 1), None)

    target = [0.3] * 8
    first_loss = head.adapt(x, target)
    assert first_loss > 0.0

    for _ in range(199):
        loss = head.adapt(x, target)

    assert loss < first_loss
    prediction = head.predict(x)
    assert abs(prediction[0] - 0.3) < 0.01

    before = head.weights.copy()
    assert head.adapt(x, [float("nan")] * 8) == 0.0
    assert np.allclose(head.weights, before)


def test_blend_leaves_own_prediction_without_history():
    fake = FakeForwardModel()
    blend = TopDownBlend(fake, window=32, lr=1e-3)

    f1 = [1.0] * 8
    assert blend.step(f1) == 0.0
    assert blend.last_top_weight == 0.0

    f2 = [2.0] * 8
    err2 = blend.step(f2)
    assert err2 == _l2(f2, [0.5] * 8)


def test_blend_uses_top_down_once_window_has_entry():
    fake = FakeForwardModel()
    blend = TopDownBlend(fake, window=32, lr=1e-3)

    f1 = [1.0] * 8
    f2 = [2.0] * 8
    f3 = [3.0] * 8

    blend.step(f1)
    blend.step(f2)

    own_next = [0.5 * v for v in f2]
    top_next = blend._top
    w_own, w_top = blend_weights(_mean(blend._own_errors), _mean(blend._top_errors))
    expected = [w_own * o + w_top * t for o, t in zip(own_next, top_next)]

    err3 = blend.step(f3)
    assert err3 == pytest.approx(_l2(f3, expected), rel=1e-12)


def test_disagreement_is_gap_over_mean_blend_error():
    fake = FakeForwardModel()
    blend = TopDownBlend(fake, window=32, lr=1e-3)

    f1 = [1.0] * 8
    f2 = [2.0] * 8
    f3 = [3.0] * 8

    blend.step(f1)
    blend.step(f2)
    gap = blend._pending_gap

    blend.step(f3)
    mean_blend = _mean(list(blend._blend_errors))

    assert blend.last_disagreement == pytest.approx(gap / mean_blend, rel=1e-12)


def test_null_blend_tracks_null_context():
    fake = FakeForwardModel()
    blend = TopDownBlend(fake, window=32, lr=1e-3)

    f1 = [1.0] * 8
    f2 = [2.0] * 8
    f3 = [3.0] * 8
    context = [0.1] * 24
    null_context = [0.0] * 24

    blend.step(f1, context=context, null_context=null_context)
    blend.step(f2, context=context, null_context=null_context)
    null_blend = blend._blend_null

    blend.step(f3, context=context, null_context=null_context)
    assert blend.last_null_error == pytest.approx(_l2(f3, null_blend), rel=1e-12)

    plain = TopDownBlend(FakeForwardModel(), window=32, lr=1e-3)
    plain.step(f1)
    plain.step(f2)
    assert plain.last_null_error is None


def test_residuals_use_previous_blend():
    fake = FakeForwardModel()
    blend = TopDownBlend(fake, window=32, lr=1e-3)

    f1 = [1.0] * 8
    f2 = [2.0] * 8
    f3 = [3.0] * 8

    blend.step(f1)
    blend.step(f2)
    previous_blend = list(blend._blend)

    blend.step(f3)
    assert blend.last_residuals == tuple(a - b for a, b in zip(f3, previous_blend))


def test_skip_resets_scoring_state():
    fake = FakeForwardModel()
    blend = TopDownBlend(fake, window=32, lr=1e-3)

    blend.step([1.0] * 8)
    err_nan = blend.step([float("nan")] * 8)

    assert err_nan == 0.0
    assert blend.last_reading_skipped is True
    assert blend.last_disagreement is None

    err_after = blend.step([2.0] * 8)
    assert err_after == 0.0
    assert blend.last_error_defined is False

    err_final = blend.step([3.0] * 8)
    assert err_final > 0.0
    assert blend.last_error_defined is True


def test_suspended_stops_head_learning():
    fake = FakeForwardModel()
    blend = TopDownBlend(fake, window=32, lr=0.1)

    blend.step([1.0] * 8)
    blend.step([2.0] * 8)
    awake = blend.head.weights.copy()

    blend.step([3.0] * 8)
    learned = blend.head.weights.copy()
    assert not np.allclose(awake, learned)

    blend.suspended = True
    blend.step([4.0] * 8)
    suspended = blend.head.weights.copy()
    assert np.allclose(learned, suspended)

    blend.suspended = False
    blend.step([5.0] * 8)
    final = blend.head.weights.copy()
    assert not np.allclose(suspended, final)


def test_delegation_and_copying():
    fake = FakeForwardModel()
    blend = TopDownBlend(fake, window=32, lr=1e-3)

    assert blend.marker == "inner"
    assert blend.context_dim == 24

    with pytest.raises(NotImplementedError, match="the positive control runs with workspace feedback off"):
        blend.widened_copy()

    with pytest.raises(NotImplementedError, match="the positive control runs with workspace feedback off"):
        blend.hindsight_step([1.0] * 8)

    copied = copy.deepcopy(blend)
    assert copied.marker == "inner"
    assert copied.context_dim == 24


def test_requires_exposed_predictions():
    class BadInner:
        def step(self, x):
            pass

    with pytest.raises(ValueError, match="workspace feedback needs a forward model that exposes its predictions"):
        TopDownBlend(BadInner())


def test_feedback_channel():
    ch = FeedbackChannel("vision")

    snap = WorkspaceSnapshot(
        tick_index=1,
        inhibited=False,
        metadata={
            FEEDBACK_KEY: {
                "gains": {"vision": 1.1},
                "sequence_prediction": [0.1] * SEQUENCE_PREDICTION_DIM,
            }
        },
    )
    assert ch.observe(snap) is True
    assert ch.sequence_prediction == tuple([0.1] * SEQUENCE_PREDICTION_DIM)
    assert ch.gain == 1.1

    inhibited = WorkspaceSnapshot(
        tick_index=2,
        inhibited=True,
        metadata={
            FEEDBACK_KEY: {
                "gains": {"vision": 2.0},
                "sequence_prediction": [0.2] * SEQUENCE_PREDICTION_DIM,
            }
        },
    )
    assert ch.observe(inhibited) is False
    assert ch.sequence_prediction == tuple([0.1] * SEQUENCE_PREDICTION_DIM)
    assert ch.gain == 1.1

    no_key = WorkspaceSnapshot(tick_index=3, inhibited=False, metadata={})
    assert ch.observe(no_key) is False

    none_seq = WorkspaceSnapshot(
        tick_index=4,
        inhibited=False,
        metadata={
            FEEDBACK_KEY: {
                "sequence_prediction": None,
                "gains": {"vision": 3.0},
            }
        },
    )
    assert ch.observe(none_seq) is True
    assert ch.sequence_prediction == tuple([0.1] * SEQUENCE_PREDICTION_DIM)
    assert ch.gain == 3.0

    zero_gain = WorkspaceSnapshot(
        tick_index=5,
        inhibited=False,
        metadata={FEEDBACK_KEY: {"gains": {"vision": 0.0}}},
    )
    assert ch.observe(zero_gain) is True
    assert ch.gain == 3.0

    bool_gain = WorkspaceSnapshot(
        tick_index=6,
        inhibited=False,
        metadata={FEEDBACK_KEY: {"gains": {"vision": True}}},
    )
    assert ch.observe(bool_gain) is True
    assert ch.gain == 3.0

    nan_gain = WorkspaceSnapshot(
        tick_index=7,
        inhibited=False,
        metadata={FEEDBACK_KEY: {"gains": {"vision": float("nan")}}},
    )
    assert ch.observe(nan_gain) is True
    assert ch.gain == 3.0


def test_real_forward_models_match_unwrapped_twin():
    pytest.importorskip("torch")
    from kaine.modules.interoception.forward import SubstrateForwardModel
    from kaine.modules.vision.forward import LatentForwardModel

    context = [0.1] * 24
    null_context = [0.0] * 24
    rng = random.Random(7)
    vectors = [[rng.uniform(-1.0, 1.0) for _ in range(8)] for _ in range(3)]

    unwrapped_vision = LatentForwardModel(latent_dim=8, units=16, seed=3, context_dim=24)
    wrapped_vision = TopDownBlend(
        LatentForwardModel(latent_dim=8, units=16, seed=3, context_dim=24),
        window=32,
        lr=1e-3,
    )

    unwrapped_errors = []
    wrapped_errors = []
    for i, v in enumerate(vectors):
        unwrapped_errors.append(unwrapped_vision.step(v, context=context, null_context=null_context))
        wrapped_errors.append(wrapped_vision.step(v, context=context, null_context=null_context))
        if i == 1:
            # The blend formed at the first step had no top-down weight.
            assert unwrapped_vision.last_null_error is not None
            assert unwrapped_vision.last_null_error == wrapped_vision.last_null_error

    assert unwrapped_errors[0] == wrapped_errors[0]
    assert unwrapped_errors[1] == wrapped_errors[1]

    unwrapped_intero = SubstrateForwardModel(feature_dim=8, units=8, seed=5, context_dim=24)
    wrapped_intero = TopDownBlend(
        SubstrateForwardModel(feature_dim=8, units=8, seed=5, context_dim=24),
        window=32,
        lr=1e-3,
    )

    for i, v in enumerate(vectors):
        unwrapped_intero.step(v, timespan=1.0, context=context, null_context=null_context)
        wrapped_intero.step(v, timespan=1.0, context=context, null_context=null_context)
        if i == 1:
            assert wrapped_intero.last_residuals is not None
            assert len(wrapped_intero.last_residuals) == 8
