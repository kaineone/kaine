# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the A.6 step 1 guard release on the language organ's own output."""
from __future__ import annotations

from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.action_selection import (
    SPEAK,
    THINK,
    ActionSelection,
    DefaultActionSelectionPolicy,
)
from kaine.workspace.drive_policy import DriveBiasedActionSelectionPolicy
from kaine.workspace.planning_proposals import PlanningProposalSource
from kaine.workspace.report_policy import SelfInitiatedReportPolicy


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


def _snapshot(events, *, inhibited: bool = False) -> WorkspaceSnapshot:
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


def _proposal(proposal_id: str, kind: str, *, salience: float = 0.5) -> tuple[str, Event]:
    return (
        "p-" + proposal_id,
        _event(
            "planning",
            "planning.proposal",
            {
                "proposal_id": proposal_id,
                "action": "noop",
                "kind": kind,
                "step": 1,
                "preference": 0.5,
            },
            salience=salience,
        ),
    )


def _curiosity(salience: float = 0.5) -> tuple[str, Event]:
    return (
        "d",
        _event(
            "affect",
            "affect.drive",
            {"drive": "curiosity", "value": 0.8},
            salience=salience,
        ),
    )


def test_report_think_released_by_unaccessed_internal_speech():
    sub = _Clock()
    wall = _Clock()
    p = SelfInitiatedReportPolicy(
        report_threshold=0.6,
        think_threshold=0.45,
        speak_refractory_s=8.0,
        think_refractory_s=3.0,
        clock=sub,
        guard_clock=wall,
    )
    v = ActionSelection(policy=p)

    assert [i.kind for i in v.select(_snapshot([_curiosity(0.5)]))] == [THINK]
    sub.advance(5.0)
    wall.advance(5.0)
    v.observe_own_output(_event("language", "internal_speech", {"text": "a thought"}))
    assert [i.kind for i in v.select(_snapshot([_curiosity(0.5)]))] == [THINK]


def test_report_think_stays_muted_without_own_output():
    sub = _Clock()
    wall = _Clock()
    p = SelfInitiatedReportPolicy(
        report_threshold=0.6,
        think_threshold=0.45,
        speak_refractory_s=8.0,
        think_refractory_s=3.0,
        clock=sub,
        guard_clock=wall,
    )
    v = ActionSelection(policy=p)

    assert [i.kind for i in v.select(_snapshot([_curiosity(0.5)]))] == [THINK]
    sub.advance(5.0)
    wall.advance(5.0)
    assert v.select(_snapshot([_curiosity(0.5)])) == []


def test_report_speak_released_by_unaccessed_external_speech():
    sub = _Clock()
    wall = _Clock()
    p = SelfInitiatedReportPolicy(
        report_threshold=0.6,
        think_threshold=0.45,
        speak_refractory_s=8.0,
        think_refractory_s=3.0,
        clock=sub,
        guard_clock=wall,
    )
    v = ActionSelection(policy=p)

    alert = ("a1", _event("audition", "audition.alert", {"level": 0.8}, salience=0.7))
    assert [i.kind for i in v.select(_snapshot([alert]))] == [SPEAK]
    sub.advance(10.0)
    wall.advance(10.0)
    v.observe_own_output(_event("language", "external_speech", {"text": "I said this"}))
    vision = ("v1", _event("vision", "vision.alert", {"level": 0.8}, salience=0.7))
    assert [i.kind for i in v.select(_snapshot([vision]))] == [SPEAK]


