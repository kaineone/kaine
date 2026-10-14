# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phase 1 end-to-end: bus + cycle + workspace + RecorderModule.

Runs entirely against fakeredis — does not require the operator's
hardened Redis. The live-Redis integration tests live in
test_bus_roundtrip.py.
"""
import asyncio

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle import CognitiveCycle
from kaine.modules import ModuleRegistry, RecorderModule
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticAffectModulator,
    StaticGoalScorer,
    Workspace,
)


@pytest.mark.asyncio
async def test_phase_1_end_to_end_delivery():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    workspace = Workspace(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=8),
            goal_scorer=StaticGoalScorer(),
            affect_modulator=StaticAffectModulator(),
        ),
        top_k=5,
        publication_threshold=0.0,
    )
    registry = ModuleRegistry()
    recorder = RecorderModule(bus)
    registry.register(recorder)

    import time
    cycle = CognitiveCycle(
        bus=bus,
        workspace=workspace,
        registry=registry,
        processing_rate_hz=10.0,
        experiential_rate_hz=10.0,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    )

    await recorder.initialize()
    try:
        # 1. The recorder module publishes one event into its own stream.
        await recorder.publish_one(salience=0.8)

        # 2. Run one cycle tick. The cycle should collect the event from
        #    recorder.out, hand it to the workspace, broadcast the resulting
        #    snapshot to workspace.broadcast.
        result = await cycle.tick()
        assert result.events_collected == 1
        assert result.is_experiential is True

        # 3. Wait for the recorder module's background workspace consumer to receive the
        #    broadcast.
        for _ in range(50):
            if recorder.snapshots:
                break
            await asyncio.sleep(0.01)
        assert recorder.snapshots, "echo never received a workspace broadcast"

        snap = recorder.snapshots[-1]
        assert any(
            ev.source == "recorder" and ev.type == "recorder.ping"
            for _, ev in snap.selected_events
        ), "broadcast did not include the echo event"
        assert snap.tick_index == 0
        assert snap.inhibited is False
    finally:
        await recorder.shutdown()
        await bus.close()


@pytest.mark.asyncio
async def test_phase_1_end_to_end_with_multiple_modules():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    syn = Workspace(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=8),
            goal_scorer=StaticGoalScorer(),
            affect_modulator=StaticAffectModulator(),
        ),
        top_k=5,
        publication_threshold=0.0,
    )
    registry = ModuleRegistry()
    recorder_a = RecorderModule(bus)

    class RecorderB(RecorderModule):
        name = "echo-b"

    recorder_b = RecorderB(bus)
    registry.register(recorder_a)
    registry.register(recorder_b)

    import time
    cycle = CognitiveCycle(
        bus=bus,
        workspace=syn,
        registry=registry,
        processing_rate_hz=10.0,
        experiential_rate_hz=10.0,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    )

    await recorder_a.initialize()
    await recorder_b.initialize()
    try:
        await recorder_a.publish_one(salience=0.6)
        await recorder_b.publish_one(salience=0.8)

        result = await cycle.tick()
        assert result.events_collected == 2
        assert result.modules_seen == 2

        for _ in range(50):
            if recorder_a.snapshots and recorder_b.snapshots:
                break
            await asyncio.sleep(0.01)
        assert recorder_a.snapshots and recorder_b.snapshots
    finally:
        await recorder_a.shutdown()
        await recorder_b.shutdown()
        await bus.close()
