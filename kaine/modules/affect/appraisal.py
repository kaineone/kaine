# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Scherer Component Process Model: five-check appraisal sequence.

Each check returns a float in [-1, 1]. The 5-tuple maps to a
categorical emotion via a pure `classify` function. The check
callables themselves are defined elsewhere (`module.py` plugs in
defaults that consult goal ledger, dimensional state, etc.) so this
file stays purely about the scoring + classification protocol.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


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
    coping_available: bool = True

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

    Rules are modeled on the predicted appraisal profiles of Sander,
    Grandjean and Scherer (2005, Table 3). KAINE uses a single novelty
    check for suddenness, familiarity and predictability, so low
    familiarity in Table 3 maps to high novelty here. The classifier
    checks, in order: a neutral band; surprise (very high novelty with
    otherwise ambivalent scores); fear (negative pleasantness and low
    coping); anger (blocked goal with strong coping, matching at best
    Table 3's irritation profile); disgust (very low pleasantness, low
    familiarity as high novelty, and low goal relevance); sadness (low
    pleasantness, low coping and low novelty); joy (positive
    pleasantness, positive goal relevance and non-negative coping); and
    finally neutral. Norm compatibility is undefined because KAINE has
    no authored standards list until an operator writes one, so no rule
    reads norm_compatibility.
    """
    if _all_near_zero(scores):
        return CategoricalEmotion.NEUTRAL

    pleas = scores.intrinsic_pleasantness
    goal = scores.goal_significance
    coping = scores.coping_potential
    nov = scores.novelty

    # Surprise dominates when novelty is very high and other dims are
    # ambivalent.
    if nov >= 0.6 and abs(pleas) < 0.3 and abs(goal) < 0.3:
        return CategoricalEmotion.SURPRISE

    # Fear: negative pleasantness + low coping (especially with novelty).
    # Coping is undefined for irrelevant content (paper A.4), so this branch
    # needs relevant content.
    if scores.coping_available and pleas < 0 and coping <= -0.3:
        return CategoricalEmotion.FEAR

    # Anger: blocked goal with strong coping. This matches at best Table 3's
    # irritation profile, because KAINE attributes no obstruction to another
    # agent and has no standards check. It needs a negative goal score, which
    # the obstruction term of paper A.4 supplies. Coping is undefined for
    # irrelevant content, so this branch needs relevant content.
    if scores.coping_available and goal <= -0.3 and coping >= 0.3:
        return CategoricalEmotion.ANGER

    # Disgust: modeled on Table 3's disgust profile. Very low pleasantness,
    # low familiarity (KAINE's single novelty check, so high novelty) and low
    # goal relevance; the standards check is left open because KAINE has no
    # authored standards list.
    if pleas <= -0.5 and nov > 0.3 and abs(goal) < 0.3:
        return CategoricalEmotion.DISGUST

    # Sadness: low pleasantness + low coping + low arousal-ish proxy
    # (here approximated by low novelty too).
    # Coping is undefined for irrelevant content (paper A.4), so this branch
    # needs relevant content.
    if scores.coping_available and pleas <= -0.3 and coping <= 0 and nov <= 0.3:
        return CategoricalEmotion.SADNESS

    # Joy: positive pleasantness + positive goal_significance + non-negative
    # coping.
    if pleas >= 0.3 and goal >= 0.3 and coping >= 0:
        return CategoricalEmotion.JOY

    # Fallback when scores don't fit a sharp region.
    return CategoricalEmotion.NEUTRAL
