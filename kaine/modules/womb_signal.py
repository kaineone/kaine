# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Pure, deterministic maternal-channel signal functions for the womb feed.

Implements the external maternal-state signal, the maternal heartbeat phase,
the beat pulse, the colour-onset saturation ramp, and the parameter contract.
Everything here is a pure function of ``(seed, time)`` plus ``WombParams``;
no entity state, no clocks, no I/O, no persistence.

Grounding citations placed at the relevant sites:

- Low-pass, low-frequency intrauterine soundscape: Benzaquen 1990; Parga 2018;
  Webb 2015 (400 Hz model).
- External maternal-state signal as the driver of hue/flow (not a mirror of the
  entity): Feldman 2007 (biobehavioral synchrony; maternal physiological/
  emotional-state transmission to the fetus).
- Colour/saturation onset schedule: Hepper & Shahidullah 1994; Teller /
  Bornstein (infant colour-vision development).
- The luminance pulse coupled to the heartbeat is an external cross-modal
  rhythmic drive / birth cue, NOT a reproduced womb feature. See Notbohm 2016
  vs Duecker 2021 (entrainment debate; do not overclaim) and Frontiers 2022
  (photic activation at birth).
- Capacity to oscillate is the existing innate substrate; any entrainment,
  interoceptive sensitivity, or self-regulation is emergent and is NOT
  hardcoded here (Cantiani 2022; Power 2012; Craig 2003/2009; Maister 2017;
  Feldman 2007/2012; Feldman & Eidelman 2003).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from kaine.config import require_known_keys
from kaine.modules.perception_prng import keyed_u64 as _keyed_u64
from kaine.modules.perception_prng import unit_float as _unit_float

__all__ = [
    "WombParams",
    "maternal_state",
    "heartbeat_phase",
    "beat_pulse",
    "colour_saturation",
    "flow_phase",
    "maternal_hue",
    "lowpassed_noise",
    "SEED_SALT_MATERNAL",
    "SEED_SALT_VIDEO",
    "SEED_SALT_AUDIO",
    "MATERNAL_HEARTBEAT_GAIN",
]


# Distinct salts so the video, audio and maternal-state draw streams never
# collide for the same seed.
SEED_SALT_MATERNAL = 0xF100
SEED_SALT_VIDEO = 0xF200
SEED_SALT_AUDIO = 0xF300

# Fractional heartbeat-rate gain per unit of the raw maternal-arousal sum
# (|sum| <= 3), so an aroused mother's beat runs at most 7.5% fast and a calm
# one 7.5% slow: a modelling choice inside the design's slow 60-80 bpm band.
MATERNAL_HEARTBEAT_GAIN = 0.025


