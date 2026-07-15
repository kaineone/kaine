# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The self-initiated report policy: surprise-gated, refractory, non-chatbot."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.schema import validate_event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.report_policy import SelfInitiatedReportPolicy
from kaine.workspace.volition import (
    OWN_EXTERNAL_SPEECH_TYPE,
    SPEAK,
    THINK,
)


def _kinds(intents):
    return [i.kind for i in intents]


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _ev(source: str, type_: str = None):
    return validate_event(
        source=source,
        type=type_ or f"{source}.report",
        payload={"v": 1},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


def _snap(members, *, inhibited=False):
    """members: list of (entry_id, source, score)."""
    selected = [(eid, _ev(src)) for eid, src, _ in members]
    scores = {eid: score for eid, _, score in members}
    return WorkspaceSnapshot(
        tick_index=1,
        selected_events=selected,
        inhibited=inhibited,
        salience_scores=scores,
    )


def _policy(clock=None, **kw):
    return SelfInitiatedReportPolicy(
        report_threshold=0.6,
        think_threshold=0.45,
        speak_refractory_s=8.0,
        think_refractory_s=3.0,
        clock=clock,
        **kw,
    )


def test_high_surprise_reports_once():
    p = _policy(_Clock())
    intents = p([_snap([("e1", "soma", 0.8)])][0])
    assert [i.kind for i in intents] == [SPEAK]


def test_self_initiated_no_utterance_needed():
    # Coalition is only the entity's own predictive signals — no audition/
    # transcription anywhere — and it still speaks. Report is self-initiated.
    p = _policy(_Clock())
    intents = p(_snap([("e1", "soma", 0.9), ("e2", "chronos", 0.7)]))
    assert any(i.kind == SPEAK for i in intents)


def test_conscious_but_below_think_is_silent():
    # Above the (0.35-ish) conscious threshold but below the think bar → nothing.
    p = _policy(_Clock())
    assert p(_snap([("e1", "soma", 0.40)])) == []


def test_moderate_surprise_thinks_not_speaks():
    p = _policy(_Clock())
    intents = p(_snap([("e1", "soma", 0.50)]))  # >= think(0.45), < report(0.6)
    assert [i.kind for i in intents] == [THINK]


def test_inhibited_yields_nothing():
    p = _policy(_Clock())
    assert p(_snap([("e1", "soma", 0.9)], inhibited=True)) == []


def test_refractory_suppresses_second_speak():
    clk = _Clock()
    p = _policy(clk)
    assert _kinds(p(_snap([("e1", "soma", 0.9)]))) == [SPEAK]
    p.mark_realized()  # clear in-flight so only refractory is under test
    clk.t = 2.0  # < 8s speak refractory
    assert SPEAK not in _kinds(p(_snap([("e2", "chronos", 0.9)])))
    clk.t = 9.0  # past refractory
    assert SPEAK in _kinds(p(_snap([("e3", "topos", 0.9)])))


def test_one_in_flight_prevents_backlog():
    clk = _Clock()
    p = _policy(clk)
    assert SPEAK in _kinds(p(_snap([("e1", "soma", 0.9)])))  # speaks, arms guard
    clk.t = 100.0  # well past refractory, but guard still armed
    # No queued external report while a prior speak is in flight (think may go on).
    assert SPEAK not in _kinds(p(_snap([("e2", "chronos", 0.9)])))


def test_repeated_content_not_re_reported():
    clk = _Clock()
    p = _policy(clk)
    assert _kinds(p(_snap([("e1", "soma", 0.9)]))) == [SPEAK]
    p.mark_realized()
    clk.t = 20.0  # past refractory
    # Same content signature (soma.report) → speak suppressed by the novelty guard.
    assert SPEAK not in _kinds(p(_snap([("e2", "soma", 0.9)])))
    clk.t = 40.0
    # A different source crosses the report bar and does speak.
    assert SPEAK in _kinds(p(_snap([("e3", "topos", 0.9)])))


def test_own_speech_is_not_reported_and_clears_guard():
    clk = _Clock()
    p = _policy(clk)
    p(_snap([("e1", "soma", 0.9)]))  # arms speak guard
    clk.t = 100.0
    # The entity's own external speech becoming conscious clears the guard and is
    # not itself reported (source lingua / type external_speech).
    own = WorkspaceSnapshot(
        tick_index=2,
        selected_events=[("s1", _ev("lingua", OWN_EXTERNAL_SPEECH_TYPE))],
        salience_scores={"s1": 0.9},
    )
    assert SPEAK not in _kinds(p(own))
    assert p.speak_in_flight is False


# --- interrupt threshold (interruptible-utterance) ----------------------------


def _interrupting(clock=None):
    return SelfInitiatedReportPolicy(
        report_threshold=0.6,
        think_threshold=0.45,
        interrupt_threshold=0.9,
        speak_refractory_s=8.0,
        think_refractory_s=3.0,
        clock=clock,
    )


def test_interrupt_threshold_must_exceed_report_threshold():
    with pytest.raises(ValueError):
        SelfInitiatedReportPolicy(report_threshold=0.6, interrupt_threshold=0.5)
    with pytest.raises(ValueError):
        # Must be STRICTLY above the report bar.
        SelfInitiatedReportPolicy(report_threshold=0.6, interrupt_threshold=0.6)
    with pytest.raises(ValueError):
        SelfInitiatedReportPolicy(report_threshold=0.6, interrupt_threshold=1.5)


def test_urgent_surprise_interrupts_in_flight_speak():
    clk = _Clock()
    p = _interrupting(clk)
    # Arm the in-flight guard with an ordinary report (>=report, <interrupt).
    first = p(_snap([("e1", "soma", 0.7)]))
    assert _kinds(first) == [SPEAK]
    assert first[0].interrupt is False
    assert p.speak_in_flight is True
    # A more salient, DIFFERENT-content coalition crosses the interrupt bar while
    # the utterance is in flight → a preempting, interrupt-marked speak.
    second = p(_snap([("e2", "topos", 0.95)]))
    assert _kinds(second) == [SPEAK]
    assert second[0].interrupt is True
    # Guard stays armed (re-armed for the redirected utterance).
    assert p.speak_in_flight is True


def test_interrupt_bypasses_refractory():
    clk = _Clock()
    p = _interrupting(clk)
    assert _kinds(p(_snap([("e1", "soma", 0.7)]))) == [SPEAK]
    clk.t = 1.0  # well within the 8s speak refractory
    second = p(_snap([("e2", "topos", 0.95)]))
    assert _kinds(second) == [SPEAK] and second[0].interrupt is True


def test_below_interrupt_reportworthy_does_not_preempt():
    clk = _Clock()
    p = _interrupting(clk)
    assert _kinds(p(_snap([("e1", "soma", 0.7)]))) == [SPEAK]  # arms in-flight
    # Clears report bar (0.7 >= 0.6) but not the interrupt bar (< 0.9), different
    # content. No preempting speak — the current utterance is allowed to finish.
    second = p(_snap([("e2", "topos", 0.7)]))
    assert SPEAK not in _kinds(second)
    assert all(not i.interrupt for i in second)


def test_same_content_does_not_interrupt():
    clk = _Clock()
    p = _interrupting(clk)
    assert _kinds(p(_snap([("e1", "soma", 0.7)]))) == [SPEAK]  # sig = soma
    # Same content signature crosses the interrupt bar → do not interrupt to say
    # the same thing (novelty guard holds).
    second = p(_snap([("e2", "soma", 0.95)]))
    assert all(not i.interrupt for i in second)


def test_no_interrupt_when_nothing_in_flight():
    clk = _Clock()
    p = _interrupting(clk)
    # Crosses the interrupt bar but no speak is in flight → an ordinary (not
    # interrupt-marked) report, since there is nothing to preempt.
    out = p(_snap([("e1", "soma", 0.95)]))
    assert _kinds(out) == [SPEAK]
    assert out[0].interrupt is False


def test_default_policy_never_interrupts():
    # No interrupt_threshold configured → opt-out: an in-flight utterance always
    # runs to completion, exactly as before this change.
    clk = _Clock()
    p = _policy(clk)
    assert _kinds(p(_snap([("e1", "soma", 0.9)]))) == [SPEAK]  # in flight
    clk.t = 100.0
    second = p(_snap([("e2", "topos", 0.99)]))  # would-be urgent
    assert all(not i.interrupt for i in second)
    assert SPEAK not in _kinds(second)
