# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Latent forward model for Topos.

Predicts the next visual latent vector from the current latent and a
recurrent visual buffer.  Adapts online with a single small gradient step
per produced clip latent; skips any non-finite update (non-finite guard).
The latent dimension follows the active encoder (``latent_dim`` — 768 for the
default InternVideo-Next clip encoder, 384 for the DINOv2 fallback); nothing
here hardcodes a dimension.

Design constraints (matching the Chronos ForwardPredictionHead pattern)
-----------------------------------------------------------------------
- CPU-only: all tensors stay on CPU regardless of host hardware.
- Zero raw-sense-data persistence: ``state_dict()`` / ``load_state_dict()``
  serialise only weight and bias tensors, never raw latent buffers.  The
  visual buffer is summarised as per-feature mean and variance only.
- Non-finite guard: adaptation is skipped when the loss or any gradient is
  non-finite, protecting against degenerate inputs.
- Adaptation can be suspended externally (e.g. during Hypnos sleep) by
  setting ``suspended = True``.
- The visual encoder is NEVER touched by this module — it is frozen by its
  own class and nothing here requests gradients for it.
"""
from __future__ import annotations

import logging
import math
from collections import deque
from typing import Any, Optional

log = logging.getLogger(__name__)

# Default learning rate for online adaptation.
_DEFAULT_LR: float = 1e-3


class LatentForwardModel:
    """Shallow MLP that predicts the next visual latent from the current one.

    Architecture
    ------------
    Input: current latent (``latent_dim``-d) concatenated with the
    mean-pooled recurrent buffer context (also ``latent_dim``-d) →
    a hidden layer of size ``units`` → output projection back to
    ``latent_dim``.  All on CPU.

    The recurrent visual buffer is a bounded deque of recent latent
    vectors.  Its mean is computed on each step to form the temporal
    context fed to the MLP.  The buffer itself is NEVER serialised raw;
    only per-feature mean and variance are persisted.
    """

    def __init__(
        self,
        latent_dim: int,
        units: int = 128,
        *,
        visual_buffer_size: int = 16,
        lr: float = _DEFAULT_LR,
        seed: Optional[int] = None,
    ) -> None:
        if latent_dim <= 0:
            raise ValueError("latent_dim must be positive")
        if units <= 0:
            raise ValueError("units must be positive")
        if visual_buffer_size < 1:
            raise ValueError("visual_buffer_size must be >= 1")
        if lr <= 0:
            raise ValueError("lr must be positive")

        import torch
        import torch.nn as nn

        if seed is not None:
            torch.manual_seed(seed)

        self._torch = torch
        self._latent_dim = int(latent_dim)
        self._units = int(units)
        self._visual_buffer_size = int(visual_buffer_size)
        self._lr = float(lr)

        # MLP: [latent ‖ buffer_mean] → hidden → latent prediction.
        # Input dimension is 2 * latent_dim (current latent + buffer mean).
        input_dim = 2 * self._latent_dim
        self._net = nn.Sequential(
            nn.Linear(input_dim, self._units),
            nn.Tanh(),
            nn.Linear(self._units, self._latent_dim),
        )
        self._net.train()
        self._optim = torch.optim.SGD(self._net.parameters(), lr=self._lr)

        # Recurrent visual buffer — holds recent latent vectors.
        self._buffer: deque[list[float]] = deque(maxlen=self._visual_buffer_size)

        # Most-recent prediction (for computing error on the next step).
        self._last_prediction: Optional[list[float]] = None

        self.suspended: bool = False

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def latent_dim(self) -> int:
        return self._latent_dim

    @property
    def units(self) -> int:
        return self._units

    @property
    def visual_buffer_size(self) -> int:
        return self._visual_buffer_size

    # ------------------------------------------------------------------
    # Core per-step interface
    # ------------------------------------------------------------------

    def _buffer_mean(self) -> list[float]:
        """Return per-feature mean of the visual buffer.

        Returns a zero vector when the buffer is empty (first frame).
        """
        if not self._buffer:
            return [0.0] * self._latent_dim
        dim = self._latent_dim
        mean = [0.0] * dim
        for vec in self._buffer:
            for i, v in enumerate(vec):
                mean[i] += v
        n = len(self._buffer)
        return [v / n for v in mean]

    def _net_input(self, latent: list[float]) -> Any:
        """Build the concatenated [latent ‖ buffer_mean] tensor."""
        torch = self._torch
        buf_mean = self._buffer_mean()
        combined = latent + buf_mean
        return torch.tensor(combined, dtype=torch.float32)

    def predict(self, latent: list[float]) -> list[float]:
        """Predict the next latent given the current latent and buffer context.

        Does NOT update the buffer or adapt weights — call ``step()`` for that.
        """
        torch = self._torch
        with torch.no_grad():
            x = self._net_input(latent)
            out = self._net(x)
        return [float(v) for v in out.tolist()]

    def step(self, latent: list[float]) -> float:
        """Full online step for one frame.

        1. Computes the prediction error against the prior prediction.
        2. Appends *latent* to the buffer.
        3. Makes a new prediction for the NEXT frame.
        4. Adapts the MLP toward *latent* from the prior input (if not
           suspended and all values are finite).

        Returns the L2 prediction error ``||latent − last_prediction||``
        (0.0 on the very first frame when there is no prior prediction).
        """
        # 1. Compute prediction error from the previous step's prediction.
        if self._last_prediction is None:
            prediction_error = 0.0
        else:
            diffs = [
                (a - b) ** 2
                for a, b in zip(latent, self._last_prediction)
            ]
            prediction_error = math.sqrt(sum(diffs))

        # --- adaptation (before we update the buffer, so the MLP trains
        # on the same context it used to predict) ---
        if not self.suspended and self._last_prediction is not None:
            # Build input using the buffer state at prediction time
            # (buffer was not yet updated for this latent).
            self._adapt_toward(latent)

        # 2. Append current latent to the buffer.
        self._buffer.append(list(latent))

        # 3. Make a new prediction for the next frame (using the updated buffer).
        self._last_prediction = self.predict(latent)

        return prediction_error

    def _adapt_toward(self, target_latent: list[float]) -> float:
        """One SGD step toward target_latent; returns MSE loss (float).

        Skips the update if the loss or any gradient is non-finite.
        The MLP input uses the buffer state BEFORE this latent was appended
        (which matches what the last prediction was based on).
        """
        torch = self._torch
        # The buffer was NOT updated yet, so _net_input gives the same
        # context the previous prediction used.
        # However, we need the latent that was current when that prediction
        # was made — that is the second-to-last latent. We approximate by
        # using the buffer's last entry as the input latent, falling back
        # to the zero vector if the buffer is empty.
        if self._buffer:
            prev_latent = list(self._buffer[-1])
        else:
            prev_latent = [0.0] * self._latent_dim
        x = self._net_input(prev_latent)
        t = torch.tensor(target_latent, dtype=torch.float32)

        self._optim.zero_grad()
        pred = self._net(x)
        loss = ((pred - t) ** 2).mean()
        loss_val = float(loss.item())

        if not math.isfinite(loss_val):
            log.warning(
                "LatentForwardModel: non-finite loss %.6g; skipping update",
                loss_val,
            )
            return 0.0

        loss.backward()

        # Non-finite gradient guard
        for p in self._net.parameters():
            if p.grad is not None and not torch.isfinite(p.grad).all():
                log.warning(
                    "LatentForwardModel: non-finite gradient; skipping update"
                )
                self._optim.zero_grad()
                return 0.0

        self._optim.step()
        return loss_val

    # ------------------------------------------------------------------
    # Serialisation — weights only; buffer as statistical summary.
    # ------------------------------------------------------------------

    def state_dict(self) -> dict[str, Any]:
        """Return serialisable MLP weight tensors (no raw latent data)."""
        layers: list[dict[str, Any]] = []
        for module in self._net:
            import torch.nn as nn

            if isinstance(module, nn.Linear):
                layers.append(
                    {
                        "weight": module.weight.detach().cpu().tolist(),
                        "bias": module.bias.detach().cpu().tolist(),
                    }
                )
        return {"layers": layers}

    def matches_state_shape(self, state: dict[str, Any]) -> bool:
        """Whether a ``state_dict()`` snapshot's tensor shapes fit this model.

        Guards the dim cascade (topos-temporal-video-encoder §3): a checkpoint
        sized to a different encoder ``latent_dim`` (input ``2*latent_dim`` →
        hidden ``units`` → output ``latent_dim``) must be detected BEFORE any
        ``copy_``, so a mismatch is discarded rather than raising. Returns False
        on any malformed/short layer list too."""
        layers = state.get("layers")
        if not isinstance(layers, list) or len(layers) < 2:
            return False
        try:
            first_w = layers[0]["weight"]
            last_w = layers[-1]["weight"]
            in_units = len(first_w)  # hidden width
            in_dim = len(first_w[0])  # 2 * latent_dim
            out_dim = len(last_w)  # latent_dim
        except (KeyError, TypeError, IndexError):
            return False
        return (
            in_units == self._units
            and in_dim == 2 * self._latent_dim
            and out_dim == self._latent_dim
        )

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
        """Return a statistical descriptor of the visual buffer.

        Contains only per-feature mean and variance — never raw latent
        vectors.  This satisfies the zero raw-sense-data persistence
        requirement.
        """
        if not self._buffer:
            return {
                "n_frames": 0,
                "mean": [0.0] * self._latent_dim,
                "variance": [0.0] * self._latent_dim,
            }
        n = len(self._buffer)
        dim = self._latent_dim

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
            "n_frames": n,
            "mean": mean,
            "variance": var,
        }
