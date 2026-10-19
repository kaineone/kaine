# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Persistence of the affect drive crossing latch.

After a revive, drives that had already crossed their threshold should not
re-fire on the first tick. The ``_has_fired`` hysteresis latch is saved and
restored alongside the drive values.
"""
from __future__ import annotations

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.affect import Affect
from kaine.modules.affect.drives import DriveSet


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


async def _affect_drive_events(bus):
    entries = await bus.read("affect.out", last_id="0", count=500)
    return [e for _, e in entries if e.type == "affect.drive"]


async def _affect_goal_added_events(bus):
    entries = await bus.read("affect.out", last_id="0", count=500)
    return [
        e
        for _, e in entries
        if e.type == "affect.goal" and e.payload.get("action") == "added"
    ]


@pytest.mark.asyncio
async def test_driveset_latch_round_trip(bus):
    first = DriveSet()
    first.curiosity.value = 0.8
    assert first.curiosity.consume_crossing() is True
    assert first.fired_to_dict() == {
        "curiosity": True,
        "boredom": False,
        "social_drive": False,
        "restlessness": False,
    }

    second = DriveSet()
    second.curiosity.value = 0.8
    second.load_fired(first.fired_to_dict())
    assert second.curiosity.consume_crossing() is False


@pytest.mark.asyncio
async def test_module_latch_persistence_no_duplicate_goal(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])

    affect.drives.boredom.value = 0.80
    await affect._tick()
    boredom_goal = affect.goals.active_for_drive("boredom")
    assert boredom_goal is not None
    affect.goals.abandon(boredom_goal.id)

    state = affect.serialize()
    assert state["drive_fired"]["boredom"] is True

    before_drive = len(await _affect_drive_events(bus))
    before_goal_added = len(await _affect_goal_added_events(bus))

    t2 = [100.0]
    affect2 = Affect(bus, clock=lambda: t2[0])
    affect2.deserialize(state)
    affect2.drives.boredom.value = 0.80
    await affect2._tick()
    t2[0] += 1.0
    await affect2._tick()

    after_drive = len(await _affect_drive_events(bus))
    after_goal_added = len(await _affect_goal_added_events(bus))
    assert after_drive == before_drive
    assert after_goal_added == before_goal_added
    assert affect2.goals.active_for_drive("boredom") is None


@pytest.mark.asyncio
async def test_old_state_without_latches_infers_from_values(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    state = affect.serialize()
    del state["drive_fired"]
    state["drives"] = {
        "curiosity": 0.9,
        "boredom": 0.5,
        "social_drive": 0.0,
        "restlessness": 0.7,
    }

    affect2 = Affect(bus, clock=lambda: t[0])
    affect2.deserialize(state)
    assert affect2.drives.fired_to_dict() == {
        "curiosity": True,
        "boredom": False,
        "social_drive": False,
        "restlessness": True,
    }

    before = len(await _affect_drive_events(bus))
    await affect2._tick()
    new = [
        e
        for e in (await _affect_drive_events(bus))[before:]
        if e.payload.get("drive") in ("curiosity", "restlessness")
    ]
    assert new == []


@pytest.mark.asyncio
async def test_non_bool_latch_values_fallback(bus):
    state = {
        "curiosity_scheme": 2,
        "drive_fired": {
            "curiosity": "yes",
            "boredom": 1,
            "social_drive": None,
            "restlessness": False,
        },
        "drives": {
            "curiosity": 0.9,
            "boredom": 0.9,
            "social_drive": 0.2,
            "restlessness": 0.9,
        },
    }

    affect = Affect(bus, clock=lambda: 0.0)
    affect.deserialize(state)
    assert affect.drives.curiosity._has_fired is True
    assert affect.drives.boredom._has_fired is True
    assert affect.drives.social_drive._has_fired is False
    assert affect.drives.restlessness._has_fired is False


@pytest.mark.asyncio
async def test_saved_clear_latch_honoured(bus):
    state = {
        "curiosity_scheme": 2,
        "drive_fired": {
            "curiosity": False,
            "boredom": False,
            "social_drive": False,
            "restlessness": False,
        },
        "drives": {
            "curiosity": 0.9,
            "boredom": 0.0,
            "social_drive": 0.0,
            "restlessness": 0.0,
        },
    }

    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    affect.deserialize(state)
    before = len(await _affect_drive_events(bus))
    await affect._tick()
    new = (await _affect_drive_events(bus))[before:]
    assert len(new) == 1
    assert new[0].payload["drive"] == "curiosity"
