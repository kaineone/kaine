# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the C3 guard timeout and channel-keyed speak guard clearing."""
from __future__ import annotations

from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.nous_proposals import NousProposalSource
from kaine.workspace.report_policy import SelfInitiatedReportPolicy
from kaine.workspace.volition import (
    SPEAK,
    THINK,
    DefaultActionSelectionPolicy,
    Volition,
)


def _event(
    source: str, type_: str, payload: dict | None = None, salience: float = 0.5
) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload or {},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _soma_report(value: float = 0.5) -> tuple[str, Event]:
    return ("s1", _event("soma", "soma.report", {"wellness": value}))


def _own_speech() -> tuple[str, Event]:
    return ("e2", _event("lingua", "external_speech", {"text": "I said this"}))


def _own_internal_speech() -> tuple[str, Event]:
    return ("i1", _event("lingua", "internal_speech", {"text": "monologue"}))


def _proposal(
    proposal_id: str,
    kind: str,
    *,
    action: str = "noop",
    preference: float = 0.5,
    salience: float = 0.5,
) -> tuple[str, Event]:
    return (
        "p-" + proposal_id,
        _event(
            "nous",
            "nous.proposal",
            {
                "proposal_id": proposal_id,
                "action": action,
                "kind": kind,
                "step": 1,
                "preference": preference,
            },
            salience=salience,
        ),
    )


def _snapshot(events, *, inhibited: bool = False) -> WorkspaceSnapshot:
    # The coalition is ordered by salience (highest first) by the time it
    # reaches Volition, so the helper sorts to match real engine behavior. The
    # precision-weighted scores the report policy reads mirror each salience.
    selected = sorted(events, key=lambda item: item[1].salience, reverse=True)
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=selected,
        inhibited=inhibited,
        is_experiential=True,
        salience_scores={entry_id: event.salience for entry_id, event in selected},
    )


class _Clock:
    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _report_policy(clock=None, guard_clock=None):
    return SelfInitiatedReportPolicy(
        report_threshold=0.6,
        think_threshold=0.45,
        speak_refractory_s=8.0,
        think_refractory_s=3.0,
        clock=clock,
        guard_clock=guard_clock if guard_clock is not None else clock,
    )


def test_report_speak_guard_times_out_without_own_output():
    clock = _Clock()
    p = _report_policy(clock=clock)
    p.note_external_intent(SPEAK)

    assert p.speak_in_flight is True
    clock.advance(47.9)
    p(_snapshot([]))
    assert p.speak_in_flight is True

    clock.advance(0.1)
    p(_snapshot([]))
    assert p.speak_in_flight is False


def test_report_think_guard_times_out_without_own_output():
    clock = _Clock()
    p = _report_policy(clock=clock)
    p.note_external_intent(THINK)

    assert p.think_in_flight is True
    clock.advance(47.9)
    p(_snapshot([]))
    assert p.think_in_flight is True

    clock.advance(0.1)
    p(_snapshot([]))
    assert p.think_in_flight is False


def test_report_think_guard_from_own_emission_times_out():
    clock = _Clock()
    p = _report_policy(clock=clock)
    snap = _snapshot([_soma_report(0.5)])  # crosses think but not report bar
    intents = p(snap)

    assert [i.kind for i in intents] == [THINK]
    assert p.think_in_flight is True

    clock.advance(48.0)
    p(_snapshot([]))
    assert p.think_in_flight is False


def test_report_channel_keyed_own_output_clears_guard():
    # external_speech clears the speak guard but leaves the think guard armed
    clock = _Clock()
    p_speak = _report_policy(clock=clock)
    p_speak.note_external_intent(SPEAK)
    p_speak.note_external_intent(THINK)
    p_speak(_snapshot([_own_speech()]))
    assert p_speak.speak_in_flight is False
    assert p_speak.think_in_flight is True

    # internal_speech clears the think guard but leaves the speak guard armed
    p_think = _report_policy(clock=clock)
    p_think.note_external_intent(SPEAK)
    p_think.note_external_intent(THINK)
    p_think(_snapshot([_own_internal_speech()]))
    assert p_think.speak_in_flight is True
    assert p_think.think_in_flight is False


def test_default_policy_does_not_clear_speak_guard_on_internal_speech():
    clock = _Clock()
    p = DefaultActionSelectionPolicy(clock=clock)
    p.note_external_intent(SPEAK)
    assert p.speak_in_flight is True

    p(_snapshot([_own_internal_speech()]))
    assert p.speak_in_flight is True

    p(_snapshot([_own_speech()]))
    assert p.speak_in_flight is False


def test_nous_think_guard_timeout_through_report_policy():
    clock = _Clock()
    inner = SelfInitiatedReportPolicy(
        report_threshold=0.6,
        think_threshold=0.6,
        clock=clock,
        guard_clock=clock,
    )
    source = NousProposalSource(inner, clock=clock)
    v = Volition(policy=source)

    # Non-proposal salience stays below the inner policy's think bar so the
    # report policy itself stays silent; the Nous think proposals drive action.
    base = _soma_report(0.5)

    snap1 = _snapshot([base, _proposal("p1", THINK)])
    intents1 = v.select(snap1)
    assert len(intents1) == 1
    assert intents1[0].kind == THINK
    assert v.proposal_outcomes(snap1) == [
        {"proposal_id": "p1", "realized": True, "reason": "realized"}
    ]

    # Before the 48 s guard timeout, a second think is still in flight.
    clock.advance(47.9)
    snap2 = _snapshot([base, _proposal("p2", THINK)])
    assert v.select(snap2) == []
    assert v.proposal_outcomes(snap2) == [
        {"proposal_id": "p2", "realized": False, "reason": "in_flight"}
    ]

    # After the timeout the guard has cleared and a third think can be realized.
    clock.advance(0.1)
    snap3 = _snapshot([base, _proposal("p3", THINK)])
    intents3 = v.select(snap3)
    assert len(intents3) == 1
    assert intents3[0].kind == THINK
    assert v.proposal_outcomes(snap3) == [
        {"proposal_id": "p3", "realized": True, "reason": "realized"}
    ]


def test_report_speak_guard_uses_wall_clock_not_subjective():
    sub = _Clock()
    wall = _Clock()
    p = _report_policy(clock=sub, guard_clock=wall)
    p.note_external_intent(SPEAK)

    assert p.speak_in_flight is True
    sub.advance(1000.0)
    p(_snapshot([]))
    assert p.speak_in_flight is True

    wall.advance(48.0)
    p(_snapshot([]))
    assert p.speak_in_flight is False


def test_report_speak_refractory_uses_subjective_clock():
    sub = _Clock()
    wall = _Clock()
    p = _report_policy(clock=sub, guard_clock=wall)
    p.note_external_intent(SPEAK)
    p(_snapshot([_own_speech()]))

    wall.advance(1000.0)
    sub.advance(1.0)

    high_soma = ("s2", _event("soma", "soma.report", {"wellness": 1.0}, salience=1.0))
    snap_before = _snapshot([high_soma])
    # The speak refractory holds; the report policy may still think instead.
    assert SPEAK not in [i.kind for i in p(snap_before)]

    sub.advance(8.0)
    snap_after = _snapshot([high_soma])
    intents = p(snap_after)
    assert [i.kind for i in intents] == [SPEAK]
