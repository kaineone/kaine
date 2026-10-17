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
    otherwise ambivalent scores); fear (low pleasantness at or below -0.3,
    low familiarity as novelty above 0.3, an obstructed goal at or below
    -0.3, and very low coping at or below -0.3); anger (blocked goal with
    strong coping, matching at best Table 3's irritation profile); disgust
    (very low pleasantness, low familiarity as high novelty, and low goal
    relevance); sadness (low pleasantness, low coping and low novelty); joy
    (positive pleasantness, positive goal relevance and non-negative
    coping); and finally neutral. Norm compatibility is undefined because
    KAINE has no authored standards list until an operator writes one, so
    no category rule reads norm_compatibility; only the neutral band, which
    spans all five scores, sees its fixed 0.0.
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

    # Fear: modeled on Table 3's fear profile. Low intrinsic pleasantness,
    # low familiarity (mapped to high novelty here), an obstructed goal from
    # the obstruction term of the paper's A.4, and very low power as coping
    # at or below -0.3. The -0.3 cut-offs match the anger and disgust rules;
    # coping is undefined for irrelevant content (paper A.4), so the branch
    # needs relevant content.
    if scores.coping_available and pleas <= -0.3 and nov > 0.3 and goal <= -0.3 and coping <= -0.3:
        return CategoricalEmotion.FEAR

    # Anger: blocked goal with strong coping. This matches at best Table 3's
    # irritation profile, because KAINE attributes no obstruction to another
    # agent and has no standards check. The obstruction term of paper A.4
    # supplies the negative goal score. Coping is undefined for
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
