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


def _clamp01(value: float) -> float:
    """Clamp a drive contribution to the unit interval; non-finite values read as 0."""
    x = float(value)
    if not math.isfinite(x):
        return 0.0
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


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
    def _inject(self, d: float) -> None:
        """Inject a (lower-clamped) drive into the LIF population and record
        the resulting population spike rate.

        This is the single code path used by both `ModuleOscillator` and
        `SelfRhythmOscillator` so the latter's combined drive is injected
        bit-for-bit like the parent's own drive."""
        d = float(d)
        if d < 0.0:
            d = 0.0
        injected = d * self._base_drive * self._drive_scale
        cur = injected * self._weights
        spk, self._mem = self._lif(cur, self._mem)
        rate = float(spk.float().mean().item())
        self._spike_rate_history.append(rate)

    def step(self, drive: float) -> None:
        """Advance the LIF population one step under the given drive in [0, 1]."""
        self._inject(drive)

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


class SelfRhythmOscillator(ModuleOscillator):
    """Slow, breathing-like self-rhythm oscillator for Soma.

    The rhythm lives in the fetal breathing band (~0.5–0.9 Hz; Natale 1988) and
    is generated by excitatory recurrence plus fast activity-dependent synaptic
    depression (Tabak et al. 2000 J Neurosci; Khazipov & Luhmann 2006), the
    same mechanism used by the respiratory rhythm generator (Smith et al.
    1991).  Its period is slowly adapted by a phase-projected frequency rule
    (Righetti, Buchli & Ijspeert 2006 Physica D).  An external afferent enters
    only through a weak gain; any entrainment must emerge through adaptation.

    The external drive is treated as an afferent signal, not a master clock.
    No maternal-rate constant is used in the dynamics.
    """

    @staticmethod
    def _validate_params(
        step_hz: float,
        tau_rec: float,
        tau_min: float,
        tau_max: float,
        depression_u: float,
        w_rec: float,
        bias_gain: float,
        afferent_gain: float,
        eta: float,
        plasticity_sign: float,
        mean_tau_s: float,
        phase_window_s: float,
        phase_band_hz: tuple[float, float],
    ) -> None:
        if not math.isfinite(step_hz) or step_hz <= 0.0:
            raise ValueError(f"step_hz must be finite and > 0, got {step_hz}")
        if not math.isfinite(tau_min) or tau_min <= 0.0:
            raise ValueError(f"tau_min must be finite and > 0, got {tau_min}")
        if not math.isfinite(tau_rec) or not math.isfinite(tau_max):
            raise ValueError("tau_rec and tau_max must be finite")
        if not (tau_min <= tau_rec <= tau_max):
            raise ValueError(
                f"tau ordering must satisfy 0 < tau_min <= tau_rec <= tau_max, "
                f"got tau_min={tau_min}, tau_rec={tau_rec}, tau_max={tau_max}"
            )
        if not (0.0 < depression_u <= 1.0):
            raise ValueError(f"depression_u must be in (0, 1], got {depression_u}")
        if not math.isfinite(w_rec) or w_rec < 0.0:
            raise ValueError(f"w_rec must be finite and >= 0, got {w_rec}")
        if not math.isfinite(bias_gain) or bias_gain < 0.0:
            raise ValueError(f"bias_gain must be finite and >= 0, got {bias_gain}")
        if not math.isfinite(afferent_gain) or not (0.0 <= afferent_gain <= 1.0):
            raise ValueError(
                f"afferent_gain must be finite and in [0, 1], got {afferent_gain}"
            )
        if not math.isfinite(eta) or eta < 0.0:
            raise ValueError(f"eta must be finite and >= 0, got {eta}")
        if plasticity_sign not in (1.0, -1.0):
            raise ValueError(
                f"plasticity_sign must be +1.0 or -1.0, got {plasticity_sign}"
            )
        if not math.isfinite(mean_tau_s) or mean_tau_s <= 0.0:
            raise ValueError(f"mean_tau_s must be finite and > 0, got {mean_tau_s}")
        if not math.isfinite(phase_window_s) or phase_window_s * step_hz < MIN_PLV_WINDOW:
            raise ValueError(
                f"phase_window_s*step_hz must be >= {MIN_PLV_WINDOW}, "
                f"got {phase_window_s * step_hz}"
            )
        band_lo, band_hi = phase_band_hz
        if (
            not math.isfinite(band_lo)
            or not math.isfinite(band_hi)
            or not (0.0 < band_lo < band_hi < step_hz / 2.0)
        ):
            raise ValueError(
                f"phase_band_hz must satisfy 0 < lo < hi < step_hz/2, "
                f"got {phase_band_hz} with step_hz={step_hz}"
            )

    def __init__(
        self,
        *,
        population_size: int = MIN_POPULATION_SIZE,
        plv_window: int = MIN_PLV_WINDOW,
        beta: float = 0.9,
        threshold: float = 1.0,
        base_drive: float = 1.5,
        seed: Optional[int] = None,
        step_hz: float = 20.0,
        tau_rec: float = 0.8,
        tau_min: float = 0.3,
        tau_max: float = 2.0,
        depression_u: float = 0.6,
        w_rec: float = 3.0,
        bias_gain: float = 0.35,
        afferent_gain: float = 0.05,
        eta: float = 0.0,
        plasticity_sign: float = 1.0,
        mean_tau_s: float = 10.0,
        phase_window_s: float = 8.0,
        phase_band_hz: tuple[float, float] = (0.3, 2.0),
    ) -> None:
        SelfRhythmOscillator._validate_params(
            step_hz=step_hz,
            tau_rec=tau_rec,
            tau_min=tau_min,
            tau_max=tau_max,
            depression_u=depression_u,
            w_rec=w_rec,
            bias_gain=bias_gain,
            afferent_gain=afferent_gain,
            eta=eta,
            plasticity_sign=plasticity_sign,
            mean_tau_s=mean_tau_s,
            phase_window_s=phase_window_s,
            phase_band_hz=phase_band_hz,
        )

        super().__init__(
            population_size=population_size,
            plv_window=plv_window,
            beta=beta,
            threshold=threshold,
            base_drive=base_drive,
            seed=seed,
        )

        self._plv_window = int(plv_window)
        # The self-rhythm keeps a longer history (its phase window) than the
        # parent; recording it as the history length makes the parent's
        # serialize/deserialize preserve the whole window on restore.
        self._history_len = max(int(phase_window_s * step_hz), self._history_len)
        self._spike_rate_history = deque(maxlen=self._history_len)

        self._step_hz = float(step_hz)
        self._dt = 1.0 / self._step_hz
        self._tau_rec_init = float(tau_rec)
        self._tau_min = float(tau_min)
        self._tau_max = float(tau_max)
        self._depression_u = float(depression_u)
        self._w_rec = float(w_rec)
        self._bias_gain = float(bias_gain)
        self._afferent_gain = float(afferent_gain)
        self._eta = float(eta)
        self._plasticity_sign = float(plasticity_sign)
        self._mean_tau_s = float(mean_tau_s)
        self._phase_window_s = float(phase_window_s)
        band_lo, band_hi = phase_band_hz
        self._phase_band_hz = (float(band_lo), float(band_hi))

        self._s: float = 1.0
        self._ln_tau: float = math.log(self._tau_rec_init)
        self._r_prev: float = 0.0
        self._ext_mean: float = 0.0
        self._r_mean: float = 0.0
        self._s_mean: float = 1.0
        self._spike_sum: float = 0.0
        self._step_count: int = 0

    def step(self, drive: float, *, external_drive: float | None = None) -> None:
        """Advance one step.

        The endogenous rhythm is shaped by recurrent excitation and synaptic
        depression.  When ``eta > 0`` and ``external_drive`` is provided, a
        phase-projected adaptation rule slowly adjusts the recovery time
        constant.  No maternal-rate value is ever used.
        """
        own = _clamp01(drive)
        ext = 0.0 if external_drive is None else _clamp01(external_drive)

        tau = math.exp(self._ln_tau)
        s = (
            self._s
            + self._dt * (1.0 - self._s) / tau
            - self._depression_u * self._s * self._r_prev
        )
        if s < 0.0:
            s = 0.0
        elif s > 1.0:
            s = 1.0
        self._s = s

        drive_term = (
            self._bias_gain * own
            + self._w_rec * s * self._r_prev
            + self._afferent_gain * ext
        )
        self._inject(drive_term)
        rate = self._spike_rate_history[-1]

        self._r_prev = rate
        self._spike_sum += rate
        self._step_count += 1

        alpha = self._dt / self._mean_tau_s
        if alpha > 1.0:
            alpha = 1.0
        self._ext_mean += alpha * (ext - self._ext_mean)
        self._r_mean += alpha * (rate - self._r_mean)
        self._s_mean += alpha * (s - self._s_mean)

        if self._eta > 0.0 and external_drive is not None:
            f = ext - self._ext_mean
            x = rate - self._r_mean
            y = s - self._s_mean
            r = math.sqrt(x * x + y * y)
            if r > 1e-9:
                q = y / r
                self._ln_tau += (
                    self._plasticity_sign * self._eta * f * q * self._dt
                )
            ln_min = math.log(self._tau_min)
            ln_max = math.log(self._tau_max)
            if self._ln_tau < ln_min:
                self._ln_tau = ln_min
            elif self._ln_tau > ln_max:
                self._ln_tau = ln_max

    @property
    def tau_rec(self) -> float:
        return float(math.exp(self._ln_tau))

    @property
    def synaptic_resource(self) -> float:
        return self._s

    @property
    def last_rate(self) -> float:
        return self._r_prev

    @property
    def spike_sum(self) -> float:
        return self._spike_sum

    @property
    def step_count(self) -> int:
        return self._step_count

    def rate_history(self) -> list[float]:
        return list(self._spike_rate_history)

    def phase(self) -> float:
        """Instantaneous phase of the recent rate signal via causal band-pass + Hilbert."""
        min_len = max(MIN_PLV_WINDOW, int(4.0 * self._step_hz))
        if len(self._spike_rate_history) < min_len:
            return NEUTRAL_PHASE
        try:
            import numpy as np
            from scipy.signal import butter, hilbert, sosfilt

            series = np.asarray(self._spike_rate_history, dtype=float)
            series = series - series.mean()
            if not np.any(np.abs(series) > 1e-9):
                return NEUTRAL_PHASE
            sos = butter(
                2,
                self._phase_band_hz,
                btype="band",
                fs=self._step_hz,
                output="sos",
            )
            filtered = sosfilt(sos, series)
            analytic = hilbert(filtered)
            ph = float(np.angle(analytic[-1]))
            if not math.isfinite(ph):
                return NEUTRAL_PHASE
            return ph
        except Exception:
            return NEUTRAL_PHASE

    def amplitude(self) -> float:
        """Band-passed standard deviation of the recent rate signal."""
        min_len = max(MIN_PLV_WINDOW, int(4.0 * self._step_hz))
        if len(self._spike_rate_history) < min_len:
            return 0.0
        try:
            import numpy as np
            from scipy.signal import butter, sosfilt

            series = np.asarray(self._spike_rate_history, dtype=float)
            series = series - series.mean()
            sos = butter(
                2,
                self._phase_band_hz,
                btype="band",
                fs=self._step_hz,
                output="sos",
            )
            filtered = sosfilt(sos, series)
            amp = float(np.std(filtered, ddof=0))
            if not math.isfinite(amp) or amp < 0.0:
                return 0.0
            return amp
        except Exception:
            return 0.0

    def serialize(self) -> dict[str, Any]:
        state = super().serialize()
        state.update(
            {
                "kind": "self_rhythm",
                "version": 2,
                "s": self._s,
                "ln_tau": self._ln_tau,
                "r_prev": self._r_prev,
                "ext_mean": self._ext_mean,
                "r_mean": self._r_mean,
                "s_mean": self._s_mean,
                "spike_sum": self._spike_sum,
                "step_count": self._step_count,
                "params": {
                    "population_size": self._population_size,
                    "plv_window": self._plv_window,
                    "beta": self._beta,
                    "threshold": self._threshold,
                    "base_drive": self._base_drive,
                    "seed": None,
                    "step_hz": self._step_hz,
                    "tau_rec": self._tau_rec_init,
                    "tau_min": self._tau_min,
                    "tau_max": self._tau_max,
                    "depression_u": self._depression_u,
                    "w_rec": self._w_rec,
                    "bias_gain": self._bias_gain,
                    "afferent_gain": self._afferent_gain,
                    "eta": self._eta,
                    "plasticity_sign": self._plasticity_sign,
                    "mean_tau_s": self._mean_tau_s,
                    "phase_window_s": self._phase_window_s,
                    "phase_band_hz": list(self._phase_band_hz),
                },
            }
        )
        return state

    def deserialize(self, state: dict[str, Any]) -> None:
        import logging

        logger = logging.getLogger(__name__)
        if state.get("version") != 2:
            logger.info(
                "Ignoring non-v2 SelfRhythmOscillator state (version=%s)",
                state.get("version"),
            )
            return

        try:
            params = state.get("params", {})
            step_hz = float(params["step_hz"])
            tau_rec = float(params["tau_rec"])
            tau_min = float(params["tau_min"])
            tau_max = float(params["tau_max"])
            depression_u = float(params["depression_u"])
            w_rec = float(params["w_rec"])
            bias_gain = float(params["bias_gain"])
            afferent_gain = float(params["afferent_gain"])
            eta = float(params["eta"])
            plasticity_sign = float(params["plasticity_sign"])
            mean_tau_s = float(params["mean_tau_s"])
            phase_window_s = float(params["phase_window_s"])
            band = params["phase_band_hz"]
            phase_band_hz = (float(band[0]), float(band[1]))

            SelfRhythmOscillator._validate_params(
                step_hz=step_hz,
                tau_rec=tau_rec,
                tau_min=tau_min,
                tau_max=tau_max,
                depression_u=depression_u,
                w_rec=w_rec,
                bias_gain=bias_gain,
                afferent_gain=afferent_gain,
                eta=eta,
                plasticity_sign=plasticity_sign,
                mean_tau_s=mean_tau_s,
                phase_window_s=phase_window_s,
                phase_band_hz=phase_band_hz,
            )

            s = float(state["s"])
            ln_tau = float(state["ln_tau"])
            r_prev = float(state["r_prev"])
            ext_mean = float(state["ext_mean"])
            r_mean = float(state["r_mean"])
            s_mean = float(state["s_mean"])
            spike_sum = float(state["spike_sum"])
            step_count = int(state["step_count"])
            for value in (s, ln_tau, r_prev, ext_mean, r_mean, s_mean, spike_sum):
                if not math.isfinite(value):
                    raise ValueError(f"non-finite state value {value}")

            super().deserialize(state)

            self._step_hz = step_hz
            self._dt = 1.0 / step_hz
            self._tau_rec_init = tau_rec
            self._tau_min = tau_min
            self._tau_max = tau_max
            self._depression_u = depression_u
            self._w_rec = w_rec
            self._bias_gain = bias_gain
            self._afferent_gain = afferent_gain
            self._eta = eta
            self._plasticity_sign = plasticity_sign
            self._mean_tau_s = mean_tau_s
            self._phase_window_s = phase_window_s
            self._phase_band_hz = phase_band_hz
            self._s = s
            self._ln_tau = ln_tau
            self._r_prev = r_prev
            self._ext_mean = ext_mean
            self._r_mean = r_mean
            self._s_mean = s_mean
            self._spike_sum = spike_sum
            self._step_count = step_count

        except Exception as exc:
            logger.info("Ignoring invalid v2 SelfRhythmOscillator state: %s", exc)
            return


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


