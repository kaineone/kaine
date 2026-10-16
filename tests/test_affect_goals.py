# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.affect.goals import GoalLedger, GoalState


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
    r = ledger.relevance("interoception report from the garden module")
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


def test_add_with_drive_and_likelihood():
    ledger = GoalLedger()
    g = ledger.add("relieve hunger", drive="hunger", likelihood=0.8)
    assert g.drive == "hunger"
    assert g.likelihood == 0.8


def test_invalid_likelihood_rejected():
    ledger = GoalLedger()
    with pytest.raises(ValueError):
        ledger.add("x", likelihood=1.5)
    with pytest.raises(ValueError):
        ledger.add("x", likelihood=-0.1)
    with pytest.raises(ValueError):
        ledger.add("x", likelihood=float("nan"))


def test_empty_drive_rejected():
    ledger = GoalLedger()
    with pytest.raises(ValueError):
        ledger.add("x", drive="")


def test_active_for_drive():
    ledger = GoalLedger()
    g = ledger.add("relieve hunger", drive="hunger", likelihood=0.8)
    assert ledger.active_for_drive("hunger") == g
    ledger.complete(g.id)
    assert ledger.active_for_drive("hunger") is None


def test_set_likelihood_updates_active_goal():
    ledger = GoalLedger()
    g = ledger.add("test", likelihood=0.5)
    updated = ledger.set_likelihood(g.id, 0.9)
    assert updated.likelihood == 0.9
    assert ledger.get(g.id).likelihood == 0.9


def test_set_likelihood_unknown_id_raises():
    ledger = GoalLedger()
    with pytest.raises(KeyError):
        ledger.set_likelihood("nope", 0.5)


def test_set_likelihood_invalid_value_raises():
    ledger = GoalLedger()
    g = ledger.add("test")
    with pytest.raises(ValueError):
        ledger.set_likelihood(g.id, 1.2)


def test_set_likelihood_completed_unchanged():
    ledger = GoalLedger()
    g = ledger.add("test", likelihood=0.5)
    completed = ledger.complete(g.id)
    updated = ledger.set_likelihood(g.id, 0.9)
    assert updated is completed
    assert updated.likelihood == 0.5


def test_clear_active_removes_only_active_and_preserves_counts():
    counter = {"t": 0.0}

    def clock():
        counter["t"] += 1.0
        return counter["t"]

    ledger = GoalLedger(clock=clock)
    a = ledger.add("active one")
    b = ledger.add("active two")
    c = ledger.add("complete me")
    d = ledger.add("abandon me")
    ledger.complete(c.id)
    ledger.abandon(d.id)
    assert ledger.outcome_counts() == (1, 1)
    removed = ledger.clear_active()
    assert ledger.outcome_counts() == (1, 1)
    assert len(removed) == 2
    assert {g.id for g in removed} == {a.id, b.id}
    assert ledger.active() == []
    assert len(ledger.all()) == 2
    assert ledger.get(c.id).state == GoalState.COMPLETED
    assert ledger.get(d.id).state == GoalState.ABANDONED


def test_outcome_counts_counts_transitions_once():
    ledger = GoalLedger()
    g = ledger.add("test")
    ledger.complete(g.id)
    assert ledger.outcome_counts() == (1, 0)
    ledger.complete(g.id)
    assert ledger.outcome_counts() == (1, 0)


def test_pruning_finished_goals(monkeypatch):
    counter = {"t": 0.0}

    def clock():
        counter["t"] += 1.0
        return counter["t"]

    monkeypatch.setattr(GoalLedger, "MAX_FINISHED", 3)
    ledger = GoalLedger(clock=clock)
    goals = [ledger.add(f"goal {i}") for i in range(5)]
    for g in goals:
        ledger.complete(g.id)
    finished = [g for g in ledger.all() if g.state == GoalState.COMPLETED]
    assert len(finished) == 3
    assert [g.description for g in finished] == ["goal 2", "goal 3", "goal 4"]
    assert ledger.outcome_counts() == (5, 0)


def test_round_trip_preserves_drive_likelihood_and_counters(monkeypatch):
    counter = {"t": 0.0}

    def clock():
        counter["t"] += 1.0
        return counter["t"]

    monkeypatch.setattr(GoalLedger, "MAX_FINISHED", 3)
    ledger = GoalLedger(clock=clock)
    g = ledger.add("relieve hunger", drive="hunger", likelihood=0.8)
    goals = [ledger.add(f"goal {i}") for i in range(5)]
    for h in goals:
        ledger.complete(h.id)
    ledger.abandon(g.id)
    data = ledger.to_dict()
    restored = GoalLedger.from_dict(data)
    assert restored.outcome_counts() == (5, 1)
    assert restored.get(g.id).drive == "hunger"
    assert restored.get(g.id).likelihood == 0.8
    assert restored.get(g.id).state == GoalState.ABANDONED
    # The abandoned goal is finished too, so the cap of 3 holds it and the two
    # most recently completed goals.
    assert len(restored.all()) == 3


def test_old_format_load():
    data = {
        "goals": [
            {
                "id": "a",
                "description": "active goal",
                "priority": 0.5,
                "state": "active",
                "created_at": 1.0,
                "completed_at": None,
            },
            {
                "id": "b",
                "description": "completed goal",
                "priority": 0.5,
                "state": "completed",
                "created_at": 2.0,
                "completed_at": 3.0,
            },
        ]
    }
    ledger = GoalLedger.from_dict(data)
    assert ledger.get("a").drive is None
    assert ledger.get("a").likelihood is None
    assert ledger.outcome_counts() == (1, 0)


def test_load_dict_drops_invalid_drive_and_likelihood_and_keeps_others():
    data = {
        "goals": [
            {
                "id": "good",
                "description": "valid goal",
                "priority": 0.5,
                "state": "active",
                "created_at": 1.0,
                "completed_at": None,
                "drive": "hunger",
                "likelihood": 0.7,
            },
            {
                "id": "bad_likelihood",
                "description": "bad likelihood",
                "priority": 0.5,
                "state": "active",
                "created_at": 2.0,
                "completed_at": None,
                "likelihood": 2.0,
            },
            {
                "id": "bad_drive",
                "description": "bad drive",
                "priority": 0.5,
                "state": "active",
                "created_at": 3.0,
                "completed_at": None,
                "drive": "",
            },
        ]
    }
    ledger = GoalLedger.from_dict(data)
    assert set(ledger._goals.keys()) == {"good"}
    assert ledger.get("good").drive == "hunger"
    assert ledger.get("good").likelihood == 0.7
