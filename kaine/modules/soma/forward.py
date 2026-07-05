# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Substrate forward model for Soma — closed-form continuous-time (CfC) network.

Per paper §3.4.1 (Soma) and the §4.2 instrument table ("Temporal and
substrate modeling | CfC via ncps | Prediction models (Chronos, Soma)"), Soma
maintains a closed-form continuous-time network (Hasani et al. 2022), via the
`ncps` package, that learns the entity's normal substrate patterns from GPU
temperature, CPU and RAM utilization, and cognitive-cycle latency. The signal
it publishes is the prediction error between expected and actual substrate
state.

This mirrors the Chronos CfC pattern (`kaine.modules.chronos.network`,
`CfCNetwork` / `ForwardPredictionHead`): a frozen, randomly-initialised CfC
reservoir turns the raw metric vector into a recurrent hidden state, and a
small linear readout learns ONLINE (one SGD step per tick) to predict the
NEXT feature vector from that hidden state. Keeping the reservoir frozen and
the readout linear keeps online adaptation a convex, single-step problem —
stable enough to update every tick without diverging.

Design constraints (matching the Chronos CfCNetwork / ForwardPredictionHead
pattern)
-----------------------------------------------------------------------
- CPU-only: all tensors stay on CPU regardless of host hardware.
- Zero raw-sense-data persistence: ``state_dict()`` / ``load_state_dict()``
  serialise only the readout's weight and bias tensors. The CfC reservoir's
  weights are never serialised — like Chronos's ``CfCNetwork``, it is a
  frozen, reseedable random projection, not learned content, so there is
  nothing it would mean to "persist". The recurrent hidden state is
  ephemeral runtime context and is likewise never persisted.
- Non-finite guard: adaptation is skipped when the loss or any gradient is
  non-finite. Soma's feature vectors come from raw host-sensor reads (unlike
  Chronos's already-curated featurizer output) and can glitch, so a
  non-finite *input* vector also skips the recurrent-state commit for that
  tick entirely — protecting the CfC's persistent hidden state from being
  permanently corrupted by a single bad sensor read.
- Adaptation can be suspended externally (e.g. during Hypnos sleep) by
  setting ``suspended = True``.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

log = logging.getLogger(__name__)

# Default learning rate for online adaptation of the readout.
_DEFAULT_LR: float = 1e-3

# Default feature vector dimension. Soma's normalized metrics include
# cpu_percent, ram_percent, cycle_latency_avg_ms, and (where available) GPU
# temperature; the model uses a fixed-size vector padded/truncated to match.
DEFAULT_FEATURE_DIM: int = 8


class SubstrateForwardModel:
    """CfC-backed model that predicts the next substrate feature vector.

    Architecture
    ------------
    A `ncps.torch.CfC` reservoir (``feature_dim`` inputs -> ``units`` hidden
    units) turns the current feature vector into a recurrent hidden state.
    The reservoir's weights are randomly initialised and FROZEN (never
    trained) — it is a fixed temporal feature extractor, exactly like
    Chronos's `CfCNetwork`. A linear readout (``units`` -> ``feature_dim``)
    maps that hidden state to a feature prediction and adapts online via
    SGD, exactly like Chronos's `ForwardPredictionHead`.
    """

    def __init__(
        self,
        feature_dim: int = DEFAULT_FEATURE_DIM,
        units: int = 32,
        *,
        lr: float = _DEFAULT_LR,
        seed: Optional[int] = None,
    ) -> None:
        if feature_dim <= 0:
            raise ValueError("feature_dim must be positive")
        if units <= 0:
            raise ValueError("units must be positive")
        if lr <= 0:
            raise ValueError("lr must be positive")

        from kaine.hardware import select_device

        device = select_device("cpu")
        if device != "cpu":
            log.warning(
                "Soma forward model requested cpu but select_device returned "
                "%s; pinning to cpu regardless to keep the network small and "
                "the cycle predictable",
                device,
            )
            device = "cpu"

        # Lazy import so the rest of the soma package can be tested without
        # torch / ncps installed.
        import torch
        import torch.nn as nn
        from ncps.torch import CfC  # type: ignore[import-untyped]

        if seed is not None:
            torch.manual_seed(seed)

        self._torch = torch
        self._device = device
        self._feature_dim = int(feature_dim)
        self._units = int(units)
        self._lr = float(lr)

        # Frozen CfC reservoir — a fixed, randomly-initialised temporal
        # feature extractor (mirrors Chronos's CfCNetwork).
        self._cfc = CfC(self._feature_dim, self._units, batch_first=True).to(device)
        self._cfc.eval()
        for p in self._cfc.parameters():
            p.requires_grad_(False)

        # Online-adapting linear readout (mirrors Chronos's
        # ForwardPredictionHead).
        self._readout = nn.Linear(self._units, self._feature_dim)
        self._readout.train()
        self._optim = torch.optim.SGD(self._readout.parameters(), lr=self._lr)

        # Count of real online-adaptation steps taken (one SGD step per tick
        # where a finite feature vector was learned from, not suspended). This
        # is the direct "logged lived events" analogue the Soma developmental
        # warm-up reads for its samples-seen end-condition (see module.py and
        # paper §6.6). Runtime-only; never serialised.
        self._adaptation_steps: int = 0

        # Persistent recurrent hidden state — ephemeral, never serialised.
        self._hx: Optional[Any] = None
        # Hidden state that produced ``_last_prediction``, kept so adapt()
        # trains the readout against the SAME context it predicted from.
        self._last_hidden: Optional[list[float]] = None
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
    def adaptation_steps(self) -> int:
        """Number of real online-adaptation (SGD) steps performed so far.

        Increments only on ticks where the readout actually learned from a
        finite feature vector (not suspended, prior context available). During
        Hypnos sleep (``suspended``) or on a non-finite/first tick it does not
        advance — so a paused or sensory-starved entity does not accrue
        "samples", exactly what the warm-up end-condition needs.
        """
        return self._adaptation_steps

    @property
    def device(self) -> str:
        return self._device

    def parameter_count(self) -> int:
        """Total parameter count across the frozen reservoir and the readout."""
        return int(
            sum(p.numel() for p in self._cfc.parameters())
            + sum(p.numel() for p in self._readout.parameters())
        )

    def reset(self) -> None:
        """Clear recurrent CfC state.

        The hidden state is ephemeral runtime context (never persisted); this
        is the equivalent of `CfCNetwork.reset()` for callers (e.g. tests)
        that need to compare two models from the same all-zero starting
        context.
        """
        self._hx = None
        self._last_hidden = None
        self._last_prediction = None

    # ------------------------------------------------------------------
    # Core per-step interface
    # ------------------------------------------------------------------

    def _tick(self, feature: list[float], *, commit: bool) -> list[float]:
        """Run one CfC step on *feature*.

        When ``commit`` is True, the resulting hidden state is persisted as
        the model's recurrent state (used by ``step()``). When False, the
        tick is a side-effect-free "peek" against the CURRENT persisted
        state, leaving it untouched (used by ``predict()``).
        """
        torch = self._torch
        with torch.no_grad():
            x = torch.tensor(feature, dtype=torch.float32, device=self._device)
            x = x.view(1, 1, -1)
            out, hx = self._cfc(x, hx=self._hx)
            hidden = [float(v) for v in out.view(-1).tolist()]
        if commit:
            self._hx = hx
        return hidden

    def _readout_predict(self, hidden: list[float]) -> list[float]:
        torch = self._torch
        with torch.no_grad():
            h = torch.tensor(hidden, dtype=torch.float32)
            pred = self._readout(h)
        return [float(v) for v in pred.tolist()]

    def predict(self, feature: list[float]) -> list[float]:
        """Predict the next feature vector given the current feature.

        Side-effect-free: ticks the CfC as a peek against the current hidden
        state without persisting the result, and does not adapt weights.
        Call ``step()`` for the stateful online-learning path.
        """
        if len(feature) != self._feature_dim:
            raise ValueError(
                f"expected {self._feature_dim}-dim input, got {len(feature)}"
            )
        hidden = self._tick(feature, commit=False)
        return self._readout_predict(hidden)

    def step(self, feature: list[float]) -> float:
        """Full online step for one tick.

        1. Computes the prediction error against the prior prediction.
        2. Adapts the readout toward *feature* (if not suspended), using the
           hidden state that produced the prior prediction.
        3. Advances the CfC's recurrent state by ticking on *feature*.
        4. Makes a new prediction for the NEXT tick from the now-current
           hidden state.

        Returns the L2 prediction error ``||feature - last_prediction||``
        (0.0 on the very first tick when there is no prior prediction, and
        0.0 — with the tick skipped entirely — when *feature* itself
        contains a non-finite value).
        """
        if len(feature) != self._feature_dim:
            raise ValueError(
                f"expected {self._feature_dim}-dim input, got {len(feature)}"
            )

        if not all(math.isfinite(v) for v in feature):
            log.warning(
                "SubstrateForwardModel: non-finite feature vector; skipping tick"
            )
            return 0.0

        # 1. Prediction error from the previous tick's prediction.
        if self._last_prediction is None:
            prediction_error = 0.0
        else:
            diffs = [(a - b) ** 2 for a, b in zip(feature, self._last_prediction)]
            prediction_error = math.sqrt(sum(diffs))

        # 2. Adapt the readout toward this feature, using the hidden state
        # that produced the prior prediction (before this tick advances it).
        if not self.suspended and self._last_hidden is not None:
            self._adapt_toward(self._last_hidden, feature)
            self._adaptation_steps += 1

        # 3. Advance recurrent state by ticking on the observed feature.
        hidden = self._tick(feature, commit=True)

        # 4. Predict the NEXT feature from the now-current hidden state.
        self._last_prediction = self._readout_predict(hidden)
        self._last_hidden = hidden

        return prediction_error

    def _adapt_toward(self, hidden: list[float], target_feature: list[float]) -> float:
        """One SGD step toward target_feature from `hidden`; returns MSE loss.

        Skips the update if the loss or any gradient is non-finite.
        """
        torch = self._torch
        h = torch.tensor(hidden, dtype=torch.float32)
        t = torch.tensor(target_feature, dtype=torch.float32)

        self._optim.zero_grad()
        pred = self._readout(h)
        loss = ((pred - t) ** 2).mean()
        loss_val = float(loss.item())

        if not math.isfinite(loss_val):
            log.warning(
                "SubstrateForwardModel: non-finite loss %.6g; skipping update",
                loss_val,
            )
            return 0.0

        loss.backward()

        # Non-finite gradient guard
        for p in self._readout.parameters():
            if p.grad is not None and not torch.isfinite(p.grad).all():
                log.warning(
                    "SubstrateForwardModel: non-finite gradient; skipping update"
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
                ratio = min(raw_error / (2.0 * mean_err), 1.0)
            else:
                ratio = 0.0
        else:
            # No window yet — use a simple clamp; normalized features are in [0, 1]
            # so L2 over 8 dims maxes near sqrt(8) = 2.83.
            ratio = min(raw_error / 3.0, 1.0)

        return baseline_salience + ratio * (alert_salience - baseline_salience)

    # ------------------------------------------------------------------
    # Serialisation — readout weights only. The CfC reservoir is frozen and
    # reseedable, not learned content, so (like Chronos's CfCNetwork) it is
    # never serialised. The recurrent hidden state is ephemeral runtime
    # context and is likewise never persisted.
    # ------------------------------------------------------------------

    def state_dict(self) -> dict[str, Any]:
        """Return serialisable readout weight tensors (no raw feature data)."""
        return {
            "weight": self._readout.weight.detach().cpu().tolist(),
            "bias": self._readout.bias.detach().cpu().tolist(),
        }

    def load_state_dict(self, state: dict[str, Any]) -> None:
        """Restore readout weights from a ``state_dict()`` snapshot."""
        torch = self._torch
        weight = torch.tensor(state["weight"], dtype=torch.float32)
        bias = torch.tensor(state["bias"], dtype=torch.float32)
        with torch.no_grad():
            self._readout.weight.copy_(weight)
            self._readout.bias.copy_(bias)


def metrics_to_feature_vector(
    metrics: dict[str, float],
    feature_dim: int = DEFAULT_FEATURE_DIM,
    *,
    cycle_latency_target_ms: float = 300.0,
    gpu_temp_max_c: float = 100.0,
) -> list[float]:
    """Convert a soma metrics dict to a fixed-size normalized feature vector.

    Layout (first four slots are the primary substrate-wellness contributors):
      [0] cpu_percent / 100.0                    (0 = 0%, 1 = 100%)
      [1] ram_percent / 100.0                     (0 = 0%, 1 = 100%)
      [2] cycle_latency_avg_ms / (2 * target)     (0 = no latency, 1 = 2x target)
      [3] max(gpu_*_temp_c) / gpu_temp_max_c      (0 = no GPU data, else hottest GPU)
      [4..feature_dim-1] zero-padded

    GPU temperature is read from any ``gpu_<index>_temp_c`` key (as produced
    by `SystemMetricsReader`'s per-GPU pynvml read); when multiple GPUs are
    present the hottest one is used, matching the alerting philosophy of
    `ThresholdAnomalyDetector`'s `gpu_*_temp_c` wildcard threshold. Hosts
    without GPU telemetry (no `pynvml`, or no GPU) leave this slot at 0.0.

    All values are clamped to [0, 1]. Unknown/missing metrics default to 0.0.
    The vector is then truncated or zero-padded to exactly feature_dim floats.
    """
    def _clamp01(x: float) -> float:
        return max(0.0, min(1.0, x))

    vec = [0.0] * max(feature_dim, 4)
    if "cpu_percent" in metrics:
        vec[0] = _clamp01(metrics["cpu_percent"] / 100.0)
    if "ram_percent" in metrics:
        vec[1] = _clamp01(metrics["ram_percent"] / 100.0)
    if "cycle_latency_avg_ms" in metrics:
        denom = max(2.0 * cycle_latency_target_ms, 1.0)
        vec[2] = _clamp01(metrics["cycle_latency_avg_ms"] / denom)

    gpu_temps = [
        v
        for k, v in metrics.items()
        if k.startswith("gpu_") and k.endswith("_temp_c")
    ]
    if gpu_temps:
        denom = max(gpu_temp_max_c, 1.0)
        vec[3] = _clamp01(max(gpu_temps) / denom)

    # Truncate or pad to feature_dim
    return vec[:feature_dim]
