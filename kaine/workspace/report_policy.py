# SPDX-License-Identifier: LicenseRef-CAL-0.4
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
    consciousness. ``interrupt_threshold`` (optional, strictly above the report
    bar) is a third, higher bar: a coalition crossing it while a ``speak`` is in
    flight — with different content from what is being said — emits a preempting,
    interrupt-marked ``speak`` that redirects the utterance mid-stream. Absent, an
    in-flight utterance always runs to completion (opt-in interruption).
    ``*_refractory_s`` are minimum intervals between reports, read off the injected
    ``clock`` (the entity's subjective clock in production; default monotonic).
    ``guard_clock`` times the in-flight speak/think guards; in production it is
    the real monotonic wall clock while ``clock`` remains subjective.
    """

    # C3: the same guard timeout as the default and drive policies. A guard
    # armed this long without the entity's matching output becoming conscious
    # is cleared, so a failed realization cannot permanently mute the entity.
    _GUARD_TIMEOUT_S = 48.0

    def __init__(
        self,
        *,
        report_threshold: float = 0.6,
        think_threshold: float = 0.45,
        interrupt_threshold: Optional[float] = None,
        speak_refractory_s: float = 8.0,
        think_refractory_s: float = 3.0,
        sig_expiry_s: Optional[float] = None,
        clock: Optional[Callable[[], float]] = None,
        guard_clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if not 0.0 <= think_threshold <= report_threshold <= 1.0:
            raise ValueError(
                "require 0 <= think_threshold <= report_threshold <= 1, got "
                f"think={think_threshold}, report={report_threshold}"
            )
        # Interrupt is opt-in: absent → the current await-to-completion behavior
        # (an in-flight utterance always finishes). When set it is a surprise bar
        # strictly ABOVE the report bar — only a rarer, more urgent coalition
        # preempts speech (interruptible-utterance D3).
        if interrupt_threshold is not None and not (
            report_threshold < interrupt_threshold <= 1.0
        ):
            raise ValueError(
                "require report_threshold < interrupt_threshold <= 1, got "
                f"report={report_threshold}, interrupt={interrupt_threshold}"
            )
        if speak_refractory_s < 0 or think_refractory_s < 0:
            raise ValueError("refractory intervals must be >= 0")
        self._report_threshold = float(report_threshold)
        self._think_threshold = float(think_threshold)
        self._interrupt_threshold = (
            float(interrupt_threshold) if interrupt_threshold is not None else None
        )
        self._speak_refractory_s = float(speak_refractory_s)
        self._think_refractory_s = float(think_refractory_s)
        self._clock = clock or time.monotonic
        # The in-flight guards time real generation and playback, so the guard
        # timeout reads wall time; refractory periods stay on the subjective clock.
        self._guard_clock = guard_clock or time.monotonic
        self._speak_in_flight = False
        self._think_in_flight = False
        self._speak_armed_at = float("-inf")
        self._think_armed_at = float("-inf")
        # -inf so the first eligible report is never suppressed by refractory.
        self._last_speak_at = float("-inf")
        self._last_think_at = float("-inf")
        self._last_report_sig: Optional[tuple[str, str]] = None
        # H4 — the coarse (source, type) novelty signature must not suppress
        # forever: on a stable feed the top coalition rarely changes signature,
        # and a permanent block drives external speech to zero over days. When
        # sig_expiry_s is set, a remembered signature older than the window no
        # longer counts as "the same content"; None preserves the old behavior.
        self._sig_expiry_s = float(sig_expiry_s) if sig_expiry_s is not None else None
        self._sig_set_at = float("-inf")

    def _sig_blocks(self, signature: tuple[str, str], now: float) -> bool:
        """True while the remembered signature still suppresses ``signature``."""
        if signature != self._last_report_sig:
            return False
        if self._sig_expiry_s is None:
            return True
        return (now - self._sig_set_at) < self._sig_expiry_s

    @property
    def speak_in_flight(self) -> bool:
        return self._speak_in_flight

    @property
    def think_in_flight(self) -> bool:
        return self._think_in_flight

    def mark_realized(self) -> None:
        """Clear the speak one-in-flight guard (a prior utterance completed)."""
        self._speak_in_flight = False
        self._speak_armed_at = float("-inf")

    def mark_think_realized(self) -> None:
        """Clear the think one-in-flight guard (a prior think completed)."""
        self._think_in_flight = False
        self._think_armed_at = float("-inf")

    def note_external_intent(self, kind: str, when: float | None = None) -> None:
        """Arm the in-flight guard and refractory for ``kind`` as if emitted here.

        Does not update the novelty signature. ``when`` sets the refractory
        timestamps only; the guard is always armed on the wall-time
        ``guard_clock``, so generation and playback latency is measured in real
        seconds.
        """
        now = when if when is not None else float(self._clock())
        if kind == SPEAK:
            self._speak_in_flight = True
            self._last_speak_at = now
            self._speak_armed_at = float(self._guard_clock())
        elif kind == THINK:
            self._think_in_flight = True
            self._last_think_at = now
            self._think_armed_at = float(self._guard_clock())

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
                self._speak_armed_at = float("-inf")
            elif event.type == OWN_INTERNAL_SPEECH_TYPE:
                self._think_in_flight = False
                self._think_armed_at = float("-inf")

        # C3 belt-and-suspenders: a guard armed longer than the timeout window
        # without the entity's own output becoming conscious is cleared, so a
        # failed realization (LLM error, dead organ) can never permanently
        # mute the entity. Uses the wall-time guard_clock so a failed
        # realization recovers after real seconds.
        guard_now = float(self._guard_clock())
        if (
            self._speak_in_flight
            and (guard_now - self._speak_armed_at) >= self._GUARD_TIMEOUT_S
        ):
            self._speak_in_flight = False
            self._speak_armed_at = float("-inf")
        if (
            self._think_in_flight
            and (guard_now - self._think_armed_at) >= self._GUARD_TIMEOUT_S
        ):
            self._think_in_flight = False
            self._think_armed_at = float("-inf")

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

        # Interrupt: an urgent surprise preempts an in-flight utterance and
        # redirects (interruptible-utterance D3). It bypasses the speak refractory
        # (an interrupt is urgent by definition) but keeps the novelty guard
        # (don't interrupt to say the same thing) and re-arms the in-flight guard
        # for the redirected utterance. Only fires WHILE a speak is in flight —
        # otherwise the ordinary report bar below already covers it. The emergent
        # trigger is workspace competition: the flag is set only because a more
        # salient coalition crossed a higher bar, not by any hardwired rule.
        if (
            self._interrupt_threshold is not None
            and self._speak_in_flight
            and surprise >= self._interrupt_threshold
            and not self._sig_blocks(signature, now)
        ):
            # _speak_in_flight stays True (re-armed for the new utterance).
            self._last_speak_at = now
            self._speak_armed_at = float(self._guard_clock())
            self._last_report_sig = signature
            self._sig_set_at = now
            return [
                Intent(
                    kind=SPEAK,
                    about=f"{top_event.source} (surprise={surprise:.3f})",
                    entry_id=top_entry_id or None,
                    interrupt=True,
                    about_kind="event",
                )
            ]

        # External speak: the high, refractory, novelty-gated report bar.
        if (
            surprise >= self._report_threshold
            and not self._speak_in_flight
            and (now - self._last_speak_at) >= self._speak_refractory_s
            and not self._sig_blocks(signature, now)
        ):
            self._speak_in_flight = True
            self._speak_armed_at = float(self._guard_clock())
            self._last_speak_at = now
            self._last_report_sig = signature
            self._sig_set_at = now
            return [
                Intent(
                    kind=SPEAK,
                    about=f"{top_event.source} (surprise={surprise:.3f})",
                    entry_id=top_entry_id or None,
                    about_kind="event",
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
            self._think_armed_at = float(self._guard_clock())
            self._last_think_at = now
            return [
                Intent(
                    kind=THINK,
                    about=f"{top_event.source} (surprise={surprise:.3f})",
                    entry_id=top_entry_id or None,
                    about_kind="event",
                )
            ]

        return []


__all__ = ["SelfInitiatedReportPolicy"]
