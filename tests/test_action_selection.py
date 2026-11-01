# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for the executive action-selection step (the action selection module)."""
from __future__ import annotations

from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.action_selection import (
    ACT,
    SPEAK,
    ActionSelection,
    DefaultActionSelectionPolicy,
    Intent,
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
    return ("e2", _event("language", "external_speech", {"text": "I said this"}))


def _snapshot(events, *, inhibited: bool = False) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=list(events),
        inhibited=inhibited,
        is_experiential=True,
    )


def test_inhibited_snapshot_produces_no_intents():
    v = ActionSelection()
    snap = _snapshot([_transcription("hello there")], inhibited=True)
    assert v.select(snap) == []


def test_default_policy_never_answers_heard_speech():
    # operator-speech-as-perception: heard speech is perception. The default
    # policy is the inert library default: an accessed operator utterance with
    # words, from any channel or none, forms no intent.
    v = ActionSelection()
    for payload in (
        {"text": "how are you?"},
        {"text": "how are you?", "source_label": "live_mic"},
        {"text": "how are you?", "source_label": "remote"},
        {"text_chars": 12, "text_words": 3, "source_label": "microphone"},
    ):
        snap = _snapshot([("e1", _event("audition", "audition.transcription", payload, salience=1.0))])
        assert v.select(snap) == []
        assert v.policy.speak_in_flight is False


def test_no_disposed_content_produces_no_intent():
    # Experiential broadcast with only a non-communication event.
    v = ActionSelection()
    snap = _snapshot([("e3", _event("interoception", "interoception.report", {"wellness": 0.5}))])
    assert v.select(snap) == []


def test_own_external_speech_does_not_trigger_response():
    v = ActionSelection()
    snap = _snapshot([_own_speech()])
    assert v.select(snap) == []


def test_default_policy_guard_armed_externally_clears_on_own_speech():
    # The default policy keeps its guard for a wrapper that arms it (a
    # realized planning proposal) and clears it when the own speech is accessed.
    policy = DefaultActionSelectionPolicy()
    policy.note_external_intent(SPEAK)
    assert policy.speak_in_flight is True
    assert policy(_snapshot([_transcription("a question")])) == []
    assert policy.speak_in_flight is True
    assert policy(_snapshot([_own_speech()])) == []
    assert policy.speak_in_flight is False


def test_injectable_policy_used():
    calls: list[WorkspaceSnapshot] = []

    def policy(snapshot: WorkspaceSnapshot) -> list[Intent]:
        calls.append(snapshot)
        return [Intent(kind=ACT, about="x", effector="notify", params={"a": 1})]

    v = ActionSelection(policy=policy)
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

    v = ActionSelection(policy=policy)
    snap = _snapshot([_transcription("hi")], inhibited=True)
    assert v.select(snap) == []
    assert called is False


def test_policy_exception_yields_no_intents():
    def policy(snapshot: WorkspaceSnapshot) -> list[Intent]:
        raise RuntimeError("boom")

    v = ActionSelection(policy=policy)
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
    assert policy(_snapshot([_transcription("hi")])) == []
    assert policy.speak_in_flight is False
    policy.note_external_intent(SPEAK)
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
    v = ActionSelection(policy=_act_policy(effector="shell", params={"command": "echo"}), signer=signer)
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
    v = ActionSelection(policy=_act_policy(), signer=signer)
    first = v.select(_snapshot([_transcription("a")]))[0]
    second = v.select(_snapshot([_transcription("b")]))[0]
    assert (first.seq, second.seq) == (0, 1)


def test_non_act_intent_is_not_signed():
    from kaine.security.intent_signing import IntentSigner

    signer = IntentSigner(b"2" * 32, "run-2")

    def speak_policy(snapshot: WorkspaceSnapshot) -> list[Intent]:
        return [Intent(kind=SPEAK, about="vision (surprise=0.700)", about_kind="event")]

    v = ActionSelection(policy=speak_policy, signer=signer)
    intents = v.select(_snapshot([_transcription("hello there")]))
    assert intents and intents[0].kind == SPEAK
    assert intents[0].sig is None
    assert "sig" not in intents[0].to_event_payload()


def test_unsigned_when_no_signer():
    v = ActionSelection(policy=_act_policy())
    intent = v.select(_snapshot([_transcription("x")]))[0]
    assert intent.sig is None and intent.run_id is None and intent.seq is None
