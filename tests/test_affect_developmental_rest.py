# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.modules.affect import Affect


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _make_affect(bus: AsyncBus, t: list[float], probe=None):
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    affect._development_probe = probe
    lp: list[float] = [0.0]
    nb: list[float] = [0.0]
    affect._progress = lambda: (lp[0], 0.0)
    affect._alert_excess = lambda: nb[0]
    return affect, lp, nb


async def _tick(affect, t, lp, nb, *, boredom=0.95, restlessness=None):
    affect.drives.boredom.value = boredom
    if restlessness is not None:
        affect.drives.restlessness.value = restlessness
    t[0] += 1.0
    await affect._tick()


async def _read_events(bus: AsyncBus) -> list[Event]:
    return [ev for _id, ev in await bus.read("affect.out", last_id="0", count=5000)]


def _rest_requests(events: list[Event]) -> list[Event]:
    return [ev for ev in events if ev.type == "affect.rest_request"]


def _abandoned_stalled(events: list[Event]) -> list[Event]:
    return [
        ev
        for ev in events
        if ev.type == "affect.goal"
        and ev.payload.get("action") == "abandoned"
        and ev.payload.get("reason") == "stalled"
    ]


@pytest.mark.asyncio
async def test_developmental_rest_request_on_spent_stimulus(bus):
    t = [0.0]
    affect, lp, nb = _make_affect(bus, t, probe=lambda: True)
    for _ in range(605):
        lp[0] = 0.0
        nb[0] = 0.0
        await _tick(affect, t, lp, nb, boredom=0.95)
    events = await _read_events(bus)
    rests = _rest_requests(events)
    assert len(rests) == 1
    assert rests[0].payload["reason"] == "stimulus_spent"
    assert rests[0].payload["drive"] == "boredom"
    assert rests[0].payload["stall_s"] >= 600.0
    assert _abandoned_stalled(events)


@pytest.mark.asyncio
async def test_no_rest_request_when_lp_engagement_during_stall(bus):
    t = [0.0]
    affect, lp, nb = _make_affect(bus, t, probe=lambda: True)
    for i in range(605):
        lp[0] = 0.2 if i == 300 else 0.0
        nb[0] = 0.0
        await _tick(affect, t, lp, nb, boredom=0.95)
    events = await _read_events(bus)
    assert _rest_requests(events) == []
    assert _abandoned_stalled(events)


@pytest.mark.asyncio
async def test_no_rest_request_when_alert_excess_during_stall(bus):
    t = [0.0]
    affect, lp, nb = _make_affect(bus, t, probe=lambda: True)
    for i in range(605):
        lp[0] = 0.0
        nb[0] = 0.3 if i == 300 else 0.0
        await _tick(affect, t, lp, nb, boredom=0.95)
    events = await _read_events(bus)
    assert _rest_requests(events) == []
    assert _abandoned_stalled(events)


@pytest.mark.asyncio
async def test_rest_request_when_engagement_preceded_stall_clock(bus):
    t = [0.0]
    affect, lp, nb = _make_affect(bus, t, probe=lambda: True)
    for _ in range(10):
        lp[0] = 0.2
        nb[0] = 0.0
        await _tick(affect, t, lp, nb, boredom=0.0)
    for _ in range(605):
        lp[0] = 0.0
        nb[0] = 0.0
        await _tick(affect, t, lp, nb, boredom=0.95)
    events = await _read_events(bus)
    rests = _rest_requests(events)
    assert len(rests) == 1
    assert rests[0].payload["reason"] == "stimulus_spent"
    assert _abandoned_stalled(events)


@pytest.mark.asyncio
async def test_no_rest_request_when_development_probe_false(bus):
    t = [0.0]
    affect, lp, nb = _make_affect(bus, t, probe=lambda: False)
    for _ in range(605):
        lp[0] = 0.0
        nb[0] = 0.0
        await _tick(affect, t, lp, nb, boredom=0.95)
    events = await _read_events(bus)
    assert _rest_requests(events) == []
    assert _abandoned_stalled(events)


@pytest.mark.asyncio
async def test_no_rest_request_without_development_probe(bus):
    t = [0.0]
    affect, lp, nb = _make_affect(bus, t, probe=None)
    for _ in range(605):
        lp[0] = 0.0
        nb[0] = 0.0
        await _tick(affect, t, lp, nb, boredom=0.95)
    events = await _read_events(bus)
    assert _rest_requests(events) == []
    assert _abandoned_stalled(events)


@pytest.mark.asyncio
async def test_rest_request_when_development_probe_raises(bus):
    t = [0.0]

    def _raise():
        raise RuntimeError("development probe failure")

    affect, lp, nb = _make_affect(bus, t, probe=_raise)
    for _ in range(605):
        lp[0] = 0.0
        nb[0] = 0.0
        await _tick(affect, t, lp, nb, boredom=0.95)
    events = await _read_events(bus)
    rests = _rest_requests(events)
    assert len(rests) == 1
    assert rests[0].payload["reason"] == "stimulus_spent"
    assert _abandoned_stalled(events)


@pytest.mark.asyncio
async def test_no_rest_request_for_stalled_non_boredom_drive(bus):
    t = [0.0]
    affect, lp, nb = _make_affect(bus, t, probe=lambda: True)
    for _ in range(605):
        lp[0] = 0.0
        nb[0] = 0.0
        await _tick(affect, t, lp, nb, boredom=0.0, restlessness=0.95)
    events = await _read_events(bus)
    assert _rest_requests(events) == []
    assert _abandoned_stalled(events)


@pytest.mark.asyncio
async def test_serialize_boredom_engaged_elapsed(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    assert affect.serialize()["boredom_engaged_elapsed"] is None
    t[0] = 100.0
    affect._boredom_engaged_at = 87.5
    assert affect.serialize()["boredom_engaged_elapsed"] == pytest.approx(12.5)


@pytest.mark.asyncio
async def test_deserialize_boredom_engaged_elapsed(bus):
    t = [50.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    affect.deserialize({"boredom_engaged_elapsed": 12.5})
    assert affect._boredom_engaged_at == pytest.approx(37.5)

    affect.deserialize({"boredom_engaged_elapsed": None})
    assert affect._boredom_engaged_at is None

    fresh = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    fresh.deserialize({})
    assert fresh._boredom_engaged_at == pytest.approx(t[0])

    for bad in ("x", True, -1.0, float("nan"), float("inf")):
        a = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
        a.deserialize({"boredom_engaged_elapsed": bad})
        assert a._boredom_engaged_at == pytest.approx(t[0])
