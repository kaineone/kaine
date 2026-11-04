# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Workspace feedback blend processor.

Each context-conditioned processor can blend its own online forward prediction
with a top-down prediction read from broadcast context and a sequence-module
prediction. Errors are weighted by inverse square of recent mean error.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any, Sequence

import numpy as np

from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.context import CONTEXT_DIM
from kaine.workspace.feedback import FEEDBACK_KEY, SEQUENCE_PREDICTION_DIM


def blend_weights(own_mean: float, top_mean: float | None) -> tuple[float, float]:
    """Return normalized blend weights from recent mean errors.

    Weights are proportional to the inverse square of the supplied mean
    errors and always sum to one.
    """
    if top_mean is None:
        return (1.0, 0.0)
    if own_mean <= 0.0:
        return (1.0, 0.0)
    if top_mean <= 0.0:
        return (0.0, 1.0)
    raw_own = 1.0 / (own_mean * own_mean)
    raw_top = 1.0 / (top_mean * top_mean)
    total = raw_own + raw_top
    return (raw_own / total, raw_top / total)


def blend_weights_3(
    own_mean: float,
    top_mean: float | None,
    content_mean: float | None,
) -> tuple[float, float, float]:
    """3-way precision blend: (own, head, content), inverse-square weighting."""
    if top_mean is None and content_mean is None:
        return (1.0, 0.0, 0.0)
    if content_mean is None:
        w_own, w_top = blend_weights(own_mean, top_mean)
        return (w_own, w_top, 0.0)
    if top_mean is None:
        if own_mean <= 0.0:
            return (0.0, 0.0, 1.0) if content_mean > 0.0 else (1.0, 0.0, 0.0)
        if content_mean <= 0.0:
            return (1.0, 0.0, 0.0)
        raw_own = 1.0 / (own_mean * own_mean)
        raw_c = 1.0 / (content_mean * content_mean)
        total = raw_own + raw_c
        return (raw_own / total, 0.0, raw_c / total)
    if own_mean <= 0.0:
        entries = []
        if top_mean > 0.0:
            entries.append(("top", 1.0 / (top_mean * top_mean)))
        if content_mean > 0.0:
            entries.append(("content", 1.0 / (content_mean * content_mean)))
        if not entries:
            return (1.0, 0.0, 0.0)
        total = sum(v for _, v in entries)
        w_top = next((v / total for k, v in entries if k == "top"), 0.0)
        w_c = next((v / total for k, v in entries if k == "content"), 0.0)
        return (0.0, w_top, w_c)
    raw_own = 1.0 / (own_mean * own_mean)
    raw_top = 1.0 / (top_mean * top_mean) if top_mean > 0.0 else 0.0
    raw_c = 1.0 / (content_mean * content_mean) if content_mean > 0.0 else 0.0
    total = raw_own + raw_top + raw_c
    if total <= 0.0:
        return (1.0, 0.0, 0.0)
    return (raw_own / total, raw_top / total, raw_c / total)


def _l2(a: Sequence[float], b: Sequence[float]) -> float:
    """Euclidean distance between two equal-length float sequences."""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def _mean_window(window: deque[float]) -> float:
    """Arithmetic mean of a deque, or 0.0 when empty."""
    if not window:
        return 0.0
    return float(sum(window)) / len(window)


