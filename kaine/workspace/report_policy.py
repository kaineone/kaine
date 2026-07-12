# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Self-initiated report action selection (the "report or stay silent" decision).

The default policy answers a *user utterance*; the drive-biased policy adds
*drive*-initiated intents. Both need something external (a transcript) or Thymos
to move the entity. The base-thesis configuration has neither — no chatbot input
path, Thymos gated off — so nothing would make the entity speak.

This policy closes that without any input trigger: the entity reports **its own
state**. It treats "worth saying" as a higher bar than "conscious" — a report
threshold ABOVE the workspace publication (conscious) threshold — driven by the
coalition's own precision-weighted surprise (the top selected member's precision-
weighted prediction error expressed as salience). Consciousness at 3-10 Hz is far
broader than report; only a rare, high-surprise, novel coalition crosses into
external speech.

Guards (reusing the executive design, never bypassing it):
  - Volition checks inhibition first; this policy is only called on a NON-inhibited
    snapshot (it also returns nothing defensively if handed an inhibited one).
  - A report always describes the CURRENT coalition. With the one-in-flight guard,
    no new intent forms while a prior is being realized, so stale coalitions are
    DROPPED, not queued — when the guard clears, only the then-current state is
    eligible. The entity speaks about now, or not at all.
  - Novelty: the same content signature (top source/type) is not re-reported back
    to back; a refractory interval prevents chatter even when eligible.
  - Two channels: internal ``think`` at a lower threshold (the saved, observed
    monologue) and external ``speak`` at the report threshold (rare).
  - Never reports the entity's own output (source ``lingua``), and never reads a
    user-utterance / transcription event — report is self-initiated.

Injectable exactly like the other policies (selected via ``[volition].policy``).
"""
from __future__ import annotations

import time
from typing import Callable, Optional

from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.volition import (
    OWN_EXTERNAL_SPEECH_SOURCE,
    OWN_EXTERNAL_SPEECH_TYPE,
    OWN_INTERNAL_SPEECH_TYPE,
    SPEAK,
    THINK,
    Intent,
)


class SelfInitiatedReportPolicy:
    """Surprise-gated, refractory, self-initiated ``think`` / ``speak`` selection.

    ``report_threshold`` / ``think_threshold`` are the two report bars; both should
    sit ABOVE the workspace publication threshold so report is rarer than
    consciousness. ``*_refractory_s`` are minimum intervals between reports, read
    off the injected ``clock`` (the entity's subjective clock in production;
    default monotonic).
    """

    def __init__(
        self,
        *,
        report_threshold: float = 0.6,
        think_threshold: float = 0.45,
        speak_refractory_s: float = 8.0,
        think_refractory_s: float = 3.0,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if not 0.0 <= think_threshold <= report_threshold <= 1.0:
            raise ValueError(
                "require 0 <= think_threshold <= report_threshold <= 1, got "
                f"think={think_threshold}, report={report_threshold}"
            )
        if speak_refractory_s < 0 or think_refractory_s < 0:
            raise ValueError("refractory intervals must be >= 0")
        self._report_threshold = float(report_threshold)
        self._think_threshold = float(think_threshold)
        self._speak_refractory_s = float(speak_refractory_s)
        self._think_refractory_s = float(think_refractory_s)
        self._clock = clock or time.monotonic
        self._speak_in_flight = False
        self._think_in_flight = False
        # -inf so the first eligible report is never suppressed by refractory.
        self._last_speak_at = float("-inf")
        self._last_think_at = float("-inf")
        self._last_report_sig: Optional[tuple[str, str]] = None

    @property
    def speak_in_flight(self) -> bool:
        return self._speak_in_flight

    @property
    def think_in_flight(self) -> bool:
        return self._think_in_flight

    def mark_realized(self) -> None:
        """Clear the speak one-in-flight guard (a prior utterance completed)."""
        self._speak_in_flight = False

    def mark_think_realized(self) -> None:
        """Clear the think one-in-flight guard (a prior think completed)."""
        self._think_in_flight = False

    @staticmethod
    def _is_own_speech(event) -> bool:
        return getattr(event, "source", None) == OWN_EXTERNAL_SPEECH_SOURCE

    def _clear_guards_on_own_output(self, snapshot: WorkspaceSnapshot) -> None:
        """Clear each guard when the entity's matching output is now conscious —
        ``lingua.external`` realizes a prior ``speak``, ``lingua.internal`` a prior
        ``think`` (keyed on channel so one does not clear the other)."""
        for _, event in snapshot.selected_events:
            if getattr(event, "source", None) != OWN_EXTERNAL_SPEECH_SOURCE:
                continue
            if event.type == OWN_EXTERNAL_SPEECH_TYPE:
                self._speak_in_flight = False
            elif event.type == OWN_INTERNAL_SPEECH_TYPE:
                self._think_in_flight = False

    def __call__(self, snapshot: WorkspaceSnapshot) -> list[Intent]:
        if snapshot.inhibited:
            return []
        self._clear_guards_on_own_output(snapshot)

        # The report signal is the top precision-weighted salience among the
        # coalition members, excluding the entity's own speech (never report on
        # your own output).
        scores = snapshot.salience_scores or {}
        candidates = [
            (entry_id, event)
            for entry_id, event in snapshot.selected_events
            if not self._is_own_speech(event)
        ]
        if not candidates:
            return []
        top_entry_id, top_event = max(
            candidates, key=lambda t: float(scores.get(t[0], 0.0))
        )
        surprise = float(scores.get(top_entry_id, 0.0))
        signature = (top_event.source, top_event.type)
        now = float(self._clock())

        # External speak: the high, refractory, novelty-gated report bar.
        if (
            surprise >= self._report_threshold
            and not self._speak_in_flight
            and (now - self._last_speak_at) >= self._speak_refractory_s
            and signature != self._last_report_sig
        ):
            self._speak_in_flight = True
            self._last_speak_at = now
            self._last_report_sig = signature
            return [
                Intent(
                    kind=SPEAK,
                    about=f"{top_event.source} (surprise={surprise:.3f})",
                    entry_id=top_entry_id or None,
                )
            ]

        # Internal think: a lower bar, its own refractory + guard. Only when the
        # report bar was not met (a single channel fires per call).
        if (
            surprise >= self._think_threshold
            and not self._think_in_flight
            and (now - self._last_think_at) >= self._think_refractory_s
        ):
            self._think_in_flight = True
            self._last_think_at = now
            return [
                Intent(
                    kind=THINK,
                    about=f"{top_event.source} (surprise={surprise:.3f})",
                    entry_id=top_entry_id or None,
                )
            ]

        return []


__all__ = ["SelfInitiatedReportPolicy"]
