# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Nous proposal realization for Volition.

This module implements the Volition side of ``nous-drives-action``: a policy
wrapper that considers the most salient ``nous.proposal`` in the conscious
coalition and, when appropriate, emits an intent with ``origin: "nous"``. For
every proposal it sees it records a content-free outcome payload that Volition
publishes to ``volition_feedback.out`` so Nous can learn from what actually
happened.
"""
from __future__ import annotations

import dataclasses
import logging
import time
from typing import Callable, Optional

from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.volition import (
    OWN_EXTERNAL_SPEECH_SOURCE,
    OWN_EXTERNAL_SPEECH_TYPE,
    OWN_INTERNAL_SPEECH_TYPE,
    REST,
    SPEAK,
    THINK,
    USER_COMMUNICATION_SOURCE,
    USER_COMMUNICATION_TYPE,
    ActionSelectionPolicy,
    Intent,
)

log = logging.getLogger(__name__)

# Nous → Volition event contract.
NOUS_SOURCE = "nous"
NOUS_PROPOSAL_TYPE = "nous.proposal"

# Drive summary helpers are mirrored here so this module stays independent of
# kaine.workspace.drive_policy (the drive policy already imports from volition).
THYMOS_DRIVE_SOURCE = "thymos"
THYMOS_DRIVE_TYPE = "thymos.drive"


class NousProposalSource:
    """Policy wrapper that realizes conscious Nous proposals.

    Runs the wrapped ``inner`` policy first. For each kind the wrapped policy
    guards itself (it exposes ``<kind>_in_flight`` and implements
    :meth:`note_external_intent`), a realized Nous proposal arms that policy's
    own guard. For any other kind the source keeps a local guard and drops
    inner intents of that kind while it is armed. Records an outcome for every
    proposal seen.
    """

    _GUARD_TIMEOUT_S = 48.0

    def __init__(
        self,
        inner: ActionSelectionPolicy,
        *,
        drive_actions: bool = True,
        clock: Callable[[], float] | None = None,
        time_fn: Callable[[], float] | None = None,
        think_refractory_s: float = 3.0,
        speak_refractory_s: float = 8.0,
        rest_min_interval_s: float = 1800.0,
    ) -> None:
        self._inner = inner
        self._drive_actions = bool(drive_actions)
        # Prefer an explicit clock, then the wrapped policy's clock, then wall
        # time so arming and timeout checks never diverge.
        self._clock = clock or getattr(inner, "_clock", None) or time.monotonic
        # Entity clock for rest forwarding; falls back to the policy clock.
        self._time_fn = time_fn or self._clock

        self._think_refractory_s = float(think_refractory_s)
        self._speak_refractory_s = float(speak_refractory_s)
        self._rest_min_interval_s = float(rest_min_interval_s)

        can_note = hasattr(inner, "note_external_intent")
        self._inner_guards = {
            kind: can_note and hasattr(inner, f"{kind}_in_flight")
            for kind in (SPEAK, THINK)
        }

        self._think_in_flight = False
        self._speak_in_flight = False
        self._think_armed_at: Optional[float] = None
        self._speak_armed_at: Optional[float] = None
        # Refractory intervals count the most recent intent of each kind from
        # either the wrapped policy or a realized proposal.
        self._last_at = {
            SPEAK: float("-inf"),
            THINK: float("-inf"),
            # Seeded at construction so the first rest proposal after boot is
            # refractory until the interval passes.
            REST: self._time_fn(),
        }

        self._last_outcomes: list[dict] = []

    @property
    def drive_actions(self) -> bool:
        return self._drive_actions

    def proposal_outcomes(self, snapshot: WorkspaceSnapshot) -> list[dict]:
        """Outcomes recorded during the most recent ``__call__``."""
        return list(self._last_outcomes)

    def observe_inhibited(self, snapshot: WorkspaceSnapshot) -> None:
        """Record an outcome for every Nous proposal in the coalition.

        Guard clearing still runs on every call, including inhibited
        observations. With ``drive_actions=False`` the recorded reason is
        ``disabled`` rather than ``inhibited``.
        """
        self._last_outcomes = []
        self._clear_guards_on_own_output(snapshot)
        reason = "disabled" if not self._drive_actions else "inhibited"
        for _, event in self._find_proposals(snapshot):
            self._record_outcome(event, reason, realized=False)

    def __call__(self, snapshot: WorkspaceSnapshot) -> list[Intent]:
        self._last_outcomes = []
        # Guard clearing and timeout checks must run at the start of EVERY
        # path: normal, ablation, and no-proposal.
        self._clear_guards_on_own_output(snapshot)

        inner_intents = list(self._inner(self._without_proposals(snapshot)))
        # Local guards are only ever armed for kinds the inner policy does not
        # guard, so this never second-guesses the inner policy's own guard.
        passed_intents = self._filter_inner_intents(inner_intents)
        self._update_last_at(passed_intents)

        proposals = self._find_proposals(snapshot)
        if not proposals:
            return passed_intents

        if not self._drive_actions:
            # Observational ablation: outcomes only, never proposal intents.
            for _, event in proposals:
                self._record_outcome(event, "disabled", realized=False)
            return passed_intents

        # The most salient proposal is the first in coalition order; the rest
        # are superseded.
        for _, event in proposals[1:]:
            self._record_outcome(event, "superseded", realized=False)

        top_entry_id, top_event = proposals[0]
        proposal_kind = top_event.payload.get("kind")

        # A proposal whose kind is already produced by the wrapped policy is
        # superseded, preserving the inner policy's decision.
        if proposal_kind in (SPEAK, THINK) and any(
            intent.kind == proposal_kind for intent in passed_intents
        ):
            self._record_outcome(top_event, "superseded", realized=False)
            return passed_intents

        return self._realize_proposal(
            proposal_kind, top_entry_id, top_event, snapshot, passed_intents
        )

    @staticmethod
    def _without_proposals(snapshot: WorkspaceSnapshot) -> WorkspaceSnapshot:
        """The coalition as the wrapped policy sees it: without Nous proposals.

        A proposal is Nous's own choice of action, handled only here. Leaving it
        in would let the wrapped policy report on the proposal itself, and would
        make the wrapped policy decide differently with Nous on than with it off.
        """
        kept = [
            (entry_id, event)
            for entry_id, event in snapshot.selected_events
            if not (event.source == NOUS_SOURCE and event.type == NOUS_PROPOSAL_TYPE)
        ]
        if len(kept) == len(snapshot.selected_events):
            return snapshot
        kept_ids = {entry_id for entry_id, _ in kept}
        scores = {
            entry_id: score
            for entry_id, score in (snapshot.salience_scores or {}).items()
            if entry_id in kept_ids
        }
        return dataclasses.replace(snapshot, selected_events=kept, salience_scores=scores)

    def _find_proposals(
        self, snapshot: WorkspaceSnapshot
    ) -> list[tuple[Optional[str], object]]:
        return [
            (entry_id, event)
            for entry_id, event in snapshot.selected_events
            if event.source == NOUS_SOURCE and event.type == NOUS_PROPOSAL_TYPE
        ]

    def _non_nous_members(
        self, snapshot: WorkspaceSnapshot
    ) -> list[tuple[Optional[str], object]]:
        # Referents must be neither Nous proposals nor the entity's own speech.
        return [
            (entry_id, event)
            for entry_id, event in snapshot.selected_events
            if event.source != NOUS_SOURCE
            and event.source != OWN_EXTERNAL_SPEECH_SOURCE
        ]

    def _top_non_nous_member(
        self, snapshot: WorkspaceSnapshot
    ) -> tuple[Optional[str], object] | None:
        members = self._non_nous_members(snapshot)
        return members[0] if members else None

    def _filter_inner_intents(self, inner_intents: list[Intent]) -> list[Intent]:
        """Drop speak/think intents of a kind whose source guard is armed."""
        passed: list[Intent] = []
        for intent in inner_intents:
            if intent.kind == SPEAK and self._speak_in_flight:
                log.debug("Dropping inner speak intent while Nous speak guard is armed")
                continue
            if intent.kind == THINK and self._think_in_flight:
                log.debug("Dropping inner think intent while Nous think guard is armed")
                continue
            passed.append(intent)
        return passed

    def _update_last_at(self, intents: list[Intent]) -> None:
        """Record the most recent emission time for each kind."""
        now = self._clock()
        for intent in intents:
            # Rest is timed on the entity clock and only ever forwarded here.
            if intent.kind in (SPEAK, THINK):
                self._last_at[intent.kind] = now

    def _summarize_event(self, event: object) -> str:
        """Mirror the summary style used by the drive policy."""
        if (
            event.source == USER_COMMUNICATION_SOURCE
            and event.type == USER_COMMUNICATION_TYPE
        ):
            text = str(event.payload.get("text") or "").strip()
            if text:
                return text
        if (
            event.source == THYMOS_DRIVE_SOURCE
            and event.type == THYMOS_DRIVE_TYPE
        ):
            name = event.payload.get("drive")
            if isinstance(name, str):
                return f"{name} (value={event.payload.get('value')})"
        return f"{event.source}:{event.type}"

    def _record_outcome(self, event: object, reason: str, realized: bool) -> None:
        proposal_id = event.payload.get("proposal_id")
        if proposal_id is None:
            return
        self._last_outcomes.append(
            {"proposal_id": proposal_id, "realized": realized, "reason": reason}
        )

    def _clear_guards_on_own_output(self, snapshot: WorkspaceSnapshot) -> None:
        self._apply_guard_timeouts()
        for _, event in snapshot.selected_events:
            if event.source != OWN_EXTERNAL_SPEECH_SOURCE:
                continue
            if event.type == OWN_EXTERNAL_SPEECH_TYPE:
                self._speak_in_flight = False
                self._speak_armed_at = None
            elif event.type == OWN_INTERNAL_SPEECH_TYPE:
                self._think_in_flight = False
                self._think_armed_at = None

    def _apply_guard_timeouts(self) -> None:
        now = self._clock()
        if self._speak_in_flight:
            if self._speak_armed_at is None:
                self._speak_armed_at = now
            elif (now - self._speak_armed_at) >= self._GUARD_TIMEOUT_S:
                self._speak_in_flight = False
                self._speak_armed_at = None
        if self._think_in_flight:
            if self._think_armed_at is None:
                self._think_armed_at = now
            elif (now - self._think_armed_at) >= self._GUARD_TIMEOUT_S:
                self._think_in_flight = False
                self._think_armed_at = None

    def _realize_proposal(
        self,
        kind: str,
        proposal_entry_id: Optional[str],
        proposal_event: object,
        snapshot: WorkspaceSnapshot,
        inner_intents: list[Intent],
    ) -> list[Intent]:
        now = self._clock()
        proposal_id = proposal_event.payload.get("proposal_id")

        if kind in (SPEAK, THINK):
            local_in_flight = (
                self._speak_in_flight if kind == SPEAK else self._think_in_flight
            )
            in_flight = local_in_flight or bool(
                getattr(self._inner, f"{kind}_in_flight", False)
            )
            if in_flight:
                self._record_outcome(proposal_event, "in_flight", realized=False)
                return inner_intents

            refractory_s = (
                self._speak_refractory_s if kind == SPEAK else self._think_refractory_s
            )
            if (now - self._last_at[kind]) < refractory_s:
                self._record_outcome(proposal_event, "refractory", realized=False)
                return inner_intents

            top = self._top_non_nous_member(snapshot)
            if top is None:
                self._record_outcome(proposal_event, "self_response", realized=False)
                return inner_intents

            entry_id, event = top
            about = self._summarize_event(event)

            if self._inner_guards[kind]:
                self._inner.note_external_intent(kind)
            else:
                if kind == SPEAK:
                    self._speak_in_flight = True
                    self._speak_armed_at = now
                else:
                    self._think_in_flight = True
                    self._think_armed_at = now
            self._last_at[kind] = now

            self._record_outcome(proposal_event, "realized", realized=True)
            return inner_intents + [
                Intent(kind=kind, about=about, entry_id=entry_id, origin="nous")
            ]

        if kind == REST:
            rest_now = self._time_fn()
            if (rest_now - self._last_at[REST]) < self._rest_min_interval_s:
                self._record_outcome(proposal_event, "refractory", realized=False)
                return inner_intents

            self._last_at[REST] = rest_now
            self._record_outcome(proposal_event, "forwarded", realized=False)
            return inner_intents + [
                Intent(kind=REST, about="rest", origin="nous", proposal_id=proposal_id)
            ]

        # Unknown proposal kind: treat as disabled.
        self._record_outcome(proposal_event, "disabled", realized=False)
        return inner_intents
