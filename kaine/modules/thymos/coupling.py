# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Affect coupling for Thymos: familiarity-weighted perceived emotion as
an *input to the entity's own Scherer appraisal*.

A detected speaker emotion (``audition.emotion``) is not written onto the
entity's dimensional (valence/arousal/dominance) state. Instead it is
recorded as a transient, decaying perceptual signal and folded into the
five-check Scherer appraisal: the perceived other's pleasantness enters
``intrinsic_pleasantness`` and the perceived emotional intensity enters
``novelty``, each weighted by ``compute_coupling`` (familiarity-modulated)
and by the recency of the signal. The entity's *own* appraisal — together
with its goal significance, coping, and novelty — then determines the
classified emotion and the resulting bounded state change via the existing
appraisal→state nudge.

Resonance with others is thereby an *output* of the entity's appraisal,
modulated by familiarity, goals and current condition — it emerges, rather
than being imposed by a direct mirror-write. The ``EMOTION_VAD`` table is
reused only to derive the *perceived other's* pleasantness/intensity, never
as a target the state is moved toward.

Boundedness comes from two places: the contribution weight is clamped by
``coupling_ceiling`` and each appraisal dimension is clamped to ``[-1, 1]``;
and the signal decays to zero over ``decay_s`` so a speaker who stops talking
stops influencing appraisal. The existing drift/hysteresis then recovers the
dimensional state toward baseline.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


# ---------------------------------------------------------------------------
# Perceived-emotion VAD reference per audition emotion category
# Keys mirror kaine/modules/audition/emotion.py CATEGORIES.
# Values are (valence, arousal, dominance) describing the *perceived other's*
# emotion. Used only to derive the perceived pleasantness (valence) and
# intensity (arousal) that enter Thymos's own appraisal — NOT a state target.
#   valence   ∈ [-1, 1]
#   arousal   ∈ [0,  1]
#   dominance ∈ [-1, 1]
# ---------------------------------------------------------------------------

#: Emotion category → (valence, arousal, dominance)
EMOTION_VAD: dict[str, Tuple[float, float, float]] = {
    "happy":    ( 0.8,  0.7,  0.5),
    "sad":      (-0.7,  0.2, -0.5),
    "angry":    (-0.6,  0.8,  0.6),
    "fearful":  (-0.7,  0.8, -0.7),
    "surprised": (0.3,  0.8,  0.0),
    "disgusted":(-0.8,  0.5,  0.3),
    "neutral":  ( 0.0,  0.3,  0.0),
}


# ---------------------------------------------------------------------------
# Appraisal-influence weight helper
# ---------------------------------------------------------------------------

def compute_coupling(
    *,
    coupling_base: float,
    coupling_familiarity_gain: float,
    familiarity: float,
    coupling_ceiling: float,
) -> float:
    """Return the appraisal-influence weight, clamped to [0, ceiling].

    This weight scales how strongly a perceived other-emotion enters the
    entity's own Scherer appraisal (you appraise the feelings of those you
    are close to as more significant). It is NOT a direct state-nudge rate.

    weight = clamp(coupling_base + coupling_familiarity_gain × familiarity,
                   0, coupling_ceiling)
    """
    raw = coupling_base + coupling_familiarity_gain * familiarity
    return max(0.0, min(coupling_ceiling, raw))


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CouplingConfig:
    """All `[thymos.coupling]` knobs in one immutable bag.

    The knobs are appraisal-influence weights, not direct state-nudge rates:

    - ``enabled`` — master toggle; ships ``False``.
    - ``coupling_base`` — appraisal-influence weight with no known familiarity.
    - ``coupling_familiarity_gain`` — extra weight per unit Empatheia familiarity.
    - ``coupling_ceiling`` — hard clamp on the appraisal-influence weight.
    - ``decay_s`` — window over which a perceived-emotion signal decays to zero;
      once older than ``decay_s`` it contributes nothing to appraisal.
    """

    enabled: bool = False
    coupling_base: float = 0.05
    coupling_familiarity_gain: float = 0.10
    coupling_ceiling: float = 0.15
    decay_s: float = 10.0

    def __post_init__(self) -> None:
        if self.coupling_base < 0:
            raise ValueError("coupling_base must be >= 0")
        if self.coupling_familiarity_gain < 0:
            raise ValueError("coupling_familiarity_gain must be >= 0")
        if self.coupling_ceiling < 0:
            raise ValueError("coupling_ceiling must be >= 0")
        if self.decay_s <= 0:
            raise ValueError("decay_s must be > 0")
