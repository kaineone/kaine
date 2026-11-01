# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared definitions for external (other-initiated) input events.

External-input types are events whose entire text payload is heard input
produced by someone else, not by the entity.

The heard rule (``heard_texts`` and ``is_heard_event``) decides which events
are heard. The language module uses it to split heard events from the entity's
own notes, and the episodic memory module uses it to keep heard events out of
every stored trace. Three narrower checks deliberately use ``HEARD_TEXT_FIELDS``
without ``text`` on events other than the external-input types: the renderers'
redaction (``redact_heard_speech``), the language module's guard check
(``_holds_outside_material``) and its log-residual and publish-time redaction.

``INTERNAL_EVENT_TYPES`` declares the event types whose payloads hold only the
entity's own values and words. The language module brings its heard-speech
guard for any other type, and the episodic memory module keeps the payload of
no other type in a trace.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from kaine.bus.schema import Event

# Other-initiated workspace coalition member types.
# These events carry heard input: every text value in their payload is speech
# said to or near the entity.
EXTERNAL_INPUT_TYPES = frozenset({"audition.transcription", "embodiment.chat"})

# Events whose payloads hold only the entity's own values and words; any other
# event, including one of an unknown type, counts as outside material: the
# language module brings its heard-speech guard, and the episodic memory module
# stores it without its payload. Adding a type here asserts that no producer of
# it ever carries another speaker's words, under any field name.
INTERNAL_EVENT_TYPES = frozenset(
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

HEARD_TEXT_FIELDS = frozenset({
    "text",
    "user_input",
    "user_text",
    "transcription",
    "heard_text",
    "faithful_rendering",
})
"""Field names that may contain heard speech.

``faithful_rendering`` is included because a rendering can embed earlier heard
lines. External-input event types (``audition.transcription`` and
``embodiment.chat``) are heard wholesale by type. On the language module's own
events no field is heard (it redacts heard words before it publishes). On every
other module's event, these fields are heard at any depth (``heard_texts``).
The renderers' redaction leaves ``text`` out of that set on non-external
events (``redact_heard_speech``).
"""


def iter_text_leaves(value: Any) -> Iterator[str]:
    """Yield every non-empty stripped `str` found recursively in dicts, lists
    and tuples.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            yield stripped
    elif isinstance(value, dict):
        for child in value.values():
            yield from iter_text_leaves(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from iter_text_leaves(child)


def heard_texts(event: "Event") -> list[str]:
    """Return the outside words an event carries.

    Every text leaf of an external-input event is heard. The language module's
    own events carry none. Any other module's event carries the text leaves
    found under a ``HEARD_TEXT_FIELDS`` key at any depth.
    """
    payload = event.payload
    if not isinstance(payload, dict):
        return []
    if event.type in EXTERNAL_INPUT_TYPES:
        return list(iter_text_leaves(payload))
    if event.source == "language":
        return []

    def _collect(obj: Any) -> list[str]:
        if isinstance(obj, dict):
            leaves: list[str] = []
            for key, value in obj.items():
                if key in HEARD_TEXT_FIELDS:
                    leaves.extend(iter_text_leaves(value))
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


def is_heard_event(event: "Event") -> bool:
    """True when the event is heard input or carries heard words.

    Decided per event, before any rendering or storage.
    """
    return event.type in EXTERNAL_INPUT_TYPES or bool(heard_texts(event))
