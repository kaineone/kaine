# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Supervisor.assess — crash-primary, hang-gated, sleep-gated liveness model."""
from __future__ import annotations

import asyncio

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.supervisor import Supervisor, SupervisorConfig
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry


class _Mod(BaseModule):
    name = "m"


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _make_supervisor(registry, clock):
    return Supervisor(
        registry=registry,
        fork_manager=object(),
        kaine_config={},
        config=SupervisorConfig(enabled=True, heartbeat_timeout_s=60.0),
        rebuild_module=lambda name: None,
        bus=object(),
        clock=clock,
    )


async def _finished_task(coro):
    t = asyncio.create_task(coro)
    await asyncio.gather(t, return_exceptions=True)
    return t


async def test_dead_on_task_exception(bus):
    mod = _Mod(bus)

    async def _boom():
        raise RuntimeError("crash")

    mod._tasks = [await _finished_task(_boom())]
    supervisor = _make_supervisor(ModuleRegistry(), lambda: 0.0)
    assert supervisor.assess(mod).state == "dead"


async def test_dead_on_self_exit_while_not_stopping(bus):
    mod = _Mod(bus)

    async def _exits():
        return None

    # Task returned normally but the module is NOT stopping -> organ exited.
    assert not mod._stopped.is_set()
    mod._tasks = [await _finished_task(_exits())]
    supervisor = _make_supervisor(ModuleRegistry(), lambda: 0.0)
    assert supervisor.assess(mod).state == "dead"


async def test_returned_task_while_stopping_is_not_dead(bus):
    mod = _Mod(bus)

    async def _exits():
        return None

    mod._stopped.set()  # module is stopping; a returned task is expected
    mod._tasks = [await _finished_task(_exits())]
    supervisor = _make_supervisor(ModuleRegistry(), lambda: 0.0)
    assert supervisor.assess(mod).state == "alive"


async def test_alive_for_quiet_running_module_with_fresh_heartbeat(bus):
    mod = _Mod(bus)
    await mod.initialize()  # one long-running workspace task
    try:
        mod._beat()  # fresh heartbeat
        supervisor = _make_supervisor(ModuleRegistry(), lambda: 0.0)
        assert supervisor.assess(mod).state == "alive"
    finally:
        await mod.shutdown()


async def test_hung_only_when_stale_and_running_and_not_sleeping(bus):
    mod = _Mod(bus)
    await mod.initialize()
    try:
        # Make heartbeat stale: heartbeat_age uses time.monotonic directly.
        mod._last_heartbeat -= 1000.0
        supervisor = _make_supervisor(ModuleRegistry(), lambda: 0.0)
        assert supervisor.assess(mod).state == "hung"
    finally:
        await mod.shutdown()


async def test_not_hung_when_no_task_running(bus):
    mod = _Mod(bus)
    mod._last_heartbeat -= 1000.0
    mod._tasks = []  # nothing running
    supervisor = _make_supervisor(ModuleRegistry(), lambda: 0.0)
    assert supervisor.assess(mod).state == "alive"


async def test_sleep_gate_suppresses_hung(bus):
    mod = _Mod(bus)
    await mod.initialize()
    try:
        mod._last_heartbeat -= 1000.0

        class _Sleep(BaseModule):
            name = "sleep"
            is_sleeping = True

        registry = ModuleRegistry()
        registry.register(mod if mod.name == "sleep" else _Sleep(bus))
        supervisor = _make_supervisor(registry, lambda: 0.0)
        # sleep.is_sleeping True -> hang suppressed.
        assert supervisor.assess(mod).state == "alive"
    finally:
        await mod.shutdown()
