# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle import CognitiveCycle
from tests._fakes import FakeClock, FakeRegistry, FakeSyneidesis


@pytest.fixture
async def cycle():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    c = CognitiveCycle(
        bus=bus,
        syneidesis=FakeSyneidesis(),
        registry=FakeRegistry([]),
        clock=FakeClock(),
        sleep=FakeClock().sleep,
    )
    yield c
    await bus.close()


@pytest.mark.asyncio
async def test_pause_hook_fires_before_pause_completes(cycle: CognitiveCycle):
    order: list[str] = []

    async def on_pause():
        order.append("hook")

    cycle.hooks.register("pause", on_pause)
    await cycle.pause()
    order.append("after-pause")
    assert order == ["hook", "after-pause"]


@pytest.mark.asyncio
async def test_resume_hooks_fire_in_registration_order(cycle: CognitiveCycle):
    order: list[str] = []
    cycle.hooks.register("resume", lambda: _append(order, "a"))
    cycle.hooks.register("resume", lambda: _append(order, "b"))
    await cycle.pause()
    await cycle.resume()
    assert order == ["a", "b"]


@pytest.mark.asyncio
async def test_shutdown_hook_fires_once(cycle: CognitiveCycle):
    fired = []

    async def on_shutdown():
        fired.append(True)

    cycle.hooks.register("shutdown", on_shutdown)
    await cycle.shutdown()
    assert fired == [True]


@pytest.mark.asyncio
async def test_hook_error_does_not_stop_subsequent_hooks(cycle: CognitiveCycle):
    order: list[str] = []

    async def bad():
        order.append("bad")
        raise RuntimeError("boom")

    async def good():
        order.append("good")

    cycle.hooks.register("pause", bad)
    cycle.hooks.register("pause", good)
    await cycle.pause()
    assert order == ["bad", "good"]


@pytest.mark.asyncio
async def test_unknown_event_rejected(cycle: CognitiveCycle):
    with pytest.raises(ValueError):
        cycle.hooks.register("not-a-real-event", lambda: None)


async def _append(buf: list[str], value: str) -> None:
    buf.append(value)
