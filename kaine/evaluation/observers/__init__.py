# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Read-only sidecar evaluation observers.

Each observer is individually toggleable under ``[evaluation.observers]``
and degrades to a clean no-op when its source stream is absent.  None
publish to the bus; all write daily-rotated JSONL.
"""
from kaine.evaluation.observers.coherence_observer import CoherenceObserver
from kaine.evaluation.observers.empatheia_observer import EmpatheiaObserver
from kaine.evaluation.observers.fatigue_observer import FatigueObserver
from kaine.evaluation.observers.nous_policy_observer import NousPolicyObserver
from kaine.evaluation.observers.prediction_error_observer import PredictionErrorObserver
from kaine.evaluation.observers.replay_observer import ReplayObserver
from kaine.evaluation.observers.voice_alignment_divergence_observer import (
    VoiceAlignmentDivergenceObserver,
)
from kaine.evaluation.observers.welfare_observer import WelfareObserver

__all__ = [
    "CoherenceObserver",
    "EmpatheiaObserver",
    "FatigueObserver",
    "NousPolicyObserver",
    "PredictionErrorObserver",
    "ReplayObserver",
    "VoiceAlignmentDivergenceObserver",
    "WelfareObserver",
]
