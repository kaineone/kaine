# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The one heard rule lives in kaine.faithful.external_input.

The language module and the episodic memory module both classify heard words
with it, and the language module's results are the same as before the rule
moved: ``_reference_heard_texts`` below is the language module's own function
as it stood in ``kaine/modules/language/context.py`` before the move, kept here
verbatim as the oracle.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

import kaine.faithful.templates as templates
import kaine.modules.episodic_memory.module as episodic_module
import kaine.modules.language.context as language_context
from kaine.bus import Event
from kaine.faithful import external_input
from kaine.faithful.external_input import (
    EXTERNAL_INPUT_TYPES,
    HEARD_TEXT_FIELDS,
    heard_texts,
    is_heard_event,
)

# --- the pre-move language-module rule, verbatim (oracle) -------------------


def _reference_string_leaves(value: Any) -> list[str]:
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, dict):
        leaves: list[str] = []
        for item in value.values():
            leaves.extend(_reference_string_leaves(item))
        return leaves
    if isinstance(value, (list, tuple)):
        leaves: list[str] = []
        for item in value:
            leaves.extend(_reference_string_leaves(item))
        return leaves
    return []


def _reference_heard_texts(event: Event) -> list[str]:
    payload = event.payload
    if not isinstance(payload, dict):
        return []
    if event.type in EXTERNAL_INPUT_TYPES:
        return _reference_string_leaves(payload)
    if event.source == "language":
        return []

    def _collect(obj: Any) -> list[str]:
        if isinstance(obj, dict):
            leaves: list[str] = []
            for key, value in obj.items():
                if key in HEARD_TEXT_FIELDS:
                    leaves.extend(_reference_string_leaves(value))
                else:
                    leaves.extend(_collect(value))
            return leaves
        if isinstance(obj, (list, tuple)):
            leaves: list[str] = []
            for value in obj:
                leaves.extend(_collect(value))
            return leaves
        return []

    return _collect(payload)


def _reference_is_heard_event(event: Event) -> bool:
    return event.type in EXTERNAL_INPUT_TYPES or bool(_reference_heard_texts(event))


# --- cases -------------------------------------------------------------------

S = "PURPLE-HERON-4471"


def _ev(source: str, type_: str, payload: dict[str, Any]) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


def _cases() -> list[Event]:
    cases = [
        _ev("audition", "audition.transcription", {"text": S}),
        _ev("audition", "audition.transcription", {"text": ""}),
        _ev("audition", "audition.transcription", {}),
        _ev("audition", "audition.transcription", {"text": "  ", "segments": [{"t": S}, (S, 3)]}),
        _ev("embodiment", "embodiment.chat", {"message": S, "sender": "Avatar Two"}),
        _ev("embodiment", "embodiment.chat", {"message": {"body": [S, " ", 4]}}),
        _ev("embodiment", "embodiment.chat", {"n": 3}),
        _ev("language", "external_speech", {"text": S, "user_input": S}),
        _ev("language", "internal_speech", {"text": "my own words"}),
        _ev("vision", "vision.report", {"change_score": 0.4, "habituation_score": 0.2}),
        _ev("social_cognition", "social_cognition.update", {"partner": {"heard_text": S}}),
        _ev("dashboard", "dashboard.note", {"x": {"user_input": S}, "items": [{"heard_text": S}]}),
        _ev("mystery", "mystery.thing", {f: S for f in HEARD_TEXT_FIELDS}),
        _ev("mystery", "mystery.thing", {"deep": [{"a": ({"transcription": [S, {"x": S}]},)}]}),
        _ev("mystery", "mystery.thing", {"text": S}),
        _ev("mystery", "mystery.thing", {"text": "   "}),
        _ev("mystery", "mystery.thing", {"faithful_rendering": ""}),
        _ev("mystery", "mystery.thing", {"user_text": 7, "heard_text": None}),
        _ev("episodic_memory", "episodic_memory.recall", {"count": 2, "collection": "short_term"}),
        _ev("episodic_memory", "episodic_memory.replay", {"memory_id": "abc", "text": S}),
        _ev("planning", "planning.belief", {"belief": {"text": S}}),
    ]
    for field in sorted(HEARD_TEXT_FIELDS):
        cases.append(_ev("somewhere", "something.happened", {field: S}))
        cases.append(_ev("somewhere", "something.happened", {"outer": {field: S}}))
        cases.append(_ev("somewhere", "something.happened", {"outer": [{"inner": {field: [S]}}]}))
        cases.append(_ev("language", "external_speech", {"outer": {field: S}}))
    return cases


@pytest.mark.parametrize("event", _cases(), ids=lambda e: f"{e.source}:{e.type}:{sorted(e.payload)}")
def test_shared_rule_matches_the_language_modules_former_rule(event: Event):
    assert heard_texts(event) == _reference_heard_texts(event)
    assert is_heard_event(event) == _reference_is_heard_event(event)


def test_language_and_episodic_memory_use_the_one_rule():
    assert language_context.heard_texts is external_input.heard_texts
    assert language_context.is_heard_event is external_input.is_heard_event
    assert episodic_module.is_heard_event is external_input.is_heard_event
    assert not hasattr(language_context, "_heard_texts")
    assert not hasattr(language_context, "_is_heard_event")


def test_internal_event_types_have_one_home():
    assert language_context.INTERNAL_EVENT_TYPES is external_input.INTERNAL_EVENT_TYPES
    assert episodic_module.INTERNAL_EVENT_TYPES is external_input.INTERNAL_EVENT_TYPES
    # The language module's list, unchanged by the move (its layout digest hashes it).
    assert external_input.INTERNAL_EVENT_TYPES == frozenset(
        {
            ("vision", "vision.report"),
            ("audition", "audition.perception"),
            ("audition", "audition.emotion"),
            ("audition", "audition.prosody"),
            ("interoception", "interoception.report"),
            ("interoception", "interoception.fatigue"),
            ("interoception", "interoception.regulation"),
            ("sequence", "sequence.report"),
            ("affect", "affect.state"),
            ("affect", "affect.drive"),
            ("affect", "affect.emotion"),
            ("affect", "affect.goal"),
            ("sleep", "sleep.sleep.started"),
            ("sleep", "sleep.sleep.completed"),
            ("sleep", "sleep.rest_request"),
            ("cycle", "cycle.tick"),
            ("language", "internal_speech"),
            ("language", "external_speech"),
        }
    )


def test_heard_text_fields_have_one_home():
    assert templates.HEARD_TEXT_FIELDS is external_input.HEARD_TEXT_FIELDS
    assert HEARD_TEXT_FIELDS == frozenset(
        {"text", "user_input", "user_text", "transcription", "heard_text", "faithful_rendering"}
    )


def test_external_input_types_are_heard_even_without_words():
    for type_ in sorted(EXTERNAL_INPUT_TYPES):
        assert is_heard_event(_ev("x", type_, {}))
