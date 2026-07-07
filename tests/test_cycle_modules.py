# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle import CognitiveCycle
from tests._fakes import FailingReadBus, FakeClock, FakeRegistry, FakeSyneidesis


def _ev(source: str, value: int) -> Event:
    return Event(
        source=source,
        type="m.test",
        payload={"value": value},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_quiet_module_skipped_silently():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    try:
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=FakeSyneidesis(),
            registry=FakeRegistry(["chronos.out", "soma.out"]),
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        result = await cycle.tick()
        assert result.events_collected == 0
        assert result.modules_seen == 0
        assert result.error is False
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_events_from_module_collected_and_cursor_advances():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    try:
        for i in range(3):
            await bus.publish(_ev("chronos", i))
        syn = FakeSyneidesis()
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=syn,
            registry=FakeRegistry(["chronos.out"]),
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        result1 = await cycle.tick()
        assert result1.events_collected == 3
        assert result1.modules_seen == 1
        result2 = await cycle.tick()
        # Cursor advanced; no new events since last tick.
        assert result2.events_collected == 0
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_erroring_read_does_not_stop_cycle():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    real = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    try:
        await real.publish(_ev("soma", 1))
        wrapped = FailingReadBus(real, fail_stream="chronos.out")
        cycle = CognitiveCycle(
            bus=wrapped,  # type: ignore[arg-type]
            syneidesis=FakeSyneidesis(),
            registry=FakeRegistry(["soma.out", "chronos.out"]),
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        result = await cycle.tick()
        # soma.out's event was still collected; chronos.out errored and was
        # counted but the cycle did not stop.
        assert result.events_collected == 1
        assert cycle.error_counts.get("chronos.out", 0) >= 1
    finally:
        await real.close()


@pytest.mark.asyncio
async def test_syneidesis_error_recorded_but_cycle_continues():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    try:
        syn = FakeSyneidesis(raise_on_tick=0)
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=syn,
            registry=FakeRegistry([]),
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        result0 = await cycle.tick()
        assert result0.error is True
        # Next tick should still run.
        result1 = await cycle.tick()
        assert result1.error is False
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_workspace_broadcast_only_on_experiential_ticks():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    try:
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=FakeSyneidesis(),
            registry=FakeRegistry([]),
            processing_rate_hz=10.0,
            experiential_rate_hz=2.0,
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        experiential = 0
        for _ in range(30):
            if (await cycle.tick()).is_experiential:
                experiential += 1
        broadcasts = await bus.length("workspace.broadcast")
        assert broadcasts == experiential
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_dynamic_module_addition_picked_up_next_tick():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    try:
        registry = FakeRegistry([])
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=FakeSyneidesis(),
            registry=registry,
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        await cycle.tick()
        # Now register a new module mid-run and publish.
        await bus.publish(_ev("soma", 42))
        registry.set_streams(["soma.out"])
        result = await cycle.tick()
        assert result.events_collected == 1
    finally:
        await bus.close()
