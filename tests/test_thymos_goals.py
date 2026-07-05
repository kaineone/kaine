# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.thymos.goals import Goal, GoalLedger, GoalState


def test_add_returns_goal_with_id():
    ledger = GoalLedger()
    goal = ledger.add("walk the perimeter", priority=0.7)
    assert goal.id
    assert goal.description == "walk the perimeter"
    assert goal.priority == 0.7
    assert goal.state == GoalState.ACTIVE


def test_invalid_priority_rejected():
    ledger = GoalLedger()
    with pytest.raises(ValueError):
        ledger.add("x", priority=1.5)
    with pytest.raises(ValueError):
        ledger.add("x", priority=-0.1)


def test_empty_description_rejected():
    ledger = GoalLedger()
    with pytest.raises(ValueError):
        ledger.add("")
    with pytest.raises(ValueError):
        ledger.add("   ")


def test_complete_updates_state():
    ledger = GoalLedger()
    g = ledger.add("test")
    completed = ledger.complete(g.id)
    assert completed.state == GoalState.COMPLETED


def test_abandon_updates_state():
    ledger = GoalLedger()
    g = ledger.add("test")
    abandoned = ledger.abandon(g.id)
    assert abandoned.state == GoalState.ABANDONED


def test_unknown_id_raises():
    ledger = GoalLedger()
    with pytest.raises(KeyError):
        ledger.complete("nope")
    with pytest.raises(KeyError):
        ledger.abandon("nope")


def test_active_excludes_completed_and_abandoned():
    ledger = GoalLedger()
    a = ledger.add("a")
    b = ledger.add("b")
    c = ledger.add("c")
    ledger.complete(b.id)
    ledger.abandon(c.id)
    actives = ledger.active()
    assert len(actives) == 1
    assert actives[0].id == a.id


def test_relevance_for_overlapping_event():
    ledger = GoalLedger()
    ledger.add("explore the garden", priority=0.8)
    r = ledger.relevance("soma report from the garden module")
    assert r > 0


def test_relevance_zero_for_no_overlap():
    ledger = GoalLedger()
    ledger.add("walk the perimeter")
    assert ledger.relevance("xyz qrt") == 0.0


def test_relevance_uses_completed_goal_excluded():
    ledger = GoalLedger()
    g = ledger.add("explore the garden", priority=1.0)
    ledger.complete(g.id)
    assert ledger.relevance("explore garden activity") == 0.0


def test_len_counts_all_goals():
    ledger = GoalLedger()
    ledger.add("a")
    ledger.add("b")
    assert len(ledger) == 2


def test_relevance_weighted_by_priority():
    ledger = GoalLedger()
    ledger.add("rust", priority=0.2)
    low = ledger.relevance("rust experiment")
    ledger2 = GoalLedger()
    ledger2.add("rust", priority=1.0)
    high = ledger2.relevance("rust experiment")
    assert high > low
