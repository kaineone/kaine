# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Executive action selection ("Volition").

KAINE's global workspace (Syneidesis) decides *what is conscious* and flags
executive inhibition (`WorkspaceSnapshot.inhibited`) when the winning coalition
fails to clear the publication threshold. Per the paper (§37, §147) a winning
coalition must clear that threshold *before reaching the action layer* — "the
system can consider speaking and decide that silence is the better choice."

This module is that action layer. Each experiential tick the cognitive cycle
hands ``Volition.select`` the broadcast ``WorkspaceSnapshot`` and Volition
returns zero or more :class:`Intent` objects describing what the entity has
decided to DO. The cycle publishes those intents to the ``volition.out`` stream;
effectors (Lingua, Praxis) realize them. Effectors never self-trigger off the
raw broadcast — the only path to action is an intent, and intents only exist
when the snapshot is *not* inhibited.

The core safeguard lives here and is checked first: when ``snapshot.inhibited``
is true, ``select`` returns ``[]`` — no intent, so no effector acts, for every
effector at once.

The decision policy is injectable (:class:`ActionSelectionPolicy`) so later
changes (`drives-to-behavior`, `spontaneous-recall`) can supply a richer policy
that biases the decision with motivational state / recalled context without
touching the cycle wiring or the intent transport.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Any, Optional, Protocol, runtime_checkable

from kaine.cycle.types import WorkspaceSnapshot
from kaine.security.intent_signing import IntentSigner

log = logging.getLogger(__name__)

# Intent kinds.
SPEAK = "speak"
THINK = "think"
ACT = "act"

# Bus transport for intents.
VOLITION_SOURCE = "volition"
VOLITION_STREAM = "volition.out"

# Event types used when an intent is published to the bus.
INTENT_TYPES: dict[str, str] = {
    SPEAK: "intent.speak",
    THINK: "intent.think",
    ACT: "intent.act",
}

# The source/type of a user-communication event the default policy is disposed
# to answer (a transcribed utterance heard by the ears).
USER_COMMUNICATION_SOURCE = "audition"
USER_COMMUNICATION_TYPE = "audition.transcription"

# The entity's own speech — never something to "respond" to. Both external
# (TTS-bound) and internal (private monologue) speech carry source "lingua";
# the event type distinguishes the channel a given output was realized on.
OWN_EXTERNAL_SPEECH_SOURCE = "lingua"
OWN_EXTERNAL_SPEECH_TYPE = "external_speech"
OWN_INTERNAL_SPEECH_TYPE = "internal_speech"


@dataclass(frozen=True)
class Intent:
    """An explicit decision to act, produced by action selection.

    ``kind`` is one of ``speak`` / ``think`` / ``act``. ``about`` references the
    conscious content the intent concerns: a short textual summary the realizing
    effector can use as a prompt. ``entry_id`` carries the broadcast entry id of
    the referenced coalition member when there is one (for audit/traceability).
    For ``act`` intents, ``effector`` names the Praxis effector and ``params``
    carries its request fields.

    ``run_id`` / ``seq`` / ``sig`` are the provenance envelope attached to
    ``act`` intents by :meth:`Volition.select` when a signer is wired (see
    ``kaine.security.intent_signing``). They are absent (``None``) for unsigned
    intents and for non-``act`` kinds. ``sig`` is an HMAC over
    ``canonical(kind, effector, params, run_id, seq)`` that Praxis verifies
    before running any effector; ``(run_id, seq)`` is the replay guard.

    ``interrupt`` marks a ``speak`` intent as *urgent redirect*: a sufficiently
    surprising new coalition that should preempt an in-flight utterance rather
    than wait behind it (see ``interruptible-utterance``). Only ``speak`` intents
    carry it; Lingua honors it by cancelling the in-flight generation and
    starting this one. Default ``False`` — the flag is emitted on the wire only
    when set, so non-Lingua consumers (Praxis) simply never see an unknown field.
    """

    kind: str
    about: str = ""
    entry_id: Optional[str] = None
    effector: Optional[str] = None
    params: dict[str, Any] = field(default_factory=dict)
    run_id: Optional[str] = None
    seq: Optional[int] = None
    sig: Optional[str] = None
    interrupt: bool = False

    def to_event_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"kind": self.kind, "about": self.about}
        if self.entry_id is not None:
            payload["entry_id"] = self.entry_id
        # Emitted only when set so the wire payload stays minimal and non-Lingua
        # consumers never encounter the field on ordinary intents.
        if self.interrupt:
            payload["interrupt"] = True
        if self.effector is not None:
            payload["effector"] = self.effector
        if self.params:
            payload["params"] = dict(self.params)
        # Provenance envelope — emitted only when the intent was signed. seq may
        # legitimately be 0 (the first intent of a run), so guard on `is not
        # None`, never on truthiness.
        if self.run_id is not None:
            payload["run_id"] = self.run_id
        if self.seq is not None:
            payload["seq"] = self.seq
        if self.sig is not None:
            payload["sig"] = self.sig
        return payload


@runtime_checkable
class ActionSelectionPolicy(Protocol):
    """Maps a *non-inhibited* snapshot to zero or more intents.

    Implementations MUST NOT be called when the snapshot is inhibited — Volition
    enforces the inhibition gate before delegating. A policy may be stateful (the
    default one keeps a one-in-flight guard).
    """

    def __call__(self, snapshot: WorkspaceSnapshot) -> list[Intent]:
        ...


