# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.workspace.core import Workspace
from kaine.workspace.novelty import NoveltyTracker, fingerprint
from kaine.workspace.salience import RuleBasedSalience
from kaine.workspace.strategies import (
    AffectModulator,
    DriveRelevanceGoalScorer,
    GoalScorer,
    InterestGoalScorer,
    SalienceStrategy,
    StaticAffectModulator,
    StaticGoalScorer,
    dominant_drive,
)

__all__ = [
    "DriveRelevanceGoalScorer",
    "GoalScorer",
    "InterestGoalScorer",
    "NoveltyTracker",
    "RuleBasedSalience",
    "SalienceStrategy",
    "StaticGoalScorer",
    "StaticAffectModulator",
    "Workspace",
    "AffectModulator",
    "dominant_drive",
    "fingerprint",
]
