# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CfC wrapper for Chronos.

Imports torch / ncps lazily so the rest of the chronos package can be
tested without those deps installed. CPU-only by policy — the CfC is
small enough that GPU offers no benefit, and pinning CPU keeps the
cycle's tick budget predictable.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

log = logging.getLogger(__name__)

# Default learning rate for online adaptation of the prediction head.
# Small enough not to destabilise the head between ticks; large enough
# to track a stable cadence within a few hundred observations.
_DEFAULT_ADAPTATION_LR: float = 1e-3


class ForwardPredictionHead:
    """Linear head that predicts the next temporal feature vector.

    The head is a single-layer linear map from the CfC hidden state
    (dimension *units*) to the feature space (dimension *input_size*).
    It adapts online via SGD with a small fixed learning rate.

    Design constraints
    ------------------
    - CPU-only: all tensors stay on CPU regardless of host hardware.
    - Zero raw-sense-data persistence: ``state_dict()`` / ``load_state_dict()``
      serialise only weight and bias tensors, never raw feature buffers.
    - Non-finite guard: adaptation is skipped when the loss or any gradient
      is non-finite, protecting against degenerate inputs.
    - Adaptation can be suspended externally (e.g. during Hypnos sleep) by
      setting ``suspended = True``.
    """

    def __init__(
        self,
        input_size: int,
        units: int,
        *,
        lr: float = _DEFAULT_ADAPTATION_LR,
        seed: Optional[int] = None,
    ) -> None:
        if input_size <= 0 or units <= 0:
            raise ValueError("input_size and units must be positive")
        if lr <= 0:
            raise ValueError("lr must be positive")

        import torch
        import torch.nn as nn

        if seed is not None:
            torch.manual_seed(seed)

        self._torch = torch
        self._input_size = int(input_size)
        self._units = int(units)
        self._lr = float(lr)
        # Linear: hidden → feature prediction
        self._head = nn.Linear(units, input_size)
        self._head.train()
        self._optim = torch.optim.SGD(self._head.parameters(), lr=self._lr)
        # Last hidden state used to produce a prediction; stored between ticks.
        self._last_hidden: Optional[Any] = None
        self.suspended: bool = False

    @property
    def input_size(self) -> int:
        return self._input_size

    @property
    def units(self) -> int:
        return self._units

    def predict(self, hidden: list[float]) -> list[float]:
        """Return the predicted next feature vector given the current hidden state."""
        torch = self._torch
        with torch.no_grad():
            h = torch.tensor(hidden, dtype=torch.float32)
            pred = self._head(h)
        return [float(v) for v in pred.tolist()]

    def adapt(self, hidden: list[float], target_feature: list[float]) -> float:
        """Update head weights toward *target_feature* from *hidden* state.

        Returns the MSE loss value (as a plain Python float).  Returns 0.0
        and skips the update when adaptation is suspended or when the loss
        or any gradient is non-finite.
        """
        if self.suspended:
            return 0.0
        torch = self._torch
        h = torch.tensor(hidden, dtype=torch.float32)
        t = torch.tensor(target_feature, dtype=torch.float32)
        self._optim.zero_grad()
        pred = self._head(h)
        loss = ((pred - t) ** 2).mean()
        loss_val = float(loss.item())
        if not math.isfinite(loss_val):
            log.warning("ForwardPredictionHead: non-finite loss %.6g; skipping update", loss_val)
            return 0.0
        loss.backward()
        # Non-finite gradient guard
        for p in self._head.parameters():
            if p.grad is not None and not torch.isfinite(p.grad).all():
                log.warning("ForwardPredictionHead: non-finite gradient; skipping update")
                self._optim.zero_grad()
                return 0.0
        self._optim.step()
        return loss_val

    def prediction_error(self, predicted: list[float], actual: list[float]) -> float:
        """Return the mean absolute error between *predicted* and *actual*."""
        if len(predicted) != len(actual):
            raise ValueError("predicted and actual must have the same length")
        return sum(abs(p - a) for p, a in zip(predicted, actual)) / len(predicted)

    def state_dict(self) -> dict[str, Any]:
        """Return serialisable weight tensors (no raw feature data)."""
        torch = self._torch
        return {
            "weight": self._head.weight.detach().cpu().tolist(),
            "bias": self._head.bias.detach().cpu().tolist(),
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore weights from a ``state_dict()`` snapshot."""
        torch = self._torch
        weight = torch.tensor(state["weight"], dtype=torch.float32)
        bias = torch.tensor(state["bias"], dtype=torch.float32)
        with torch.no_grad():
            self._head.weight.copy_(weight)
            self._head.bias.copy_(bias)


class CfCNetwork:
    """Stateful per-step wrapper around `ncps.torch.CfC`."""

    def __init__(
        self,
        input_size: int = 24,
        units: int = 32,
        seed: Optional[int] = None,
    ) -> None:
        if input_size <= 0 or units <= 0:
            raise ValueError("input_size and units must be positive")
        from kaine.hardware import select_device

        device = select_device("cpu")
        if device != "cpu":
            log.warning(
                "Chronos requested cpu but select_device returned %s; "
                "Chronos pins to cpu regardless to keep the network small "
                "and the cycle predictable",
                device,
            )
            device = "cpu"

        # Lazy import so testing featurizer / anomaly / rumination doesn't
        # require torch to be installed.
        import torch
        from ncps.torch import CfC  # type: ignore[import-untyped]

        if seed is not None:
            torch.manual_seed(seed)
        self._torch = torch
        self._device = device
        self._units = int(units)
        self._input_size = int(input_size)
        self._net = CfC(input_size, units, batch_first=True).to(device)
        self._net.eval()
        for p in self._net.parameters():
            p.requires_grad_(False)
        self._hx: Optional[Any] = None

    @property
    def units(self) -> int:
        return self._units

    @property
    def input_size(self) -> int:
        return self._input_size

    @property
    def device(self) -> str:
        return self._device

    def parameter_count(self) -> int:
        return int(sum(p.numel() for p in self._net.parameters()))

    def reset(self) -> None:
        self._hx = None

    def tick(self, feature_vec: list[float]) -> list[float]:
        if len(feature_vec) != self._input_size:
            raise ValueError(
                f"expected {self._input_size}-dim input, got {len(feature_vec)}"
            )
        torch = self._torch
        with torch.no_grad():
            x = torch.tensor(feature_vec, dtype=torch.float32, device=self._device)
            x = x.view(1, 1, -1)
            out, hx = self._net(x, hx=self._hx)
            self._hx = hx
            hidden = out.view(-1).tolist()
        return [float(v) for v in hidden]
