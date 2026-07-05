# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for the drive-biased action-selection policy.

Validates the `drives-to-behavior` change with fakes only (no live boot):
WorkspaceSnapshot objects are built directly, mirroring tests/test_volition.py.
Covers: social_drive → speak; curiosity/boredom/restlessness → think;
inhibited → none (via Volition.select, proving the gate still holds);
user utterance outranks social-drive speak; in-flight guards prevent stacking
and clear on the entity's own output; drive_initiative-off parity with the
default policy.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.drive_policy import DriveBiasedActionSelectionPolicy
from kaine.workspace.volition import (
    SPEAK,
    THINK,
    DefaultActionSelectionPolicy,
    Volition,
)


def _event(source: str, type_: str, payload=None, salience: float = 0.5) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload or {},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _transcription(text: str) -> tuple[str, Event]:
    return ("u1", _event("audition", "audition.transcription", {"text": text}))


def _drive(name: str, value: float = 0.9) -> tuple[str, Event]:
    return (f"d-{name}", _event("thymos", "thymos.drive", {"drive": name, "value": value}))


def _own_external() -> tuple[str, Event]:
    return ("x1", _event("lingua", "external_speech", {"text": "I said this"}))


def _own_internal() -> tuple[str, Event]:
    return ("i1", _event("lingua", "internal_speech", {"text": "I thought this"}))


def _snapshot(events, *, inhibited: bool = False) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=list(events),
        inhibited=inhibited,
        is_experiential=True,
    )


# --- 3.1 social_drive crossing → one speak intent --------------------------


def test_social_drive_crossing_initiates_speak():
    policy = DriveBiasedActionSelectionPolicy()
    intents = policy(_snapshot([_drive("social_drive")]))
    assert len(intents) == 1
    assert intents[0].kind == SPEAK
    assert intents[0].entry_id == "d-social_drive"


# --- 3.2 curiosity/boredom/restlessness crossing → one think intent --------


@pytest.mark.parametrize("name", ["curiosity", "boredom", "restlessness"])
def test_deliberative_drive_crossing_initiates_think(name):
    policy = DriveBiasedActionSelectionPolicy()
    intents = policy(_snapshot([_drive(name)]))
    assert len(intents) == 1
    assert intents[0].kind == THINK
    assert intents[0].entry_id == f"d-{name}"


def test_think_intent_is_internal_not_external():
    # A think intent is the only intent produced for a deliberative drive — it
    # never becomes a speak (external) intent.
    policy = DriveBiasedActionSelectionPolicy()
    intents = policy(_snapshot([_drive("curiosity")]))
    assert [i.kind for i in intents] == [THINK]


# --- 3.3 inhibited snapshot → no intent (via Volition gate) ----------------


def test_inhibited_snapshot_produces_no_intent_via_volition():
    v = Volition(policy=DriveBiasedActionSelectionPolicy())
    snap = _snapshot(
        [_drive("social_drive"), _drive("curiosity"), _transcription("hi")],
        inhibited=True,
    )
    assert v.select(snap) == []


def test_inhibited_gate_does_not_arm_guards():
    # Proving the gate holds: an inhibited snapshot must not even reach the
    # policy, so the in-flight guards stay clear and a later non-inhibited
    # snapshot still acts.
    policy = DriveBiasedActionSelectionPolicy()
    v = Volition(policy=policy)
    assert v.select(_snapshot([_drive("social_drive")], inhibited=True)) == []
    assert policy.speak_in_flight is False
    assert policy.think_in_flight is False
    # Now non-inhibited: it acts.
    intents = v.select(_snapshot([_drive("social_drive")]))
    assert len(intents) == 1 and intents[0].kind == SPEAK


# --- 3.4 user utterance outranks social-drive speak ------------------------


def test_user_utterance_outranks_social_drive_speak():
    policy = DriveBiasedActionSelectionPolicy()
    intents = policy(_snapshot([_drive("social_drive"), _transcription("hello kaine")]))
    speaks = [i for i in intents if i.kind == SPEAK]
    assert len(speaks) == 1
    # The single speak answers the user, not the social drive.
    assert speaks[0].about == "hello kaine"
    assert speaks[0].entry_id == "u1"


def test_user_and_think_drive_coexist_one_speak():
    # User utterance (speak) + curiosity (think) → one speak (user) + one think.
    policy = DriveBiasedActionSelectionPolicy()
    intents = policy(_snapshot([_transcription("hi"), _drive("curiosity")]))
    kinds = sorted(i.kind for i in intents)
    assert kinds == [SPEAK, THINK]
    speak = next(i for i in intents if i.kind == SPEAK)
    assert speak.about == "hi"


def test_only_one_speak_when_user_and_social_drive_present():
    policy = DriveBiasedActionSelectionPolicy()
    intents = policy(_snapshot([_drive("social_drive"), _transcription("hey")]))
    assert sum(1 for i in intents if i.kind == SPEAK) == 1


