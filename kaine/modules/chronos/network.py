# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CfC wrapper for Chronos.

Imports torch / ncps lazily so the rest of the chronos package can be
tested without those deps installed. CPU-only by policy — the CfC is
small enough that GPU offers no benefit, and pinning CPU keeps the
cycle's tick budget predictable.

The reservoir is generated in NumPy and shared between backends; the numpy
backend needs no torch at all.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

from kaine.cfc_numpy import draw_reservoir_seed, load_reservoir_into_ncps

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
    - ``backend="numpy"`` needs no torch and matches the torch
      path to 1e-5 from the same seed.
    """

    def __init__(
        self,
        input_size: int,
        units: int,
        *,
        lr: float = _DEFAULT_ADAPTATION_LR,
        seed: Optional[int] = None,
        backend: str = "numpy",
    ) -> None:
        if input_size <= 0 or units <= 0:
            raise ValueError("input_size and units must be positive")
        if lr <= 0:
            raise ValueError("lr must be positive")
        if backend not in ("numpy", "torch"):
            raise ValueError("backend must be 'numpy' or 'torch'")

        if seed is None:
            seed = draw_reservoir_seed()

        self._backend = backend
        self._input_size = int(input_size)
        self._units = int(units)
        self._lr = float(lr)

        from kaine.cfc_numpy import NumpyReadout, generate_cfc_weights

        # Consume the same reservoir draws the network uses, then draw the
        # readout.  This keeps the head's initial weights deterministic from
        # the shared seed and identical across backends.
        _, readout_init = generate_cfc_weights(
            seed, self._input_size, self._units, self._input_size
        )

        if backend == "torch":
            import torch
            import torch.nn as nn

            self._torch = torch
            self._head = nn.Linear(units, input_size)
            with torch.no_grad():
                self._head.weight.copy_(torch.from_numpy(readout_init.W))
                self._head.bias.copy_(torch.from_numpy(readout_init.b))
            self._head.train()
            self._optim = torch.optim.SGD(self._head.parameters(), lr=self._lr)
        else:
            self._torch = None
            self._head = NumpyReadout.from_arrays(readout_init.W, readout_init.b)

        # Last hidden state used to produce a prediction; stored between ticks.
        self._last_hidden: Optional[Any] = None
        self.suspended: bool = False

    @property
    def input_size(self) -> int:
        return self._input_size

    @property
    def units(self) -> int:
        return self._units

    @property
    def lr(self) -> float:
        return self._lr

    @property
    def backend(self) -> str:
        return self._backend

    def predict(self, hidden: list[float]) -> list[float]:
        """Return the predicted next feature vector given the current hidden state."""
        if self._backend == "numpy":
            return self._head.predict(hidden)

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

        if self._backend == "numpy":
            loss = self._head.sgd_step(hidden, target_feature, self._lr)
            if not math.isfinite(loss):
                log.warning(
                    "ForwardPredictionHead: non-finite loss or gradient; skipping update"
                )
                return 0.0
            return loss

        torch = self._torch
        h = torch.tensor(hidden, dtype=torch.float32)
        t = torch.tensor(target_feature, dtype=torch.float32)
        self._optim.zero_grad()
        pred = self._head(h)
        loss = ((pred - t) ** 2).mean()
        loss_val = float(loss.item())
        if not math.isfinite(loss_val):
            log.warning(
                "ForwardPredictionHead: non-finite loss or gradient; skipping update"
            )
            return 0.0
        loss.backward()
        # Non-finite gradient guard
        for p in self._head.parameters():
            if p.grad is not None and not torch.isfinite(p.grad).all():
                log.warning(
                    "ForwardPredictionHead: non-finite loss or gradient; skipping update"
                )
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
        if self._backend == "numpy":
            return self._head.state_dict()
        return {
            "weight": self._head.weight.detach().cpu().tolist(),
            "bias": self._head.bias.detach().cpu().tolist(),
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore weights from a ``state_dict()`` snapshot."""
        if self._backend == "numpy":
            self._head.load_state_dict(state)
            return
        torch = self._torch
        weight = torch.tensor(state["weight"], dtype=torch.float32)
        bias = torch.tensor(state["bias"], dtype=torch.float32)
        with torch.no_grad():
            self._head.weight.copy_(weight)
            self._head.bias.copy_(bias)


