# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Soma on wetware: interoceptive forward model.

The biological substrate replaces Soma's frozen CfC reservoir; the readout
stays a small online linear model so prediction error keeps the silicon
semantics (L2 in feature space) that Soma's salience, fatigue and warm-up depend
on.  See `openspec/changes/soma-on-wetware/`.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional, Sequence

import numpy as np

from kaine_cl1.substrate.broker import ChannelTerritory, SubstrateBroker
from kaine_cl1.substrate.codec import FiringRateDecoder, PopulationEncoder

log = logging.getLogger(__name__)


class WetwareInteroceptiveModel:
    """Drop-in for Soma's `forward_model=` (silicon CfC reservoir + readout).

    The biological substrate replaces the frozen recurrent reservoir; the
    readout remains a tiny linear head trained online so prediction-error
    semantics stay identical to silicon.
    """

    def __init__(
        self,
        broker: SubstrateBroker,
        territory: ChannelTerritory,
        *,
        feature_dim: int = 8,
        lr: float = 1e-3,
        max_uA: float = 3.0,
        hidden_scale: float = 12.0,
    ) -> None:
        if feature_dim <= 0:
            raise ValueError(f"feature_dim must be positive, got {feature_dim}")
        if lr <= 0.0:
            raise ValueError(f"lr must be positive, got {lr}")
        self._broker = broker
        self._module = territory.module
        self._channels = territory.channels
        self._encoder = PopulationEncoder(self._channels, max_uA=max_uA)
        self._decoder = FiringRateDecoder(self._channels)
        self._hidden_scale = float(hidden_scale)
        self._lr = float(lr)
        units = len(self._channels)
        self._W = np.zeros((feature_dim, units))
        self._b = np.zeros(feature_dim)
        self._adaptation_steps = 0
        self._last_hidden: Optional[np.ndarray] = None
        self._last_prediction: Optional[np.ndarray] = None
        self.suspended = False

    @property
    def feature_dim(self) -> int:
        return int(self._W.shape[0])

    @property
    def units(self) -> int:
        return len(self._channels)

    @property
    def adaptation_steps(self) -> int:
        return self._adaptation_steps

    def _encode(self, feature: Sequence[float]) -> list[float]:
        """Map the feature vector onto one clamped value per channel."""
        n = self.feature_dim
        units = self.units
        out = []
        for i in range(units):
            idx = (i * n) // units
            val = float(feature[idx])
            out.append(max(0.0, min(1.0, val)))
        return out

    def _substrate_tick(self, feature: Sequence[float]) -> np.ndarray:
        """Run one cognitive tick and return the decoded hidden state.

        In beat mode the returned observation is the territory's latest completed
        window, so the response to this step's stimulation arrives one tick later.
        """
        obs = self._broker.exchange(self._module, self._encoder.encode(self._encode(feature)))
        return self._decoder.decode(obs.spikes) / self._hidden_scale

    def _sgd_step(self, hidden: np.ndarray, target: np.ndarray) -> bool:
        """One SGD step of the readout toward `target` from `hidden`.

        Returns True if the weights were updated, False if the step was skipped.
        """
        pred = self._W @ hidden + self._b
        err = pred - target
        loss = float(np.mean(err * err))
        if not math.isfinite(loss):
            log.warning("Soma readout loss is non-finite; skipping SGD step")
            return False
        fd = self.feature_dim
        grad_W = (2.0 / fd) * np.outer(err, hidden)
        grad_b = (2.0 / fd) * err
        if not np.isfinite(grad_W).all() or not np.isfinite(grad_b).all():
            log.warning("Soma readout gradients are non-finite; skipping SGD step")
            return False
        self._W -= self._lr * grad_W
        self._b -= self._lr * grad_b
        return True

    def step(self, feature: Sequence[float]) -> float:
        """Step the model, adapt the readout, and return the prediction error."""
        if len(feature) != self.feature_dim:
            raise ValueError(f"expected {self.feature_dim}-dim input, got {len(feature)}")
        feature_arr = np.asarray(feature, dtype=float)
        if not np.isfinite(feature_arr).all():
            log.warning("Soma received non-finite input; returning 0.0 without stepping")
            return 0.0
        if self._last_prediction is None:
            prediction_error = 0.0
        else:
            prediction_error = float(np.linalg.norm(feature_arr - self._last_prediction))
        if not self.suspended and self._last_hidden is not None:
            if self._sgd_step(self._last_hidden, feature_arr):
                self._adaptation_steps += 1
        new_hidden = self._substrate_tick(feature)
        self._last_prediction = self._W @ new_hidden + self._b
        self._last_hidden = new_hidden
        return prediction_error

    def prediction_error_to_salience(
        self,
        raw_error: float,
        baseline_salience: float,
        alert_salience: float,
        *,
        error_window: Optional[Sequence[float]] = None,
    ) -> float:
        if not math.isfinite(raw_error) or raw_error < 0.0:
            return baseline_salience
        if error_window:
            mean_err = sum(error_window) / len(error_window)
            ratio = min(raw_error / (2.0 * mean_err), 1.0) if mean_err > 0.0 else 0.0
        else:
            ratio = min(raw_error / 3.0, 1.0)
        return baseline_salience + ratio * (alert_salience - baseline_salience)

    def reset(self) -> None:
        """Clear the readout's running state."""
        self._last_hidden = None
        self._last_prediction = None

    def state_dict(self) -> dict[str, Any]:
        return {"weight": self._W.tolist(), "bias": self._b.tolist()}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        expected_w = (self.feature_dim, self.units)
        expected_b = (self.feature_dim,)
        new_W = np.asarray(state["weight"], dtype=float)
        new_b = np.asarray(state["bias"], dtype=float)
        if new_W.shape != expected_w or new_b.shape != expected_b:
            raise ValueError(
                f"expected state shapes {expected_w} for weight and {expected_b} for bias, "
                f"got {new_W.shape} and {new_b.shape}"
            )
        if not np.isfinite(new_W).all() or not np.isfinite(new_b).all():
            raise ValueError("state contains non-finite values")
        self._W = new_W.copy()
        self._b = new_b.copy()
