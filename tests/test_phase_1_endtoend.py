# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phase 1 end-to-end: bus + cycle + Syneidesis + EchoModule.

Runs entirely against fakeredis — does not require the operator's
hardened Redis. The live-Redis integration tests live in
test_bus_roundtrip.py.
"""
import asyncio

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle import CognitiveCycle
from kaine.modules import EchoModule, ModuleRegistry
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticGoalScorer,
    StaticThymosModulator,
    Syneidesis,
)


@pytest.mark.asyncio
async def test_phase_1_end_to_end_delivery():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    syneidesis = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=8),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=5,
        publication_threshold=0.0,
    )
    registry = ModuleRegistry()
    echo = EchoModule(bus)
    registry.register(echo)

    import time
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syneidesis,
        registry=registry,
        processing_rate_hz=10.0,
        experiential_rate_hz=10.0,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    )

    await echo.initialize()
    try:
        # 1. Echo publishes one event into its own stream.
        await echo.publish_one(salience=0.8)

        # 2. Run one cycle tick. The cycle should collect the event from
        #    echo.out, hand it to syneidesis, broadcast the resulting
        #    snapshot to workspace.broadcast.
        result = await cycle.tick()
        assert result.events_collected == 1
        assert result.is_experiential is True

        # 3. Wait for echo's background workspace consumer to receive the
        #    broadcast.
        for _ in range(50):
            if echo.snapshots:
                break
            await asyncio.sleep(0.01)
        assert echo.snapshots, "echo never received a workspace broadcast"

        snap = echo.snapshots[-1]
        assert any(
            ev.source == "echo" and ev.type == "echo.ping"
            for _, ev in snap.selected_events
        ), "broadcast did not include the echo event"
        assert snap.tick_index == 0
        assert snap.inhibited is False
    finally:
        await echo.shutdown()
        await bus.close()


@pytest.mark.asyncio
async def test_phase_1_end_to_end_with_multiple_modules():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    syn = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=8),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=5,
        publication_threshold=0.0,
    )
    registry = ModuleRegistry()
    echo_a = EchoModule(bus)

    class EchoB(EchoModule):
        name = "echo-b"

    echo_b = EchoB(bus)
    registry.register(echo_a)
    registry.register(echo_b)

    import time
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syn,
        registry=registry,
        processing_rate_hz=10.0,
        experiential_rate_hz=10.0,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    )

    await echo_a.initialize()
    await echo_b.initialize()
    try:
        await echo_a.publish_one(salience=0.6)
        await echo_b.publish_one(salience=0.8)

        result = await cycle.tick()
        assert result.events_collected == 2
        assert result.modules_seen == 2

        for _ in range(50):
            if echo_a.snapshots and echo_b.snapshots:
                break
            await asyncio.sleep(0.01)
        assert echo_a.snapshots and echo_b.snapshots
    finally:
        await echo_a.shutdown()
        await echo_b.shutdown()
        await bus.close()