class CfCNetwork:
    """Stateful per-step wrapper around the CfC reservoir."""

    def __init__(
        self,
        input_size: int = 24,
        units: int = 32,
        seed: Optional[int] = None,
        backend: str = "numpy",
    ) -> None:
        if input_size <= 0 or units <= 0:
            raise ValueError("input_size and units must be positive")
        if backend not in ("numpy", "torch"):
            raise ValueError("backend must be 'numpy' or 'torch'")

        if seed is None:
            seed = draw_reservoir_seed()

        self._backend = backend
        self._input_size = int(input_size)
        self._units = int(units)
        self.reservoir_seed = int(seed)

        from kaine.cfc_numpy import generate_cfc_weights

        self._reservoir, self._readout_init = generate_cfc_weights(
            seed, self._input_size, self._units, self._input_size
        )

        if backend == "torch":
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

            import torch
            from ncps.torch import CfC  # type: ignore[import-untyped]

            self._torch = torch
            self._device = device
            self._net = CfC(input_size, units, batch_first=True)
            load_reservoir_into_ncps(self._net, self._reservoir, torch)
            self._net.to(device)
            self._net.eval()
            for p in self._net.parameters():
                p.requires_grad_(False)
        else:
            self._torch = None
            self._device = "cpu"
            self._net = None

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

    @property
    def backend(self) -> str:
        return self._backend

    def parameter_count(self) -> int:
        if self._backend == "numpy":
            return int(
                sum(
                    arr.size
                    for arr in (
                        self._reservoir.backbone_w,
                        self._reservoir.backbone_b,
                        self._reservoir.ff1_w,
                        self._reservoir.ff1_b,
                        self._reservoir.ff2_w,
                        self._reservoir.ff2_b,
                        self._reservoir.time_a_w,
                        self._reservoir.time_a_b,
                        self._reservoir.time_b_w,
                        self._reservoir.time_b_b,
                    )
                )
            )
        return int(sum(p.numel() for p in self._net.parameters()))

    def reset(self) -> None:
        self._hx = None

    def load_state(self, state: dict[str, Any]) -> None:
        """Rebuild the reservoir from a persisted seed."""
        seed = state.get("reservoir_seed")
        if seed is None:
            return
        self.reservoir_seed = int(seed)
        from kaine.cfc_numpy import generate_cfc_weights

        self._reservoir, self._readout_init = generate_cfc_weights(
            self.reservoir_seed, self._input_size, self._units, self._input_size
        )
        if self._backend == "torch":
            import torch
            from ncps.torch import CfC  # type: ignore[import-untyped]

            self._net = CfC(self._input_size, self._units, batch_first=True)
            load_reservoir_into_ncps(self._net, self._reservoir, torch)
            self._net.to(self._device)
            self._net.eval()
            for p in self._net.parameters():
                p.requires_grad_(False)
        self._hx = None

    accepts_timespan: bool = True

    def tick(
        self,
        feature_vec: list[float],
        timespan: float = 1.0,
    ) -> list[float]:
        if len(feature_vec) != self._input_size:
            raise ValueError(
                f"expected {self._input_size}-dim input, got {len(feature_vec)}"
            )
        if self._backend == "numpy":
            from kaine.cfc_numpy import numpy_cfc_step

            h = self._hx if self._hx is not None else [0.0] * self._units
            self._hx = numpy_cfc_step(self._reservoir, feature_vec, h, ts=timespan)
            return self._hx

        torch = self._torch
        with torch.no_grad():
            x = torch.tensor(feature_vec, dtype=torch.float32, device=self._device)
            x = x.view(1, 1, -1)
            out, hx = self._net(
                x,
                hx=self._hx,
                timespans=torch.tensor(
                    [[float(timespan)]], dtype=torch.float32, device=self._device
                ),
            )
            self._hx = hx
            hidden = out.view(-1).tolist()
        return [float(v) for v in hidden]
