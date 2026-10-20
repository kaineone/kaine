# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>


import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle import CognitiveCycle
from kaine.cycle.types import WorkspaceSnapshot
from tests._fakes import FakeClock, FakeRegistry, FakeWorkspace


@pytest.fixture
async def cycle_with_fakes():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    clock = FakeClock()
    syn = FakeWorkspace()
    reg = FakeRegistry([])
    cycle = CognitiveCycle(
        bus=bus,
        workspace=syn,
        registry=reg,
        processing_rate_hz=5.0,
        experiential_rate_hz=5.0,
        clock=clock,
        sleep=clock.sleep,
    )
    yield cycle, bus, clock, syn, reg
    await bus.close()


async def _cheap_select(clock, events, context):
    clock.advance(0.001)
    return WorkspaceSnapshot(tick_index=context["tick_index"])


@pytest.mark.asyncio
async def test_run_forever_slip_includes_pacing_wait_oversleep(cycle_with_fakes):
    cycle, bus, clock, syn, _reg = cycle_with_fakes
    requested_sleeps: list[float] = []

    async def cheap_select(events, context):
        return await _cheap_select(clock, events, context)

    async def oversleeping_sleep(seconds: float) -> None:
        requested_sleeps.append(seconds)
        clock.advance(seconds + 0.003)

    syn.select = cheap_select  # type: ignore[assignment]
    cycle._sleep = oversleeping_sleep

    await cycle.run_forever(max_ticks=5)

    entries = await bus.read("cycle.out", last_id="0")
    assert len(entries) == 5
    slips = [event.payload["slip_ms"] for _entry_id, event in entries]
    assert slips[0] == 0.0
    for slip in slips[1:]:
        assert slip == pytest.approx(3.0, rel=1e-2)

    assert len(requested_sleeps) == 4
    for requested in requested_sleeps:
        assert requested == pytest.approx(0.199, rel=1e-3)

    stats = cycle.pacing_stats
    assert stats["overrun_ticks"] == 0
    assert stats["mean_slip_ms"] == pytest.approx(3.0 * 4 / 5, rel=1e-2)


@pytest.mark.asyncio
async def test_first_tick_reports_no_slip(cycle_with_fakes):
    cycle, _bus, clock, syn, _reg = cycle_with_fakes

    async def cheap_select(events, context):
        return await _cheap_select(clock, events, context)

    syn.select = cheap_select  # type: ignore[assignment]
    result = await cycle.tick()
    assert result.slip_ms == 0.0


@pytest.mark.asyncio
async def test_pause_clears_tick_start_reference(cycle_with_fakes):
    cycle, _bus, clock, syn, _reg = cycle_with_fakes

    async def cheap_select(events, context):
        return await _cheap_select(clock, events, context)

    syn.select = cheap_select  # type: ignore[assignment]
    await cycle.tick()
    await cycle.pause()
    clock.advance(10.0)
    await cycle.resume()
    result = await cycle.tick()
    assert result.slip_ms == 0.0


@pytest.mark.asyncio
async def test_overrun_counts_body_not_start_delay(cycle_with_fakes):
    cycle, _bus, clock, syn, _reg = cycle_with_fakes
    cycle.set_processing_rate(5.0)  # 200 ms target

    async def slow_select(events, context):
        clock.advance(0.350)  # 350 ms body, exceeds 200 ms budget
        return WorkspaceSnapshot(tick_index=context["tick_index"])

    async def cheap_select(events, context):
        return await _cheap_select(clock, events, context)

    syn.select = cheap_select  # type: ignore[assignment]
    await cycle.tick()
    assert cycle.pacing_stats["overrun_ticks"] == 0

    clock.advance(0.300)  # 300 ms gap between tick starts
    result = await cycle.tick()
    assert cycle.pacing_stats["overrun_ticks"] == 0
    assert result.slip_ms == pytest.approx(100.0, rel=1e-2)

    syn.select = slow_select  # type: ignore[assignment]
    await cycle.tick()
    assert cycle.pacing_stats["overrun_ticks"] == 1


@pytest.mark.asyncio
async def test_tick_result_slip_matches_event_payload(cycle_with_fakes):
    cycle, bus, clock, syn, _reg = cycle_with_fakes

    async def cheap_select(events, context):
        return await _cheap_select(clock, events, context)

    syn.select = cheap_select  # type: ignore[assignment]

    result = await cycle.tick()
    entries = await bus.read("cycle.out", last_id="0")
    assert entries
    _, first_event = entries[0]
    assert first_event.payload["slip_ms"] == pytest.approx(result.slip_ms, abs=1e-6)

    clock.advance(0.300)
    result = await cycle.tick()
    entries = await bus.read("cycle.out", last_id="0")
    _, second_event = entries[-1]
    assert second_event.payload["slip_ms"] == pytest.approx(result.slip_ms, abs=1e-6)