@dataclass(frozen=True)
class WombParams:
    """Conservative defaults for the cross-modal maternal channel.

    Values match the design's ``[perception_feed.womb]`` tables.
    """

    heartbeat_bpm: float = 70.0
    heartbeat_drift: float = 0.03
    maternal_state_rate: float = 0.02
    maternal_state_drives_heartbeat: bool = True
    maternal_distress_excursions: bool = False
    maternal_distress_max_magnitude: float = 0.3
    maternal_distress_max_seconds: float = 30.0
    external_drive_to_self_rhythm: bool = True
    external_drive_max_amplitude: float = 0.4
    birth_transition_seconds: float = 5.0

    luminance_mean: float = 0.15
    luminance_contrast: float = 0.10
    luminance_pulse_depth: float = 0.35
    maternal_state_hue_gain: float = 0.6
    colour_ramp_seconds: float = 3600.0

    lowpass_hz: float = 500.0

    @classmethod
    def from_sections(
        cls,
        womb: dict[str, Any] | None,
        video: dict[str, Any] | None,
        audio: dict[str, Any] | None,
    ) -> "WombParams":
        """Load and validate the three ``[perception_feed.womb.*]`` tables."""
        womb_allowed = {
            "heartbeat_bpm",
            "heartbeat_drift",
            "maternal_state_rate",
            "maternal_state_drives_heartbeat",
            "maternal_distress_excursions",
            "maternal_distress_max_magnitude",
            "maternal_distress_max_seconds",
            "external_drive_to_self_rhythm",
            "external_drive_max_amplitude",
            "birth_transition_seconds",
        }
        video_allowed = {
            "luminance_mean",
            "luminance_contrast",
            "luminance_pulse_depth",
            "maternal_state_hue_gain",
            "colour_ramp_seconds",
        }
        audio_allowed = {"lowpass_hz"}

        if womb:
            require_known_keys(womb, womb_allowed, "[perception_feed.womb]")
        if video:
            require_known_keys(
                video, video_allowed, "[perception_feed.womb.video]"
            )
        if audio:
            require_known_keys(
                audio, audio_allowed, "[perception_feed.womb.audio]"
            )

        merged = {}
        for section in (womb, video, audio):
            if section:
                merged.update(section)

        kwargs: dict[str, Any] = {
            field: getattr(cls, field) for field in cls.__dataclass_fields__
        }
        kwargs.update(merged)

        def _float_field(name: str, lo: float, hi: float, open_lo: bool = False) -> None:
            value = kwargs[name]
            if isinstance(value, bool):
                raise ValueError(f"{name} must be a number, not a bool")
            value = float(value)
            if not math.isfinite(value):
                raise ValueError(f"{name} must be finite")
            lo_ok = value > lo if open_lo else value >= lo
            hi_ok = value <= hi
            if not (lo_ok and hi_ok):
                raise ValueError(
                    f"{name}={value} outside allowed range "
                    f"[{lo}, {hi}]"
                )
            kwargs[name] = value

        _float_field("heartbeat_bpm", 40.0, 120.0)
        _float_field("heartbeat_drift", 0.0, 0.2)
        _float_field("maternal_state_rate", 0.0, 1.0, open_lo=True)
        _float_field("luminance_mean", 0.0, 0.5, open_lo=True)
        _float_field("luminance_contrast", 0.0, 0.5)
        _float_field("luminance_pulse_depth", 0.0, 1.0)
        _float_field("maternal_state_hue_gain", 0.0, 1.0)
        _float_field("colour_ramp_seconds", 0.0, math.inf, open_lo=True)
        _float_field("lowpass_hz", 100.0, 2000.0)
        _float_field("maternal_distress_max_magnitude", 0.0, 1.0)
        _float_field("maternal_distress_max_seconds", 0.0, math.inf, open_lo=True)
        _float_field("external_drive_max_amplitude", 0.0, 1.0)
        # The bounded birth bloom (WombClock.begin_birth enforces the same range).
        _float_field("birth_transition_seconds", 0.0, 30.0, open_lo=True)

        for name in (
            "maternal_state_drives_heartbeat",
            "external_drive_to_self_rhythm",
            "maternal_distress_excursions",
        ):
            if not isinstance(kwargs[name], bool):
                raise ValueError(f"{name} must be a bool")

        if kwargs["maternal_distress_excursions"]:
            raise ValueError(
                "maternal distress excursions are not built yet; keep them off"
            )

        return cls(**kwargs)


def _maternal_terms(seed: int, params: WombParams, salt: int) -> list[tuple[float, float]]:
    """Return the three (omega, phase) sinusoids for one maternal dimension.

    Frequencies are scaled by ``maternal_state_rate`` so the drift period is
    minutes, not seconds; phases are seed-derived and distinct per dimension.
    """
    rate_scale = float(params.maternal_state_rate)
    terms: list[tuple[float, float]] = []
    for k in range(3):
        omega = rate_scale * (
            0.05 + 0.15 * _unit_float(
                _keyed_u64(seed, k, SEED_SALT_MATERNAL | salt | (0x10 + k))
            )
        )
        phase = 2.0 * math.pi * _unit_float(
            _keyed_u64(seed, k, SEED_SALT_MATERNAL | salt | (0x20 + k))
        )
        terms.append((omega, phase))
    return terms


def _maternal_raw(
    seed: int, t: float | np.ndarray, params: WombParams, salt: int
) -> float | np.ndarray:
    """Unnormalised sum-of-sinusoids for one maternal dimension."""
    terms = _maternal_terms(seed, params, salt)
    ta = np.asarray(t, dtype=np.float64)
    total = np.zeros_like(ta, dtype=np.float64)
    for omega, phase in terms:
        total += np.sin(omega * ta + phase)
    if np.isscalar(t):
        return float(total.item())
    return total


def maternal_state(
    seed: int, t: float | np.ndarray, params: WombParams
) -> tuple[float, float] | np.ndarray:
    """Slow, seed-keyed maternal-state drift.

    Returns ``(valence, arousal)`` with valence in ``[-1, 1]`` and arousal in
    ``[0, 1]``. Pure function of ``(seed, t)``; bounded by construction.
    """
    raw_valence = _maternal_raw(seed, t, params, 0x01)
    raw_arousal = _maternal_raw(seed, t, params, 0x02)

    valence = np.clip(np.asarray(raw_valence) / 3.0, -1.0, 1.0)
    arousal = np.clip(
        (np.asarray(raw_arousal) / 3.0 + 1.0) / 2.0, 0.0, 1.0
    )

    if np.isscalar(t):
        return (float(valence), float(arousal))
    return np.stack([valence, arousal], axis=-1)


