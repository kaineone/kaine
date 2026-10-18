# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Sustained-concern re-entry of drive events (paper 3.5, A.4)."""
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


async def test_cadence_and_intensity(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75

    await affect._tick()
    events = await _drive_events(bus)
    crossings = [e for _, e in events if not e.payload.get("reentry")]
    assert len(crossings) == 1
    assert crossings[0].payload == {
        "drive": "curiosity",
        "value": 0.75,
        "alert": True,
    }

    t[0] = 29.9
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 0

    t[0] = 30.0
    await affect._tick()
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 1
    for _, e in reentries:
        assert e.payload == {
            "drive": "curiosity",
            "value": 0.75,
            "alert": False,
            "reentry": True,
        }
        assert e.salience == pytest.approx(0.75)

    t[0] = 45.0
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 1

    t[0] = 60.0
    await affect._tick()
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 2
    for _, e in reentries:
        assert e.payload == {
            "drive": "curiosity",
            "value": 0.75,
            "alert": False,
            "reentry": True,
        }
        assert e.salience == pytest.approx(0.75)


async def test_intensity_follows_drive(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75
    await affect._tick()

    t[0] = 29.9
    await affect._tick()
    affect.drives.curiosity.value = 0.9

    t[0] = 30.0
    await affect._tick()
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 1
    _, e = reentries[0]
    assert e.payload["value"] == 0.9
    assert e.salience == pytest.approx(0.9)


async def test_sparse_updates(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75
    await affect._tick()

    t[0] = 100.0
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 1

    t[0] = 129.0
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 1

    t[0] = 130.0
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 2


async def test_below_threshold_keeps_schedule(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75
    await affect._tick()
    assert affect.goals.active_for_drive("curiosity") is not None

    affect.drives.curiosity.value = 0.65
    t[0] = 30.0
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 0
    assert affect.goals.active_for_drive("curiosity") is not None

    affect.drives.curiosity.value = 0.75
    t[0] = 31.0
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 1


async def test_goal_end_stops_reentry(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75
    await affect._tick()
    goal_id = affect.goals.active_for_drive("curiosity").id

    affect.drives.curiosity.value = 0.5
    t[0] = 10.0
    await affect._tick()
    assert affect.goals.get(goal_id).state != GoalState.ACTIVE

    affect.drives.curiosity.value = 0.69
    t[0] = 40.0
    await affect._tick()
    t[0] = 80.0
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 0
    assert affect._reentry_due == {}


async def test_stall_stops_reentry(bus):
    t = [0.0]
    affect = Affect(
        bus, clock=lambda: t[0], drives=_static(), goal_stall_s=50.0
    )
    affect.drives.curiosity.value = 0.75
    await affect._tick()
    goal_id = affect.goals.active_for_drive("curiosity").id

    t[0] = 30.0
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 1

    t[0] = 55.0
    await affect._tick()
    assert affect.goals.get(goal_id).state == GoalState.ABANDONED

    t[0] = 90.0
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 1


async def test_sleep_reset_clears_schedule(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75
    await affect._tick()

    t[0] = 30.0
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 1

    await affect.affective_reset()
    assert affect._reentry_due == {}

    affect.drives.curiosity.value = 0.75
    t[0] = 31.0
    await affect._tick()
    assert affect.goals.active_for_drive("curiosity") is not None

    t[0] = 40.0
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 1

    t[0] = 61.0
    await affect._tick()
    reentries = _reentries(await _drive_events(bus), "curiosity")
    assert len(reentries) == 2
    assert len(affect._reentry_due) == 1
    new_goal_id = affect.goals.active_for_drive("curiosity").id
    assert new_goal_id in affect._reentry_due


async def test_no_drive_no_reentry(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    await affect.add_goal("watch the window")
    for ts in (0.0, 30.0, 60.0):
        t[0] = ts
        await affect._tick()
    assert len(await _drive_events(bus)) == 0


async def test_intent_about_reentry_is_about_drive(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.boredom.value = 0.75
    await affect._tick()

    t[0] = 30.0
    await affect._tick()
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


async def test_off_no_reentry(bus):
    t = [0.0]
    affect = Affect(
        bus, clock=lambda: t[0], drives=_static(), concern_reentry_s=0.0
    )
    affect.drives.curiosity.value = 0.75
    for ts in (0.0, 30.0, 60.0, 120.0):
        t[0] = ts
        await affect._tick()
    events = await _drive_events(bus)
    assert len(events) == 1
    assert events[0][1].payload.get("alert") is True
    assert "reentry" not in events[0][1].payload
    assert affect._reentry_due == {}


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


async def test_restore_restarts_schedule(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], drives=_static())
    affect.drives.curiosity.value = 0.75
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 0

    t[0] = 20.0
    await affect._tick()
    state = affect.serialize()
    affect.deserialize(state)
    assert affect._reentry_due == {}

    t[0] = 30.0
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 0

    t[0] = 59.9
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 0

    t[0] = 60.0
    await affect._tick()
    assert len(_reentries(await _drive_events(bus), "curiosity")) == 1
