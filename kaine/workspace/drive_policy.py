# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Drive-biased executive action selection.

The keystone ``executive-action-intent`` change gave KAINE an inhibition-gated
action layer (:mod:`kaine.workspace.volition`) whose default policy only
*responds* to a user utterance. Thymos already publishes ``thymos.drive``
threshold-crossing events for its four drives (curiosity, boredom,
social_drive, restlessness) — but until now nothing consumed them. The entity
had motivations that could not move it.

This module closes that loop. :class:`DriveBiasedActionSelectionPolicy`
subsumes the default user-communication handling and, additionally, turns a
drive crossing that reached the (non-inhibited) conscious coalition into an
intent — the paper's framing that executive inhibition is what "prevents the
system from acting on every impulse" (§37): a drive crossing is an impulse,
and only one that was *selected* into the coalition and *not inhibited* can
move the entity.

Mapping (conservative v1):
  - ``social_drive``   → ``speak``  (communicative initiative; external).
  - ``curiosity`` /
    ``boredom`` /
    ``restlessness``   → ``think``  (internal deliberation; never reaches TTS).

Guards (all inherited from the executive design, never bypassing it):
  - Volition checks inhibition first; this policy is only called when the
    snapshot is NOT inhibited.
  - At most ONE ``speak`` intent per call. A present user utterance OUTRANKS a
    social-drive initiative (the single speak answers the user).
  - Separate one-in-flight guards for ``speak`` and ``think`` prevent storms;
    each clears when the entity's corresponding own output
    (``lingua.external`` / ``lingua.internal``) next becomes conscious, reusing
    the keystone's realization-observed pattern.
  - The entity never responds to its own output (source ``lingua``).

Injectable like the default policy, so a future change can parameterize the
drive→kind mapping without touching Volition's plumbing.
"""
from __future__ import annotations

from typing import Optional

from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.volition import (
    OWN_EXTERNAL_SPEECH_SOURCE,
    OWN_EXTERNAL_SPEECH_TYPE,
    OWN_INTERNAL_SPEECH_TYPE,
    SPEAK,
    THINK,
    DefaultActionSelectionPolicy,
    Intent,
)

# The drive-crossing events Thymos publishes.
THYMOS_DRIVE_SOURCE = "thymos"
THYMOS_DRIVE_TYPE = "thymos.drive"

# Drive → intent-kind mapping (conservative v1; see module docstring).
DRIVE_INTENT_KINDS: dict[str, str] = {
    "social_drive": SPEAK,
    "curiosity": THINK,
    "boredom": THINK,
    "restlessness": THINK,
}


class DriveBiasedActionSelectionPolicy(DefaultActionSelectionPolicy):
    """Default user-response behavior PLUS drive-initiated intents.

    Subclasses :class:`DefaultActionSelectionPolicy` to reuse its
    user-communication detection and ``speak``-in-flight guard, and adds a
    parallel ``think``-in-flight guard for drive-initiated internal speech.
    """

    def __init__(self) -> None:
        super().__init__()
        self._think_in_flight = False

    @property
    def think_in_flight(self) -> bool:
        return self._think_in_flight

    def mark_think_realized(self) -> None:
        """Clear the think one-in-flight guard (a prior think has completed)."""
        self._think_in_flight = False

    def _clear_guards_on_own_output(self, snapshot: WorkspaceSnapshot) -> None:
        """Clear each guard when the entity's matching output is now conscious.

        ``lingua.external`` realizes a prior ``speak``; ``lingua.internal``
        realizes a prior ``think``. We key on the event *type* (channel) rather
        than just the source so a private monologue does not spuriously clear
        the external-speech guard, and vice versa.
        """
        for _, event in snapshot.selected_events:
            if event.source != OWN_EXTERNAL_SPEECH_SOURCE:
                continue
            if event.type == OWN_EXTERNAL_SPEECH_TYPE:
                self._speak_in_flight = False
            elif event.type == OWN_INTERNAL_SPEECH_TYPE:
                self._think_in_flight = False

    def _drive_name(self, event) -> Optional[str]:
        """Return the drive name on a ``thymos.drive`` crossing event, else None."""
        if event.source == THYMOS_DRIVE_SOURCE and event.type == THYMOS_DRIVE_TYPE:
            name = event.payload.get("drive")
            if isinstance(name, str) and name in DRIVE_INTENT_KINDS:
                return name
        return None

    def __call__(self, snapshot: WorkspaceSnapshot) -> list[Intent]:
        # Realization-observed: clear the speak/think guards independently when
        # the corresponding own output becomes conscious.
        self._clear_guards_on_own_output(snapshot)

        intents: list[Intent] = []

        # --- speak (at most one per call) ---------------------------------
        # A present user utterance OUTRANKS a social-drive initiative.
        if not self._speak_in_flight:
            speak_intent = self._user_response_intent(snapshot)
            if speak_intent is None:
                # No user to answer; consider a social-drive initiative.
                speak_intent = self._social_drive_speak(snapshot)
            if speak_intent is not None:
                self._speak_in_flight = True
                intents.append(speak_intent)

        # --- think (separate one-in-flight guard) -------------------------
        if not self._think_in_flight:
            think_intent = self._deliberative_drive_think(snapshot)
            if think_intent is not None:
                self._think_in_flight = True
                intents.append(think_intent)

        return intents

    def _social_drive_speak(self, snapshot: WorkspaceSnapshot) -> Optional[Intent]:
        """A ``speak`` intent from a ``social_drive`` crossing, if present."""
        for entry_id, event in snapshot.selected_events:
            if self._is_own_speech(event):
                continue
            name = self._drive_name(event)
            if name == "social_drive":
                return Intent(
                    kind=SPEAK,
                    about=f"social_drive (value={event.payload.get('value')})",
                    entry_id=entry_id or None,
                )
        return None

    def _deliberative_drive_think(
        self, snapshot: WorkspaceSnapshot
    ) -> Optional[Intent]:
        """A ``think`` intent from a curiosity/boredom/restlessness crossing."""
        for entry_id, event in snapshot.selected_events:
            if self._is_own_speech(event):
                continue
            name = self._drive_name(event)
            if name is not None and DRIVE_INTENT_KINDS[name] == THINK:
                return Intent(
                    kind=THINK,
                    about=f"{name} (value={event.payload.get('value')})",
                    entry_id=entry_id or None,
                )
        return None
