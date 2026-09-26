# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import math
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle import CognitiveCycle
from kaine.cycle.access_rate import AccessRateConfig, AccessRateController
from tests._fakes import FakeClock, FakeRegistry, FakeSyneidesis


@pytest.fixture
async def adaptive_cycle():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    clock = FakeClock()
    syn = FakeSyneidesis()
    reg = FakeRegistry([])

    _arousal = [0.3]

    def arousal_provider():
        return _arousal[0]

    def set_arousal(value: float) -> None:
        _arousal[0] = value

    access_rate = AccessRateController(AccessRateConfig())
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syn,
        registry=reg,
        processing_rate_hz=10.0,
        experiential_rate_hz=3.333,
        clock=clock,
        sleep=clock.sleep,
        access_rate=access_rate,
        arousal_provider=arousal_provider,
    )
    yield cycle, bus, clock, syn, reg, access_rate, set_arousal
    await bus.close()


@pytest.mark.asyncio
async def test_calm_entity_broadcasts_at_resting_rate(adaptive_cycle):
    cycle, *_rest = adaptive_cycle
    cycle._arousal_provider()  # type: ignore[misc]
    promoted = 0
    for _ in range(300):
        result = await cycle.tick()
        if result.is_experiential:
            promoted += 1
    assert 95 <= promoted <= 105, f"expected ~100 experiential ticks, got {promoted}"


@pytest.mark.asyncio
async def test_full_arousal_broadcasts_every_tick(adaptive_cycle):
    cycle, *_rest, set_arousal = adaptive_cycle
    set_arousal(1.0)
    for i in range(100):
        result = await cycle.tick()
        assert result.is_experiential, f"tick {i} was not experiential"


@pytest.mark.asyncio
async def test_salient_report_raises_access_then_decays(adaptive_cycle):
    cycle, bus, _clock, _syn, reg, _access_rate, set_arousal = adaptive_cycle
    set_arousal(0.3)
    reg.set_streams(["topos.out"])
    await bus.publish(
        Event(
            source="topos",
            type="report",
            payload={},
            salience=1.0,
            timestamp=datetime.now(timezone.utc),
        )
    )

    result = await cycle.tick()
    assert cycle.access_drive == pytest.approx(1.0)
    assert result.is_experiential

    for n in range(1, 21):
        await cycle.tick()
        expected = math.exp(-0.1 * n)
        assert cycle.access_drive == pytest.approx(expected, abs=1e-9)

    for _ in range(30):
        await cycle.tick()
    assert cycle.access_drive < 0.05


@pytest.mark.asyncio
async def test_cycle_telemetry_is_not_a_report(adaptive_cycle):
    cycle, bus, _clock, _syn, reg, _access_rate, _set_arousal = adaptive_cycle
    reg.set_streams(["cycle.out"])
    await bus.publish(
        Event(
            source="cycle",
            type="cycle.tick",
            payload={},
            salience=1.0,
            timestamp=datetime.now(timezone.utc),
        )
    )
    await cycle.tick()
    assert cycle.access_drive == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_disabled_adaptation_is_fixed_rate(adaptive_cycle):
    cycle, *_rest, _access_rate, set_arousal = adaptive_cycle
    cycle._access_rate = AccessRateController(AccessRateConfig(enabled=False))
    set_arousal(1.0)
    promoted = 0
    for _ in range(100):
        result = await cycle.tick()
        if result.is_experiential:
            promoted += 1
    assert 30 <= promoted <= 36, f"expected ~33 fixed-rate broadcasts, got {promoted}"
    assert cycle.access_drive == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_operator_lowers_resting_rate(adaptive_cycle):
    cycle, *_rest, set_arousal = adaptive_cycle
    set_arousal(1.0)
    cycle.set_experiential_rate(2.0)
    for _ in range(50):
        await cycle.tick()
        assert 2.0 <= cycle.effective_experiential_rate_hz <= 10.0
    assert cycle.experiential_rate_hz == pytest.approx(2.0)


@pytest.mark.asyncio
async def test_tick_payload_carries_effective_rate_and_drive(adaptive_cycle):
    cycle, bus, _clock, _syn, reg, _access_rate, set_arousal = adaptive_cycle
    set_arousal(1.0)
    reg.set_streams(["topos.out"])
    await bus.publish(
        Event(
            source="topos",
            type="report",
            payload={},
            salience=1.0,
            timestamp=datetime.now(timezone.utc),
        )
    )
    await cycle.tick()
    entries, _last = await bus.read_entries("cycle.out", last_id="0", count=100, block_ms=0)
    assert len(entries) >= 1
    _entry_id, tick_event = entries[-1]
    assert tick_event.type == "cycle.tick"
    assert tick_event.payload["experiential_rate_hz"] == pytest.approx(10.0)
    assert tick_event.payload["access_drive"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_two_cycles_are_deterministic():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    arousal_sequence = [0.3, 0.3, 1.0, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]

    def make_cycle():
        client = fakeredis.FakeRedis(decode_responses=True)
        bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
        clock = FakeClock()
        syn = FakeSyneidesis()
        reg = FakeRegistry([])
        idx = [0]

        def arousal_provider():
            value = arousal_sequence[idx[0]]
            idx[0] += 1
            return value

        access_rate = AccessRateController(AccessRateConfig())
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=syn,
            registry=reg,
            processing_rate_hz=10.0,
            experiential_rate_hz=3.333,
            clock=clock,
            sleep=clock.sleep,
            access_rate=access_rate,
            arousal_provider=arousal_provider,
            deterministic=True,
        )
        return cycle, bus

    cycle_a, bus_a = make_cycle()
    cycle_b, bus_b = make_cycle()
    try:
        results_a = [await cycle_a.tick() for _ in range(10)]
        results_b = [await cycle_b.tick() for _ in range(10)]
        assert [r.is_experiential for r in results_a] == [
            r.is_experiential for r in results_b
        ]
        assert [cycle_a.access_drive for _ in range(10)] == [
            cycle_b.access_drive for _ in range(10)
        ]
    finally:
        await bus_a.close()
        await bus_b.close()
