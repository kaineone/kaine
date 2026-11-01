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

The spoken-text rule (``split_spoken_text``) uses the same definitions to keep
words off the persisted bus: heard text and the entity's own utterance text
travel only on the never-persisted instance (``kaine.bus.companion``). Every
string leaf of an external-input event is spoken text, except under the
reviewed metadata keys ``SPOKEN_TEXT_METADATA_KEYS``; on every other event,
the language module's own included, every value under a ``HEARD_TEXT_FIELDS``
key at any depth is. A diverted top-level ``text`` leaves its length and word
count behind (``text_chars``, ``text_words``), which cannot be turned back
into words.
"""

from __future__ import annotations

from collections.abc import Mapping
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


#: The version of the spoken-text rule; a companion producer under it names it.
SPOKEN_TEXT_RULE_VERSION = 1

#: Reviewed keys of an external-input event whose strings are never words:
SPOKEN_TEXT_METADATA_KEYS = frozenset(
    {
        # the audio channel an utterance arrived on (live_mic, playlist, remote, ...)
        "source_label",
        # the speech-to-text model's identity string
        "model",
        # the speech-to-text backend's name
        "backend",
    }
)

#: The field set name of this rule on the companion mechanism.
SPOKEN_TEXT_FIELD_SET = "spoken_text"


def split_spoken_text(event: "Event") -> tuple[dict[str, Any], list[tuple[tuple[Any, ...], Any, Any]]]:
    """``(main_payload, diverted)`` for ``event`` under the spoken-text rule.

    ``diverted`` lists each diverted value with its path. With nothing to
    divert, the event's own payload object is returned and the list is empty.
    """
    return split_spoken_payload(event.type, event.payload)


def split_spoken_payload(
    event_type: str, payload: Mapping[str, Any], extra_fields: frozenset[str] = frozenset()
) -> tuple[dict[str, Any], list[tuple[tuple[Any, ...], Any, Any]]]:
    """The payload form of ``split_spoken_text`` (the bus applies it by type).

    ``extra_fields`` are field names a producer declared into this rule
    (``kaine.bus.companion.CompanionDeclaration.extra_fields``): on every event
    they are diverted at any depth, like ``HEARD_TEXT_FIELDS``.
    """
    diverted: list[tuple[tuple[Any, ...], Any, Any]] = []
    if not isinstance(payload, Mapping):
        return payload, diverted
    if event_type in EXTERNAL_INPUT_TYPES:
        main = _divert_strings(payload, (), diverted)
    else:
        main = _divert_heard_fields(payload, (), diverted, HEARD_TEXT_FIELDS | extra_fields)
    if not diverted:
        return payload, diverted
    main = dict(main)
    for path, value, _index in diverted:
        if path == ("text",) and isinstance(value, str):
            main["text_chars"] = len(value)
            main["text_words"] = len(value.split())
    return main, diverted


def _holds_string(value: Any) -> bool:
    if isinstance(value, str):
        return True
    if isinstance(value, Mapping):
        return any(_holds_string(v) for v in value.values())
    if isinstance(value, (list, tuple)):
        return any(_holds_string(v) for v in value)
    return False


def _divert_strings(node: Any, path: tuple[Any, ...], diverted: list) -> Any:
    """Divert every string leaf, except under the reviewed metadata keys."""
    if isinstance(node, Mapping):
        changed = False
        out: dict[Any, Any] = {}
        for index, (key, value) in enumerate(node.items()):
            if key in SPOKEN_TEXT_METADATA_KEYS:
                out[key] = value
                continue
            if isinstance(value, str) or (
                isinstance(value, (list, tuple))
                and any(isinstance(v, str) or (isinstance(v, (list, tuple)) and _holds_string(v)) for v in value)
            ):
                # A string, or a list holding strings directly: the whole value.
                diverted.append((path + (key,), value, index))
                changed = True
                continue
            new = _divert_strings(value, path + (key,), diverted)
            changed = changed or new is not value
            out[key] = new
        return out if changed else node
    if isinstance(node, (list, tuple)):
        items = [_divert_strings(v, path + (i,), diverted) for i, v in enumerate(node)]
        if all(a is b for a, b in zip(items, node)):
            return node
        return items if isinstance(node, list) else tuple(items)
    return node


def _divert_heard_fields(
    node: Any, path: tuple[Any, ...], diverted: list, keys: frozenset[str] = HEARD_TEXT_FIELDS
) -> Any:
    """Divert every value under a key in ``keys`` at any depth."""
    if isinstance(node, Mapping):
        changed = False
        out: dict[Any, Any] = {}
        for index, (key, value) in enumerate(node.items()):
            if key in keys:
                diverted.append((path + (key,), value, index))
                changed = True
                continue
            new = _divert_heard_fields(value, path + (key,), diverted, keys)
            changed = changed or new is not value
            out[key] = new
        return out if changed else node
    if isinstance(node, (list, tuple)):
        items = [_divert_heard_fields(v, path + (i,), diverted, keys) for i, v in enumerate(node)]
        if all(a is b for a, b in zip(items, node)):
            return node
        return items if isinstance(node, list) else tuple(items)
    return node


def drop_spoken_counts(payload: dict[str, Any], diverted: list) -> dict[str, Any]:
    """Undo the counts the split added once the top-level ``text`` is back."""
    if any(tuple(item[0]) == ("text",) for item in diverted) and "text" in payload:
        payload = dict(payload)
        payload.pop("text_chars", None)
        payload.pop("text_words", None)
    return payload


def spoken_counts(payload: Mapping[str, Any]) -> tuple[int, int]:
    """``(characters, words)`` of an event's top-level ``text``: from the text
    when it is present (a joined or an in-process event), else from the counts
    the main-bus copy keeps."""
    text = payload.get("text") if isinstance(payload, Mapping) else None
    if isinstance(text, str):
        return len(text), len(text.split())
    chars = payload.get("text_chars") if isinstance(payload, Mapping) else None
    words = payload.get("text_words") if isinstance(payload, Mapping) else None
    ok = lambda v: isinstance(v, int) and not isinstance(v, bool) and v >= 0  # noqa: E731
    return (chars if ok(chars) else 0), (words if ok(words) else 0)


def words_unavailable(payload: Mapping[str, Any]) -> bool:
    """True when an event's words were diverted and are not here: the main-bus
    copy counts a non-empty ``text`` but holds none (its companion entry is
    gone or was never joined)."""
    if not isinstance(payload, Mapping) or "text" in payload:
        return False
    chars = payload.get("text_chars")
    return isinstance(chars, int) and not isinstance(chars, bool) and chars > 0
