# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Scherer Component Process Model — five-check appraisal sequence.

Each check returns a float in [-1, 1]. The 5-tuple maps to a
categorical emotion via a pure `classify` function. The check
callables themselves are defined elsewhere (`module.py` plugs in
defaults that consult goal ledger, dimensional state, etc.) so this
file stays purely about the scoring + classification protocol.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple


class CategoricalEmotion(str, Enum):
    JOY = "joy"
    SADNESS = "sadness"
    ANGER = "anger"
    FEAR = "fear"
    SURPRISE = "surprise"
    DISGUST = "disgust"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class AppraisalScores:
    novelty: float                # surprise / suddenness
    intrinsic_pleasantness: float
    goal_significance: float
    coping_potential: float
    norm_compatibility: float

    def as_tuple(self) -> tuple[float, float, float, float, float]:
        return (
            self.novelty,
            self.intrinsic_pleasantness,
            self.goal_significance,
            self.coping_potential,
            self.norm_compatibility,
        )


_NEUTRAL_BAND = 0.1


def _all_near_zero(scores: AppraisalScores) -> bool:
    return all(abs(v) <= _NEUTRAL_BAND for v in scores.as_tuple())


def classify(scores: AppraisalScores) -> CategoricalEmotion:
    """Map five appraisal scores to one of seven emotions.

    Rules are documented in `docs/kaine-paper.md` references and the
    Scherer 2009 paper. The mapping is intentionally simple: future
    learned classifiers can replace it.
    """
    if _all_near_zero(scores):
        return CategoricalEmotion.NEUTRAL

    pleas = scores.intrinsic_pleasantness
    goal = scores.goal_significance
    coping = scores.coping_potential
    nov = scores.novelty
    norm = scores.norm_compatibility

    # Surprise dominates when novelty is very high and other dims are
    # ambivalent.
    if nov >= 0.6 and abs(pleas) < 0.3 and abs(goal) < 0.3:
        return CategoricalEmotion.SURPRISE

    # Disgust: strongly negative pleasantness + strong norm violation.
    if pleas <= -0.5 and norm <= -0.4:
        return CategoricalEmotion.DISGUST

    # Fear: negative pleasantness + low coping (especially with novelty).
    if pleas < 0 and coping <= -0.3:
        return CategoricalEmotion.FEAR

    # Anger: blocked goal (negative goal_significance interpreted as
    # an obstacle) with strong coping.
    if goal <= -0.3 and coping >= 0.3:
        return CategoricalEmotion.ANGER

    # Sadness: low pleasantness + low coping + low arousal-ish proxy
    # (here approximated by low novelty too).
    if pleas <= -0.3 and coping <= 0 and nov <= 0.3:
        return CategoricalEmotion.SADNESS

    # Joy: positive pleasantness + positive goal_significance + non-negative
    # coping.
    if pleas >= 0.3 and goal >= 0.3 and coping >= 0:
        return CategoricalEmotion.JOY

    # Fallback when scores don't fit a sharp region.
    return CategoricalEmotion.NEUTRAL
