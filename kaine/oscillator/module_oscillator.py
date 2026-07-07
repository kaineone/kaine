# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""ModuleOscillator + FakeOscillator.

`ModuleOscillator` wraps a small LIF (leaky integrate-and-fire) population from
snnTorch, run on CPU. Each tick the owning module injects a drive current
proportional to its recent activity (publish rate / salience); the population's
spiking produces a rhythm whose instantaneous **phase** is estimated from the
binned spike-rate via ``scipy.signal.hilbert``. Only the phase is exposed
upward — it is cheap to carry and serialize.

`set_frequency(scale)` multiplies the drive-injection magnitude, which slows
(scale < 1) or quickens the emergent rhythm. It is called by
``hypnos-fatigue-phases`` phase 1 at maintenance entry.

snnTorch (and scipy) are imported lazily. If snnTorch is unavailable,
`make_oscillator` returns ``None`` and the owning module reports the neutral
phase, so module import never breaks and the coherence factor degrades to 1.0.

`FakeOscillator` is a deterministic, dependency-free implementation used by the
test suite: it advances its phase by a fixed step per tick, ignores
`set_frequency`, and never imports snnTorch.

Serialization: oscillator numeric state (membrane voltages, recent spike
history, phase buffer, drive scale) round-trips through a plain dict for
checkpoint/resume. PLV sliding-window buffers live in
``kaine/workspace/coherence.py`` and are deliberately NOT persisted (ephemeral;
re-initialise to neutral on restart).
"""
from __future__ import annotations

import math
from collections import deque
from typing import Any, Optional, Protocol, runtime_checkable

# Neutral phase reported by modules with no oscillator (or when snnTorch is
# absent). 0.0 is an arbitrary but stable reference; what matters is that all
# neutral modules report the SAME value so their pairwise PLV is maximal among
# themselves and they never spuriously boost or attenuate a coalition relative
# to one another. The coherence layer treats a coalition with no live
# oscillators as fully coherent (factor mapped from PLV 1.0); since the layer is
# off by default this never changes live behavior.
NEUTRAL_PHASE: float = 0.0

# Minimum invariants enforced at construction (spec: oscillatory-binding).
MIN_POPULATION_SIZE: int = 16
MIN_PLV_WINDOW: int = 10


def neutral_phase() -> float:
    """The phase a module without a live oscillator reports."""
    return NEUTRAL_PHASE


@runtime_checkable
class OscillatorProtocol(Protocol):
    """Surface the rest of KAINE depends on. Both `ModuleOscillator` and
    `FakeOscillator` satisfy it; modules type their hook against this."""

    def step(self, drive: float) -> None:
        ...

    def phase(self) -> float:
        ...

    def set_frequency(self, scale: float) -> None:
        ...

    def serialize(self) -> dict[str, Any]:
        ...

    def deserialize(self, state: dict[str, Any]) -> None:
        ...


def snntorch_available() -> bool:
    """True when both snnTorch and scipy can be imported (the real oscillator's
    hard dependencies). Used to decide whether `make_oscillator` can build a
    live oscillator; callers fall back to the neutral phase otherwise."""
    try:  # pragma: no cover - exercised indirectly / via monkeypatch in tests
        import scipy.signal  # noqa: F401
        import snntorch  # noqa: F401
        import torch  # noqa: F401
    except Exception:
        return False
    return True


class FakeOscillator:
    """Deterministic, dependency-free oscillator for tests and snnTorch-absent
    environments. Advances phase by a fixed step per `step` call regardless of
    drive; ignores `set_frequency` entirely (phase output is unaffected)."""

    def __init__(self, *, phase_step: float = math.pi / 8) -> None:
        self._phase_step = float(phase_step)
        self._phase = NEUTRAL_PHASE
        self._ticks = 0

    def step(self, drive: float) -> None:  # noqa: ARG002 - drive ignored by design
        self._ticks += 1
        self._phase = (self._phase + self._phase_step) % (2.0 * math.pi)

    def phase(self) -> float:
        return self._phase

    def set_frequency(self, scale: float) -> None:  # noqa: ARG002 - no-op by design
        """No-op: deterministic phase output is unchanged (spec scenario)."""
        return

    def serialize(self) -> dict[str, Any]:
        return {
            "kind": "fake",
            "phase": self._phase,
            "phase_step": self._phase_step,
            "ticks": self._ticks,
        }

    def deserialize(self, state: dict[str, Any]) -> None:
        self._phase = float(state.get("phase", NEUTRAL_PHASE))
        self._phase_step = float(state.get("phase_step", self._phase_step))
        self._ticks = int(state.get("ticks", 0))


class ModuleOscillator:
    """A small snnTorch LIF population whose spiking rhythm yields a phase.

    The population is driven each `step` by ``drive * drive_scale``; the drive
    is the owning module's recent activity (publish rate / salience) in [0, 1].
    Each step records the population spike rate (fraction of units that fired);
    `phase()` runs a Hilbert transform over the recent spike-rate window and
    returns the instantaneous phase of the most recent sample.

    Construction validates the spec minimums (population >= 16, history window
    >= 10). snnTorch/scipy/torch are imported lazily in ``__init__``; build via
    `make_oscillator`, which returns ``None`` when they are unavailable.
    """

    def __init__(
        self,
        *,
        population_size: int = MIN_POPULATION_SIZE,
        plv_window: int = MIN_PLV_WINDOW,
        beta: float = 0.9,
        threshold: float = 1.0,
        base_drive: float = 1.5,
        seed: Optional[int] = None,
    ) -> None:
        if population_size < MIN_POPULATION_SIZE:
            raise ValueError(
                f"population_size must be >= {MIN_POPULATION_SIZE}, got {population_size}"
            )
        if plv_window < MIN_PLV_WINDOW:
            raise ValueError(
                f"plv_window must be >= {MIN_PLV_WINDOW}, got {plv_window}"
            )

        import torch  # lazy
        from snntorch import Leaky  # lazy

        self._torch = torch
        self._population_size = int(population_size)
        # Keep a spike-rate history at least as long as the PLV window so a
        # single phase() call has enough samples for a meaningful Hilbert
        # transform. A little extra headroom stabilises edge effects.
        self._history_len = max(int(plv_window) * 2, int(plv_window))
        self._beta = float(beta)
        self._threshold = float(threshold)
        self._base_drive = float(base_drive)
        self._drive_scale = 1.0

        if seed is not None:
            torch.manual_seed(int(seed))

        self._lif = Leaky(beta=self._beta, threshold=self._threshold)
        # Per-unit membrane potential; reset to the snnTorch zero state.
        self._mem = self._lif.init_leaky()
        if not isinstance(self._mem, torch.Tensor) or self._mem.numel() == 1:
            self._mem = torch.zeros(self._population_size)
        else:  # pragma: no cover - snnTorch versions returning a sized state
            self._mem = torch.zeros(self._population_size)
        # Fixed per-unit input weights give the population heterogeneity so it
        # produces a rhythm rather than firing in lockstep.
        gen = torch.Generator()
        if seed is not None:
            gen.manual_seed(int(seed))
        self._weights = 0.5 + torch.rand(self._population_size, generator=gen)
        self._spike_rate_history: deque[float] = deque(maxlen=self._history_len)

    # -- live dynamics ----------------------------------------------------
    def step(self, drive: float) -> None:
        """Advance the LIF population one step under the given drive in [0, 1]."""
        d = float(drive)
        if d < 0.0:
            d = 0.0
        injected = d * self._base_drive * self._drive_scale
        cur = injected * self._weights
        spk, self._mem = self._lif(cur, self._mem)
        rate = float(spk.float().mean().item())
        self._spike_rate_history.append(rate)

    def phase(self) -> float:
        """Instantaneous phase of the recent spike-rate signal via Hilbert.

        Returns the neutral phase until enough samples have accumulated for a
        stable estimate."""
        n = len(self._spike_rate_history)
        if n < MIN_PLV_WINDOW:
            return NEUTRAL_PHASE
        try:
            import numpy as np
            from scipy.signal import hilbert
        except Exception:  # pragma: no cover - scipy guaranteed by make_oscillator
            return NEUTRAL_PHASE
        series = np.asarray(self._spike_rate_history, dtype=float)
        # Remove DC so the analytic signal's phase reflects the oscillation,
        # not the mean firing level.
        series = series - series.mean()
        if not np.any(np.abs(series) > 1e-9):
            return NEUTRAL_PHASE
        analytic = hilbert(series)
        ph = float(np.angle(analytic[-1]))
        if not math.isfinite(ph):
            return NEUTRAL_PHASE
        return ph

    def set_frequency(self, scale: float) -> None:
        """Scale the drive-injection magnitude. scale < 1.0 slows the rhythm.

        Called by ``hypnos-fatigue-phases`` phase 1 at maintenance entry."""
        s = float(scale)
        if s < 0.0:
            s = 0.0
        self._drive_scale = s

    @property
    def drive_scale(self) -> float:
        return self._drive_scale

    @property
    def population_size(self) -> int:
        return self._population_size

    # -- serialization ----------------------------------------------------
    def serialize(self) -> dict[str, Any]:
        return {
            "kind": "lif",
            "population_size": self._population_size,
            "history_len": self._history_len,
            "beta": self._beta,
            "threshold": self._threshold,
            "base_drive": self._base_drive,
            "drive_scale": self._drive_scale,
            "mem": [float(x) for x in self._mem.tolist()],
            "weights": [float(x) for x in self._weights.tolist()],
            "spike_rate_history": list(self._spike_rate_history),
        }

    def deserialize(self, state: dict[str, Any]) -> None:
        torch = self._torch
        self._beta = float(state.get("beta", self._beta))
        self._threshold = float(state.get("threshold", self._threshold))
        self._base_drive = float(state.get("base_drive", self._base_drive))
        self._drive_scale = float(state.get("drive_scale", self._drive_scale))
        mem = state.get("mem")
        if mem is not None:
            self._mem = torch.tensor([float(x) for x in mem])
        weights = state.get("weights")
        if weights is not None:
            self._weights = torch.tensor([float(x) for x in weights])
        hist = state.get("spike_rate_history")
        if hist is not None:
            self._spike_rate_history = deque(
                (float(x) for x in hist), maxlen=self._history_len
            )


def make_oscillator(
    *,
    population_size: int = MIN_POPULATION_SIZE,
    plv_window: int = MIN_PLV_WINDOW,
    beta: float = 0.9,
    threshold: float = 1.0,
    base_drive: float = 1.5,
    seed: Optional[int] = None,
) -> Optional[ModuleOscillator]:
    """Build a live `ModuleOscillator`, or return ``None`` when snnTorch/scipy
    are unavailable. Callers that get ``None`` report the neutral phase, so the
    coherence factor degrades gracefully to 1.0."""
    if not snntorch_available():
        return None
    try:
        return ModuleOscillator(
            population_size=population_size,
            plv_window=plv_window,
            beta=beta,
            threshold=threshold,
            base_drive=base_drive,
            seed=seed,
        )
    except Exception:  # pragma: no cover - defensive: any lazy-import failure
        return None
