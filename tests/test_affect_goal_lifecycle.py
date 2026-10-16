# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Goal generation and obstruction in the affect module (paper A.4)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.affect import Affect
from kaine.modules.affect.appraisal import CategoricalEmotion, classify
from kaine.modules.affect.goals import GoalLedger, GoalState
from kaine.workspace.strategies import dominant_drive


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _snapshot(events=None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=0, selected_events=events or [], inhibited=False)


def _ev(source="interoception", type_="t", salience=0.5, eid="e0", **payload):
    return eid, Event(
        source=source,
        type=type_,
        payload=payload or {"k": "v"},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


DRIVE_SOURCES = {
    "social_drive": frozenset({"audition"}),
    "curiosity": frozenset({"vision"}),
    "boredom": frozenset(),
    "restlessness": frozenset(),
}


async def _goal_events(bus):
    entries = await bus.read("affect.out", last_id="0", count=200)
    return [e for _, e in entries if e.type == "affect.goal"]


@pytest.mark.asyncio
async def test_crossing_creates_one_goal(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    affect.drives.curiosity.own_ends = 1
    affect.drives.curiosity.value = 0.75
    await affect._tick()
    active = affect.goals.active()
    assert len(active) == 1
    g = active[0]
    assert g.drive == "curiosity"
    assert g.state == GoalState.ACTIVE
    assert g.priority == pytest.approx(0.75, abs=0.05)
    assert g.likelihood == pytest.approx(2 / 3)
    events = await _goal_events(bus)
    assert len(events) == 1
    assert events[0].payload["action"] == "added"
    assert events[0].payload["drive"] == "curiosity"


@pytest.mark.asyncio
async def test_no_duplicate_goal_for_active_drive(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    affect.drives.curiosity.value = 0.75
    await affect._tick()
    assert len(affect.goals.active()) == 1
    affect.drives.curiosity._has_fired = False
    t[0] += 0.1
    await affect._tick()
    assert len(affect.goals.active()) == 1
    events = await _goal_events(bus)
    assert len([e for e in events if e.payload["action"] == "added"]) == 1


@pytest.mark.asyncio
async def test_own_response_completes_goal(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    affect.drives.restlessness.value = 0.75
    await affect._tick()
    goal = affect.goals.active_for_drive("restlessness")
    assert goal is not None
    t[0] += 0.1
    intent = Event(
        source="action_selection",
        type="intent.speak",
        payload={},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await affect._handle_peer_event("action_selection.out", intent)
    assert affect.goals.outcome_counts() == (1, 0)
    assert affect.goals.get(goal.id).state == GoalState.COMPLETED
    events = await _goal_events(bus)
    completed = [e for e in events if e.payload["action"] == "completed"]
    assert len(completed) == 1
    assert completed[0].payload["reason"] == "own_response"


@pytest.mark.asyncio
async def test_other_response_abandons_goal(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    affect.drives.social_drive.value = 0.75
    await affect._tick()
    goal = affect.goals.active_for_drive("social_drive")
    assert goal is not None
    t[0] += 0.1
    first = Event(
        source="sequence",
        type="sequence.report",
        payload={"time_since_last_interaction_s": 10.0},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    second = Event(
        source="sequence",
        type="sequence.report",
        payload={"time_since_last_interaction_s": 1.0},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await affect._handle_peer_event("sequence.out", first)
    await affect._handle_peer_event("sequence.out", second)
    assert affect.goals.outcome_counts() == (0, 1)
    assert affect.goals.get(goal.id).state == GoalState.ABANDONED
    events = await _goal_events(bus)
    abandoned = [e for e in events if e.payload["action"] == "abandoned"]
    assert len(abandoned) == 1
    assert abandoned[0].payload["reason"] == "without_response"


@pytest.mark.asyncio
async def test_stall_timer_abandons_and_resets_on_dip(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], goal_stall_s=5.0)

    # Straight stall: drive stays high until abandonment.
    affect.drives.curiosity.value = 0.80
    await affect._tick()
    goal = affect.goals.active_for_drive("curiosity")
    assert goal is not None
    for _ in range(6):
        t[0] += 1.0
        affect.drives.curiosity.value = 0.80
        await affect._tick()
    assert affect.goals.get(goal.id).state == GoalState.ABANDONED
    assert affect.goals.outcome_counts() == (0, 1)

    # Reset state and verify a dip below threshold resets the timer.
    affect2 = Affect(bus, clock=lambda: t[0], goal_stall_s=5.0)
    t[0] = 0.0
    affect2.drives.curiosity.value = 0.80
    await affect2._tick()
    goal2 = affect2.goals.active_for_drive("curiosity")
    assert goal2 is not None
    for _ in range(3):
        t[0] += 1.0
        affect2.drives.curiosity.value = 0.80
        await affect2._tick()
    t[0] += 1.0
    affect2.drives.curiosity.value = 0.65
    await affect2._tick()
    t[0] += 1.0
    affect2.drives.curiosity.value = 0.80
    await affect2._tick()
    assert affect2.goals.get(goal2.id).state == GoalState.ACTIVE
    t[0] += 3.0
    affect2.drives.curiosity.value = 0.80
    await affect2._tick()
    assert affect2.goals.get(goal2.id).state == GoalState.ACTIVE
    t[0] += 2.0
    affect2.drives.curiosity.value = 0.80
    await affect2._tick()
    assert affect2.goals.get(goal2.id).state == GoalState.ABANDONED


@pytest.mark.asyncio
async def test_goal_cap_drops_lowest_priority(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], goal_cap=3)
    affect._interaction_seen = True
    drives = [
        ("curiosity", 0.80),
        ("boredom", 0.75),
        ("restlessness", 0.90),
        ("social_drive", 0.71),
    ]
    for name, value in drives:
        t[0] += 0.1
        getattr(affect.drives, name).value = value
        await affect._tick()
    assert len(affect.goals.active()) == 3
    assert affect.goals.active_for_drive("social_drive") is None
    events = await _goal_events(bus)
    caps = [e for e in events if e.payload.get("reason") == "cap"]
    assert len(caps) == 1
    assert caps[0].payload["drive"] == "social_drive"


@pytest.mark.asyncio
async def test_likelihood_fall_and_obstruction(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        goal_response_window_s=10.0,
        goal_likelihood_fall=0.5,
    )
    affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
    affect.drives.curiosity.value = 0.80
    await affect._tick()
    goal = affect.goals.active_for_drive("curiosity")
    assert goal is not None
    assert goal.likelihood == pytest.approx(0.5)

    t[0] += 1.0
    intent = Event(
        source="action_selection",
        type="intent.speak",
        payload={},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await affect._handle_peer_event("action_selection.out", intent)
    for _ in range(21):
        t[0] += 0.5
        affect.drives.curiosity.value = 0.80
        await affect._tick()
    goal = affect.goals.get(goal.id)
    assert goal.likelihood == pytest.approx(0.25)

    affect.drives.curiosity.value = 0.80
    scores = affect._score_snapshot(
        _snapshot([_ev(source="interoception", salience=0.5)])
    )
    assert scores.goal_significance == pytest.approx(-0.8 * 0.25)
    assert scores.coping_available is True
    assert affect._last_obstruction == pytest.approx(0.2)

    await affect._appraise_snapshot(
        _snapshot([_ev(source="interoception", salience=0.5)])
    )
    scores2 = affect._score_snapshot(
        _snapshot([_ev(source="interoception", salience=0.5)])
    )
    assert scores2.goal_significance == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_fall_within_window_keeps_likelihood(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        goal_response_window_s=10.0,
        goal_likelihood_fall=0.5,
    )
    affect.drives.restlessness.value = 0.75
    await affect._tick()
    goal = affect.goals.get(affect.goals.active_for_drive("restlessness").id)
    assert goal.likelihood == pytest.approx(0.5)

    t[0] += 1.0
    intent = Event(
        source="action_selection",
        type="intent.speak",
        payload={},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await affect._handle_peer_event("action_selection.out", intent)
    for _ in range(25):
        t[0] += 0.5
        await affect._tick()
    completed = affect.goals.get(goal.id)
    assert completed.state == GoalState.COMPLETED
    assert completed.likelihood == pytest.approx(0.5)
    assert affect._held_obstruction == {}


@pytest.mark.asyncio
async def test_non_dominant_goal_does_not_obstruct(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        goal_response_window_s=10.0,
        goal_likelihood_fall=0.5,
    )
    affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
    affect.drives.curiosity.value = 0.80
    await affect._tick()
    t[0] += 1.0
    intent = Event(
        source="action_selection",
        type="intent.speak",
        payload={},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await affect._handle_peer_event("action_selection.out", intent)
    for _ in range(21):
        t[0] += 0.5
        affect.drives.curiosity.value = 0.80
        await affect._tick()
    assert affect._held_obstruction

    affect.drives.social_drive._has_fired = True
    affect.drives.social_drive.value = 0.85
    scores = affect._score_snapshot(
        _snapshot([_ev(source="interoception", salience=0.5)])
    )
    assert scores.goal_significance == pytest.approx(0.0)
    assert affect._last_obstruction == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_anger_reachable_via_obstruction(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        goal_response_window_s=10.0,
        goal_likelihood_fall=0.5,
    )
    affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
    affect.drives.curiosity.own_ends = 8
    affect.drives.curiosity.other_ends = 0
    affect.drives.curiosity.value = 0.80
    await affect._tick()

    t[0] += 1.0
    intent = Event(
        source="action_selection",
        type="intent.speak",
        payload={},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await affect._handle_peer_event("action_selection.out", intent)
    for _ in range(21):
        t[0] += 0.5
        affect.drives.curiosity.value = 0.80
        await affect._tick()

    affect.drives.curiosity.value = 0.80
    scores = affect._score_snapshot(
        _snapshot([_ev(source="interoception", salience=0.5)])
    )
    assert scores.goal_significance <= -0.3
    assert scores.coping_potential == pytest.approx(0.8)
    assert classify(scores) == CategoricalEmotion.ANGER


@pytest.mark.asyncio
async def test_sleep_reset_clears_active_goals(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    affect.drives.curiosity.value = 0.80
    await affect._tick()
    affect.drives.restlessness.value = 0.80
    await affect._tick()
    curiosity_goal = affect.goals.active_for_drive("curiosity")
    affect.goals.complete(curiosity_goal.id)
    assert len(affect.goals.active()) == 1
    assert affect.goals.outcome_counts() == (1, 0)

    await affect.affective_reset()
    assert len(affect.goals.active()) == 0
    assert affect.goals.outcome_counts() == (1, 0)
    assert affect._response_windows == []
    assert affect._held_obstruction == {}


@pytest.mark.asyncio
async def test_persistence_keeps_likelihood_and_id(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        goal_response_window_s=10.0,
        goal_likelihood_fall=0.5,
    )
    affect.drives.curiosity.value = 0.80
    await affect._tick()
    t[0] += 1.0
    intent = Event(
        source="action_selection",
        type="intent.speak",
        payload={},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await affect._handle_peer_event("action_selection.out", intent)
    for _ in range(21):
        t[0] += 0.5
        affect.drives.curiosity.value = 0.80
        await affect._tick()
    goal = affect.goals.get(affect.goals.active_for_drive("curiosity").id)
    assert goal.likelihood == pytest.approx(0.25)
    gid = goal.id

    state = affect.serialize()
    t2 = [100.0]
    affect2 = Affect(bus, clock=lambda: t2[0])
    affect2.deserialize(state)
    restored = affect2.goals.active_for_drive("curiosity")
    assert restored is not None
    assert restored.id == gid
    assert restored.likelihood == pytest.approx(0.25)

    await affect2._tick()
    events = await _goal_events(bus)
    lifecycle = [
        e for e in events
        if e.payload.get("action") in ("completed", "abandoned")
        and e.payload.get("id") == gid
    ]
    assert len(lifecycle) == 0


@pytest.mark.asyncio
async def test_inactive_goal_leaves_scores_unchanged(bus):
    fresh = Affect(bus, clock=lambda: 0.0)
    fresh.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
    fresh.drives.curiosity.value = 0.5
    fresh.drives.social_drive.value = 0.5

    used = Affect(bus, clock=lambda: 0.0)
    used.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
    used.drives.curiosity.value = 0.80
    await used._tick()
    goal = used.goals.active_for_drive("curiosity")
    used.goals.complete(goal.id)
    used._held_obstruction.clear()
    used.drives.curiosity.value = 0.5
    used.drives.social_drive.value = 0.5

    snapshot = _snapshot([
        _ev(source="vision", salience=0.6),
        _ev(source="interoception", salience=0.4),
    ])
    s1 = fresh._score_snapshot(snapshot)
    s2 = used._score_snapshot(snapshot)
    assert s1.as_tuple() == s2.as_tuple()
    assert s1.coping_available == s2.coping_available
    assert fresh._goal_method == used._goal_method

    quiet = Affect(bus, clock=lambda: 0.0)
    before = len(await _goal_events(bus))
    for _ in range(20):
        await quiet._tick()
    after = len(await _goal_events(bus))
    assert after == before
    assert len(quiet.goals.active()) == 0


@pytest.mark.asyncio
async def test_constructor_validation(bus):
    with pytest.raises(ValueError, match="goal_stall_s"):
        Affect(bus, clock=lambda: 0.0, goal_stall_s=0)
    with pytest.raises(ValueError, match="goal_cap"):
        Affect(bus, clock=lambda: 0.0, goal_cap=0)
    with pytest.raises(ValueError, match="goal_cap"):
        Affect(bus, clock=lambda: 0.0, goal_cap=True)
    with pytest.raises(ValueError, match="goal_response_window_s"):
        Affect(bus, clock=lambda: 0.0, goal_response_window_s=-1)
    with pytest.raises(ValueError, match="goal_likelihood_fall"):
        Affect(bus, clock=lambda: 0.0, goal_likelihood_fall=1.5)


@pytest.mark.asyncio
async def test_injected_empty_ledger_kept(bus):
    ledger = GoalLedger()
    affect = Affect(bus, goals=ledger)
    assert affect.goals is ledger
