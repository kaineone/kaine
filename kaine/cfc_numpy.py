# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""NumPy CfC reservoir, step, and readout shared by Soma and Chronos.

This module intentionally uses only NumPy (and the Python standard library)
so it can be imported on hosts without torch/ncps.  It replicates the default
``ncps.torch.CfC`` construction and forward pass in float32:

- LeCun-tanh backbone of 128 units / 1 layer,
- two tanh heads,
- sigmoid time gate at ts = 1.0,
- Xavier-uniform reservoir weights and uniform biases,
- linear readout with uniform ±1/√units initialisation and SGD on MSE.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np


@dataclass(frozen=True, slots=True)
class ReservoirWeights:
    """Frozen, NumPy-generated CfC reservoir weights.

    Shapes follow ``ncps.torch.CfCCell`` in default mode:

    - ``backbone_*``: ``Linear(input_size + units -> backbone_units)``
    - ``ff1_*``, ``ff2_*``, ``time_a_*``, ``time_b_*``:
      ``Linear(backbone_units -> units)``
    """

    input_size: int
    units: int
    backbone_units: int
    backbone_w: np.ndarray
    backbone_b: np.ndarray
    ff1_w: np.ndarray
    ff1_b: np.ndarray
    ff2_w: np.ndarray
    ff2_b: np.ndarray
    time_a_w: np.ndarray
    time_a_b: np.ndarray
    time_b_w: np.ndarray
    time_b_b: np.ndarray

    @classmethod
    def generate(
        cls,
        seed: int,
        input_size: int,
        units: int,
        backbone_units: int = 128,
    ) -> ReservoirWeights:
        """Draw a frozen reservoir from ``seed`` in ncps construction order."""
        rng = np.random.default_rng(seed)
        return cls._from_rng(rng, input_size, units, backbone_units)

    @classmethod
    def _from_rng(
        cls,
        rng: np.random.Generator,
        input_size: int,
        units: int,
        backbone_units: int = 128,
    ) -> ReservoirWeights:
        fan_in_bb = input_size + units
        backbone_w = _xavier(rng, backbone_units, fan_in_bb)
        backbone_b = _uniform_bias(rng, backbone_units, fan_in_bb)
        ff1_w = _xavier(rng, units, backbone_units)
        ff1_b = _uniform_bias(rng, units, backbone_units)
        ff2_w = _xavier(rng, units, backbone_units)
        ff2_b = _uniform_bias(rng, units, backbone_units)
        time_a_w = _xavier(rng, units, backbone_units)
        time_a_b = _uniform_bias(rng, units, backbone_units)
        time_b_w = _xavier(rng, units, backbone_units)
        time_b_b = _uniform_bias(rng, units, backbone_units)
        return cls(
            input_size,
            units,
            backbone_units,
            backbone_w,
            backbone_b,
            ff1_w,
            ff1_b,
            ff2_w,
            ff2_b,
            time_a_w,
            time_a_b,
            time_b_w,
            time_b_b,
        )


def _xavier(rng: np.random.Generator, out: int, in_: int) -> np.ndarray:
    bound = math.sqrt(6.0 / (in_ + out))
    return rng.uniform(-bound, bound, size=(out, in_)).astype(np.float32)


def _uniform_bias(rng: np.random.Generator, out: int, fan_in: int) -> np.ndarray:
    """nn.Linear's default bias: one value per output, uniform in +/-1/sqrt(fan_in)."""
    bound = 1.0 / math.sqrt(fan_in)
    return rng.uniform(-bound, bound, size=(out,)).astype(np.float32)


def draw_reservoir_seed() -> int:
    """Return a reservoir seed drawn from the legacy global NumPy RNG.

    The seed comes from the process's legacy global NumPy random state, which
    ``kaine.experiment.seeding.set_global_seed`` seeds, so a seeded experiment
    rebuilds the same reservoir; an unseeded process gets a fresh seed from
    NumPy's entropy-seeded state. The seed is not secret; it is persisted with
    the module's state.
    """
    return int(np.random.randint(0, 2**63 - 1, dtype=np.int64))


def generate_cfc_weights(
    seed: int,
    input_size: int,
    units: int,
    out: int,
    backbone_units: int = 128,
) -> tuple[ReservoirWeights, NumpyReadout]:
    """Generate a reservoir and an initial readout from the same seed.

    The readout weights are drawn *after* the reservoir so that Soma and
    Chronos can share one seed and still obtain the same readout initialisation
    as the torch path.
    """
    rng = np.random.default_rng(seed)
    reservoir = ReservoirWeights._from_rng(rng, input_size, units, backbone_units)
    readout = NumpyReadout(units, out, rng=rng)
    return reservoir, readout


