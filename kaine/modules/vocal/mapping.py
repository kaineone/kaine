# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Affect → vocal expressivity controls.

Chatterbox mapping — pure function. Documented monotonicity:
  - higher arousal → strictly higher exaggeration
  - higher arousal → strictly higher temperature (within band)
  - stronger |valence| → strictly higher cfg_weight (more committed)
  - high negative valence → slower speed; high positive valence → faster

Qwen3-TTS mapping — natural-language instruct string derived from the same
dimensional state.
"""
from __future__ import annotations

from dataclasses import dataclass

from kaine.modules.affect.state import DimensionalState


def _clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


@dataclass(frozen=True)
class ChatterboxParams:
    temperature: float
    exaggeration: float
    cfg_weight: float
    speed_factor: float

    def to_request_kwargs(self) -> dict[str, float]:
        return {
            "temperature": float(self.temperature),
            "exaggeration": float(self.exaggeration),
            "cfg_weight": float(self.cfg_weight),
            "speed_factor": float(self.speed_factor),
        }


# Documented bands. Wide-enough to be expressive without breaking
# Chatterbox's stability envelope.
_TEMPERATURE_BAND = (0.4, 0.95)
_EXAGGERATION_BAND = (0.3, 0.95)
_CFG_WEIGHT_BAND = (0.3, 0.95)
_SPEED_BAND = (0.85, 1.15)


def affect_to_chatterbox(
    state: DimensionalState,
    *,
    baseline_temperature: float = 0.7,
    baseline_exaggeration: float = 0.5,
    baseline_cfg_weight: float = 0.5,
    baseline_speed: float = 1.0,
) -> ChatterboxParams:
    """Linear interpolation inside each documented band.

    Arousal drives temperature + exaggeration; |valence| drives cfg_weight;
    valence sign drives a small speed shift around 1.0.
    """
    arousal = _clamp(state.arousal, 0.0, 1.0)
    valence = _clamp(state.valence, -1.0, 1.0)
    valence_mag = abs(valence)

    temp_lo, temp_hi = _TEMPERATURE_BAND
    exag_lo, exag_hi = _EXAGGERATION_BAND
    cfg_lo, cfg_hi = _CFG_WEIGHT_BAND
    spd_lo, spd_hi = _SPEED_BAND

    temperature = temp_lo + (temp_hi - temp_lo) * arousal
    exaggeration = exag_lo + (exag_hi - exag_lo) * arousal
    cfg_weight = cfg_lo + (cfg_hi - cfg_lo) * valence_mag
    # Speed: 0.85 at valence=-1, 1.0 at valence=0, 1.15 at valence=+1.
    speed_factor = 1.0 + (spd_hi - 1.0) * valence  # symmetric since spd_lo + spd_hi - 2 = 0

    # Apply baseline pulls so callers without the affect module still get sensible
    # defaults — the math above just keeps the bands monotonic in inputs.
    if state == DimensionalState():
        return ChatterboxParams(
            temperature=baseline_temperature,
            exaggeration=baseline_exaggeration,
            cfg_weight=baseline_cfg_weight,
            speed_factor=baseline_speed,
        )

    return ChatterboxParams(
        temperature=_clamp(temperature, temp_lo, temp_hi),
        exaggeration=_clamp(exaggeration, exag_lo, exag_hi),
        cfg_weight=_clamp(cfg_weight, cfg_lo, cfg_hi),
        speed_factor=_clamp(speed_factor, spd_lo, spd_hi),
    )


_AROUSAL_HIGH = 0.6
_VALENCE_POSITIVE = 0.3
_VALENCE_NEGATIVE = -0.3
_DOMINANCE_HIGH = 0.5


def affect_to_instruct(state: DimensionalState) -> str:
    """Map dimensional affect to a Qwen3-TTS instruct string.

    Returns an empty string for neutral affect so the model uses its default
    prosody.
    """
    arousal = _clamp(state.arousal, 0.0, 1.0)
    valence = _clamp(state.valence, -1.0, 1.0)
    dominance = _clamp(state.dominance, -1.0, 1.0)

    if state == DimensionalState():
        return ""

    high_arousal = arousal > _AROUSAL_HIGH
    positive = valence > _VALENCE_POSITIVE
    negative = valence < _VALENCE_NEGATIVE

    if positive and high_arousal:
        phrase = "Speak with warm enthusiasm"
    elif positive and not high_arousal:
        phrase = "Speak gently and contentedly"
    elif negative and high_arousal:
        phrase = "Speak with urgency and distress"
    elif negative and not high_arousal:
        phrase = "Speak quietly and sadly"
    elif high_arousal:
        phrase = "Speak with energy and intensity"
    else:
        return ""

    if dominance > _DOMINANCE_HIGH:
        phrase += ", with confidence"

    return phrase
