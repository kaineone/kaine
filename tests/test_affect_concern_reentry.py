# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Sustained-concern re-entry of drive events (paper 3.5, A.4)."""
import asyncio
from datetime import datetime, timezone

import pytest

from kaine.boot.factories.affect import make_affect
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
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


def _static():
    return DriveSet(
        curiosity=Drive(name="curiosity", build_rate=0.0, decay_rate=0.0),
        boredom=Drive(
            name="boredom", build_rate=0.0, decay_rate=0.0, relief_gain=0.3
        ),
        social_drive=Drive(name="social_drive", build_rate=0.0, decay_rate=0.0),
        restlessness=Drive(
            name="restlessness", build_rate=0.0, decay_rate=0.0
        ),
    )


async def _drive_events(bus):
    entries = await bus.read("affect.out", last_id="0", count=500)
    return [(eid, e) for eid, e in entries if e.type == "affect.drive"]


def _reentries(events, drive):
    return [
        (eid, e)
        for eid, e in events
        if e.payload.get("drive") == drive and e.payload.get("reentry")
    ]


def _snap(key, event, *, score=0.5, threshold=0.3, inhibited=False, selected=True):
    return WorkspaceSnapshot(
        tick_index=1,
        selected_events=[(key, event)] if selected else [],
        inhibited=inhibited,
        salience_scores={key: score},
        metadata={"access_threshold": threshold},
    )


def _assert_reentry(event, name, value):
    assert event.payload == {
        "drive": name,
        "value": value,
        "alert": False,
        "reentry": True,
    }
    assert event.salience == pytest.approx(value)


