# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import dataclasses

from kaine.modules.affect.appraisal import (
    AppraisalScores,
    CategoricalEmotion,
    classify,
)


def _scores(novelty=0, pleasantness=0, goal=0, coping=0, norm=0):
    return AppraisalScores(
        novelty=novelty,
        intrinsic_pleasantness=pleasantness,
        goal_significance=goal,
        coping_potential=coping,
        norm_compatibility=norm,
    )


def test_neutral_when_all_near_zero():
    assert classify(_scores()) == CategoricalEmotion.NEUTRAL
    assert classify(_scores(novelty=0.05, pleasantness=-0.05)) == CategoricalEmotion.NEUTRAL


def test_joy_for_positive_pleasantness_and_goal():
    assert classify(_scores(pleasantness=0.7, goal=0.6, coping=0.5)) == CategoricalEmotion.JOY


def test_fear_for_negative_pleasantness_low_coping():
    assert classify(_scores(novelty=0.7, pleasantness=-0.6, coping=-0.5)) == CategoricalEmotion.FEAR


def test_surprise_for_high_novelty_neutral_otherwise():
    assert classify(_scores(novelty=0.8)) == CategoricalEmotion.SURPRISE


def test_anger_for_blocked_goal_with_coping():
    assert classify(_scores(pleasantness=-0.3, goal=-0.5, coping=0.4)) == CategoricalEmotion.ANGER


def test_sadness_for_low_pleasantness_low_coping_low_novelty():
    assert classify(_scores(pleasantness=-0.5, coping=-0.2, novelty=0.1)) == CategoricalEmotion.SADNESS


def test_disgust_table3_profile_with_zero_norm():
    profile = AppraisalScores(
        novelty=0.7,
        intrinsic_pleasantness=-0.7,
        goal_significance=0.0,
        coping_potential=0.0,
        norm_compatibility=0.0,
        coping_available=False,
    )
    assert classify(profile) == CategoricalEmotion.DISGUST


def test_disgust_table3_profile_with_default_coping_available():
    profile = AppraisalScores(
        novelty=0.7,
        intrinsic_pleasantness=-0.7,
        goal_significance=0.0,
        coping_potential=0.0,
        norm_compatibility=0.0,
    )
    assert classify(profile) == CategoricalEmotion.DISGUST


def test_norm_violation_alone_is_not_disgust():
    assert classify(_scores(pleasantness=-0.7, norm=-0.6)) != CategoricalEmotion.DISGUST


def test_relevant_content_is_not_disgust():
    assert classify(_scores(novelty=0.7, pleasantness=-0.7, goal=0.5)) != CategoricalEmotion.DISGUST


def test_familiar_content_is_not_disgust():
    assert classify(_scores(novelty=0.2, pleasantness=-0.7)) != CategoricalEmotion.DISGUST


def test_mildly_unpleasant_content_is_not_disgust():
    assert classify(_scores(novelty=0.7, pleasantness=-0.4)) != CategoricalEmotion.DISGUST


def test_fear_keeps_precedence_over_disgust():
    assert classify(_scores(novelty=0.7, pleasantness=-0.6, goal=0.2, coping=-0.5)) == CategoricalEmotion.FEAR


def test_disgust_norm_score_does_not_move_result():
    profile = AppraisalScores(
        novelty=0.7,
        intrinsic_pleasantness=-0.7,
        goal_significance=0.0,
        coping_potential=0.0,
        norm_compatibility=0.0,
        coping_available=False,
    )
    for norm in (-1.0, 0.0, 1.0):
        assert classify(dataclasses.replace(profile, norm_compatibility=norm)) == CategoricalEmotion.DISGUST


def test_as_tuple():
    s = AppraisalScores(novelty=0.1, intrinsic_pleasantness=0.2, goal_significance=0.3, coping_potential=0.4, norm_compatibility=0.5)
    assert s.as_tuple() == (0.1, 0.2, 0.3, 0.4, 0.5)


def test_categorical_emotion_str_values():
    assert CategoricalEmotion.JOY.value == "joy"
    assert CategoricalEmotion.NEUTRAL.value == "neutral"