# --- 3.5 in-flight guards: prevent stacking; clear on own output -----------


def test_speak_in_flight_suppresses_second_social_drive():
    policy = DriveBiasedActionSelectionPolicy()
    assert len(policy(_snapshot([_drive("social_drive")]))) == 1
    # Second crossing while the first speak is still in flight: suppressed.
    assert policy(_snapshot([_drive("social_drive")])) == []


def test_think_in_flight_suppresses_second_curiosity():
    policy = DriveBiasedActionSelectionPolicy()
    assert len(policy(_snapshot([_drive("curiosity")]))) == 1
    assert policy(_snapshot([_drive("curiosity")])) == []


def test_speak_guard_clears_on_own_external_speech():
    policy = DriveBiasedActionSelectionPolicy()
    assert len(policy(_snapshot([_drive("social_drive")]))) == 1
    assert policy.speak_in_flight is True
    # Own external speech becomes conscious → speak guard clears.
    assert policy(_snapshot([_own_external()])) == []
    assert policy.speak_in_flight is False
    # A fresh social-drive crossing can act again.
    assert len(policy(_snapshot([_drive("social_drive")]))) == 1


def test_think_guard_clears_on_own_internal_speech():
    policy = DriveBiasedActionSelectionPolicy()
    assert len(policy(_snapshot([_drive("boredom")]))) == 1
    assert policy.think_in_flight is True
    # Own internal speech becomes conscious → think guard clears.
    assert policy(_snapshot([_own_internal()])) == []
    assert policy.think_in_flight is False
    assert len(policy(_snapshot([_drive("restlessness")]))) == 1


def test_internal_speech_does_not_clear_speak_guard():
    # The two guards are independent: a private monologue surfacing must not
    # clear the external-speech guard.
    policy = DriveBiasedActionSelectionPolicy()
    policy(_snapshot([_drive("social_drive")]))  # arm speak guard
    policy(_snapshot([_drive("curiosity")]))  # arm think guard
    assert policy.speak_in_flight is True
    assert policy.think_in_flight is True
    # Only internal speech surfaces.
    policy(_snapshot([_own_internal()]))
    assert policy.think_in_flight is False
    assert policy.speak_in_flight is True  # still armed


def test_external_speech_does_not_clear_think_guard():
    policy = DriveBiasedActionSelectionPolicy()
    policy(_snapshot([_drive("social_drive")]))
    policy(_snapshot([_drive("curiosity")]))
    policy(_snapshot([_own_external()]))
    assert policy.speak_in_flight is False
    assert policy.think_in_flight is True  # still armed


def test_speak_and_think_in_same_call_when_both_drives_present():
    policy = DriveBiasedActionSelectionPolicy()
    intents = policy(_snapshot([_drive("social_drive"), _drive("curiosity")]))
    assert sorted(i.kind for i in intents) == [SPEAK, THINK]


# --- no-self-response -------------------------------------------------------


def test_own_external_speech_alone_produces_no_intent():
    policy = DriveBiasedActionSelectionPolicy()
    assert policy(_snapshot([_own_external()])) == []


def test_own_internal_speech_alone_produces_no_intent():
    policy = DriveBiasedActionSelectionPolicy()
    assert policy(_snapshot([_own_internal()])) == []


# --- non-drive / unknown drive ---------------------------------------------


def test_unknown_drive_name_ignored():
    policy = DriveBiasedActionSelectionPolicy()
    bad = ("d-x", _event("thymos", "thymos.drive", {"drive": "unknown"}))
    assert policy(_snapshot([bad])) == []


def test_non_drive_thymos_event_ignored():
    policy = DriveBiasedActionSelectionPolicy()
    other = ("t1", _event("thymos", "thymos.emotion", {"valence": 0.1}))
    assert policy(_snapshot([other])) == []


# --- 3.6 drive_initiative disabled → identical to default policy -----------


def test_disabled_drive_initiative_matches_default_on_drives():
    # When the operator disables drive initiative, the plain default policy is
    # used; drive crossings produce nothing (no user utterance present).
    default = DefaultActionSelectionPolicy()
    assert default(_snapshot([_drive("social_drive"), _drive("curiosity")])) == []


def test_disabled_drive_initiative_matches_default_on_user_utterance():
    # Both policies answer a user utterance identically.
    default = DefaultActionSelectionPolicy()
    biased = DriveBiasedActionSelectionPolicy()
    snap = _snapshot([_transcription("how are you?")])
    d_intents = default(snap)
    b_intents = biased(_snapshot([_transcription("how are you?")]))
    assert len(d_intents) == 1 and len(b_intents) == 1
    assert d_intents[0].kind == b_intents[0].kind == SPEAK
    assert d_intents[0].about == b_intents[0].about == "how are you?"
