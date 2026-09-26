# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""tests for the optional plugin cycle-tick hook (OpenSpec plugin-cycle-hook)."""

import logging
import time

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle import CognitiveCycle
from kaine.plugins import LoadedPlugins
from tests._fakes import FakeClock, FakeRegistry, FakeSyneidesis


def _loaded(**plugins):
    return LoadedPlugins(
        {
            name: {
                "plugin": plugin,
                "config": {},
                "seams": set(),
                "distribution": f"dist-{name}",
                "version": "1",
            }
            for name, plugin in plugins.items()
        }
    )


class _Recorder:
    def __init__(self):
        self.ticks = []

    def on_cycle_tick(self, tick):
        self.ticks.append(tick)


class _NoHook:
    pass


class _Raises:
    def on_cycle_tick(self, tick):
        raise RuntimeError("boom")


class _Slow:
    def on_cycle_tick(self, tick):
        time.sleep(0.05)


class _Mutates:
    def on_cycle_tick(self, tick):
        tick["experiential_rate_hz"] = 0.0
        tick["tick_index"] = -1


def test_cycle_observer_none_without_hooks():
    assert _loaded(a=_NoHook()).cycle_observer() is None
    assert LoadedPlugins({}).cycle_observer() is None


def test_cycle_observer_present_with_hook():
    rec = _Recorder()
    observer = _loaded(a=rec).cycle_observer()
    assert observer is not None
    observer({"tick_index": 1}, 100.0)
    assert rec.ticks == [{"tick_index": 1}]


def test_dispatch_skips_plugins_without_hook():
    rec = _Recorder()
    lp = _loaded(a=_NoHook(), b=rec)
    lp.dispatch_cycle_tick({"tick_index": 2}, 100.0)
    assert rec.ticks == [{"tick_index": 2}]


@pytest.mark.asyncio
async def test_three_ticks_call_hook_three_times():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    rec = _Recorder()
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=FakeSyneidesis(),
        registry=FakeRegistry(["chronos.out"]),
        clock=FakeClock(),
        sleep=FakeClock().sleep,
        tick_observer=_loaded(r=rec).cycle_observer(),
    )
    for _ in range(3):
        await cycle.tick()
    await bus.close()

    indexes = [t["tick_index"] for t in rec.ticks]
    assert len(indexes) == 3
    assert indexes == sorted(indexes) and len(set(indexes)) == 3
    assert all("experiential_rate_hz" in t for t in rec.ticks)


def _plugin_warnings(caplog):
    return [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and r.name == "kaine.plugins"
    ]


def test_raising_hook_warns_once_in_five(caplog):
    lp = _loaded(bad=_Raises())
    caplog.set_level(logging.WARNING, logger="kaine.plugins")
    for i in range(5):
        lp.dispatch_cycle_tick({"tick_index": i}, 100.0)
    warnings = _plugin_warnings(caplog)
    assert len(warnings) == 1
    message = str(warnings[0].message)
    assert "bad" in message
    assert "boom" in message


def test_slow_hook_warns_once_in_three(caplog):
    lp = _loaded(slow=_Slow())
    caplog.set_level(logging.WARNING, logger="kaine.plugins")
    for _ in range(3):
        lp.dispatch_cycle_tick({"tick_index": 1}, 100.0)
    warnings = _plugin_warnings(caplog)
    assert len(warnings) == 1
    message = str(warnings[0].message)
    assert "slow" in message
    assert "ms" in message


def test_fast_hook_does_not_warn(caplog):
    lp = _loaded(fast=_Recorder())
    caplog.set_level(logging.WARNING, logger="kaine.plugins")
    for _ in range(3):
        lp.dispatch_cycle_tick({"tick_index": 1}, 100.0)
    assert not _plugin_warnings(caplog)


@pytest.mark.asyncio
async def test_hook_cannot_change_the_cycle_or_event():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    mut = _Mutates()
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=FakeSyneidesis(),
        registry=FakeRegistry(["chronos.out"]),
        clock=FakeClock(),
        sleep=FakeClock().sleep,
        tick_observer=_loaded(m=mut).cycle_observer(),
    )
    for _ in range(2):
        await cycle.tick()
    entries = await bus.read("cycle.tick", last_id="0")
    payloads = [event.payload for _, event in entries]
    await bus.close()

    for payload in payloads:
        assert payload["experiential_rate_hz"] > 0
        assert payload["tick_index"] >= 0
    assert cycle.effective_experiential_rate_hz > 0


@pytest.mark.asyncio
async def test_observer_exception_never_stops_the_cycle():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    def _boom(payload, target_ms):
        raise RuntimeError("boom")

    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=FakeSyneidesis(),
        registry=FakeRegistry(["chronos.out"]),
        clock=FakeClock(),
        sleep=FakeClock().sleep,
        tick_observer=_boom,
    )
    for _ in range(3):
        result = await cycle.tick()
        assert result.error is False
    await bus.close()


@pytest.mark.asyncio
async def test_no_observer_publishes_identical_events():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    syneidesis = FakeSyneidesis()
    registry = FakeRegistry(["chronos.out"])
    clock = FakeClock()
    sleep_fn = clock.sleep

    client1 = fakeredis.FakeRedis(decode_responses=True)
    bus1 = AsyncBus(BusConfig(password="x", audit_required=False), client=client1)
    cycle1 = CognitiveCycle(
        bus=bus1,
        syneidesis=syneidesis,
        registry=registry,
        clock=clock,
        sleep=sleep_fn,
        deterministic=True,
    )

    client2 = fakeredis.FakeRedis(decode_responses=True)
    bus2 = AsyncBus(BusConfig(password="x", audit_required=False), client=client2)
    cycle2 = CognitiveCycle(
        bus=bus2,
        syneidesis=syneidesis,
        registry=registry,
        clock=FakeClock(),
        sleep=FakeClock().sleep,
        deterministic=True,
        tick_observer=None,
    )

    for _ in range(3):
        await cycle1.tick()
        await cycle2.tick()

    entries1 = await bus1.read("cycle.tick", last_id="0")
    entries2 = await bus2.read("cycle.tick", last_id="0")
    payloads1 = [event.payload for _, event in entries1]
    payloads2 = [event.payload for _, event in entries2]

    await bus1.close()
    await bus2.close()

    assert payloads1 == payloads2


def test_manifest_records_observes_cycle():
    manifest = _loaded(a=_Recorder(), b=_NoHook()).manifest_entry()
    assert manifest["a"]["observes_cycle"] is True
    assert manifest["b"]["observes_cycle"] is False

