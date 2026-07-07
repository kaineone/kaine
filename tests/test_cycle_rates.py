# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>


import pytest

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
    syn = FakeSyneidesis()
    reg = FakeRegistry([])
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syn,
        registry=reg,
        processing_rate_hz=5.0,
        experiential_rate_hz=5.0,
        clock=clock,
        sleep=clock.sleep,
    )
    yield cycle, bus, clock, syn, reg
    await bus.close()


@pytest.mark.asyncio
async def test_tick_records_target_and_wall_durations(cycle_with_fakes):
    cycle, _bus, clock, _syn, _reg = cycle_with_fakes

    # Each FakeSyneidesis.select call costs 1 ms of fake time.
    async def select_with_cost(events, context):
        clock.advance(0.001)
        from kaine.cycle.types import WorkspaceSnapshot
        return WorkspaceSnapshot(tick_index=context["tick_index"])

    cycle._syneidesis.select = select_with_cost  # type: ignore[assignment]
    result = await cycle.tick()
    assert result.target_duration_ms == pytest.approx(200.0, rel=1e-3)
    assert result.wall_duration_ms == pytest.approx(1.0, rel=1e-3)
    assert result.slip_ms == 0.0


@pytest.mark.asyncio
async def test_slip_recorded_when_tick_overruns(cycle_with_fakes):
    cycle, _bus, clock, _syn, _reg = cycle_with_fakes
    cycle.set_processing_rate(5.0)  # 200 ms target

    async def slow_select(events, context):
        clock.advance(0.350)  # 350 ms — overshoots 200 ms target
        from kaine.cycle.types import WorkspaceSnapshot
        return WorkspaceSnapshot(tick_index=context["tick_index"])

    cycle._syneidesis.select = slow_select  # type: ignore[assignment]
    result = await cycle.tick()
    assert result.wall_duration_ms >= 350.0
    assert result.slip_ms >= 150.0


@pytest.mark.asyncio
async def test_half_rate_experiential_promotes_roughly_half(cycle_with_fakes):
    cycle, _bus, _clock, _syn, _reg = cycle_with_fakes
    cycle.set_processing_rate(10.0)
    cycle.set_experiential_rate(5.0)

    promoted = 0
    for _ in range(100):
        result = await cycle.tick()
        if result.is_experiential:
            promoted += 1
    assert 45 <= promoted <= 55, f"expected ~50 experiential ticks, got {promoted}"


@pytest.mark.asyncio
async def test_equal_rates_promote_every_tick(cycle_with_fakes):
    cycle, _bus, _clock, _syn, _reg = cycle_with_fakes
    cycle.set_processing_rate(7.0)
    cycle.set_experiential_rate(7.0)

    results = [await cycle.tick() for _ in range(20)]
    assert all(r.is_experiential for r in results)


@pytest.mark.asyncio
async def test_arbitrary_float_ratio_works(cycle_with_fakes):
    cycle, _bus, _clock, _syn, _reg = cycle_with_fakes
    cycle.set_processing_rate(3.0)
    cycle.set_experiential_rate(1.0)
    promoted = 0
    for _ in range(30):
        if (await cycle.tick()).is_experiential:
            promoted += 1
    # 1/3 of 30 = 10, accumulator drift can give 10 or 11
    assert 9 <= promoted <= 11, f"got {promoted}"


@pytest.mark.asyncio
async def test_pause_blocks_run_forever(cycle_with_fakes):
    cycle, _bus, _clock, _syn, _reg = cycle_with_fakes
    await cycle.pause()
    assert not cycle._paused.is_set()


@pytest.mark.asyncio
async def test_resume_unblocks_run_forever(cycle_with_fakes):
    cycle, _bus, _clock, _syn, _reg = cycle_with_fakes
    await cycle.pause()
    await cycle.resume()
    assert cycle._paused.is_set()


@pytest.mark.asyncio
async def test_shutdown_releases_paused_run_loop(cycle_with_fakes):
    cycle, _bus, _clock, _syn, _reg = cycle_with_fakes
    await cycle.pause()
    await cycle.shutdown()
    assert cycle._stopped
    assert cycle._paused.is_set()


@pytest.mark.asyncio
async def test_invalid_rate_rejected(cycle_with_fakes):
    cycle, *_ = cycle_with_fakes
    with pytest.raises(ValueError):
        cycle.set_processing_rate(0.0)
    with pytest.raises(ValueError):
        cycle.set_experiential_rate(-1.0)