def test_report_speak_stays_muted_without_own_output():
    sub = _Clock()
    wall = _Clock()
    p = SelfInitiatedReportPolicy(
        report_threshold=0.6,
        think_threshold=0.45,
        speak_refractory_s=8.0,
        think_refractory_s=3.0,
        clock=sub,
        guard_clock=wall,
    )
    v = ActionSelection(policy=p)

    alert = ("a1", _event("audition", "audition.alert", {"level": 0.8}, salience=0.7))
    assert [i.kind for i in v.select(_snapshot([alert]))] == [SPEAK]
    sub.advance(10.0)
    wall.advance(10.0)
    vision = ("v1", _event("vision", "vision.alert", {"level": 0.8}, salience=0.7))
    assert [i.kind for i in v.select(_snapshot([vision]))] == [THINK]


def test_release_is_channel_keyed():
    v = ActionSelection(
        policy=SelfInitiatedReportPolicy(
            report_threshold=0.6,
            think_threshold=0.45,
            speak_refractory_s=8.0,
            think_refractory_s=3.0,
        )
    )
    p = v.policy
    p.note_external_intent(SPEAK)
    p.note_external_intent(THINK)

    v.observe_own_output(_event("language", "internal_speech", {"text": "a thought"}))
    assert p.think_in_flight is False
    assert p.speak_in_flight is True

    v.observe_own_output(_event("language", "external_speech", {"text": "I said this"}))
    assert p.speak_in_flight is False

    v2 = ActionSelection(
        policy=SelfInitiatedReportPolicy(
            report_threshold=0.6,
            think_threshold=0.45,
            speak_refractory_s=8.0,
            think_refractory_s=3.0,
        )
    )
    p2 = v2.policy
    p2.note_external_intent(SPEAK)
    p2.note_external_intent(THINK)
    v2.observe_own_output(_event("language", "external_speech", {"text": "I said this"}))
    assert p2.speak_in_flight is False
    assert p2.think_in_flight is True


def test_other_sources_and_types_release_nothing():
    v = ActionSelection(
        policy=SelfInitiatedReportPolicy(
            report_threshold=0.6,
            think_threshold=0.45,
            speak_refractory_s=8.0,
            think_refractory_s=3.0,
        )
    )
    p = v.policy
    p.note_external_intent(SPEAK)
    p.note_external_intent(THINK)

    v.observe_own_output(_event("audition", "internal_speech", {"text": "heard thought"}))
    v.observe_own_output(_event("audition", "external_speech", {"text": "heard speech"}))
    v.observe_own_output(_event("language", "realization_failed", {"reason": "timeout"}))
    assert p.speak_in_flight is True
    assert p.think_in_flight is True


def test_timeout_fallback_still_releases():
    sub = _Clock()
    wall = _Clock()
    p = SelfInitiatedReportPolicy(
        report_threshold=0.6,
        think_threshold=0.45,
        speak_refractory_s=8.0,
        think_refractory_s=3.0,
        clock=sub,
        guard_clock=wall,
    )
    v = ActionSelection(policy=p)

    assert [i.kind for i in v.select(_snapshot([_curiosity(0.5)]))] == [THINK]
    sub.advance(47.9)
    wall.advance(47.9)
    assert v.select(_snapshot([_curiosity(0.5)])) == []
    sub.advance(0.1)
    wall.advance(0.1)
    assert [i.kind for i in v.select(_snapshot([_curiosity(0.5)]))] == [THINK]


def test_drive_policy_think_and_speak_released_by_own_output():
    clock = _Clock()
    p = DriveBiasedActionSelectionPolicy(clock=clock)
    v = ActionSelection(policy=p)

    assert [i.kind for i in v.select(_snapshot([_curiosity(0.5)]))] == [THINK]
    clock.advance(1.0)
    v.observe_own_output(_event("language", "internal_speech", {"text": "a thought"}))
    assert p.think_in_flight is False
    assert [i.kind for i in v.select(_snapshot([_curiosity(0.5)]))] == [THINK]

    # The re-armed think guard must time out from the re-arm, not the first arm.
    clock.advance(47.0)
    v.select(_snapshot([]))
    assert p.think_in_flight is True

    social = (
        "sd",
        _event("affect", "affect.drive", {"drive": "social_drive", "value": 0.8}, salience=0.5),
    )
    assert SPEAK in [i.kind for i in v.select(_snapshot([social]))]
    v.observe_own_output(_event("language", "external_speech", {"text": "I said this"}))
    assert p.speak_in_flight is False
    assert SPEAK in [i.kind for i in v.select(_snapshot([social]))]


