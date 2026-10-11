# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.evaluation._base import StreamSubscriberObserver

fakeredis = pytest.importorskip("fakeredis.aioredis")


def _make_bus() -> AsyncBus:
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


class _ProbeObserver(StreamSubscriberObserver):
    name = "probe"
    streams = ("soma.out",)

    def __init__(
        self, bus: AsyncBus, seen: list[str], *, poll_interval_s: float
    ) -> None:
        super().__init__(bus, poll_interval_s=poll_interval_s)
        self.seen = seen

    async def handle(self, stream: str, entry_id: str, event: Event) -> None:
        self.seen.append(event.type)


@pytest.mark.asyncio
async def test_stream_observer_advances_past_an_undecodable_batch() -> None:
    bus = _make_bus()
    seen: list[str] = []
    observer = _ProbeObserver(bus, seen, poll_interval_s=0.01)

    for _ in range(70):
        await bus.client.xadd("soma.out", {"junk": "x"})

    event_id = await bus.publish(
        Event(
            source="soma",
            type="soma.report",
            payload={"prediction_error": 0.1},
            salience=0.2,
            timestamp=datetime.now(timezone.utc),
        )
    )

    await observer.start()
    try:
        deadline = asyncio.get_event_loop().time() + 3.0
        while "soma.report" not in seen:
            await asyncio.sleep(0.05)
            if asyncio.get_event_loop().time() > deadline:
                raise TimeoutError("observer did not consume the valid event")
    finally:
        await observer.stop()

    assert seen == ["soma.report"]
    assert observer._cursors["soma.out"] == event_id
