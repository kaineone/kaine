# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

from kaine.bus.schema import Event, validate_event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.action_selection import SPEAK, THINK, ActionSelection, Intent
from kaine.workspace.planning_proposals import PlanningProposalSource
from kaine.workspace.report_policy import SelfInitiatedReportPolicy


def _ev(source, type_=None):
    return validate_event(
        source=source,
        type=type_ or f"{source}.report",
        payload={"v": 1},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


def _snap(members, *, inhibited=False):
    selected = [(eid, _ev(src)) for eid, src, _ in members]
    scores = {eid: score for eid, _, score in members}
    return WorkspaceSnapshot(
        tick_index=1,
        selected_events=selected,
        inhibited=inhibited,
        salience_scores=scores,
    )


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _policy(clock, **kw):
    return SelfInitiatedReportPolicy(
        report_threshold=0.6,
        think_threshold=0.45,
        speak_refractory_s=8.0,
        think_refractory_s=3.0,
        clock=clock,
        guard_clock=clock,
        **kw,
    )


def _event(source, type_, payload=None, salience=0.5):
    return Event(
        source=source,
        type=type_,
        payload=payload or {},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _proposal(proposal_id, kind):
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
        ),
    )


def _psnap(events):
    selected = sorted(events, key=lambda item: item[1].salience, reverse=True)
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=selected,
        inhibited=False,
        is_experiential=True,
        salience_scores={eid: ev.salience for eid, ev in selected},
    )


def test_felt_think():
    clock = _Clock()
    policy = _policy(clock, about_style="felt")
    intents = policy(_snap([("e1", "vision", 0.588)]))
    assert len(intents) == 1
    intent = intents[0]
    assert intent.kind == THINK
    assert intent.entry_id == "e1"
    assert intent.about == "Something in what I see stands out noticeably."
    assert intent.about_kind == "felt"
    assert intent.about_values == {
        "source": "vision",
        "type": "vision.report",
        "surprise": 0.588,
    }
    assert intent.to_event_payload()["about_values"] == intent.about_values
    assert not any(ch.isdigit() for ch in intent.about)


def test_felt_speak():
    clock = _Clock()
    policy = _policy(clock, about_style="felt")
    intents = policy(_snap([("e1", "interoception", 0.9)]))
    assert len(intents) == 1
    intent = intents[0]
    assert intent.kind == SPEAK
    assert intent.about == "Something in my body stands out sharply."
    assert intent.about_kind == "felt"


def test_felt_interrupt():
    clock = _Clock()
    policy = _policy(clock, interrupt_threshold=0.8, about_style="felt")
    first = policy(_snap([("e1", "vision", 0.9)]))
    assert len(first) == 1
    assert first[0].kind == SPEAK
    assert first[0].interrupt is False

    second = policy(_snap([("e2", "audition", 0.95)]))
    assert len(second) == 1
    intent = second[0]
    assert intent.kind == SPEAK
    assert intent.interrupt is True
    assert intent.entry_id == "e2"
    assert intent.about == "Something in what I hear stands out sharply."
    assert intent.about_kind == "felt"
    assert intent.about_values == {
        "source": "audition",
        "type": "audition.report",
        "surprise": 0.95,
    }


def test_numeric_unchanged_default_and_explicit():
    clock = _Clock()
    default_policy = _policy(clock)
    intents = default_policy(_snap([("e1", "vision", 0.588)]))
    assert len(intents) == 1
    intent = intents[0]
    assert intent.kind == THINK
    assert intent.about == "vision (surprise=0.588)"
    assert intent.about_kind == "event"
    assert intent.about_values is None
    assert "about_values" not in intent.to_event_payload()

    explicit_clock = _Clock()
    explicit_policy = _policy(explicit_clock, about_style="numeric")
    speak_intents = explicit_policy(_snap([("e1", "interoception", 0.9)]))
    assert len(speak_intents) == 1
    speak = speak_intents[0]
    assert speak.kind == SPEAK
    assert speak.about == "interoception (surprise=0.900)"
    assert speak.about_kind == "event"
    assert speak.about_values is None


def test_invalid_about_style():
    try:
        SelfInitiatedReportPolicy(about_style="loud")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "about_style must be 'numeric' or 'felt'" in str(exc)
        assert "loud" in str(exc)

    try:
        PlanningProposalSource(lambda s: [], about_style="loud")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "about_style must be 'numeric' or 'felt'" in str(exc)
        assert "loud" in str(exc)


def test_intent_about_values_wire_format():
    minimal = Intent(kind="think", about="x")
    payload = minimal.to_event_payload()
    assert "about_values" not in payload

    valued = Intent(kind="think", about="x", about_values={"surprise": 0.5})
    payload = valued.to_event_payload()
    assert payload["about_values"] == {"surprise": 0.5}
    payload["surprise"] = 999
    assert valued.about_values["surprise"] == 0.5


def test_planning_felt():
    sensor = ("s1", _event("interoception", "interoception.report", {"wellness": 0.5}))
    proposal = _proposal("1", THINK)

    felt = ActionSelection(
        policy=PlanningProposalSource(lambda s: [], about_style="felt")
    )
    felt_intents = felt.select(_psnap([sensor, proposal]))
    assert len(felt_intents) == 1
    felt_intent = felt_intents[0]
    assert felt_intent.kind == THINK
    assert felt_intent.origin == "planning"
    assert felt_intent.entry_id == "s1"
    assert felt_intent.about == "Something in my body draws my attention."
    assert felt_intent.about_kind == "felt"

    numeric = ActionSelection(policy=PlanningProposalSource(lambda s: []))
    numeric_intents = numeric.select(_psnap([sensor, proposal]))
    assert len(numeric_intents) == 1
    numeric_intent = numeric_intents[0]
    assert numeric_intent.about == "interoception:interoception.report"
    assert numeric_intent.about_kind == "event"