def test_default_policy_speak_released_by_own_output():
    p = DefaultActionSelectionPolicy(clock=_Clock())
    v = ActionSelection(policy=p)

    t1 = (
        "t1",
        _event("audition", "audition.transcription", {"text": "hello"}, salience=0.6),
    )
    assert [i.kind for i in v.select(_snapshot([t1]))] == [SPEAK]

    v.observe_own_output(_event("language", "internal_speech", {"text": "a thought"}))
    assert p.speak_in_flight is True

    v.observe_own_output(_event("language", "external_speech", {"text": "I said this"}))
    assert p.speak_in_flight is False

    t2 = (
        "t2",
        _event("audition", "audition.transcription", {"text": "again"}, salience=0.6),
    )
    assert [i.kind for i in v.select(_snapshot([t2]))] == [SPEAK]


def test_planning_wrapper_local_think_guard_released():
    clock = _Clock()
    source = PlanningProposalSource(DefaultActionSelectionPolicy(clock=clock), clock=clock)
    v = ActionSelection(policy=source)

    base = ("s1", _event("interoception", "interoception.report", {"wellness": 0.5}))

    snap1 = _snapshot([base, _proposal("p1", THINK)])
    intents1 = v.select(snap1)
    assert [i.kind for i in intents1] == [THINK]
    assert intents1[0].origin == "planning"

    clock.advance(5.0)
    snap2 = _snapshot([base, _proposal("p2", THINK)])
    assert v.select(snap2) == []
    assert v.proposal_outcomes(snap2) == [
        {"proposal_id": "p2", "realized": False, "reason": "in_flight"}
    ]

    v.observe_own_output(_event("language", "internal_speech", {"text": "a thought"}))
    snap3 = _snapshot([base, _proposal("p3", THINK)])
    intents3 = v.select(snap3)
    assert [i.kind for i in intents3] == [THINK]
    assert v.proposal_outcomes(snap3) == [
        {"proposal_id": "p3", "realized": True, "reason": "realized"}
    ]


def test_planning_wrapper_forwards_release_to_inner():
    clock = _Clock()
    inner = SelfInitiatedReportPolicy(
        report_threshold=0.6,
        think_threshold=0.6,
        clock=clock,
        guard_clock=clock,
    )
    source = PlanningProposalSource(inner, clock=clock)
    v = ActionSelection(policy=source)

    base = ("s1", _event("interoception", "interoception.report", {"wellness": 0.5}))

    snap1 = _snapshot([base, _proposal("p1", THINK)])
    assert [i.kind for i in v.select(snap1)] == [THINK]
    assert inner.think_in_flight is True

    v.observe_own_output(_event("language", "internal_speech", {"text": "a thought"}))
    assert inner.think_in_flight is False

    inner.note_external_intent(SPEAK)
    assert inner.speak_in_flight is True
    v.observe_own_output(_event("language", "external_speech", {"text": "I said this"}))
    assert inner.speak_in_flight is False


def test_observe_own_output_tolerates_policy_without_hooks():
    v = ActionSelection(policy=lambda snapshot: [])
    v.observe_own_output(_event("language", "internal_speech", {"text": "a thought"}))
    v.observe_own_output(_event("language", "external_speech", {"text": "I said this"}))

    class _RaisingThinkHook:
        def __call__(self, snapshot):
            return []
        def mark_think_realized(self):
            raise RuntimeError("boom")

    v2 = ActionSelection(policy=_RaisingThinkHook())
    v2.observe_own_output(_event("language", "internal_speech", {"text": "a thought"}))
