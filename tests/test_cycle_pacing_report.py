# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phase 3 of biological-timing-and-dilation: the honest pacing report.

When the configured tick rate (or a ``time_scale > 1`` target) overruns what the
hardware can sustain, the shortfall must be VISIBLE — surfaced as an
achieved-rate / slip field via ``CognitiveCycle.pacing_stats`` (and from there
into runtime.json + Nexus health), never silently capped or faked. These tests
assert:

  * a sustainable rate reports ``overrunning=False`` and achieved ≈ target;
  * an unsustainable target (slow ticks) reports ``overrunning=True`` with the
    achieved rate honestly BELOW target and slip recorded — not silently capped;
  * the report is inert (no overrun) at the behavior-preserving default.
"""
from __future__ import annotations

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle import CognitiveCycle
from kaine.cycle.types import WorkspaceSnapshot
from tests._fakes import FakeClock, FakeRegistry, FakeSyneidesis


@pytest.fixture
async def make_cycle():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    created: list[AsyncBus] = []

    async def _make(*, processing_rate_hz: float = 5.0, time_scale: float = 1.0):
        client = fakeredis.FakeRedis(decode_responses=True)
        bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
        created.append(bus)
        clock = FakeClock()
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=FakeSyneidesis(),
            registry=FakeRegistry([]),
            processing_rate_hz=processing_rate_hz,
            experiential_rate_hz=processing_rate_hz,
            clock=clock,
            sleep=clock.sleep,
            time_scale=time_scale,
        )
        return cycle, clock

    yield _make
    for bus in created:
        await bus.close()


@pytest.mark.asyncio
async def test_pacing_report_empty_before_any_tick(make_cycle):
    cycle, _clock = await make_cycle(processing_rate_hz=5.0)
    stats = cycle.pacing_stats
    assert stats["window_ticks"] == 0
    assert stats["achieved_rate_hz"] is None
    assert stats["overrunning"] is False
    # Target rate is processing_rate * time_scale even before a tick.
    assert stats["target_rate_hz"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_sustainable_rate_is_not_overrunning(make_cycle):
    cycle, clock = await make_cycle(processing_rate_hz=5.0)

    # Each tick costs 1 ms of fake wall time — well under the 200 ms budget.
    async def cheap_select(events, context):
        clock.advance(0.001)
        return WorkspaceSnapshot(tick_index=context["tick_index"])

    cycle._syneidesis.select = cheap_select  # type: ignore[assignment]
    for _ in range(10):
        await cycle.tick()

    stats = cycle.pacing_stats
    assert stats["window_ticks"] == 10
    assert stats["overrunning"] is False
    assert stats["overrun_ticks"] == 0
    # Achieved rate holds the target (effective period = the target budget).
    assert stats["achieved_rate_hz"] == pytest.approx(5.0, rel=1e-3)
    assert stats["mean_slip_ms"] == pytest.approx(0.0, abs=1e-6)


@pytest.mark.asyncio
async def test_unsustainable_target_surfaces_shortfall_not_silently_capped(make_cycle):
    # Target 5 Hz = 200 ms budget, but each tick takes 500 ms of fake wall time
    # → a sustained overrun the cycle cannot hold.
    cycle, clock = await make_cycle(processing_rate_hz=5.0)

    async def slow_select(events, context):
        clock.advance(0.500)  # 500 ms — 2.5x over the 200 ms budget
        return WorkspaceSnapshot(tick_index=context["tick_index"])

    cycle._syneidesis.select = slow_select  # type: ignore[assignment]
    for _ in range(8):
        await cycle.tick()

    stats = cycle.pacing_stats
    # The shortfall is VISIBLE, not silently capped:
    assert stats["overrunning"] is True
    assert stats["overrun_ticks"] == 8
    # Achieved rate is honestly BELOW the target (≈ 1/0.5 s = 2 Hz, not 5 Hz).
    assert stats["target_rate_hz"] == pytest.approx(5.0)
    assert stats["achieved_rate_hz"] == pytest.approx(2.0, rel=1e-2)
    assert stats["achieved_rate_hz"] < stats["target_rate_hz"]
    # Slip recorded (≈ 500 - 200 = 300 ms per tick).
    assert stats["mean_slip_ms"] == pytest.approx(300.0, rel=1e-2)
    assert stats["max_slip_ms"] == pytest.approx(300.0, rel=1e-2)


@pytest.mark.asyncio
async def test_time_scale_gt1_raises_target_and_overrun_is_visible(make_cycle):
    # time_scale=2.0 ⇒ target real rate = 5 * 2 = 10 Hz (100 ms real budget).
    # Each tick takes 300 ms fake wall time ⇒ cannot hold the dilated target.
    cycle, clock = await make_cycle(processing_rate_hz=5.0, time_scale=2.0)

    async def slow_select(events, context):
        clock.advance(0.300)
        return WorkspaceSnapshot(tick_index=context["tick_index"])

    cycle._syneidesis.select = slow_select  # type: ignore[assignment]
    for _ in range(6):
        await cycle.tick()

    stats = cycle.pacing_stats
    assert stats["time_scale"] == pytest.approx(2.0)
    assert stats["target_rate_hz"] == pytest.approx(10.0)
    assert stats["overrunning"] is True
    # The >1 target was ATTEMPTED then honestly throttled, not silently capped.
    assert stats["achieved_rate_hz"] == pytest.approx(1.0 / 0.300, rel=1e-2)
    assert stats["achieved_rate_hz"] < stats["target_rate_hz"]