class DefaultActionSelectionPolicy:
    """Minimal but real v1 policy.

    Given a non-inhibited coalition, emit a single ``speak`` intent when the
    coalition contains a user-communication event (a non-empty transcribed
    utterance) the entity is communicatively disposed to answer.

    Safeguards (per the action-selection spec):
    - Never forms a ``speak`` intent about the entity's OWN prior external
      speech (no self-response feedback loop).
    - One-in-flight guard: does not emit a new ``speak`` intent while a prior one
      is still being realized. The guard is armed when a ``speak`` intent is
      emitted and persists across subsequent decision ticks; it is cleared by
      :meth:`mark_realized` once the prior utterance's realization is observed
      (the entity's own ``lingua.external`` output appears in a later coalition).

    Injectable so `drives-to-behavior` can supply a drive-biased policy without
    touching Volition's plumbing.
    """

    def __init__(self) -> None:
        self._speak_in_flight = False

    @property
    def speak_in_flight(self) -> bool:
        return self._speak_in_flight

    def mark_realized(self) -> None:
        """Clear the one-in-flight guard (a prior speak intent has completed)."""
        self._speak_in_flight = False

    @staticmethod
    def _is_own_speech(event: Any) -> bool:
        """True for the entity's own (external or internal) speech output."""
        return event.source == OWN_EXTERNAL_SPEECH_SOURCE

    @staticmethod
    def _user_utterance(event: Any) -> Optional[str]:
        """Return the non-empty user-utterance text on this event, else None.

        Recognizes a transcribed utterance heard by the ears (source
        ``audition``, type ``audition.transcription``) with non-empty text.
        Shared with :class:`DriveBiasedActionSelectionPolicy`.
        """
        if (
            event.source == USER_COMMUNICATION_SOURCE
            and event.type == USER_COMMUNICATION_TYPE
        ):
            text = str(event.payload.get("text") or "").strip()
            if text:
                return text
        return None

    def _user_response_intent(self, snapshot: WorkspaceSnapshot) -> Optional[Intent]:
        """The single ``speak`` intent answering a present user utterance, if any.

        Skips the entity's own speech (no self-response loop). Does NOT touch
        the in-flight guard — callers decide whether to arm it.
        """
        for entry_id, event in snapshot.selected_events:
            if self._is_own_speech(event):
                continue
            text = self._user_utterance(event)
            if text is not None:
                return Intent(kind=SPEAK, about=text, entry_id=entry_id or None)
        return None

    def __call__(self, snapshot: WorkspaceSnapshot) -> list[Intent]:
        # If the entity's own external speech is now conscious, the prior
        # speak intent has been realized — clear the in-flight guard.
        if any(
            event.source == OWN_EXTERNAL_SPEECH_SOURCE
            for _, event in snapshot.selected_events
        ):
            self._speak_in_flight = False
        if self._speak_in_flight:
            # A prior speak intent is still being realized; do not stack.
            return []
        intent = self._user_response_intent(snapshot)
        if intent is not None:
            self._speak_in_flight = True
            return [intent]
        return []


class Volition:
    """The executive action-selection step.

    Pure transform: ``select(snapshot) -> list[Intent]``. The inhibition gate is
    the first thing checked — an inhibited snapshot yields no intents, so no
    effector ever acts while the entity is inhibited. A non-inhibited snapshot is
    delegated to the injected :class:`ActionSelectionPolicy`.

    Volition never re-decides salience or inhibition; it *consumes* Syneidesis's
    verdict. It does not touch the bus — the cycle publishes the returned intents.

    When an :class:`~kaine.security.intent_signing.IntentSigner` is injected (the
    composition root wires one holding the per-boot secret), every ``act`` intent
    Volition returns carries a provenance signature over its
    ``(kind, effector, params, run_id, seq)`` so Praxis can prove the intent came
    from this action-selection step and reject forged or replayed intents. Only
    ``act`` intents are signed — they are the only kind Praxis realizes into
    real-world effects; ``speak``/``think`` are unchanged.
    """

    def __init__(
        self,
        policy: Optional[ActionSelectionPolicy] = None,
        *,
        signer: Optional[IntentSigner] = None,
    ) -> None:
        self._policy: ActionSelectionPolicy = policy or DefaultActionSelectionPolicy()
        self._signer = signer

    @property
    def policy(self) -> ActionSelectionPolicy:
        return self._policy

    @property
    def signer(self) -> Optional[IntentSigner]:
        return self._signer

    def select(self, snapshot: WorkspaceSnapshot) -> list[Intent]:
        # Core safeguard (§37/§147): inhibited → silence, for every effector.
        if snapshot.inhibited:
            return []
        try:
            intents = list(self._policy(snapshot))
        except Exception:
            log.exception("action-selection policy raised; producing no intents")
            return []
        return [self._sign(intent) for intent in intents]

    def _sign(self, intent: Intent) -> Intent:
        """Attach the provenance envelope to an ``act`` intent when signing is
        wired. Non-``act`` intents and the unsigned (no-signer) path pass through
        unchanged."""
        if self._signer is None or intent.kind != ACT:
            return intent
        run_id, seq, sig = self._signer.sign(
            kind=intent.kind,
            effector=intent.effector or "",
            params=dict(intent.params or {}),
        )
        return replace(intent, run_id=run_id, seq=seq, sig=sig)
