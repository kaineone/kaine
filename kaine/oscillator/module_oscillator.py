# SPDX-License-Identifier: LicenseRef-CAL-0.4
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
        history_len: Optional[int] = None,
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
        # A subclass may keep a longer history (the self-rhythm's phase window).
        self._history_len = max(int(plv_window) * 2, int(plv_window), int(history_len or 0))
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

    The rhythm is generated by a Tabak-style mean-field population model
    (Tabak et al. 2000 J Neurosci 20:3041) in which excitatory recurrence
    and fast activity-dependent synaptic depression produce spontaneous
    rhythms in developing networks (Khazipov & Luhmann 2006).  This is the
    same mechanism used by the respiratory rhythm generator (Smith et al.
    1991) and produces oscillations in the fetal breathing band
    (Natale et al. 1988).  Its period is slowly adapted by a phase-projected
    frequency rule (Righetti, Buchli & Ijspeert 2006 Physica D).  An
    external afferent enters only through a weak gain; any entrainment must
    emerge through adaptation (Notbohm 2016; Duecker 2021).

    The external drive is treated as an afferent signal, not a master clock.
    No maternal-rate constant is used in the dynamics.
    """

    @staticmethod
    def _validate_params(
        step_hz: float,
        substeps: int,
        w_rec: float,
        k_sig: float,
        tau_a: float,
        depression_u: float,
        margin: float,
        own_gain: float,
        afferent_gain: float,
        noise_std: float,
        tau_rec: float,
        tau_min: float,
        tau_max: float,
        eta: float,
        plasticity_sign: float,
        mean_tau_s: float,
        readout_gain: float,
        phase_window_s: float,
        phase_band_hz: tuple[float, float],
    ) -> None:
        if not math.isfinite(step_hz) or step_hz <= 0.0:
            raise ValueError(f"step_hz must be finite and > 0, got {step_hz}")
        if not isinstance(substeps, int) or substeps < 1:
            raise ValueError(f"substeps must be an int >= 1, got {substeps}")
        if not math.isfinite(w_rec) or w_rec < 0.0:
            raise ValueError(f"w_rec must be finite and >= 0, got {w_rec}")
        if not math.isfinite(k_sig) or k_sig <= 0.0:
            raise ValueError(f"k_sig must be finite and > 0, got {k_sig}")
        if not math.isfinite(tau_a) or tau_a <= 0.0:
            raise ValueError(f"tau_a must be finite and > 0, got {tau_a}")
        if not math.isfinite(depression_u) or depression_u <= 0.0:
            raise ValueError(
                f"depression_u must be finite and > 0, got {depression_u}"
            )
        if not math.isfinite(margin):
            raise ValueError(f"margin must be finite, got {margin}")
        if not math.isfinite(own_gain) or own_gain < 0.0:
            raise ValueError(f"own_gain must be finite and >= 0, got {own_gain}")
        if not math.isfinite(afferent_gain) or not (
            0.0 <= afferent_gain <= 1.0
        ):
            raise ValueError(
                f"afferent_gain must be finite and in [0, 1], got {afferent_gain}"
            )
        if not math.isfinite(noise_std) or noise_std < 0.0:
            raise ValueError(
                f"noise_std must be finite and >= 0, got {noise_std}"
            )
        if not math.isfinite(tau_min) or tau_min <= 0.0:
            raise ValueError(f"tau_min must be finite and > 0, got {tau_min}")
        if not math.isfinite(tau_rec) or not math.isfinite(tau_max):
            raise ValueError("tau_rec and tau_max must be finite")
        if not (tau_min <= tau_rec <= tau_max):
            raise ValueError(
                f"tau ordering must satisfy 0 < tau_min <= tau_rec <= tau_max, "
                f"got tau_min={tau_min}, tau_rec={tau_rec}, tau_max={tau_max}"
            )
        if not math.isfinite(eta) or eta < 0.0:
            raise ValueError(f"eta must be finite and >= 0, got {eta}")
        if plasticity_sign not in (1.0, -1.0):
            raise ValueError(
                f"plasticity_sign must be +1.0 or -1.0, got {plasticity_sign}"
            )
        if not math.isfinite(mean_tau_s) or mean_tau_s <= 0.0:
            raise ValueError(
                f"mean_tau_s must be finite and > 0, got {mean_tau_s}"
            )
        if not math.isfinite(readout_gain) or readout_gain < 0.0:
            raise ValueError(
                f"readout_gain must be finite and >= 0, got {readout_gain}"
            )
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
        substeps: int = 10,
        w_rec: float = 2.5,
        k_sig: float = 0.08,
        tau_a: float = 0.02,
        depression_u: float = 8.0,
        margin: float = -0.25,
        own_gain: float = 0.02,
        afferent_gain: float = 0.03,
        noise_std: float = 0.02,
        tau_rec: float = 2.1,
        tau_min: float = 0.9,
        tau_max: float = 2.3,
        eta: float = 0.0,
        plasticity_sign: float = -1.0,
        mean_tau_s: float = 10.0,
        readout_gain: float = 1.0,
        phase_window_s: float = 8.0,
        phase_band_hz: tuple[float, float] = (0.3, 2.0),
    ) -> None:
        SelfRhythmOscillator._validate_params(
            step_hz=step_hz,
            substeps=substeps,
            w_rec=w_rec,
            k_sig=k_sig,
            tau_a=tau_a,
            depression_u=depression_u,
            margin=margin,
            own_gain=own_gain,
            afferent_gain=afferent_gain,
            noise_std=noise_std,
            tau_rec=tau_rec,
            tau_min=tau_min,
            tau_max=tau_max,
            eta=eta,
            plasticity_sign=plasticity_sign,
            mean_tau_s=mean_tau_s,
            readout_gain=readout_gain,
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
            # The self-rhythm keeps its whole phase window, so the parent's
            # serialize/deserialize preserve it on restore.
            history_len=int(phase_window_s * step_hz),
        )

        import numpy as np

        self._plv_window = int(plv_window)

        self._activity_history: deque[float] = deque(maxlen=self._history_len)

        self._step_hz = float(step_hz)
        self._dt_step = 1.0 / self._step_hz
        self._substeps = int(substeps)
        self._dt_sub = self._dt_step / self._substeps

        self._w_rec = float(w_rec)
        self._k_sig = float(k_sig)
        self._tau_a = float(tau_a)
        self._depression_u = float(depression_u)
        self._margin = float(margin)
        self._own_gain = float(own_gain)
        self._afferent_gain = float(afferent_gain)
        self._noise_std = float(noise_std)

        self._tau_rec_init = float(tau_rec)
        self._tau_min = float(tau_min)
        self._tau_max = float(tau_max)

        self._eta = float(eta)
        self._plasticity_sign = float(plasticity_sign)
        self._mean_tau_s = float(mean_tau_s)
        self._readout_gain = float(readout_gain)
        self._phase_window_s = float(phase_window_s)
        band_lo, band_hi = phase_band_hz
        self._phase_band_hz = (float(band_lo), float(band_hi))

        self._a: float = 0.05
        self._s: float = 1.0
        self._ln_tau: float = math.log(self._tau_rec_init)

        self._ext_mean: float = 0.0
        self._a_mean: float = 0.0
        self._s_mean: float = 1.0

        self._activity_sum: float = 0.0
        self._step_count: int = 0

        self._rng = np.random.default_rng(seed)

        import uuid

        self.identity = uuid.uuid4().hex

    @staticmethod
    def _sigmoid(x: float, k: float) -> float:
        """Numerically safe logistic 1/(1+exp(-x/k)) for k > 0."""
        z = x / k
        if z >= 0.0:
            ez = math.exp(-z)
            return 1.0 / (1.0 + ez)
        ez = math.exp(z)
        return ez / (1.0 + ez)

    def step(self, drive: float, *, external_drive: float | None = None) -> None:
        """Advance one step.

        The endogenous rhythm is shaped by recurrent excitation and synaptic
        depression in the mean-field population.  When ``eta > 0`` and
        ``external_drive`` is provided, a phase-projected adaptation rule
        slowly adjusts the recovery time constant.  The 16 LIF units are
        driven by the population activity.  No maternal-rate value is ever
        used.
        """
        own = _clamp01(drive)
        ext = 0.0 if external_drive is None else _clamp01(external_drive)

        a = self._a
        s = self._s
        tau = math.exp(self._ln_tau)
        dt = self._dt_sub
        noise_scale = self._noise_std * math.sqrt(0.001 / dt)

        for _ in range(self._substeps):
            x = (
                self._w_rec * s * a
                + self._margin
                + self._own_gain * own
                + self._afferent_gain * ext
            )
            if noise_scale != 0.0:
                x += noise_scale * float(self._rng.standard_normal())
            ainf = SelfRhythmOscillator._sigmoid(x, self._k_sig)
            a = a + dt * (-a + ainf) / self._tau_a
            s = min(
                1.0,
                max(
                    0.0,
                    s
                    + dt
                    * ((1.0 - s) / tau - self._depression_u * s * a),
                ),
            )

        self._a = a
        self._s = s

        alpha = self._dt_step / self._mean_tau_s
        if alpha > 1.0:
            alpha = 1.0
        self._ext_mean += alpha * (ext - self._ext_mean)
        self._a_mean += alpha * (a - self._a_mean)
        self._s_mean += alpha * (s - self._s_mean)

        if self._eta > 0.0 and external_drive is not None:
            f = ext - self._ext_mean
            xq = a - self._a_mean
            yq = s - self._s_mean
            r = math.hypot(xq, yq)
            q = yq / r if r > 1e-9 else 0.0
            ln_tau = (
                self._ln_tau
                + self._plasticity_sign * self._eta * f * q * self._dt_step
            )
            ln_min = math.log(self._tau_min)
            ln_max = math.log(self._tau_max)
            if ln_tau < ln_min:
                ln_tau = ln_min
            elif ln_tau > ln_max:
                ln_tau = ln_max
            self._ln_tau = ln_tau

        self._inject(self._readout_gain * a)
        self._activity_history.append(a)
        self._activity_sum += a
        self._step_count += 1

    @property
    def tau_rec(self) -> float:
        return float(math.exp(self._ln_tau))

    @property
    def synaptic_resource(self) -> float:
        return self._s

    @property
    def activity(self) -> float:
        return self._a

    @property
    def step_count(self) -> int:
        return self._step_count

    @property
    def activity_sum(self) -> float:
        return self._activity_sum

    @property
    def last_rate(self) -> float:
        if self._spike_rate_history:
            return float(self._spike_rate_history[-1])
        return 0.0

    def activity_history(self) -> list[float]:
        return list(self._activity_history)

    def rate_history(self) -> list[float]:
        return list(self._spike_rate_history)

    def phase(self) -> float:
        """Instantaneous phase of the recent activity via causal band-pass + Hilbert."""
        min_len = max(MIN_PLV_WINDOW, int(4.0 * self._step_hz))
        if len(self._activity_history) < min_len:
            return NEUTRAL_PHASE
        try:
            import numpy as np
            from scipy.signal import butter, hilbert, sosfilt

            series = np.asarray(self._activity_history, dtype=float)
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
        """Band-passed standard deviation of the recent activity."""
        min_len = max(MIN_PLV_WINDOW, int(4.0 * self._step_hz))
        if len(self._activity_history) < min_len:
            return 0.0
        try:
            import numpy as np
            from scipy.signal import butter, sosfilt

            series = np.asarray(self._activity_history, dtype=float)
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
                "identity": self.identity,
                "a": self._a,
                "s": self._s,
                "ln_tau": self._ln_tau,
                "ext_mean": self._ext_mean,
                "a_mean": self._a_mean,
                "s_mean": self._s_mean,
                "activity_sum": self._activity_sum,
                "step_count": self._step_count,
                "activity_history": list(self._activity_history),
                "rng_state": self._rng.bit_generator.state,
                "params": {
                    "population_size": self._population_size,
                    "plv_window": self._plv_window,
                    "beta": self._beta,
                    "threshold": self._threshold,
                    "base_drive": self._base_drive,
                    "seed": None,
                    "step_hz": self._step_hz,
                    "substeps": self._substeps,
                    "w_rec": self._w_rec,
                    "k_sig": self._k_sig,
                    "tau_a": self._tau_a,
                    "depression_u": self._depression_u,
                    "margin": self._margin,
                    "own_gain": self._own_gain,
                    "afferent_gain": self._afferent_gain,
                    "noise_std": self._noise_std,
                    "tau_rec": self._tau_rec_init,
                    "tau_min": self._tau_min,
                    "tau_max": self._tau_max,
                    "eta": self._eta,
                    "plasticity_sign": self._plasticity_sign,
                    "mean_tau_s": self._mean_tau_s,
                    "readout_gain": self._readout_gain,
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
            structural: dict[str, float] = {
                "w_rec": float(params["w_rec"]),
                "k_sig": float(params["k_sig"]),
                "tau_a": float(params["tau_a"]),
                "depression_u": float(params["depression_u"]),
                "margin": float(params["margin"]),
                "own_gain": float(params["own_gain"]),
                "afferent_gain": float(params["afferent_gain"]),
                "noise_std": float(params["noise_std"]),
                "tau_min": float(params["tau_min"]),
                "tau_max": float(params["tau_max"]),
                "readout_gain": float(params["readout_gain"]),
            }
            if any(
                abs(structural[k] - getattr(self, f"_{k}")) > 1e-12
                for k in structural
            ):
                logger.info(
                    "Ignoring v2 SelfRhythmOscillator state: structural "
                    "generator parameters differ"
                )
                return

            a = float(state["a"])
            s = float(state["s"])
            ln_tau = float(state["ln_tau"])
            ext_mean = float(state["ext_mean"])
            a_mean = float(state["a_mean"])
            s_mean = float(state["s_mean"])
            activity_sum = float(state["activity_sum"])
            step_count = int(state["step_count"])
            for value in (
                a, s, ln_tau, ext_mean, a_mean, s_mean, activity_sum
            ):
                if not math.isfinite(value):
                    raise ValueError(f"non-finite state value {value}")

            self._history_len = max(
                int(self._phase_window_s * self._step_hz), self._history_len
            )

            super().deserialize(state)

            self._a = a
            self._s = s
            # Clamp in log space to the current bounds.
            self._ln_tau = max(math.log(self._tau_min), min(ln_tau, math.log(self._tau_max)))
            self._ext_mean = ext_mean
            self._a_mean = a_mean
            self._s_mean = s_mean
            self._activity_sum = activity_sum
            self._step_count = step_count

            self._activity_history = deque(
                (float(x) for x in state.get("activity_history", [])),
                maxlen=self._history_len,
            )

            rng_state = state.get("rng_state")
            if rng_state is not None:
                self._rng.bit_generator.state = rng_state

            stored_identity = state.get("identity")
            if isinstance(stored_identity, str):
                self.identity = stored_identity

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
    substeps: int = 10,
    w_rec: float = 2.5,
    k_sig: float = 0.08,
    tau_a: float = 0.02,
    depression_u: float = 8.0,
    margin: float = -0.25,
    own_gain: float = 0.02,
    afferent_gain: float = 0.03,
    noise_std: float = 0.02,
    tau_rec: float = 2.1,
    tau_min: float = 0.9,
    tau_max: float = 2.3,
    eta: float = 0.0,
    plasticity_sign: float = -1.0,
    mean_tau_s: float = 10.0,
    readout_gain: float = 1.0,
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
            substeps=substeps,
            w_rec=w_rec,
            k_sig=k_sig,
            tau_a=tau_a,
            depression_u=depression_u,
            margin=margin,
            own_gain=own_gain,
            afferent_gain=afferent_gain,
            noise_std=noise_std,
            tau_rec=tau_rec,
            tau_min=tau_min,
            tau_max=tau_max,
            eta=eta,
            plasticity_sign=plasticity_sign,
            mean_tau_s=mean_tau_s,
            readout_gain=readout_gain,
            phase_window_s=phase_window_s,
            phase_band_hz=phase_band_hz,
        )
    except Exception:  # pragma: no cover - defensive: any lazy-import failure
        return None