class TopDownHead:
    """Linear readout predicting the next processor input from (b, s, 1)."""

    def __init__(self, output_dim: int, *, lr: float = 1e-3):
        if output_dim <= 0:
            raise ValueError("output_dim must be positive")
        if lr <= 0.0:
            raise ValueError("lr must be positive")
        self._output_dim = int(output_dim)
        self._input_dim = CONTEXT_DIM + SEQUENCE_PREDICTION_DIM + 1
        self._lr = float(lr)
        self._weights = np.zeros((self._output_dim, self._input_dim), dtype=np.float64)

    @property
    def output_dim(self) -> int:
        return self._output_dim

    @property
    def input_dim(self) -> int:
        return self._input_dim

    @property
    def lr(self) -> float:
        return self._lr

    @property
    def weights(self) -> np.ndarray:
        return self._weights.copy()

    def regressor(self, context, sequence) -> np.ndarray:
        """Build the (context, sequence, 1) regressor vector.

        Missing context or sequence is treated as a zero vector of the
        appropriate length. Both supplied vectors must have length 24.
        """
        if context is None:
            ctx = np.zeros(CONTEXT_DIM, dtype=np.float64)
        else:
            if len(context) != CONTEXT_DIM:
                raise ValueError("context must have length equal to CONTEXT_DIM")
            ctx = np.asarray(context, dtype=np.float64)

        if sequence is None:
            seq = np.zeros(SEQUENCE_PREDICTION_DIM, dtype=np.float64)
        else:
            if len(sequence) != SEQUENCE_PREDICTION_DIM:
                raise ValueError("sequence must have length equal to SEQUENCE_PREDICTION_DIM")
            seq = np.asarray(sequence, dtype=np.float64)

        return np.concatenate([ctx, seq, np.ones(1, dtype=np.float64)])

    def predict(self, x: np.ndarray) -> list[float]:
        """Return the linear readout as a list of Python floats."""
        return (self._weights @ x).tolist()

    def adapt(self, x: np.ndarray, target) -> float:
        """One SGD step on mean squared error. Returns the loss."""
        target_arr = np.asarray(target, dtype=np.float64).reshape(self._output_dim)
        if target_arr.size != self._output_dim:
            raise ValueError("target must have length equal to output_dim")

        err = self._weights @ x - target_arr
        loss = float(np.mean(err * err))
        grad = (2.0 / self._output_dim) * np.outer(err, x)

        if not math.isfinite(loss) or not np.all(np.isfinite(grad)):
            return 0.0

        self._weights -= self._lr * grad
        return loss

    def state_dict(self) -> dict[str, Any]:
        """Snapshot: weights as nested list, structural dimensions, learning rate."""
        return {
            "weights": self._weights.tolist(),
            "output_dim": self._output_dim,
            "lr": self._lr,
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore from a state_dict() snapshot."""
        weights = np.asarray(state["weights"], dtype=np.float64)
        if weights.shape != (self._output_dim, self._input_dim):
            raise ValueError(
                f"TopDownHead state shape mismatch: expected "
                f"({self._output_dim}, {self._input_dim}), got {weights.shape}"
            )
        if not np.all(np.isfinite(weights)):
            raise ValueError("TopDownHead state contains non-finite weights")
        self._weights = weights
        # lr is structural and set at construction; log if it changed but don't reject
        saved_lr = state.get("lr")
        if saved_lr is not None and saved_lr != self._lr:
            import logging

            logging.getLogger(__name__).info(
                "TopDownHead: snapshot lr=%s differs from construction lr=%s",
                saved_lr,
                self._lr,
            )


class FeedbackChannel:
    """Adapter that reads sequence predictions and gains from broadcasts."""

    def __init__(self, processor: str):
        self.processor = processor
        self.sequence_prediction: tuple[float, ...] | None = None
        self.content_prediction: list[float] | None = None
        self.gain: float = 1.0

    def observe(self, snapshot: WorkspaceSnapshot) -> bool:
        """Adopt feedback from a workspace snapshot if present and valid.

        Returns True unless the broadcast is inhibited or carries no
        workspace_feedback metadata. Invalid values leave the previous
        state unchanged.
        """
        if snapshot.inhibited:
            return False

        fb = snapshot.metadata.get(FEEDBACK_KEY)
        if not isinstance(fb, dict):
            return False

        seq = fb.get("sequence_prediction")
        if isinstance(seq, (list, tuple)):
            if (
                len(seq) == SEQUENCE_PREDICTION_DIM
                and all(
                    isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                    for v in seq
                )
            ):
                self.sequence_prediction = tuple(float(v) for v in seq)

        gains = fb.get("gains")
        if isinstance(gains, dict):
            value = gains.get(self.processor)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(value)
                and value > 0.0
            ):
                self.gain = float(value)

        content = fb.get("content")
        if isinstance(content, dict):
            preds = content.get("predictions")
            if isinstance(preds, dict):
                pred = preds.get(self.processor)
                if isinstance(pred, list) and all(
                    isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
                    for v in pred
                ):
                    self.content_prediction = [float(v) for v in pred]

        return True


class TopDownBlend:
    """Wrapper that blends an inner forward model with a top-down head."""

    def __init__(self, inner, *, window: int = 32, lr: float = 1e-3):
        if (
            not hasattr(inner, "_last_prediction")
            or not hasattr(inner, "_last_null_prediction")
            or not hasattr(inner, "step")
        ):
            raise ValueError("workspace feedback needs a forward model that exposes its predictions")
        if window < 1:
            raise ValueError("window must be at least 1")

        self._inner = inner
        self._window = int(window)
        self._lr = float(lr)

        self._own_errors: deque[float] = deque(maxlen=self._window)
        self._top_errors: deque[float] = deque(maxlen=self._window)
        self._content_errors: deque[float] = deque(maxlen=self._window)
        self._blend_errors: deque[float] = deque(maxlen=self._window)

        self._head: TopDownHead | None = None

        self._blend = None
        self._blend_null = None
        self._top = None
        self._regressor = None
        self._pending_gap = None

        self.last_null_error = None
        self.last_residuals = None
        self.last_disagreement = None
        self.last_own_error = None
        self.last_top_error = None
        self.last_content_error = None
        self.last_top_weight = 0.0
        self.last_content_weight = 0.0

    @property
    def last_scored_had_context(self):
        return self._inner.last_scored_had_context

    @property
    def last_error_defined(self):
        return self._inner.last_error_defined

    @property
    def last_reading_skipped(self):
        return self._inner.last_reading_skipped

    @property
    def context_dim(self):
        return self._inner.context_dim

    @property
    def suspended(self):
        return self._inner.suspended

    @suspended.setter
    def suspended(self, value):
        self._inner.suspended = value

    @property
    def inner(self):
        return self._inner

    @property
    def head(self):
        return self._head

    def __getattr__(self, name: str):
        if name.startswith("__") or name == "_inner":
            raise AttributeError(name)
        return getattr(self._inner, name)

    def widened_copy(self):
        raise NotImplementedError("the positive control runs with workspace feedback off")

    def hindsight_step(self, feature):
        raise NotImplementedError("the positive control runs with workspace feedback off")

    def _clear_formed_state(self) -> None:
        self._blend = None
        self._blend_null = None
        self._top = None
        self._content = None
        self._regressor = None
        self._pending_gap = None
        self.last_top_weight = 0.0
        self.last_content_weight = 0.0

    def step(
        self,
        feature,
        context=None,
        null_context=None,
        *,
        timespan=None,
        sequence_prediction=None,
        content_prediction=None,
    ) -> float:
        """Step the inner model, score the previous blend, and form the next blend."""
        own_prev = self._inner._last_prediction

        if timespan is None:
            own_error = self._inner.step(feature, context=context, null_context=null_context)
        else:
            own_error = self._inner.step(
                feature, timespan=timespan, context=context, null_context=null_context
            )

        if self._inner.last_reading_skipped:
            self._clear_formed_state()
            self.last_null_error = None
            self.last_residuals = None
            self.last_disagreement = None
            self.last_own_error = None
            self.last_top_error = None
            return 0.0

        defined = self._inner.last_error_defined

        if own_prev is not None and self._blend is not None:
            error = _l2(feature, self._blend)
            top_error = _l2(feature, self._top)
            content_error = (
                _l2(feature, self._content) if self._content is not None else None
            )

            self.last_null_error = (
                _l2(feature, self._blend_null) if self._blend_null is not None else None
            )
            self.last_residuals = tuple(a - b for a, b in zip(feature, self._blend))
            self.last_own_error = own_error
            self.last_top_error = top_error
            self.last_content_error = content_error

            if defined:
                self._own_errors.append(own_error)
                self._top_errors.append(top_error)
                if content_error is not None:
                    self._content_errors.append(content_error)
                self._blend_errors.append(error)

            mean_blend = _mean_window(self._blend_errors)
            if self._pending_gap is not None and mean_blend > 0.0:
                self.last_disagreement = self._pending_gap / mean_blend
            else:
                self.last_disagreement = None

            if not self._inner.suspended and self._head is not None:
                self._head.adapt(self._regressor, feature)

        elif own_prev is not None:
            error = own_error
            self.last_null_error = self._inner.last_null_error
            self.last_residuals = tuple(a - b for a, b in zip(feature, own_prev))
            self.last_own_error = own_error
            self.last_top_error = None
            self.last_disagreement = None
            if defined:
                self._own_errors.append(own_error)
                self._blend_errors.append(error)

        else:
            error = own_error
            self.last_null_error = None
            self.last_residuals = None
            self.last_own_error = own_error if defined else None
            self.last_top_error = None
            self.last_disagreement = None
            if defined:
                self._own_errors.append(own_error)
                self._blend_errors.append(error)

        own_next = self._inner._last_prediction
        own_null_next = self._inner._last_null_prediction

        if own_next is None:
            self._clear_formed_state()
            return error

        if self._head is None:
            self._head = TopDownHead(len(own_next), lr=self._lr)

        x = self._head.regressor(context, sequence_prediction)
        top_next = self._head.predict(x)

        top_mean = _mean_window(self._top_errors) if self._top_errors else None
        content_mean = _mean_window(self._content_errors) if self._content_errors else None
        content_next = list(content_prediction) if content_prediction is not None else None
        if content_next is not None and len(content_next) != len(own_next):
            content_next = None

        if content_next is not None:
            w_own, w_top, w_content = blend_weights_3(
                _mean_window(self._own_errors), top_mean, content_mean,
            )
        else:
            w_own, w_top = blend_weights(_mean_window(self._own_errors), top_mean)
            w_content = 0.0

        blend = [0.0] * len(own_next)
        for i in range(len(own_next)):
            v = w_own * own_next[i] + w_top * top_next[i]
            if content_next is not None and w_content > 0.0:
                v += w_content * content_next[i]
            blend[i] = v

        blend_null = None
        if own_null_next is not None and null_context is not None:
            top_null = self._head.predict(self._head.regressor(null_context, sequence_prediction))
            blend_null = [0.0] * len(own_null_next)
            for i in range(len(own_null_next)):
                v = w_own * own_null_next[i] + w_top * top_null[i]
                if content_next is not None and w_content > 0.0:
                    v += w_content * content_next[i]
                blend_null[i] = v

        self._blend = blend
        self._blend_null = blend_null
        self._top = top_next
        self._content = content_next
        self._regressor = x
        self._pending_gap = _l2(top_next, own_next)
        self.last_top_weight = w_top
        self.last_content_weight = w_content

        return error

    # -- state persistence (preservation / revive) -------------------------

    def state_dict(self) -> dict[str, Any]:
        """Wrap the inner model's state with the top-down head's state and error windows."""
        state: dict[str, Any] = {"inner": self._inner.state_dict()}
        if self._head is not None:
            state["head"] = self._head.state_dict()
        state["own_errors"] = list(self._own_errors)
        state["top_errors"] = list(self._top_errors)
        state["content_errors"] = list(self._content_errors)
        state["blend_errors"] = list(self._blend_errors)
        return state

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore inner model + head + error windows from a state_dict() snapshot."""
        # Always restore the inner model. Legacy snapshots have no "inner" key.
        self._inner.load_state_dict(state.get("inner", state))

        # Restore the head if the snapshot has one.
        head_state = state.get("head")
        if head_state is not None:
            output_dim = head_state.get("output_dim")
            if output_dim is not None and output_dim > 0:
                if self._head is None:
                    self._head = TopDownHead(output_dim, lr=self._lr)
                self._head.load_state_dict(head_state)

        # Restore error windows.
        for key, deq in [
            ("own_errors", self._own_errors),
            ("top_errors", self._top_errors),
            ("content_errors", self._content_errors),
            ("blend_errors", self._blend_errors),
        ]:
            values = state.get(key)
            if isinstance(values, list):
                deq.clear()
                deq.extend(values[-self._window :])

        # Clear transient blend state (formed from the next step).
        self._clear_formed_state()

    def matches_state_shape(self, state: dict[str, Any]) -> bool:
        """True when the snapshot's structure fits this blend's inner model."""
        inner_state = state.get("inner", state)
        checker = getattr(self._inner, "matches_state_shape", None)
        if callable(checker):
            return checker(inner_state)
        return True

    def state_shape_mismatch(self, state: dict[str, Any]) -> str | None:
        """Explain why a snapshot doesn't fit, or None when it fits."""
        inner_state = state.get("inner", state)
        explainer = getattr(self._inner, "state_shape_mismatch", None)
        if callable(explainer):
            return explainer(inner_state)
        checker = getattr(self._inner, "matches_state_shape", None)
        if callable(checker) and not checker(inner_state):
            return "inner model state shape mismatch"
        return None
