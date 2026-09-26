# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the running local womb presence publisher."""
from __future__ import annotations

import asyncio

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.womb_presence import (
    PRESENCE_SOURCE,
    PRESENCE_TYPE,
    WombPresencePublisher,
)
from kaine.modules.topos.feed import WombClock


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def test_no_payload_before_any_delivery():
    clock = WombClock(lived_offset_seconds=0.0, clock=FakeClock())
    publisher = WombPresencePublisher(None, clock)
    assert publisher.presence_payload() is None


def test_no_payload_with_only_video_delivered():
    clock = WombClock(lived_offset_seconds=0.0, clock=FakeClock())
    clock.mark_delivered("video", 5)
    publisher = WombPresencePublisher(None, clock)
    assert publisher.presence_payload() is None


def test_payload_once_both_surfaces_delivered_recently():
    fake = FakeClock(0.0)
    clock = WombClock(lived_offset_seconds=0.0, clock=fake)
    clock.mark_delivered("video", 7)
    clock.mark_delivered("audio", 3)
    publisher = WombPresencePublisher(None, clock, max_staleness_s=2.0)
    assert publisher.presence_payload() == {
        "provider": "local",
        "frame_index": 7,
    }


def test_payload_none_when_audio_goes_stale():
    fake = FakeClock(0.0)
    clock = WombClock(lived_offset_seconds=0.0, clock=fake)
    clock.mark_delivered("video", 7)
    clock.mark_delivered("audio", 3)
    publisher = WombPresencePublisher(None, clock, max_staleness_s=2.0)
    fake.advance(3.0)
    # Video keeps delivering; only audio has gone quiet. The womb must be
    # seen AND heard, so there is no presence.
    clock.mark_delivered("video", 97)
    assert publisher.presence_payload() is None


def test_payload_none_when_video_goes_stale():
    fake = FakeClock(0.0)
    clock = WombClock(lived_offset_seconds=0.0, clock=fake)
    clock.mark_delivered("video", 7)
    clock.mark_delivered("audio", 3)
    publisher = WombPresencePublisher(None, clock, max_staleness_s=2.0)
    fake.advance(3.0)
    clock.mark_delivered("audio", 97)
    assert publisher.presence_payload() is None


@pytest.mark.parametrize(
    "period_s,max_staleness_s",
    [
        (0.0, 1.0),
        (-1.0, 1.0),
        (float("nan"), 1.0),
        (1.0, 0.0),
        (1.0, -1.0),
        (1.0, float("nan")),
    ],
)
def test_constructor_rejects_bad_timing(period_s, max_staleness_s):
    with pytest.raises(ValueError):
        WombPresencePublisher(
            None,
            None,  # type: ignore[arg-type]
            period_s=period_s,
            max_staleness_s=max_staleness_s,
        )


@pytest.mark.asyncio
async def test_run_publishes_presence_events_while_fresh(bus):
    fake = FakeClock(0.0)
    clock = WombClock(lived_offset_seconds=0.0, clock=fake)
    clock.mark_delivered("video", 9)
    clock.mark_delivered("audio", 4)

    publisher = WombPresencePublisher(bus, clock, period_s=0.01, max_staleness_s=2.0)
    stop = asyncio.Event()
    task = asyncio.create_task(publisher.run(stop))

    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    entries = await bus.range("gestation.out", start="-", end="+", count=None)
    presence_entries = [
        (_id, e) for _id, e in entries if getattr(e, "type", None) == PRESENCE_TYPE
    ]
    assert len(presence_entries) >= 1
    for _id, event in presence_entries:
        assert getattr(event, "source", None) == PRESENCE_SOURCE
        payload = getattr(event, "payload", {})
        assert payload == {"provider": "local", "frame_index": 9}


@pytest.mark.asyncio
async def test_run_survives_publish_exception_and_stops_on_event():
    class RaisingBus:
        async def publish(self, event: Event) -> None:
            raise RuntimeError("publish broken")

    fake = FakeClock(0.0)
    clock = WombClock(lived_offset_seconds=0.0, clock=fake)
    clock.mark_delivered("video", 1)
    clock.mark_delivered("audio", 1)

    publisher = WombPresencePublisher(RaisingBus(), clock, period_s=0.001)
    stop = asyncio.Event()
    task = asyncio.create_task(publisher.run(stop))

    await asyncio.sleep(0.02)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    assert task.done()
    assert task.exception() is None