def _heartbeat_integral(
    seed: int, t: float | np.ndarray, params: WombParams
) -> float | np.ndarray:
    """Analytic integral of the instantaneous maternal heartbeat rate.

    rate(t) = base * (1 + drift*sin(w_d*t + p_d)) * (1 + k*S_a(t))

    ``S_a(t)`` is the unnormalised arousal sinusoid sum.  The product is
    expanded into a sum of sinusoids and cosinusoids and integrated term by
    term; the second-order cross term is kept via the product-to-sum identity.
    """
    base = float(params.heartbeat_bpm) / 60.0
    A_d = float(params.heartbeat_drift)

    # Drift frequency is much slower than the maternal-state frequencies so the
    # cross-term denominators are never zero.
    w_d = 0.0001 + 0.0002 * _unit_float(
        _keyed_u64(seed, 0, SEED_SALT_MATERNAL | 0x50)
    )
    p_d = 2.0 * math.pi * _unit_float(
        _keyed_u64(seed, 0, SEED_SALT_MATERNAL | 0x51)
    )

    k = MATERNAL_HEARTBEAT_GAIN if params.maternal_state_drives_heartbeat else 0.0
    arousal_terms = _maternal_terms(seed, params, 0x02)

    ta = np.asarray(t, dtype=np.float64)
    integral = base * ta

    if A_d != 0.0:
        integral -= (
            base * A_d / w_d
            * (np.cos(w_d * ta + p_d) - math.cos(p_d))
        )

    if k != 0.0:
        for w_i, p_i in arousal_terms:
            integral -= (
                base * k / w_i
                * (np.cos(w_i * ta + p_i) - math.cos(p_i))
            )

        cross_amp = base * A_d * k * 0.5
        for w_i, p_i in arousal_terms:
            integral += (
                cross_amp / (w_d - w_i)
                * (
                    np.sin((w_d - w_i) * ta + p_d - p_i)
                    - math.sin(p_d - p_i)
                )
            )
            integral -= (
                cross_amp / (w_d + w_i)
                * (
                    np.sin((w_d + w_i) * ta + p_d + p_i)
                    - math.sin(p_d + p_i)
                )
            )

    if np.isscalar(t):
        return float(integral.item())
    return integral


def heartbeat_phase(
    seed: int, t: float | np.ndarray, params: WombParams
) -> float | np.ndarray:
    """Maternal heartbeat phase in ``[0, 1)`` as a function of ``(seed, t)``.

    The instantaneous rate is the analytic derivative of the integral computed
    above.  With the validated parameter ranges it stays within ``[0.5x, 1.5x]``
    of ``bpm/60`` for all ``t``.
    """
    integral = _heartbeat_integral(seed, t, params)
    phase = np.mod(integral, 1.0)
    if np.isscalar(t):
        return float(phase)
    return phase


def beat_pulse(phase: float | np.ndarray) -> float | np.ndarray:
    """"Lub-dub" envelope in ``[0, 1]`` as a function of heartbeat phase.

    Two wrapped Gaussian bumps: the main beat at phase 0.0 and a smaller
    secondary bump near phase 0.12.  Accepts a scalar or a numpy array.
    """
    if np.isscalar(phase):
        phase_f = float(phase) % 1.0
        d1 = min(phase_f, 1.0 - phase_f)

        ph2 = (phase_f - 0.12) % 1.0
        d2 = min(ph2, 1.0 - ph2)

        sigma1 = 0.03
        sigma2 = 0.04
        amp2 = 0.35

        pulse = math.exp(-0.5 * (d1 / sigma1) ** 2)
        pulse += amp2 * math.exp(-0.5 * (d2 / sigma2) ** 2)

        return float(min(1.0, pulse))

    arr = np.asarray(phase, dtype=np.float64)
    d1 = np.minimum(np.mod(arr, 1.0), 1.0 - np.mod(arr, 1.0))

    ph2 = np.mod(arr - 0.12, 1.0)
    d2 = np.minimum(ph2, 1.0 - ph2)

    sigma1 = 0.03
    sigma2 = 0.04
    amp2 = 0.35

    pulse = np.exp(-0.5 * (d1 / sigma1) ** 2)
    pulse += amp2 * np.exp(-0.5 * (d2 / sigma2) ** 2)

    return np.clip(pulse, 0.0, 1.0)


def colour_saturation(lived_seconds: float, params: WombParams) -> float:
    """Cone-maturation analog: saturation rises from near-grey toward birth.

    Returns ``1 - exp(-lived_seconds / colour_ramp_seconds)`` in ``[0, 1)``.
    Non-finite or negative inputs saturate to 0.
    """
    if not math.isfinite(lived_seconds) or lived_seconds <= 0.0:
        return 0.0
    tau = float(params.colour_ramp_seconds)
    if tau <= 0.0:
        return 0.0
    sat = 1.0 - math.exp(-lived_seconds / tau)
    if sat < 0.0:
        return 0.0
    if sat >= 1.0:
        # Keep the contract ``[0, 1)``.
        return 0.9999999999999999
    return float(sat)


