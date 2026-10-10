# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the Nous proposal action-selection source."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.cycle.engine import CognitiveCycle
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.lingua.module import Lingua
from kaine.workspace.drive_policy import DriveBiasedActionSelectionPolicy
from kaine.workspace.nous_proposals import NousProposalSource
from kaine.workspace.report_policy import SelfInitiatedReportPolicy
from kaine.workspace.volition import (
    REST,
    SPEAK,
    THINK,
    USER_COMMUNICATION_SOURCE,
    USER_COMMUNICATION_TYPE,
    DefaultActionSelectionPolicy,
    Intent,
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


def _user_comm(text: str = "Hello", salience: float = 0.5) -> tuple[str, Event]:
    return (
        "u1",
        _event(
            USER_COMMUNICATION_SOURCE,
            USER_COMMUNICATION_TYPE,
            {"text": text, "source_label": "operator"},
            salience=salience,
        ),
    )


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


def test_inhibited_snapshot_with_proposal_returns_empty_intents_and_inhibited_outcome():
    v = Volition(policy=NousProposalSource(lambda s: []))
    snap = _snapshot([_proposal("p1", "think")], inhibited=True)
    assert v.select(snap) == []
    outcomes = v.proposal_outcomes(snap)
    assert len(outcomes) == 1
    assert outcomes[0] == {
        "proposal_id": "p1",
        "realized": False,
        "reason": "inhibited",
    }


def test_snapshot_without_proposal_produces_no_intent_and_no_outcome():
    v = Volition(policy=NousProposalSource(lambda s: []))
    snap = _snapshot([_soma_report()])
    assert v.select(snap) == []
    assert v.proposal_outcomes(snap) == []


def test_conscious_think_proposal_emits_think_intent_from_nous():
    v = Volition(policy=NousProposalSource(lambda s: []))
    snap = _snapshot([_soma_report(), _proposal("p1", "think")])
    intents = v.select(snap)
    assert len(intents) == 1
    intent = intents[0]
    assert intent.kind == THINK
    assert intent.origin == "nous"
    assert intent.about
    assert intent.entry_id == "s1"
    assert v.proposal_outcomes(snap) == [
        {"proposal_id": "p1", "realized": True, "reason": "realized"}
    ]


class _Clock:
    def __init__(self, start: float = 0.0) -> None:
        self.t = start

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_second_think_within_refractory_is_refractory():
    clock = _Clock()
    source = NousProposalSource(lambda s: [], clock=clock)
    v = Volition(policy=source)

    snap1 = _snapshot([_soma_report(), _proposal("p1", "think")])
    assert v.select(snap1)
    assert v.proposal_outcomes(snap1)[0]["reason"] == "realized"

    # Clear the in-flight guard with the entity's own internal speech, but stay
    # inside the refractory window.
    clock.advance(1.0)
    snap2 = _snapshot([_own_internal_speech(), _soma_report(), _proposal("p2", "think")])
    assert v.select(snap2) == []
    assert v.proposal_outcomes(snap2)[0]["reason"] == "refractory"


def test_inner_think_in_flight_declines_think():
    class Inner:
        think_in_flight = True

        def __call__(self, snapshot: WorkspaceSnapshot) -> list[Intent]:
            return []

    v = Volition(policy=NousProposalSource(Inner()))
    snap = _snapshot([_soma_report(), _proposal("p1", "think")])
    assert v.select(snap) == []
    assert v.proposal_outcomes(snap)[0]["reason"] == "in_flight"


def test_inner_speak_supersedes_speak_proposal():
    v = Volition(policy=NousProposalSource(lambda s: [Intent(kind=SPEAK, about="hi")]))
    snap = _snapshot([_soma_report(), _proposal("p1", "speak")])
    intents = v.select(snap)
    assert len(intents) == 1
    assert intents[0].kind == SPEAK
    assert intents[0].origin is None
    assert v.proposal_outcomes(snap)[0]["reason"] == "superseded"


def test_self_response_when_only_own_speech_accompanies_proposal():
    v = Volition(policy=NousProposalSource(lambda s: []))
    snap = _snapshot([_own_speech(), _proposal("p1", "think")])
    assert v.select(snap) == []
    assert v.proposal_outcomes(snap)[0]["reason"] == "self_response"


def test_speak_self_response_when_only_own_speech_accompanies_proposal():
    v = Volition(policy=NousProposalSource(lambda s: []))
    snap = _snapshot([_own_speech(), _proposal("p1", "speak")])
    assert v.select(snap) == []
    assert v.proposal_outcomes(snap)[0]["reason"] == "self_response"


def test_rest_proposal_emits_rest_intent_without_signature():
    class FakeSigner:
        def sign(self, **kwargs) -> tuple[str, int, str]:
            return ("run", 0, "sig")

    clock = _Clock()
    v = Volition(policy=NousProposalSource(lambda s: [], clock=clock), signer=FakeSigner())
    # Rest is refractory from construction until the minimum interval passes.
    clock.advance(1800.0)
    snap = _snapshot([_soma_report(), _proposal("p1", "rest")])
    intents = v.select(snap)
    assert len(intents) == 1
    assert intents[0].kind == REST
    assert intents[0].about == "rest"
    assert intents[0].origin == "nous"
    assert intents[0].proposal_id == "p1"
    assert intents[0].sig is None
    # Rest outcomes are forwarded to Hypnos; realization is decided there.
    assert v.proposal_outcomes(snap)[0] == {
        "proposal_id": "p1",
        "realized": False,
        "reason": "forwarded",
    }


def test_drive_actions_false_records_disabled_and_emits_no_intent():
    v = Volition(policy=NousProposalSource(lambda s: [], drive_actions=False))
    snap = _snapshot([_soma_report(), _proposal("p1", "think")])
    assert v.select(snap) == []
    outcomes = v.proposal_outcomes(snap)
    assert outcomes[0] == {
        "proposal_id": "p1",
        "realized": False,
        "reason": "disabled",
    }


def test_drive_actions_false_on_inhibited_snapshot_records_disabled():
    source = NousProposalSource(lambda s: [], drive_actions=False)
    snap = _snapshot([_proposal("p1", "think")], inhibited=True)
    source.observe_inhibited(snap)
    outcomes = source.proposal_outcomes(snap)
    assert len(outcomes) == 1
    assert outcomes[0]["reason"] == "disabled"


def test_run_volition_publishes_outcome_but_no_intent_on_inhibited_snapshot():
    class FakeBus:
        def __init__(self) -> None:
            self.events: list[Event] = []

        async def publish(self, event: Event) -> None:
            self.events.append(event)

    bus = FakeBus()
    v = Volition(policy=NousProposalSource(lambda s: []))
    snap = _snapshot([_proposal("p1", "think")], inhibited=True)

    class FakeCycle:
        _tick_index = 1

        def __init__(self) -> None:
            self._volition = v
            self._bus = bus

        def _now(self) -> datetime:
            return datetime.now(timezone.utc)

    fake = FakeCycle()
    asyncio.run(CognitiveCycle._run_volition(fake, snap))

    out_events = [e for e in bus.events if e.type.startswith("intent.")]
    feedback_events = [e for e in bus.events if e.type == "volition.proposal_outcome"]
    assert out_events == []
    # The bus maps a source to "<source>.out": nothing may land on volition.out
    # on an inhibited snapshot, so the outcome must come from its own source.
    from kaine.bus.schema import module_stream

    assert not [e for e in bus.events if module_stream(e.source) == "volition.out"]
    assert len(feedback_events) == 1
    assert feedback_events[0].source == "volition_feedback"
    assert module_stream(feedback_events[0].source) == "volition_feedback.out"
    assert feedback_events[0].salience == 0.0
    assert feedback_events[0].payload == {
        "proposal_id": "p1",
        "realized": False,
        "reason": "inhibited",
    }


def test_lingua_ignores_rest_intent():
    class FakeLingua:
        def __init__(self) -> None:
            self._gen_task = None
            self.calls: list[tuple[str, ...]] = []

        async def _settle_gen_task(self) -> None:
            self.calls.append(("settle",))

        async def _realize_intent(self, kind: str, about: str) -> None:
            self.calls.append(("realize", kind, about))

    fake = FakeLingua()
    rest_event = _event(
        "volition",
        "intent.rest",
        {"kind": "rest", "about": "rest", "origin": "nous"},
    )
    asyncio.run(Lingua._dispatch_intent(fake, rest_event))
    assert fake.calls == []


def test_default_policy_speak_dropped_while_source_speak_guard_armed():
    # Regression (N1): a realized Nous speak must arm the WRAPPED policy's
    # guard, not a source-side guard that drops already-decided inner intents.
    # The inner guard clears by its own 48 s timeout; a user reply after that
    # is answered and no replies are permanently lost.
    clock = _Clock()
    inner = DefaultActionSelectionPolicy(clock=clock, operator_sources=["operator"])
    source = NousProposalSource(inner, clock=clock, speak_refractory_s=8.0)
    v = Volition(policy=source)

    # t=0: a Nous speak proposal is realized; the inner policy's speak guard
    # is armed externally.
    snap1 = _snapshot(
        [
            ("s1", _event("soma", "soma.report", {"wellness": 0.6}, salience=0.6)),
            _proposal("p1", "speak", preference=0.9),
        ]
    )
    intents1 = v.select(snap1)
    assert len(intents1) == 1
    assert intents1[0].kind == SPEAK
    assert intents1[0].origin == "nous"

    # t=40: a user utterance would normally make the default policy speak, but
    # the inner policy's own guard is still armed from the Nous speak at t=0.
    # With the old bug the inner intent was dropped *after* arming that guard,
    # leaving a ghost guard until t=88.
    clock.advance(40.0)
    snap2 = _snapshot([_user_comm()])
    assert v.select(snap2) == []

    # t=49: the inner guard has timed out at t=48; the user reply is answered.
    clock.advance(9.0)
    snap3 = _snapshot([_user_comm()])
    intents3 = v.select(snap3)
    assert len(intents3) == 1
    assert intents3[0].kind == SPEAK
    assert intents3[0].origin is None

    # After the original Nous guard times out, the system is responsive through
    # t=88. We clear the guard between replies by simulating own output.
    for t in [48.0, 60.0, 88.0]:
        clock.t = t
        v.select(_snapshot([_own_speech()]))
        snap = _snapshot([_user_comm(f"hello-{t}")])
        intents = v.select(snap)
        assert len(intents) == 1, f"user reply lost at t={t}"
        assert intents[0].kind == SPEAK


def test_report_policy_think_dropped_while_source_think_guard_armed():
    # Regression: a realized Nous think/speak now arms the report policy's own
    # guard and refractory via note_external_intent, so the next report intent
    # of that kind is declined by the wrapped policy itself.
    clock = _Clock()
    inner = SelfInitiatedReportPolicy(
        report_threshold=0.8,
        think_threshold=0.45,
        clock=clock,
    )
    source = NousProposalSource(inner, clock=clock, think_refractory_s=3.0)
    v = Volition(policy=source)

    # Tick 1: the soma report is below the think threshold, so the Nous think
    # proposal is realized. This arms the inner think guard and stamps the
    # report policy's think refractory.
    snap1 = _snapshot(
        [
            ("s1", _event("soma", "soma.report", {"wellness": 0.2}, salience=0.2)),
            _proposal("p1", "think", preference=0.9),
        ]
    )
    intents1 = v.select(snap1)
    assert len(intents1) == 1
    assert intents1[0].kind == THINK
    assert intents1[0].origin == "nous"
    assert v.proposal_outcomes(snap1)[0]["reason"] == "realized"

    # Tick 2: the report now crosses the think threshold, but the report
    # policy's own in-flight guard and refractory block a new think.
    clock.advance(0.3)
    snap2 = _snapshot(
        [("s2", _event("soma", "soma.report", {"wellness": 0.6}, salience=0.6))]
    )
    assert v.select(snap2) == []


def test_report_policy_speak_refractory_after_nous_speak():
    # A realized Nous speak sets the report policy's last-speak-at refractory;
    # after the in-flight guard is cleared, the refractory still suppresses a
    # report speak until the interval passes.
    clock = _Clock()
    inner = SelfInitiatedReportPolicy(
        report_threshold=0.5,
        think_threshold=0.45,
        clock=clock,
        speak_refractory_s=8.0,
    )
    source = NousProposalSource(inner, clock=clock, speak_refractory_s=8.0)
    v = Volition(policy=source)

    # Tick 1: the report is below both report bars, so the Nous speak proposal
    # is realized rather than superseded by a report speak.
    snap1 = _snapshot(
        [
            ("s1", _event("soma", "soma.report", {"wellness": 0.3}, salience=0.3)),
            _proposal("p1", "speak", preference=0.9),
        ]
    )
    intents1 = v.select(snap1)
    assert len(intents1) == 1
    assert intents1[0].kind == SPEAK
    assert intents1[0].origin == "nous"
    assert v.proposal_outcomes(snap1)[0]["reason"] == "realized"

    # Clear the in-flight guard with own external speech, but stay inside the
    # speak refractory window.
    clock.advance(1.0)
    v.select(_snapshot([_own_speech()]))
    assert not inner.speak_in_flight

    snap2 = _snapshot(
        [("s1", _event("soma", "soma.report", {"wellness": 0.6}, salience=0.6))]
    )
    # The speak refractory holds; the report policy may still think instead.
    assert SPEAK not in [i.kind for i in v.select(snap2)]

    # Past the refractory window, the report speak is emitted.
    clock.advance(8.0)
    snap3 = _snapshot(
        [("s1", _event("soma", "soma.report", {"wellness": 0.6}, salience=0.6))]
    )
    intents3 = v.select(snap3)
    assert len(intents3) == 1
    assert intents3[0].kind == SPEAK
    assert intents3[0].origin is None


def test_think_guard_clears_on_own_internal_speech_without_proposal():
    clock = _Clock()
    source = NousProposalSource(lambda s: [], clock=clock, think_refractory_s=3.0)
    v = Volition(policy=source)

    snap1 = _snapshot([_soma_report(), _proposal("p1", "think")])
    assert v.select(snap1)[0].kind == THINK

    # The entity's own internal speech appears on a snapshot with no proposal;
    # this clears the think guard.
    clock.advance(1.0)
    snap2 = _snapshot([_own_internal_speech()])
    assert v.select(snap2) == []

    # Enough time has passed for the refractory window, so the next think
    # proposal is realized.
    clock.advance(4.0)
    snap3 = _snapshot([_soma_report(), _proposal("p2", "think")])
    intents = v.select(snap3)
    assert len(intents) == 1
    assert intents[0].kind == THINK
    assert v.proposal_outcomes(snap3)[0]["reason"] == "realized"


def test_think_guard_clears_after_timeout_on_no_proposal_snapshot():
    clock = _Clock()
    source = NousProposalSource(lambda s: [], clock=clock, think_refractory_s=3.0)
    v = Volition(policy=source)

    snap1 = _snapshot([_soma_report(), _proposal("p1", "think")])
    assert v.select(snap1)[0].kind == THINK

    # No proposal for longer than the guard timeout; the guard is cleared.
    clock.advance(50.0)
    snap2 = _snapshot([_soma_report()])
    assert v.select(snap2) == []

    # The refractory window has also passed, so the next proposal is realized.
    clock.advance(1.0)
    snap3 = _snapshot([_soma_report(), _proposal("p2", "think")])
    intents = v.select(snap3)
    assert len(intents) == 1
    assert intents[0].kind == THINK


def test_speak_referent_skips_entitys_own_external_speech():
    source = NousProposalSource(lambda s: [])
    v = Volition(policy=source)

    own = _own_speech()  # most salient, but must not be the referent
    soma = ("s1", _event("soma", "soma.report", {"wellness": 0.6}, salience=0.4))
    snap = _snapshot([own, soma, _proposal("p1", "speak")])
    intents = v.select(snap)
    assert len(intents) == 1
    assert intents[0].kind == SPEAK
    assert intents[0].entry_id == "s1"


def test_rest_proposal_refractory_and_later_realized():
    clock = _Clock()
    source = NousProposalSource(
        lambda s: [], clock=clock, time_fn=clock, rest_min_interval_s=1800.0
    )
    v = Volition(policy=source)

    # Right after construction, rest is refractory (seeded at construction).
    snap1 = _snapshot([_proposal("p1", "rest")])
    assert v.select(snap1) == []
    assert v.proposal_outcomes(snap1)[0]["reason"] == "refractory"

    clock.advance(1800.0)
    snap2 = _snapshot([_proposal("p2", "rest")])
    intents = v.select(snap2)
    assert len(intents) == 1
    assert intents[0].kind == REST
    assert intents[0].proposal_id == "p2"
    assert v.proposal_outcomes(snap2)[0] == {
        "proposal_id": "p2",
        "realized": False,
        "reason": "forwarded",
    }


def test_two_proposals_most_salient_first_supersedes_second():
    source = NousProposalSource(lambda s: [])
    v = Volition(policy=source)

    # p1 is more salient than p2, so p1 is considered and p2 is superseded.
    p1 = _proposal("p1", "think", preference=0.9, salience=0.9)
    p2 = _proposal("p2", "think", preference=0.5, salience=0.5)
    snap = _snapshot([_soma_report(), p1, p2])
    intents = v.select(snap)
    assert len(intents) == 1
    assert intents[0].kind == THINK

    outcomes = v.proposal_outcomes(snap)
    by_id = {o["proposal_id"]: o["reason"] for o in outcomes}
    assert by_id == {"p1": "realized", "p2": "superseded"}


def test_plain_callable_fallback_filters_inner_intents():
    # A wrapped policy without note_external_intent keeps the source's local
    # guard and intent filtering.
    clock = _Clock()

    def inner(s):
        # Speaks only on a quiet tick, so the proposal is not superseded.
        return [] if s.selected_events else [Intent(kind=SPEAK, about="inner")]

    source = NousProposalSource(inner, clock=clock, speak_refractory_s=8.0)
    v = Volition(policy=source)

    snap1 = _snapshot([_soma_report(), _proposal("p1", "speak")])
    intents1 = v.select(snap1)
    assert len(intents1) == 1
    assert intents1[0].origin == "nous"

    clock.advance(1.0)
    snap2 = _snapshot([])
    intents2 = v.select(snap2)
    assert intents2 == []


def test_default_policy_note_external_intent_arms_speak_guard():
    clock = _Clock()
    policy = DefaultActionSelectionPolicy(clock=clock)
    assert not policy.speak_in_flight
    policy.note_external_intent(SPEAK)
    assert policy.speak_in_flight
    # The default policy only guards speak; think is a no-op.
    policy.note_external_intent(THINK)
    assert policy.speak_in_flight


def test_drive_policy_note_external_intent_arms_speak_and_think_guards():
    clock = _Clock()
    policy = DriveBiasedActionSelectionPolicy(clock=clock)
    assert not policy.speak_in_flight
    assert not policy.think_in_flight
    policy.note_external_intent(SPEAK)
    assert policy.speak_in_flight
    policy.note_external_intent(THINK)
    assert policy.think_in_flight


def test_report_policy_note_external_intent_arms_guard_and_refractory():
    clock = _Clock()
    policy = SelfInitiatedReportPolicy(clock=clock, speak_refractory_s=8.0)
    assert not policy.speak_in_flight
    policy.note_external_intent(SPEAK)
    assert policy.speak_in_flight
    assert policy._last_speak_at == 0.0
    # Novelty signature must not be touched.
    assert policy._last_report_sig is None
    policy.note_external_intent(THINK)
    assert policy.think_in_flight
    assert policy._last_think_at == 0.0


def test_wrapped_policy_never_sees_proposals():
    # A salient proposal must not win the report policy's signal: the report
    # policy decides on the coalition without it, so it never thinks about the
    # proposal itself and decides the same way with drive_actions on or off.
    def run(drive_actions: bool):
        clock = _Clock()
        inner = SelfInitiatedReportPolicy(
            report_threshold=0.8, think_threshold=0.45, clock=clock
        )
        v = Volition(
            policy=NousProposalSource(inner, clock=clock, drive_actions=drive_actions)
        )
        snap = _snapshot(
            [
                ("s1", _event("soma", "soma.report", {"wellness": 0.2}, salience=0.2)),
                _proposal("p1", "think", preference=0.9, salience=0.9),
            ]
        )
        return v.select(snap), v.proposal_outcomes(snap)

    on_intents, on_outcomes = run(True)
    assert [(i.kind, i.origin, i.entry_id) for i in on_intents] == [(THINK, "nous", "s1")]
    assert on_outcomes[0]["reason"] == "realized"

    off_intents, off_outcomes = run(False)
    assert off_intents == []
    assert off_outcomes[0]["reason"] == "disabled"
