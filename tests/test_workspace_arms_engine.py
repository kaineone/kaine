# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Engine tests for the workspace arms."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import WORKSPACE_STREAM, Event
from kaine.cycle import CognitiveCycle
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticAffectModulator,
    StaticGoalScorer,
    Syneidesis,
)
from tests._fakes import FakeClock, FakeRegistry

fakeredis = pytest.importorskip("fakeredis.aioredis")


async def _publish_three_events(bus, tick):
    for i in range(3):
        await bus.publish(
            Event(
                source="soma",
                type="soma.report",
                payload={"i": i, "tick": tick},
                salience=0.2 + 0.2 * i,
                timestamp=datetime.now(timezone.utc),
            )
        )


@pytest.mark.asyncio
async def test_matched_draws_only_on_broadcast_ticks():
    client = fakeredis.FakeRedis(decode_responses=True)
    syn = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=64),
            goal_scorer=StaticGoalScorer(),
            affect_modulator=StaticAffectModulator(),
        ),
        top_k=2,
        arm="matched",
        arm_seed=4,
    )
    draws = []
    real = syn._rng.sample
    syn._rng.sample = lambda population, k: draws.append(k) or real(population, k)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    clock = FakeClock()
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syn,
        registry=FakeRegistry(["soma.out"]),
        processing_rate_hz=10.0,
        experiential_rate_hz=10.0 / 3.0,
        clock=clock,
        sleep=clock.sleep,
    )
    try:
        broadcasts = 0
        for t in range(30):
            await _publish_three_events(bus, t)
            result = await cycle.tick()
            if result.is_experiential:
                broadcasts += 1
    finally:
        await bus.close()
    assert len(draws) == broadcasts
    assert broadcasts > 0
    assert broadcasts < 30
    assert all(k == 2 for k in draws)


@pytest.mark.asyncio
async def test_pooled_publishes_only_broadcast_ticks():
    client = fakeredis.FakeRedis(decode_responses=True)
    syn = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=64),
            goal_scorer=StaticGoalScorer(),
            affect_modulator=StaticAffectModulator(),
        ),
        top_k=2,
        arm="pooled",
    )
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    clock = FakeClock()
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syn,
        registry=FakeRegistry(["soma.out"]),
        processing_rate_hz=10.0,
        experiential_rate_hz=10.0 / 3.0,
        clock=clock,
        sleep=clock.sleep,
    )
    try:
        experiential_ticks = []
        for t in range(30):
            await _publish_three_events(bus, t)
            result = await cycle.tick()
            if result.is_experiential:
                experiential_ticks.append(t)
    finally:
        await bus.close()
    entries = await client.xrange(WORKSPACE_STREAM)
    published_ticks = []
    for _entry_id, fields in entries:
        snap = json.loads(fields["snapshot"])
        published_ticks.append(snap["tick_index"])
        assert snap.get("metadata") == {"arm": "pooled"}
        assert snap.get("inhibited") is False
        assert len(snap["selected"]) == 3
    assert experiential_ticks
    assert published_ticks == experiential_ticks


@pytest.mark.asyncio
async def test_competitive_default_publishes_coalition_of_top_k():
    client = fakeredis.FakeRedis(decode_responses=True)
    syn = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=64),
            goal_scorer=StaticGoalScorer(),
            affect_modulator=StaticAffectModulator(),
        ),
        top_k=2,
    )
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    clock = FakeClock()
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syn,
        registry=FakeRegistry(["soma.out"]),
        processing_rate_hz=10.0,
        experiential_rate_hz=10.0 / 3.0,
        clock=clock,
        sleep=clock.sleep,
    )
    try:
        for t in range(9):
            await _publish_three_events(bus, t)
            await cycle.tick()
    finally:
        await bus.close()
    entries = await client.xrange(WORKSPACE_STREAM)
    assert entries
    for _entry_id, fields in entries:
        snap = json.loads(fields["snapshot"])
        assert snap.get("metadata", {}).get("arm") == "competitive"
        assert len(snap["selected"]) <= 2
