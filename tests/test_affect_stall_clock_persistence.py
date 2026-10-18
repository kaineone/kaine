# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The affect module's goal stall clock survives a restore (paper A.4, Delta_stall)."""

from __future__ import annotations

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.affect import Affect
from kaine.modules.affect.goals import GoalState


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


async def _goal_events(bus):
    entries = await bus.read("affect.out", last_id="0", count=200)
    return [e for _, e in entries if e.type == "affect.goal"]


async def _make_stalled_curiosity_goal(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], goal_stall_s=5.0)
    affect.drives.curiosity.value = 0.80
    await affect._tick()
    for _ in range(4):
        t[0] += 1.0
        affect.drives.curiosity.value = 0.80
        await affect._tick()
    return affect, t


@pytest.mark.asyncio
async def test_serialize_stores_elapsed_above_threshold(bus):
    affect, t = await _make_stalled_curiosity_goal(bus)
    gid = affect.goals.active_for_drive("curiosity").id
    state = affect.serialize()
    assert state["goal_above_elapsed"] == {gid: pytest.approx(4.0)}


@pytest.mark.asyncio
async def test_restored_goal_keeps_stall_horizon(bus):
    affect, _ = await _make_stalled_curiosity_goal(bus)
    gid = affect.goals.active_for_drive("curiosity").id
    state = affect.serialize()

    t2 = [100.0]
    affect2 = Affect(bus, clock=lambda: t2[0], goal_stall_s=5.0)
    affect2.deserialize(state)
    affect2.drives.curiosity._has_fired = True
    affect2.drives.curiosity.value = 0.80
    await affect2._tick()
    assert affect2.goals.get(gid).state == GoalState.ACTIVE

    t2[0] += 1.0
    affect2.drives.curiosity.value = 0.80
    await affect2._tick()
    assert affect2.goals.get(gid).state == GoalState.ABANDONED

    events = await _goal_events(bus)
    goal_events = [e for e in events if e.payload.get("id") == gid]
    assert goal_events[-1].payload["action"] == "abandoned"
    assert goal_events[-1].payload["reason"] == "stalled"


@pytest.mark.asyncio
async def test_old_state_without_field_restarts_clock(bus):
    affect, _ = await _make_stalled_curiosity_goal(bus)
    gid = affect.goals.active_for_drive("curiosity").id
    state = affect.serialize()
    del state["goal_above_elapsed"]

    t2 = [100.0]
    affect2 = Affect(bus, clock=lambda: t2[0], goal_stall_s=5.0)
    affect2.deserialize(state)
    affect2.drives.curiosity._has_fired = True
    for tick_time in (100.0, 101.0, 104.0):
        t2[0] = tick_time
        affect2.drives.curiosity.value = 0.80
        await affect2._tick()
        assert affect2.goals.get(gid).state == GoalState.ACTIVE

    t2[0] = 105.0
    affect2.drives.curiosity.value = 0.80
    await affect2._tick()
    assert affect2.goals.get(gid).state == GoalState.ABANDONED


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "bad_value",
    [
        -1.0,
        float("nan"),
        float("inf"),
        True,
        "4",
        None,
    ],
)
async def test_invalid_entries_restart_clock(bus, bad_value):
    affect, _ = await _make_stalled_curiosity_goal(bus)
    gid = affect.goals.active_for_drive("curiosity").id
    state = affect.serialize()
    state["goal_above_elapsed"] = {gid: bad_value}

    t2 = [100.0]
    affect2 = Affect(bus, clock=lambda: t2[0], goal_stall_s=5.0)
    affect2.deserialize(state)
    affect2.drives.curiosity._has_fired = True
    for tick_time in (100.0, 101.0, 104.0):
        t2[0] = tick_time
        affect2.drives.curiosity.value = 0.80
        await affect2._tick()
        assert affect2.goals.get(gid).state == GoalState.ACTIVE

    t2[0] = 105.0
    affect2.drives.curiosity.value = 0.80
    await affect2._tick()
    assert affect2.goals.get(gid).state == GoalState.ABANDONED


@pytest.mark.asyncio
async def test_unknown_goal_id_is_ignored(bus):
    affect, _ = await _make_stalled_curiosity_goal(bus)
    state = affect.serialize()
    state["goal_above_elapsed"] = {"no-such-goal": 4.0}

    t2 = [100.0]
    affect2 = Affect(bus, clock=lambda: t2[0], goal_stall_s=5.0)
    affect2.deserialize(state)
    assert affect2._goal_above_since == {}


@pytest.mark.asyncio
async def test_non_dict_field_is_ignored(bus):
    affect, _ = await _make_stalled_curiosity_goal(bus)
    state = affect.serialize()
    state["goal_above_elapsed"] = [4.0]

    t2 = [100.0]
    affect2 = Affect(bus, clock=lambda: t2[0], goal_stall_s=5.0)
    affect2.deserialize(state)
    assert affect2._goal_above_since == {}


@pytest.mark.asyncio
async def test_goal_below_threshold_has_no_entry(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], goal_stall_s=5.0)
    affect.drives.curiosity.value = 0.80
    await affect._tick()
    t[0] += 1.0
    affect.drives.curiosity.value = 0.65
    await affect._tick()
    assert affect.goals.active_for_drive("curiosity") is not None
    state = affect.serialize()
    assert state["goal_above_elapsed"] == {}


@pytest.mark.asyncio
async def test_elapsed_is_only_numbers(bus):
    affect, _ = await _make_stalled_curiosity_goal(bus)
    gid = affect.goals.active_for_drive("curiosity").id
    state = affect.serialize()
    elapsed = state["goal_above_elapsed"]
    assert isinstance(elapsed, dict)
    assert set(elapsed.keys()) == {gid}
    for value in elapsed.values():
        assert isinstance(value, float)
        assert value >= 0.0
        assert value < float("inf")
