# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Engagement relieves boredom as the entity's own response (paper 3.5, A.4)."""
from datetime import datetime, timezone

import pytest

from kaine.boot.factories.affect import make_affect
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.modules.affect import Affect
from kaine.modules.affect.drives import Drive, DriveSet
from kaine.modules.affect.goals import GoalState


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _intent(type_="intent.think", about_kind="event"):
    payload = {"kind": type_.split(".", 1)[1], "about": "vision (surprise=0.6)"}
    if about_kind is not None:
        payload["about_kind"] = about_kind
    return Event(
        source="action_selection",
        type=type_,
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


async def _goal_events(bus):
    entries = await bus.read("affect.out", last_id="0", count=200)
    return [e for _, e in entries if e.type == "affect.goal"]


async def _bored(affect, t):
    """Fire a boredom crossing so a boredom goal is active."""
    affect.drives.boredom.value = 0.75
    await affect._tick()
    assert affect.drives.boredom._has_fired
    assert affect.goals.active_for_drive("boredom") is not None
    t[0] += 0.1


def test_relieve_fraction_clamps_and_counts_own():
    d = Drive(name="boredom", relief_gain=0.3)
    d.value = 0.6
    d.relieve_fraction(0.5, own=True)
    assert d.value == pytest.approx(0.3)

    d.value = 0.6
    d.relieve_fraction(1.5, own=True)
    assert d.value == pytest.approx(0.0)

    d.value = 0.6
    d.relieve_fraction(0.0, own=True)
    assert d.value == pytest.approx(0.6)

    d.value = 0.75
    assert d.consume_crossing()
    d.relieve_fraction(0.5, own=True)
    assert d.own_ends == 1
    assert d.other_ends == 0
    assert not d._has_fired


def test_relieve_fraction_unknown_drive():
    with pytest.raises(KeyError):
        DriveSet().relieve_fraction("nope", 0.5, own=True)


async def test_engagement_relieves_boredom_and_counts_own(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    await _bored(affect, t)
    before = affect.drives.boredom.value
    await affect._handle_peer_event("action_selection.out", _intent())
    assert affect.drives.boredom.value == pytest.approx(before * 0.5)
    assert affect.drives.boredom.own_ends == 1
    assert affect.drives.boredom.other_ends == 0


async def test_engagement_completes_boredom_goal(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    await _bored(affect, t)
    goal_id = affect.goals.active_for_drive("boredom").id
    await affect._handle_peer_event("action_selection.out", _intent())
    assert affect.goals.get(goal_id).state == GoalState.COMPLETED
    assert affect.goals.outcome_counts() == (1, 0)

    events = await _goal_events(bus)
    completed = [
        e
        for e in events
        if e.payload.get("drive") == "boredom"
        and e.payload.get("action") == "completed"
        and e.payload.get("reason") == "own_response"
    ]
    abandoned = [
        e
        for e in events
        if e.payload.get("drive") == "boredom"
        and e.payload.get("action") == "abandoned"
    ]
    assert len(completed) == 1
    assert len(abandoned) == 0


async def test_non_rest_intents_relieve_boredom(bus):
    t = [0.0]
    for type_ in ("intent.speak", "intent.think", "intent.act"):
        affect = Affect(bus, clock=lambda: t[0])
        affect.drives.boredom.value = 0.5
        await affect._handle_peer_event("action_selection.out", _intent(type_=type_))
        assert affect.drives.boredom.value == pytest.approx(0.25), type_
        t[0] += 0.1

    affect = Affect(bus, clock=lambda: t[0])
    affect.drives.boredom.value = 0.5
    await affect._handle_peer_event("action_selection.out", _intent(about_kind=None))
    assert affect.drives.boredom.value == pytest.approx(0.25)

    affect = Affect(bus, clock=lambda: t[0])
    affect.drives.boredom.value = 0.5
    await affect._handle_peer_event("action_selection.out", _intent(type_="intent.rest"))
    assert affect.drives.boredom.value == pytest.approx(0.5)


async def test_felt_intent_does_not_relieve_boredom(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    affect.drives.boredom.value = 0.5
    affect.drives.restlessness.value = 0.8
    await affect._handle_peer_event(
        "action_selection.out", _intent(about_kind="felt")
    )
    assert affect.drives.boredom.value == pytest.approx(0.5)
    assert affect.drives.restlessness.value == pytest.approx(0.4)


async def test_novelty_alone_credits_other(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    await _bored(affect, t)
    affect._alert_fast = 10.0
    affect._alert_slow = 1.0
    t[0] += 1.0
    await affect._tick()
    assert affect.drives.boredom.value < 0.63
    assert affect.drives.boredom.own_ends == 0
    assert affect.drives.boredom.other_ends == 1
    assert affect.goals.outcome_counts() == (0, 1)

    boredom_goals = [g for g in affect.goals.all() if g.drive == "boredom"]
    assert any(g.state == GoalState.ABANDONED for g in boredom_goals)

    events = await _goal_events(bus)
    abandoned = [
        e
        for e in events
        if e.payload.get("drive") == "boredom"
        and e.payload.get("action") == "abandoned"
        and e.payload.get("reason") == "without_response"
    ]
    assert len(abandoned) == 1


async def test_engagement_relief_gain_configurable(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], boredom_engagement_relief=0.2)
    affect.drives.boredom.value = 0.5
    await affect._handle_peer_event("action_selection.out", _intent())
    assert affect.drives.boredom.value == pytest.approx(0.4)


async def test_sleep_reset_unaffected(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    await _bored(affect, t)
    await affect._handle_peer_event("action_selection.out", _intent())
    assert affect.drives.boredom.own_ends == 1
    assert affect.drives.boredom.other_ends == 0
    assert affect.goals.outcome_counts() == (1, 0)

    affect.drives.boredom.value = 0.75
    t[0] += 1.0
    await affect._tick()
    assert affect.goals.active_for_drive("boredom") is not None

    await affect.affective_reset()
    assert affect.drives.boredom.value == 0.0
    assert not affect.drives.boredom._has_fired
    assert affect.drives.boredom.own_ends == 1
    assert affect.drives.boredom.other_ends == 0
    assert affect.goals.outcome_counts() == (1, 0)
    assert affect.goals.active_for_drive("boredom") is None


async def test_off_skips_engagement_channel(bus, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("relieve_fraction should not be called")

    monkeypatch.setattr(DriveSet, "relieve_fraction", boom)

    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], boredom_engagement_relief=0.0)

    for type_ in ("intent.think", "intent.speak", "intent.act"):
        await affect._handle_peer_event("action_selection.out", _intent(type_=type_))
        await affect._tick()
        t[0] += 0.1

    await affect._handle_peer_event(
        "action_selection.out", _intent(type_="intent.think", about_kind="felt")
    )
    await affect._tick()
    t[0] += 0.1

    await affect._handle_peer_event("action_selection.out", _intent(type_="intent.rest"))
    await affect._tick()

    monkeypatch.setattr(DriveSet, "relieve_fraction", boom)
    await _bored(affect, t)
    before = affect.drives.boredom.value
    await affect._handle_peer_event("action_selection.out", _intent())
    assert affect.drives.boredom.value == before
    assert affect.drives.boredom.own_ends == 0
    assert affect.goals.active_for_drive("boredom") is not None


async def test_boredom_engagement_relief_validation(bus):
    t = [0.0]
    for bad in (-0.1, 1.5, float("nan")):
        with pytest.raises(ValueError):
            Affect(bus, clock=lambda: t[0], boredom_engagement_relief=bad)

    for ok in (0.0, 1.0):
        affect = Affect(bus, clock=lambda: t[0], boredom_engagement_relief=ok)
        assert affect._boredom_engagement_relief == ok


async def test_config_wiring(bus):
    affect = make_affect(bus, {"boredom_engagement_relief": 0.35})
    assert affect._boredom_engagement_relief == 0.35

    affect_default = make_affect(bus, {})
    assert affect_default._boredom_engagement_relief == 0.5