class NumpyReadout:
    """NumPy linear readout with online SGD on MSE."""

    def __init__(
        self,
        units: int,
        out: int,
        rng: Optional[np.random.Generator] = None,
    ) -> None:
        if units <= 0 or out <= 0:
            raise ValueError("units and out must be positive")
        if rng is None:
            rng = np.random.default_rng()
        bound = 1.0 / math.sqrt(units)
        self.W = rng.uniform(-bound, bound, size=(out, units)).astype(np.float32)
        self.b = rng.uniform(-bound, bound, size=(out,)).astype(np.float32)
        self.units = int(units)
        self.out = int(out)

    @classmethod
    def from_arrays(cls, W: np.ndarray, b: np.ndarray) -> NumpyReadout:
        """Create a readout from existing weight/bias arrays."""
        self = cls.__new__(cls)
        self.W = np.asarray(W, dtype=np.float32)
        self.b = np.asarray(b, dtype=np.float32)
        self.units = self.W.shape[1]
        self.out = self.W.shape[0]
        return self

    def predict(self, h: list[float]) -> list[float]:
        h_arr = np.asarray(h, dtype=np.float32)
        y = self.W @ h_arr + self.b
        return [float(v) for v in y]

    def sgd_step(self, h: list[float], target: list[float], lr: float) -> float:
        """One SGD step toward *target* from *h*; returns MSE loss.

        Skips the update if the loss or any gradient is non-finite.
        """
        h_arr = np.asarray(h, dtype=np.float32)
        t = np.asarray(target, dtype=np.float32)
        pred = self.W @ h_arr + self.b
        err = pred - t
        loss = float(np.mean(err * err))
        if not math.isfinite(loss):
            return 0.0
        d = self.out
        grad_w = (2.0 / d) * np.outer(err, h_arr)
        grad_b = (2.0 / d) * err
        if not (np.isfinite(grad_w).all() and np.isfinite(grad_b).all()):
            return 0.0
        self.W = self.W - lr * grad_w
        self.b = self.b - lr * grad_b
        return loss

    def state_dict(self) -> dict[str, Any]:
        return {"weight": self.W.tolist(), "bias": self.b.tolist()}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        self.W = np.asarray(state["weight"], dtype=np.float32)
        self.b = np.asarray(state["bias"], dtype=np.float32)
        self.out = self.W.shape[0]
        self.units = self.W.shape[1]


def _lecun_tanh(x: np.ndarray) -> np.ndarray:
    return np.float32(1.7159) * np.tanh(np.float32(0.666) * x)


def _sigmoid(x: np.ndarray) -> np.ndarray:
    # Clipping avoids overflow for very negative inputs while keeping float32.
    return 1.0 / (1.0 + np.exp(-np.clip(x, -50.0, 50.0)))


def numpy_cfc_step(
    w: ReservoirWeights,
    x: list[float],
    h: list[float],
) -> list[float]:
    """One unbatched CfC step in NumPy.

    Matches ``ncps.torch.CfC(..., batch_first=True)`` with no timespans
    (ts = 1.0) in default mode.
    """
    x_arr = np.asarray(x, dtype=np.float32)
    h_arr = np.asarray(h, dtype=np.float32)
    z = np.concatenate([x_arr, h_arr])

    bb = z @ w.backbone_w.T + w.backbone_b
    z_bb = _lecun_tanh(bb)

    f1 = np.tanh(z_bb @ w.ff1_w.T + w.ff1_b)
    f2 = np.tanh(z_bb @ w.ff2_w.T + w.ff2_b)
    t = _sigmoid(
        (z_bb @ w.time_a_w.T + w.time_a_b)
        + (z_bb @ w.time_b_w.T + w.time_b_b)
    )
    h_new = f1 * (1.0 - t) + t * f2
    return [float(v) for v in h_new]


def load_reservoir_into_ncps(
    cfc: Any, reservoir: ReservoirWeights, torch: Any
) -> None:
    """Copy a NumPy-generated reservoir into an ``ncps.torch.CfC`` module."""
    state = cfc.state_dict()
    state["rnn_cell.backbone.0.weight"] = torch.from_numpy(reservoir.backbone_w)
    state["rnn_cell.backbone.0.bias"] = torch.from_numpy(reservoir.backbone_b)
    state["rnn_cell.ff1.weight"] = torch.from_numpy(reservoir.ff1_w)
    state["rnn_cell.ff1.bias"] = torch.from_numpy(reservoir.ff1_b)
    state["rnn_cell.ff2.weight"] = torch.from_numpy(reservoir.ff2_w)
    state["rnn_cell.ff2.bias"] = torch.from_numpy(reservoir.ff2_b)
    state["rnn_cell.time_a.weight"] = torch.from_numpy(reservoir.time_a_w)
    state["rnn_cell.time_a.bias"] = torch.from_numpy(reservoir.time_a_b)
    state["rnn_cell.time_b.weight"] = torch.from_numpy(reservoir.time_b_w)
    state["rnn_cell.time_b.bias"] = torch.from_numpy(reservoir.time_b_b)
    cfc.load_state_dict(state)