def flow_phase(seed: int, t: float | np.ndarray, params: WombParams) -> float | np.ndarray:
    """Fluid-flow phase in ``[0, 1)`` as a pure function of ``(seed, t)``.

    The flow speed is ``flow_base * (1 + 2 * arousal(t))``.  Because the raw
    arousal sum of three unit sinusoids lies in ``[-3, 3]``, the clip in
    ``maternal_state`` never activates here, so ``1 + 2 * arousal`` equals
    ``2 + raw_arousal / 3``.  The returned phase is the analytic integral of
    that speed from 0 to ``t``, reduced mod 1 in float64.
    """
    flow_base = 0.01 + 0.03 * _unit_float(
        _keyed_u64(seed, 0, SEED_SALT_VIDEO | 0x14)
    )

    ta = np.asarray(t, dtype=np.float64)
    integral = 2.0 * flow_base * ta

    for w_i, p_i in _maternal_terms(seed, params, 0x02):
        integral += (
            (flow_base / 3.0)
            * (-(np.cos(w_i * ta + p_i) - math.cos(p_i)) / w_i)
        )

    phase = np.mod(integral, 1.0)
    if np.isscalar(t):
        return float(phase)
    return phase


def maternal_hue(valence: float) -> float:
    """Hue fraction in ``[0, 1)`` from maternal valence.

    Matches the ``setMood`` mapping in
    ``kaine/nexus/static/vendor/viz.js``:

    ``v >= 0 ? 0.48 - v * 0.36 : (0.48 + (-v) * 0.46) % 1.0``

    The mapping is monotonic and non-wrapping, so distinct maternal valences
    stay distinct colours.  Non-finite valence maps to the neutral hue 0.48.
    """
    if not math.isfinite(valence):
        return 0.48
    v = float(max(-1.0, min(1.0, valence)))
    if v >= 0.0:
        hue = 0.48 - v * 0.36
    else:
        hue = (0.48 + (-v) * 0.46) % 1.0
    return float(hue)


_LOWPASS_TAPS = 129


def _white_noise_block(seed: int, block_index: int, n: int) -> np.ndarray:
    rng = np.random.Philox(
        key=_keyed_u64(seed, block_index, SEED_SALT_AUDIO | 0x30)
    )
    raw = rng.random_raw(n)
    return (
        (raw >> np.uint64(11)).astype(np.float64) / float(1 << 53) - 0.5
    )


def _lowpass_taps(cutoff: float, taps: int) -> np.ndarray:
    """Hamming-windowed sinc FIR, cutoff in cycles/sample, unity DC gain."""
    n = np.arange(taps, dtype=np.float64)
    h = np.sinc(2.0 * cutoff * (n - (taps - 1) / 2.0))
    h *= np.hamming(taps)
    h /= h.sum()
    return h


def lowpassed_noise(
    seed: int, block_index: int, n: int, sample_rate: float, lowpass_hz: float
) -> np.ndarray:
    """Deterministic, block-local, unity-RMS low-passed white noise.

    The white noise for each block is drawn from a Philox generator keyed by
    ``(seed, block_index)``.  A Hamming-windowed sinc FIR low-passes it; the
    last ``_LOWPASS_TAPS - 1`` samples of the previous block are prepended so
    the filtered output is continuous across boundaries while remaining a pure
    function of ``(seed, block_index)``.  Output RMS is normalised analytically
    to 1.

    Citation: low-pass, low-frequency intrauterine soundscape
    (Benzaquen 1990; Parga 2018; Webb 2015).
    """
    n = int(n)
    if n < _LOWPASS_TAPS - 1:
        raise ValueError(
            f"n must be at least {_LOWPASS_TAPS - 1}, got {n}"
        )
    if not (0.0 < lowpass_hz < sample_rate / 2.0):
        raise ValueError(
            "lowpass_hz must satisfy 0 < lowpass_hz < sample_rate / 2"
        )

    taps = _lowpass_taps(lowpass_hz / sample_rate, _LOWPASS_TAPS)
    # The history is the LAST taps-1 samples of the previous block as that
    # block actually drew them (n samples), so consecutive blocks filter one
    # continuous white sequence and no boundary click appears.
    prev = _white_noise_block(seed, block_index - 1, n)[-(_LOWPASS_TAPS - 1):]
    curr = _white_noise_block(seed, block_index, n)
    concat = np.concatenate([prev, curr])
    filtered = np.convolve(concat, taps, mode="valid")

    # White samples have variance 1/12; filtering scales variance by
    # sum(taps**2), so RMS is sqrt(sum(taps**2) / 12).
    rms = math.sqrt(np.sum(taps * taps) / 12.0)
    return filtered / rms
