# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle import CognitiveCycle
from tests._fakes import FakeClock, FakeRegistry, FakeSyneidesis


@pytest.fixture
async def cycle_with_fakes():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    clock = FakeClock()
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=FakeSyneidesis(),
        registry=FakeRegistry([]),
        processing_rate_hz=5.0,
        experiential_rate_hz=5.0,
        clock=clock,
        sleep=clock.sleep,
    )
    yield cycle, bus, clock
    await bus.close()


@pytest.mark.asyncio
async def test_pause_closes_the_tick_gate_resume_opens_it(cycle_with_fakes):
    """Freeze relies on `run_forever`'s `await self._paused.wait()` gate.
    Pausing must close it (the loop would block → no ticks → subjective time
    stops); resuming must reopen it."""
    cycle, *_ = cycle_with_fakes
    assert cycle.is_paused is False
    await cycle.pause()
    assert cycle.is_paused is True
    # Gate closed: the loop's wait would block.
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(cycle._paused.wait(), timeout=0.1)
    await cycle.resume()
    assert cycle.is_paused is False
    # Gate open: the wait returns immediately.
    await asyncio.wait_for(cycle._paused.wait(), timeout=0.5)


@pytest.mark.asyncio
async def test_apply_rate_control_updates_processing_rate(cycle_with_fakes):
    cycle, bus, _ = cycle_with_fakes
    ok = await cycle.apply_rate_control_event({"processing_rate_hz": 12.0})
    assert ok is True
    assert cycle.processing_rate_hz == 12.0


@pytest.mark.asyncio
async def test_apply_rate_control_updates_both_rates(cycle_with_fakes):
    cycle, bus, _ = cycle_with_fakes
    ok = await cycle.apply_rate_control_event({
        "processing_rate_hz": 10.0, "experiential_rate_hz": 2.0,
    })
    assert ok is True
    assert cycle.processing_rate_hz == 10.0
    assert cycle.experiential_rate_hz == 2.0


@pytest.mark.asyncio
async def test_apply_rate_control_publishes_cycle_rates(cycle_with_fakes):
    cycle, bus, _ = cycle_with_fakes
    await cycle.apply_rate_control_event({"processing_rate_hz": 7.0})
    entries = await bus.read("cycle.out", last_id="0", count=20)
    rates = [e for _, e in entries if e.type == "cycle.rates"]
    assert len(rates) == 1
    assert rates[0].payload["processing_rate_hz"] == 7.0


@pytest.mark.asyncio
async def test_apply_rate_control_rejects_non_positive(cycle_with_fakes):
    cycle, bus, _ = cycle_with_fakes
    prior_rate = cycle.processing_rate_hz
    ok = await cycle.apply_rate_control_event({"processing_rate_hz": -1.0})
    assert ok is False
    assert cycle.processing_rate_hz == prior_rate
    # No cycle.rates event published for failures.
    entries = await bus.read("cycle.out", last_id="0", count=20)
    rates = [e for _, e in entries if e.type == "cycle.rates"]
    assert len(rates) == 0


@pytest.mark.asyncio
async def test_apply_rate_control_rejects_non_numeric(cycle_with_fakes):
    cycle, bus, _ = cycle_with_fakes
    ok = await cycle.apply_rate_control_event({"processing_rate_hz": "fast"})
    assert ok is False


@pytest.mark.asyncio
async def test_consume_control_events_picks_up_bus_event(cycle_with_fakes):
    cycle, bus, _ = cycle_with_fakes
    # Publish a control event directly.
    await bus.publish(Event(
        source="cycle",
        type="cycle.set_rates",
        payload={"processing_rate_hz": 8.0, "experiential_rate_hz": 4.0},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    ))
    # cycle.publish writes to cycle.out (per module_stream), but the
    # control stream is cycle.control — publish there too via direct
    # xadd to bypass module_stream routing.
    import json as _j
    await bus.client.xadd(
        "cycle.control",
        {
            "source": "cycle",
            "type": "cycle.set_rates",
            "salience": "0.5",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "causal_parent": "",
            "payload": _j.dumps({"processing_rate_hz": 11.0}),
        },
    )
    await cycle.consume_control_events()
    assert cycle.processing_rate_hz == 11.0


@pytest.mark.asyncio
async def test_ratio_3_to_1_over_30_ticks(cycle_with_fakes):
    cycle, _, _ = cycle_with_fakes
    cycle.set_processing_rate(3.0)
    cycle.set_experiential_rate(1.0)
    promoted = 0
    for _ in range(30):
        if (await cycle.tick()).is_experiential:
            promoted += 1
    # 30 * (1/3) = 10, allow ±2 slack
    assert 8 <= promoted <= 12


@pytest.mark.asyncio
async def test_ratio_100_to_1_over_200_ticks(cycle_with_fakes):
    cycle, _, _ = cycle_with_fakes
    cycle.set_processing_rate(100.0)
    cycle.set_experiential_rate(1.0)
    promoted = 0
    for _ in range(200):
        if (await cycle.tick()).is_experiential:
            promoted += 1
    # 200 * (1/100) = 2, allow 0..4
    assert 0 <= promoted <= 4
