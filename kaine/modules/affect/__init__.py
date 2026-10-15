# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.modules.affect.appraisal import (
    AppraisalScores,
    CategoricalEmotion,
    classify,
)
from kaine.modules.affect.drives import Drive, DriveCrossing, DriveSet
from kaine.modules.affect.goals import Goal, GoalLedger, GoalState
from kaine.modules.affect.modulator import StateModulator
from kaine.modules.affect.module import Affect
from kaine.modules.affect.regulation import PassiveDecay, RegulationPolicy
from kaine.modules.affect.state import DimensionalState

__all__ = [
    "AppraisalScores",
    "CategoricalEmotion",
    "DimensionalState",
    "Drive",
    "DriveCrossing",
    "DriveSet",
    "Goal",
    "GoalLedger",
    "GoalState",
    "PassiveDecay",
    "RegulationPolicy",
    "StateModulator",
    "Affect",
    "classify",
]
