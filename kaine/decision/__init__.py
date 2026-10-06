# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Typed decision questions about external speech, for the K1-Jev decision model. Never part of cognition."""

from kaine.decision.render import answer_letter, render_prompt, training_example
from kaine.decision.schema import (
    QUESTIONS,
    SCHEMA_VERSION,
    TRAITS,
    get_question,
    state_text,
    systemone_questions,
)

__all__ = [
    "SCHEMA_VERSION",
    "QUESTIONS",
    "TRAITS",
    "get_question",
    "state_text",
    "systemone_questions",
    "render_prompt",
    "answer_letter",
    "training_example",
]
