# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for the executive action-selection step (Volition)."""
from __future__ import annotations

from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.volition import (
    ACT,
    SPEAK,
    DefaultActionSelectionPolicy,
    Intent,
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
    return ("e1", _event("audition", "audition.transcription", {"text": text}))


def _own_speech() -> tuple[str, Event]:
    return ("e2", _event("lingua", "external_speech", {"text": "I said this"}))


def _snapshot(events, *, inhibited: bool = False) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=list(events),
        inhibited=inhibited,
        is_experiential=True,
    )


def test_inhibited_snapshot_produces_no_intents():
    v = Volition()
    snap = _snapshot([_transcription("hello there")], inhibited=True)
    assert v.select(snap) == []


def test_non_inhibited_disposed_content_produces_one_speak_intent():
    v = Volition()
    snap = _snapshot([_transcription("how are you?")])
    intents = v.select(snap)
    assert len(intents) == 1
    intent = intents[0]
    assert intent.kind == SPEAK
    assert intent.about == "how are you?"
    assert intent.entry_id == "e1"


def test_speak_intent_carries_referent_text():
    v = Volition()
    snap = _snapshot([_transcription("  spaced out  ")])
    intents = v.select(snap)
    assert intents[0].about == "spaced out"


def test_no_disposed_content_produces_no_intent():
    # Experiential broadcast with only a non-communication event.
    v = Volition()
    snap = _snapshot([("e3", _event("soma", "soma.report", {"wellness": 0.5}))])
    assert v.select(snap) == []


def test_empty_transcription_produces_no_intent():
    v = Volition()
    snap = _snapshot([_transcription("   ")])
    assert v.select(snap) == []


def test_own_external_speech_does_not_trigger_response():
    v = Volition()
    snap = _snapshot([_own_speech()])
    assert v.select(snap) == []


def test_one_speak_intent_in_flight_suppresses_second():
    v = Volition()
    snap1 = _snapshot([_transcription("first utterance")])
    assert len(v.select(snap1)) == 1
    # A new user utterance arrives while the first intent is still in flight.
    snap2 = _snapshot([_transcription("second utterance")])
    assert v.select(snap2) == []


def test_in_flight_guard_clears_when_own_speech_becomes_conscious():
    v = Volition()
    snap1 = _snapshot([_transcription("first utterance")])
    assert len(v.select(snap1)) == 1
    # The realization (own external speech) becomes conscious — guard clears.
    snap2 = _snapshot([_own_speech()])
    assert v.select(snap2) == []  # own speech alone: no new intent, guard cleared
    # Now a fresh user utterance can produce a new intent again.
    snap3 = _snapshot([_transcription("a later question")])
    assert len(v.select(snap3)) == 1


def test_injectable_policy_used():
    calls: list[WorkspaceSnapshot] = []

    def policy(snapshot: WorkspaceSnapshot) -> list[Intent]:
        calls.append(snapshot)
        return [Intent(kind=ACT, about="x", effector="notify", params={"a": 1})]

    v = Volition(policy=policy)
    snap = _snapshot([_transcription("ignored by custom policy")])
    intents = v.select(snap)
    assert len(calls) == 1
    assert intents[0].kind == ACT
    assert intents[0].effector == "notify"


def test_injectable_policy_not_called_when_inhibited():
    called = False

    def policy(snapshot: WorkspaceSnapshot) -> list[Intent]:
        nonlocal called
        called = True
        return []

    v = Volition(policy=policy)
    snap = _snapshot([_transcription("hi")], inhibited=True)
    assert v.select(snap) == []
    assert called is False


def test_policy_exception_yields_no_intents():
    def policy(snapshot: WorkspaceSnapshot) -> list[Intent]:
        raise RuntimeError("boom")

    v = Volition(policy=policy)
    snap = _snapshot([_transcription("hi")])
    assert v.select(snap) == []


def test_intent_event_payload_shape():
    intent = Intent(kind=ACT, about="do it", entry_id="e9", effector="shell", params={"command": "echo"})
    payload = intent.to_event_payload()
    assert payload["kind"] == ACT
    assert payload["about"] == "do it"
    assert payload["entry_id"] == "e9"
    assert payload["effector"] == "shell"
    assert payload["params"] == {"command": "echo"}


def test_default_policy_speak_in_flight_property():
    policy = DefaultActionSelectionPolicy()
    assert policy.speak_in_flight is False
    policy(_snapshot([_transcription("hi")]))
    assert policy.speak_in_flight is True
    policy.mark_realized()
    assert policy.speak_in_flight is False


# ---------------------------------------------------------------------------
# Act-intent provenance signing (authenticate-intent-provenance, Mechanism B).
# ---------------------------------------------------------------------------
def _act_policy(effector="notify", params=None):
    params = params if params is not None else {"a": 1}

    def policy(snapshot: WorkspaceSnapshot) -> list[Intent]:
        return [Intent(kind=ACT, about="x", effector=effector, params=params)]

    return policy


def test_act_intent_is_signed_when_signer_wired():
    from kaine.security.intent_signing import IntentSigner, verify_intent_signature

    signer = IntentSigner(b"0" * 32, "run-xyz")
    v = Volition(policy=_act_policy(effector="shell", params={"command": "echo"}), signer=signer)
    intents = v.select(_snapshot([_transcription("go")]))
    assert len(intents) == 1
    intent = intents[0]
    # The provenance envelope is attached...
    assert intent.run_id == "run-xyz"
    assert intent.seq == 0
    assert isinstance(intent.sig, str) and intent.sig
    # ...and it verifies against the same secret over the canonical fields.
    assert verify_intent_signature(
        b"0" * 32,
        kind=ACT,
        effector="shell",
        params={"command": "echo"},
        run_id="run-xyz",
        seq=0,
        signature=intent.sig,
    )
    # The signed envelope round-trips into the published payload.
    payload = intent.to_event_payload()
    assert payload["run_id"] == "run-xyz"
    assert payload["seq"] == 0
    assert payload["sig"] == intent.sig


def test_seq_is_monotonic_across_signed_intents():
    from kaine.security.intent_signing import IntentSigner

    signer = IntentSigner(b"1" * 32, "run-1")
    v = Volition(policy=_act_policy(), signer=signer)
    first = v.select(_snapshot([_transcription("a")]))[0]
    second = v.select(_snapshot([_transcription("b")]))[0]
    assert (first.seq, second.seq) == (0, 1)


def test_non_act_intent_is_not_signed():
    from kaine.security.intent_signing import IntentSigner

    signer = IntentSigner(b"2" * 32, "run-2")
    v = Volition(signer=signer)  # default policy → a speak intent
    intents = v.select(_snapshot([_transcription("hello there")]))
    assert intents and intents[0].kind == SPEAK
    assert intents[0].sig is None
    assert "sig" not in intents[0].to_event_payload()


def test_unsigned_when_no_signer():
    v = Volition(policy=_act_policy())
    intent = v.select(_snapshot([_transcription("x")]))[0]
    assert intent.sig is None and intent.run_id is None and intent.seq is None