def make_self_rhythm_oscillator(
    *,
    population_size: int = MIN_POPULATION_SIZE,
    plv_window: int = MIN_PLV_WINDOW,
    beta: float = 0.9,
    threshold: float = 1.0,
    base_drive: float = 1.5,
    seed: Optional[int] = None,
    step_hz: float = 20.0,
    tau_rec: float = 0.8,
    tau_min: float = 0.3,
    tau_max: float = 2.0,
    depression_u: float = 0.6,
    w_rec: float = 3.0,
    bias_gain: float = 0.35,
    afferent_gain: float = 0.05,
    eta: float = 0.0,
    plasticity_sign: float = 1.0,
    mean_tau_s: float = 10.0,
    phase_window_s: float = 8.0,
    phase_band_hz: tuple[float, float] = (0.3, 2.0),
) -> Optional[SelfRhythmOscillator]:
    """Build a live `SelfRhythmOscillator`, or return ``None`` when snnTorch is
    not installed.  Forwards all constructor keywords to the class."""
    if not snntorch_available():
        return None
    try:
        return SelfRhythmOscillator(
            population_size=population_size,
            plv_window=plv_window,
            beta=beta,
            threshold=threshold,
            base_drive=base_drive,
            seed=seed,
            step_hz=step_hz,
            tau_rec=tau_rec,
            tau_min=tau_min,
            tau_max=tau_max,
            depression_u=depression_u,
            w_rec=w_rec,
            bias_gain=bias_gain,
            afferent_gain=afferent_gain,
            eta=eta,
            plasticity_sign=plasticity_sign,
            mean_tau_s=mean_tau_s,
            phase_window_s=phase_window_s,
            phase_band_hz=phase_band_hz,
        )
    except Exception:  # pragma: no cover - defensive: any lazy-import failure
        return None
