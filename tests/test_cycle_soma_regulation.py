# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for CycleEngine.consume_soma_regulation (kaine/cycle/engine.py).

The cycle engine drains ``soma.regulation`` advisories from ``soma.out`` and
acts on them within safe bounds:

* ``reduce_rate`` lowers the processing rate (clamped to configured bounds)
* ``shed_module`` requests a low-priority module suspension via the registry
* ``request_maintenance`` latches the advisory ``maintenance_requested`` flag
* a missing ``action`` logs a warning and does not raise
* an unknown ``action`` is ignored gracefully (no raise)

The bus is seeded with fakeredis so no real Redis is required.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.cycle import CognitiveCycle
from tests._fakes import FakeClock, FakeRegistry, FakeSyneidesis


class SheddableRegistry(FakeRegistry):
    """FakeRegistry that records request_shed_low_priority calls."""

    def __init__(self, streams: list[str]) -> None:
        super().__init__(streams)
        self.shed_calls = 0

    def request_shed_low_priority(self) -> None:
        self.shed_calls += 1


@pytest.fixture
async def cycle_with_fakes():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    clock = FakeClock()
    syn = FakeSyneidesis()
    reg = SheddableRegistry([])
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syn,
        registry=reg,
        processing_rate_hz=5.0,
        experiential_rate_hz=5.0,
        clock=clock,
        sleep=clock.sleep,
    )
    yield cycle, bus, reg
    await bus.close()


async def _publish_regulation(bus: AsyncBus, payload: dict) -> None:
    event = validate_event(
        source="soma",
        type="soma.regulation",
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(event)


@pytest.mark.asyncio
async def test_reduce_rate_lowers_processing_rate(cycle_with_fakes):
    cycle, bus, _reg = cycle_with_fakes
    before = cycle.processing_rate_hz
    await _publish_regulation(
        bus, {"action": "reduce_rate", "reason": "stress", "severity": 1}
    )
    await cycle.consume_soma_regulation()
    after = cycle.processing_rate_hz
    assert after < before
    assert after == pytest.approx(before * cycle._REDUCE_RATE_FACTOR)


@pytest.mark.asyncio
async def test_reduce_rate_clamped_to_floor(cycle_with_fakes):
    cycle, bus, _reg = cycle_with_fakes
    # Drop the rate near the floor, then a reduce_rate must not go below it.
    cycle.set_processing_rate(cycle._MIN_PROCESSING_RATE_HZ)
    await _publish_regulation(bus, {"action": "reduce_rate"})
    await cycle.consume_soma_regulation()
    assert cycle.processing_rate_hz >= cycle._MIN_PROCESSING_RATE_HZ
    assert cycle.processing_rate_hz == pytest.approx(cycle._MIN_PROCESSING_RATE_HZ)


@pytest.mark.asyncio
async def test_shed_module_calls_registry(cycle_with_fakes):
    cycle, bus, reg = cycle_with_fakes
    assert reg.shed_calls == 0
    await _publish_regulation(
        bus, {"action": "shed_module", "reason": "stress", "severity": 2}
    )
    await cycle.consume_soma_regulation()
    assert reg.shed_calls == 1


@pytest.mark.asyncio
async def test_request_maintenance_sets_flag(cycle_with_fakes):
    cycle, bus, _reg = cycle_with_fakes
    assert cycle.maintenance_requested is False
    await _publish_regulation(
        bus, {"action": "request_maintenance", "reason": "stress", "severity": 3}
    )
    await cycle.consume_soma_regulation()
    assert cycle.maintenance_requested is True


@pytest.mark.asyncio
async def test_missing_action_warns_and_does_not_raise(cycle_with_fakes, caplog):
    cycle, bus, _reg = cycle_with_fakes
    await _publish_regulation(bus, {"reason": "no action field"})
    with caplog.at_level("WARNING"):
        await cycle.consume_soma_regulation()  # must not raise
    assert any("missing 'action'" in rec.message for rec in caplog.records)
    # No side effects from a malformed advisory.
    assert cycle.maintenance_requested is False


@pytest.mark.asyncio
async def test_unknown_action_ignored_without_raise(cycle_with_fakes):
    cycle, bus, reg = cycle_with_fakes
    before = cycle.processing_rate_hz
    await _publish_regulation(bus, {"action": "teleport", "severity": 9})
    await cycle.consume_soma_regulation()  # must not raise
    # No recognized side effects fire for an unknown action.
    assert cycle.processing_rate_hz == before
    assert reg.shed_calls == 0
    assert cycle.maintenance_requested is False


@pytest.mark.asyncio
async def test_withheld_event_does_not_actuate(cycle_with_fakes):
    """A warm-up soma.regulation.withheld record is non-actuating: the cycle
    must not throttle, shed, or schedule maintenance in response to it."""
    cycle, bus, reg = cycle_with_fakes
    withheld = validate_event(
        source="soma",
        type="soma.regulation.withheld",
        payload={
            "would_be_action": "reduce_rate",
            "prediction_error": 1.1,
            "sustain_elapsed_s": 42.0,
            "severity": 1,
            "reason": "warmup",
        },
        salience=0.1,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(withheld)
    before = cycle.processing_rate_hz
    await cycle.consume_soma_regulation()  # must not raise
    assert cycle.processing_rate_hz == before
    assert reg.shed_calls == 0
    assert cycle.maintenance_requested is False


@pytest.mark.asyncio
async def test_non_regulation_events_ignored(cycle_with_fakes):
    cycle, bus, _reg = cycle_with_fakes
    other = validate_event(
        source="soma",
        type="soma.fatigue",
        payload={"value": 1.0, "threshold": 100.0, "crossed": False},
        salience=0.1,
        timestamp=datetime.now(timezone.utc),
    )
    await bus.publish(other)
    before = cycle.processing_rate_hz
    await cycle.consume_soma_regulation()
    assert cycle.processing_rate_hz == before
    assert cycle.maintenance_requested is False
