# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.workspace.novelty import NoveltyTracker, fingerprint
from kaine.workspace.salience import RuleBasedSalience
from kaine.workspace.strategies import (
    AffectModulator,
    DriveRelevanceGoalScorer,
    GoalScorer,
    SalienceStrategy,
    StaticAffectModulator,
    StaticGoalScorer,
    dominant_drive,
)
from kaine.workspace.syneidesis import Syneidesis

__all__ = [
    "DriveRelevanceGoalScorer",
    "GoalScorer",
    "NoveltyTracker",
    "RuleBasedSalience",
    "SalienceStrategy",
    "StaticGoalScorer",
    "StaticAffectModulator",
    "Syneidesis",
    "AffectModulator",
    "dominant_drive",
    "fingerprint",
]