async def test_missed_crossing_recurs_on_own_updates(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75

    await affect._tick()
    events = await _drive_events(bus)
    assert len([e for _, e in events if e.payload.get("alert")]) == 1
    assert len(_reentries(events, "curiosity")) == 0

    t[0] = 0.2
    await affect._tick(own_update=True)
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 0

    t[0] = 0.6
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 0

    t[0] = 1.0
    await affect._tick(own_update=True)
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 1
    _assert_reentry(reentries[0][1], "curiosity", 0.75)

    t[0] = 1.3
    await affect._tick(own_update=True)
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 1

    t[0] = 1.5
    await affect._tick(own_update=True)
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 2
    for _, e in reentries:
        _assert_reentry(e, "curiosity", 0.75)


async def test_access_starts_interval(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75

    await affect._tick()

    t[0] = 1.0
    await affect._tick(own_update=True)
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 1
    eid, reentry = reentries[0]

    t[0] = 1.2
    await affect.on_workspace(_snap(f"affect.out:{eid}", reentry))
    assert affect._concern_pending == {}
    goal = affect.goals.active_for_drive("curiosity")
    assert affect._reentry_due[goal.id] == pytest.approx(31.2)

    for ts in (2.0, 10.0, 31.1):
        t[0] = ts
        await affect._tick(own_update=True)
        assert len(_reentries(await _drive_events(bus), "curiosity")) == 1

    t[0] = 31.2
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 1

    t[0] = 31.3
    await affect._tick(own_update=True)
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 2
    for _, e in reentries:
        _assert_reentry(e, "curiosity", 0.75)


async def test_access_of_crossing_starts_interval(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75

    await affect._tick()
    events = await _drive_events(bus)
    eid, crossing = next((eid, e) for eid, e in events if e.payload.get("alert"))

    t[0] = 0.1
    await affect.on_workspace(_snap(f"affect.out:{eid}", crossing))
    assert affect._concern_pending == {}
    goal = affect.goals.active_for_drive("curiosity")
    assert affect._reentry_due[goal.id] == pytest.approx(30.1)

    for ts in (1.0, 30.0):
        t[0] = ts
        await affect._tick(own_update=True)
        assert len(_reentries(await _drive_events(bus), "curiosity")) == 0

    t[0] = 30.2
    await affect._tick(own_update=True)
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 1
    _assert_reentry(reentries[0][1], "curiosity", 0.75)


@pytest.mark.parametrize(
    "inhibited,score,selected,key_stream",
    [
        (True, 0.5, True, "affect"),
        (False, 0.2, True, "affect"),
        (False, 0.5, False, "affect"),
        (False, 0.5, True, "vision"),
    ],
)
async def test_non_access_keeps_pending(bus, inhibited, score, selected, key_stream):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75
    await affect._tick()

    t[0] = 1.0
    await affect._tick(own_update=True)
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 1
    eid, reentry = reentries[0]

    t[0] = 1.1
    key = f"{key_stream}.out:{eid}" if key_stream != "affect" else f"affect.out:{eid}"
    await affect.on_workspace(
        _snap(key, reentry, score=score, threshold=0.3, inhibited=inhibited, selected=selected)
    )

    assert affect.goals.active_for_drive("curiosity").id in affect._concern_pending

    t[0] = 1.6
    await affect._tick(own_update=True)
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 2


async def test_late_access_of_older_copy(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75
    await affect._tick()

    t[0] = 1.0
    await affect._tick(own_update=True)
    events = await _drive_events(bus)
    reentries = _reentries(events, "curiosity")
    assert len(reentries) == 1
    first_eid, first_reentry = reentries[0]

    t[0] = 1.5
    await affect._tick(own_update=True)
    events = await _drive_events(bus)
    reentries = _reentries(events, "curiosity")
    assert len(reentries) == 2

    t[0] = 1.6
    await affect.on_workspace(_snap(f"affect.out:{first_eid}", first_reentry))
    assert affect._concern_pending == {}

    t[0] = 2.5
    await affect._tick(own_update=True)
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 2


async def test_intensity_follows_drive(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75
    await affect._tick()

    affect.drives.curiosity.value = 0.9
    t[0] = 1.0
    await affect._tick(own_update=True)
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 1
    e = reentries[0][1]
    assert e.payload["value"] == 0.9
    assert e.salience == pytest.approx(0.9)


async def test_below_threshold_pauses(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75
    await affect._tick()
    assert affect.goals.active_for_drive("curiosity") is not None
    assert affect.goals.active_for_drive("curiosity").id in affect._concern_pending

    affect.drives.curiosity.value = 0.65
    t[0] = 1.0
    await affect._tick(own_update=True)
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 0
    assert affect.goals.active_for_drive("curiosity") is not None
    assert affect.goals.active_for_drive("curiosity").id in affect._concern_pending

    t[0] = 2.0
    await affect._tick(own_update=True)
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 0
    assert affect.goals.active_for_drive("curiosity").id in affect._concern_pending

    affect.drives.curiosity.value = 0.75
    t[0] = 2.1
    await affect._tick(own_update=True)
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 1
    _assert_reentry(reentries[0][1], "curiosity", 0.75)


async def test_goal_end_clears_pending(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75
    await affect._tick()

    affect.drives.curiosity.value = 0.5
    t[0] = 1.0
    await affect._tick()
    assert affect._concern_pending == {}
    assert affect._reentry_due == {}

    affect.drives.curiosity.value = 0.69
    for ts in (2.0, 3.0):
        t[0] = ts
        await affect._tick(own_update=True)
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 0


async def test_stall_clears_pending(bus):
    t = [0.0]
    affect = Affect(
        bus, clock=lambda: t[0], drives=_static(), goal_stall_s=5.0
    )
    affect.drives.curiosity.value = 0.75

    t[0] = 0.0
    await affect._tick(own_update=True)
    goal_id = affect.goals.active_for_drive("curiosity").id
    events = await _drive_events(bus)
    assert len([e for _, e in events if e.payload.get("alert")]) == 1
    assert len(_reentries(events, "curiosity")) == 0

    t[0] = 1.0
    await affect._tick(own_update=True)
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 1

    t[0] = 6.0
    await affect._tick(own_update=True)
    assert affect.goals.get(goal_id).state == GoalState.ABANDONED

    for ts in (7.0, 8.0):
        t[0] = ts
        await affect._tick(own_update=True)
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 1
    assert affect._concern_pending == {}


async def test_sleep_reset_clears_pending(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75

    await affect._tick(own_update=True)
    t[0] = 1.0
    await affect._tick(own_update=True)
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 1
    old_goal_id = affect.goals.active_for_drive("curiosity").id
    assert old_goal_id in affect._concern_pending

    await affect.affective_reset()
    assert affect._concern_pending == {}
    assert affect._reentry_due == {}

    affect.drives.curiosity.value = 0.75
    t[0] = 2.0
    await affect._tick(own_update=True)
    new_goal_id = affect.goals.active_for_drive("curiosity").id
    assert new_goal_id != old_goal_id
    assert new_goal_id in affect._concern_pending

    t[0] = 3.0
    await affect._tick(own_update=True)
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 2
    assert set(affect._concern_pending.keys()) == {new_goal_id}


async def test_restore_clears_pending(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75
    await affect._tick()
    assert affect._concern_pending

    t[0] = 20.0
    affect.deserialize(affect.serialize())
    assert affect._concern_pending == {}
    assert affect._reentry_due == {}

    t[0] = 30.0
    await affect._tick()
    goal = affect.goals.active_for_drive("curiosity")
    assert affect._reentry_due[goal.id] == pytest.approx(60.0)

    t[0] = 59.9
    await affect._tick(own_update=True)
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 0

    t[0] = 60.0
    await affect._tick(own_update=True)
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 1
    _assert_reentry(reentries[0][1], "curiosity", 0.75)


async def test_intent_about_repeat_is_about_drive(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.boredom.value = 0.75
    await affect._tick()

    t[0] = 1.0
    await affect._tick(own_update=True)
    reentries = _reentries(await _drive_events(bus), "boredom")
    assert len(reentries) == 1
    eid, _ = reentries[0]
    assert eid in affect._drive_entry_ids

    affect.drives.restlessness.value = 0.8
    event = Event(
        source="action_selection",
        type="intent.think",
        payload={
            "kind": "think",
            "about": "affect (surprise=0.5)",
            "about_kind": "event",
            "entry_id": f"affect.out:{eid}",
        },
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await affect._handle_peer_event("action_selection.out", event)
    assert affect.drives.boredom.value == 0.75
    assert affect.drives.boredom.own_ends == 0
    assert affect.drives.restlessness.value == pytest.approx(0.4)


async def test_no_drive_no_reentry(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    await affect.add_goal("watch the window")
    for ts in (0.0, 30.0, 60.0):
        t[0] = ts
        await affect._tick(own_update=True)
    assert len(await _drive_events(bus)) == 0


async def test_off_no_repeat_no_state(bus):
    t = [0.0]
    affect = Affect(
        bus, clock=lambda: t[0], drives=_static(), concern_reentry_s=0.0
    )
    affect.drives.curiosity.value = 0.75

    await affect._tick()
    t[0] = 1.0
    await affect._tick(own_update=True)
    events = await _drive_events(bus)
    assert len(events) == 1
    eid, crossing = events[0]
    assert crossing.payload == {
        "drive": "curiosity",
        "value": 0.75,
        "alert": True,
    }
    assert "reentry" not in crossing.payload
    assert affect._concern_pending == {}
    assert affect._reentry_due == {}

    t[0] = 1.5
    await affect.on_workspace(_snap(f"affect.out:{eid}", crossing))
    assert affect._concern_pending == {}
    assert affect._reentry_due == {}

    for ts in (2.0, 31.0, 61.0):
        t[0] = ts
        await affect._tick(own_update=True)
    events = await _drive_events(bus)
    assert len(events) == 1


async def test_timer_loop_is_own_update(bus):
    t = [0.0]
    affect = Affect(
        bus, clock=lambda: t[0], drives=_static(), publish_interval_s=0.05
    )
    affect.drives.curiosity.value = 0.75
    await affect._tick()

    t[0] = 1.0
    task = asyncio.create_task(affect._state_timer_loop())
    await asyncio.sleep(0.3)
    affect._stopped.set()
    await task
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 1


async def test_concern_reentry_s_validation(bus):
    t = [0.0]
    for bad in (-1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            Affect(bus, clock=lambda: t[0], concern_reentry_s=bad)


async def test_config_wiring(bus):
    affect = make_affect(bus, {"concern_reentry_s": 12.5})
    assert affect._concern_reentry_s == 12.5

    affect_default = make_affect(bus, {})
    assert affect_default._concern_reentry_s == 30.0
