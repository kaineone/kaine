# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Auditory forward model for Audition.

Predicts the next auditory feature vector (emotion-class distribution +
utterance timing/energy features) from a compact recurrent auditory buffer.
Adapts online with a single small gradient step per utterance; skips any
non-finite update (non-finite guard).

Design constraints (matching the Topos LatentForwardModel and Chronos
ForwardPredictionHead pattern)
-----------------------------------------------------------------------
- CPU-only: all tensors stay on CPU regardless of host hardware.
- Zero raw-sense-data persistence: ``state_dict()`` / ``load_state_dict()``
  serialise only weight and bias tensors.  The auditory buffer is summarised
  as per-feature mean and variance only — never raw audio or raw embeddings.
- Non-finite guard: adaptation is skipped when the loss or any gradient is
  non-finite, protecting against degenerate inputs.
- Adaptation can be suspended externally (e.g. during Hypnos sleep) by
  setting ``suspended = True``.
"""
from __future__ import annotations

import logging
import math
from collections import deque
from typing import Any, Optional

log = logging.getLogger(__name__)

# Default learning rate for online adaptation.
_DEFAULT_LR: float = 1e-3

# Feature-vector layout
# ---------------------
# The compact auditory feature vector has the following structure:
#   [0..N_CAT-1]  : softmax emotion-class distribution (N_CAT floats)
#   [N_CAT]       : utterance duration in seconds
#   [N_CAT+1]     : mean RMS energy (linear)
#
# By convention N_CAT = 7 (matches CATEGORIES in emotion.py).
N_EMOTION_CATEGORIES: int = 7
TIMING_ENERGY_DIM: int = 2        # duration_s, mean_energy
FEATURE_DIM: int = N_EMOTION_CATEGORIES + TIMING_ENERGY_DIM  # = 9


class AuditoryForwardModel:
    """Shallow MLP that predicts the next auditory feature vector.

    Architecture
    ------------
    Input: current feature vector (``feature_dim``-d) concatenated with the
    mean-pooled recurrent buffer context (also ``feature_dim``-d) →
    a hidden layer of size ``units`` → output projection back to
    ``feature_dim``.  All on CPU.

    The recurrent auditory buffer is a bounded deque of recent feature
    vectors.  Its mean is computed on each step to form the temporal
    context fed to the MLP.  The buffer itself is NEVER serialised raw;
    only per-feature mean and variance are persisted.
    """

    def __init__(
        self,
        feature_dim: int = FEATURE_DIM,
        units: int = 32,
        *,
        auditory_buffer_size: int = 16,
        lr: float = _DEFAULT_LR,
        seed: Optional[int] = None,
    ) -> None:
        if feature_dim <= 0:
            raise ValueError("feature_dim must be positive")
        if units <= 0:
            raise ValueError("units must be positive")
        if auditory_buffer_size < 1:
            raise ValueError("auditory_buffer_size must be >= 1")
        if lr <= 0:
            raise ValueError("lr must be positive")

        import torch
        import torch.nn as nn

        if seed is not None:
            torch.manual_seed(seed)

        self._torch = torch
        self._feature_dim = int(feature_dim)
        self._units = int(units)
        self._auditory_buffer_size = int(auditory_buffer_size)
        self._lr = float(lr)

        # MLP: [feature ‖ buffer_mean] → hidden → feature prediction.
        input_dim = 2 * self._feature_dim
        self._net = nn.Sequential(
            nn.Linear(input_dim, self._units),
            nn.Tanh(),
            nn.Linear(self._units, self._feature_dim),
        )
        self._net.train()
        self._optim = torch.optim.SGD(self._net.parameters(), lr=self._lr)

        # Recurrent auditory buffer — holds recent feature vectors.
        self._buffer: deque[list[float]] = deque(maxlen=self._auditory_buffer_size)

        # Most-recent prediction (for computing error on the next step).
        self._last_prediction: Optional[list[float]] = None

        self.suspended: bool = False

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def feature_dim(self) -> int:
        return self._feature_dim

    @property
    def units(self) -> int:
        return self._units

    @property
    def auditory_buffer_size(self) -> int:
        return self._auditory_buffer_size

    # ------------------------------------------------------------------
    # Core per-step interface
    # ------------------------------------------------------------------

    def _buffer_mean(self) -> list[float]:
        """Return per-feature mean of the auditory buffer.

        Returns a zero vector when the buffer is empty (first utterance).
        """
        if not self._buffer:
            return [0.0] * self._feature_dim
        dim = self._feature_dim
        mean = [0.0] * dim
        for vec in self._buffer:
            for i, v in enumerate(vec):
                mean[i] += v
        n = len(self._buffer)
        return [v / n for v in mean]

    def _net_input(self, feature: list[float]) -> Any:
        """Build the concatenated [feature ‖ buffer_mean] tensor."""
        torch = self._torch
        buf_mean = self._buffer_mean()
        combined = feature + buf_mean
        return torch.tensor(combined, dtype=torch.float32)

    def predict(self, feature: list[float]) -> list[float]:
        """Predict the next feature vector given the current feature and buffer context.

        Does NOT update the buffer or adapt weights — call ``step()`` for that.
        """
        torch = self._torch
        with torch.no_grad():
            x = self._net_input(feature)
            out = self._net(x)
        return [float(v) for v in out.tolist()]

    def step(self, feature: list[float]) -> float:
        """Full online step for one utterance.

        1. Computes the prediction error against the prior prediction.
        2. Appends *feature* to the buffer.
        3. Makes a new prediction for the NEXT utterance.
        4. Adapts the MLP toward *feature* from the prior input (if not
           suspended and all values are finite).

        Returns the L2 prediction error ``||feature − last_prediction||``
        (0.0 on the very first utterance when there is no prior prediction).
        """
        # 1. Compute prediction error from the previous step's prediction.
        if self._last_prediction is None:
            prediction_error = 0.0
        else:
            diffs = [
                (a - b) ** 2
                for a, b in zip(feature, self._last_prediction)
            ]
            prediction_error = math.sqrt(sum(diffs))

        # Adaptation (before we update the buffer, so the MLP trains
        # on the same context it used to predict).
        if not self.suspended and self._last_prediction is not None:
            self._adapt_toward(feature)

        # 2. Append current feature to the buffer.
        self._buffer.append(list(feature))

        # 3. Make a new prediction for the next utterance.
        self._last_prediction = self.predict(feature)

        return prediction_error

    def _adapt_toward(self, target_feature: list[float]) -> float:
        """One SGD step toward target_feature; returns MSE loss (float).

        Skips the update if the loss or any gradient is non-finite.
        The MLP input uses the buffer state BEFORE this feature was appended
        (which matches what the last prediction was based on).
        """
        torch = self._torch
        # Buffer has not been updated yet, so _net_input uses the state
        # that produced the previous prediction.  We use the buffer's last
        # entry as the input feature, falling back to zero if empty.
        if self._buffer:
            prev_feature = list(self._buffer[-1])
        else:
            prev_feature = [0.0] * self._feature_dim
        x = self._net_input(prev_feature)
        t = torch.tensor(target_feature, dtype=torch.float32)

        self._optim.zero_grad()
        pred = self._net(x)
        loss = ((pred - t) ** 2).mean()
        loss_val = float(loss.item())

        if not math.isfinite(loss_val):
            log.warning(
                "AuditoryForwardModel: non-finite loss %.6g; skipping update",
                loss_val,
            )
            return 0.0

        loss.backward()

        # Non-finite gradient guard
        for p in self._net.parameters():
            if p.grad is not None and not torch.isfinite(p.grad).all():
                log.warning(
                    "AuditoryForwardModel: non-finite gradient; skipping update"
                )
                self._optim.zero_grad()
                return 0.0

        self._optim.step()
        return loss_val

    def prediction_error_to_salience(
        self,
        raw_error: float,
        baseline_salience: float,
        alert_salience: float,
        *,
        error_window: Optional[list[float]] = None,
    ) -> float:
        """Map a raw L2 prediction error to a salience value in [baseline, alert].

        When *error_window* is provided (a rolling list of recent errors),
        the raw error is normalised against the window mean before scaling;
        an error twice the mean maps to alert_salience.  When the window is
        empty or the mean is zero, the raw error is clamped to [0, 1] and
        used directly to interpolate.
        """
        if not math.isfinite(raw_error) or raw_error < 0.0:
            return baseline_salience

        if error_window:
            mean_err = sum(error_window) / len(error_window)
            if mean_err > 0.0:
                # Normalise: 0 = no surprise, 1 = mean surprise, 2+ = high surprise.
                # Clamp to [0, 1] mapping.
                ratio = min(raw_error / (2.0 * mean_err), 1.0)
            else:
                ratio = 0.0
        else:
            # No window yet — use a simple clamp; feature vectors are in [0, 1]
            # so L2 over 9 dims maxes near sqrt(9) = 3.
            ratio = min(raw_error / 3.0, 1.0)

        return baseline_salience + ratio * (alert_salience - baseline_salience)

    # ------------------------------------------------------------------
    # Serialisation — weights only; buffer as statistical summary.
    # ------------------------------------------------------------------

    def state_dict(self) -> dict[str, Any]:
        """Return serialisable MLP weight tensors (no raw feature data)."""
        import torch.nn as nn

        layers: list[dict[str, Any]] = []
        for module in self._net:
            if isinstance(module, nn.Linear):
                layers.append(
                    {
                        "weight": module.weight.detach().cpu().tolist(),
                        "bias": module.bias.detach().cpu().tolist(),
                    }
                )
        return {"layers": layers}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore MLP weights from a ``state_dict()`` snapshot."""
        torch = self._torch
        import torch.nn as nn

        layers = state.get("layers", [])
        layer_idx = 0
        for module in self._net:
            if isinstance(module, nn.Linear):
                if layer_idx >= len(layers):
                    break
                layer_data = layers[layer_idx]
                weight = torch.tensor(layer_data["weight"], dtype=torch.float32)
                bias = torch.tensor(layer_data["bias"], dtype=torch.float32)
                with torch.no_grad():
                    module.weight.copy_(weight)
                    module.bias.copy_(bias)
                layer_idx += 1

    def buffer_summary(self) -> dict[str, Any]:
        """Return a statistical descriptor of the auditory buffer.

        Contains only per-feature mean and variance — never raw feature
        vectors.  This satisfies the zero raw-sense-data persistence
        requirement.
        """
        if not self._buffer:
            return {
                "n_utterances": 0,
                "mean": [0.0] * self._feature_dim,
                "variance": [0.0] * self._feature_dim,
            }
        n = len(self._buffer)
        dim = self._feature_dim

        # Per-feature mean
        mean = [0.0] * dim
        for vec in self._buffer:
            for i, v in enumerate(vec):
                mean[i] += v
        mean = [v / n for v in mean]

        # Per-feature variance (population)
        var = [0.0] * dim
        if n > 1:
            for vec in self._buffer:
                for i, v in enumerate(vec):
                    diff = v - mean[i]
                    var[i] += diff * diff
            var = [v / n for v in var]

        return {
            "n_utterances": n,
            "mean": mean,
            "variance": var,
        }


def build_feature_vector(
    emotion_scores: dict[str, float],
    categories: tuple[str, ...],
    *,
    duration_s: float = 0.0,
    mean_energy: float = 0.0,
) -> list[float]:
    """Construct the compact auditory feature vector from classification outputs.

    Layout: [emotion_cat_0, ..., emotion_cat_N-1, duration_s, mean_energy]

    All values are expected to be in [0, 1]. The caller is responsible for
    normalising duration and energy if needed.
    """
    dist = [float(emotion_scores.get(c, 0.0)) for c in categories]
    return dist + [float(duration_s), float(mean_energy)]
