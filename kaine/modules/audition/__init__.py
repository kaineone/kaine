# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.modules.audition.emotion import (
    CATEGORIES,
    EmotionClassifier,
    EmotionResult,
    Emotion2vecClassifier,
    FakeEmotionClassifier,
)
from kaine.modules.audition.module import Audition
from kaine.modules.audition.stt_client import (
    FakeSTTClient,
    SpeachesClient,
    STTClient,
    TranscriptionResult,
)

__all__ = [
    "Audition",
    "CATEGORIES",
    "Emotion2vecClassifier",
    "EmotionClassifier",
    "EmotionResult",
    "FakeEmotionClassifier",
    "FakeSTTClient",
    "SpeachesClient",
    "STTClient",
    "TranscriptionResult",
]
