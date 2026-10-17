# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Affective reset publishes ``affect.goal`` events for every cleared active goal."""
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


@pytest.mark.asyncio
async def test_reset_clears_active_goals_with_events(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])

    affect.drives.curiosity.value = 0.80
    await affect._tick()
    affect.drives.restlessness.value = 0.80
    await affect._tick()

    active = affect.goals.active()
    assert len(active) == 2
    goal_ids = {g.drive: g.id for g in active}
    goal_descriptions = {g.id: g.description for g in active}
    goal_drives = {g.id: g.drive for g in active}
    before_counts = affect.goals.outcome_counts()
    before = len(await _goal_events(bus))

    await affect.affective_reset()

    after = len(await _goal_events(bus))
    new_events = (await _goal_events(bus))[before:]
    assert after - before == 2
    assert {ev.payload["id"] for ev in new_events} == set(goal_ids.values())
    assert affect.goals.active() == []
    assert affect.goals.outcome_counts() == before_counts

    for ev in new_events:
        assert ev.payload["action"] == "cleared"
        assert ev.payload["reason"] == "sleep_reset"
        assert ev.payload["action"] not in ("completed", "abandoned")
        gid = ev.payload["id"]
        assert gid in goal_ids.values()
        assert ev.payload["drive"] == goal_drives[gid]
        assert ev.payload["description"] == goal_descriptions[gid]


@pytest.mark.asyncio
async def test_reset_leaves_finished_goal_untouched(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])

    affect.drives.curiosity.value = 0.80
    await affect._tick()
    curiosity_goal = affect.goals.active()[0]
    affect.goals.complete(curiosity_goal.id)
    assert affect.goals.outcome_counts() == (1, 0)

    affect.drives.restlessness.value = 0.80
    await affect._tick()
    restlessness_goal = affect.goals.active()[0]

    before = len(await _goal_events(bus))
    await affect.affective_reset()
    after = len(await _goal_events(bus))
    new_events = (await _goal_events(bus))[before:]

    assert after - before == 1
    assert len(new_events) == 1
    ev = new_events[0]
    assert ev.payload["action"] == "cleared"
    assert ev.payload["reason"] == "sleep_reset"
    assert ev.payload["id"] == restlessness_goal.id

    assert affect.goals.active() == []
    assert affect.goals.outcome_counts() == (1, 0)
    assert affect.goals.get(curiosity_goal.id).state == GoalState.COMPLETED


@pytest.mark.asyncio
async def test_reset_with_no_active_goals_emits_no_goal_events(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])

    before = len(await _goal_events(bus))
    await affect.affective_reset()
    after = len(await _goal_events(bus))

    assert after == before
