# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""BaseModule liveness/restart contract — heartbeat, health(), light restart()."""
from __future__ import annotations

import asyncio

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.base import BaseModule


class _PureModule(BaseModule):
    name = "pure-mod"


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


async def test_publish_bumps_heartbeat(bus: AsyncBus, monkeypatch):
    mod = _PureModule(bus)
    # Force a stale heartbeat, then publish and confirm it was bumped.
    mod._last_heartbeat -= 100.0
    aged_before = mod.heartbeat_age()
    assert aged_before > 50.0
    await mod.publish("pure.test", {"v": 1})
    assert mod.heartbeat_age() < aged_before


async def test_on_workspace_bumps_heartbeat(bus: AsyncBus):
    mod = _PureModule(bus)
    await mod.initialize()
    try:
        mod._last_heartbeat -= 100.0
        aged = mod.heartbeat_age()
        # Drive a broadcast — the workspace loop calls on_workspace then _beat.
        await bus.publish_workspace({"tick_index": 1, "selected": []})
        for _ in range(50):
            await asyncio.sleep(0.01)
            if mod.heartbeat_age() < aged:
                break
        assert mod.heartbeat_age() < aged
    finally:
        await mod.shutdown()


async def test_heartbeat_age_decreases_on_beat(bus: AsyncBus):
    mod = _PureModule(bus)
    mod._last_heartbeat -= 10.0
    before = mod.heartbeat_age()
    mod._beat()
    assert mod.heartbeat_age() < before


async def test_health_shape_and_failed_count(bus: AsyncBus):
    mod = _PureModule(bus)

    async def _boom():
        raise RuntimeError("organ crashed")

    async def _ok():
        return None

    failed = asyncio.create_task(_boom())
    ok = asyncio.create_task(_ok())
    await asyncio.gather(failed, ok, return_exceptions=True)
    mod._tasks = [failed, ok]

    health = mod.health()
    assert set(health) == {
        "name",
        "heartbeat_age_s",
        "tasks_total",
        "tasks_done",
        "tasks_failed",
    }
    assert health["name"] == "pure-mod"
    assert health["tasks_total"] == 2
    assert health["tasks_done"] == 2
    assert health["tasks_failed"] == 1
    assert isinstance(health["heartbeat_age_s"], float)


async def test_health_never_raises_on_pending_task(bus: AsyncBus):
    mod = _PureModule(bus)
    await mod.initialize()
    try:
        # A still-pending workspace task must not trip health().
        health = mod.health()
        assert health["tasks_total"] >= 1
        assert health["tasks_failed"] == 0
    finally:
        await mod.shutdown()


async def test_light_restart_round_trips(bus: AsyncBus):
    mod = _PureModule(bus)
    await mod.initialize()
    assert len(mod._tasks) == 1
    first_task = mod._tasks[0]
    await mod.restart()
    # A fresh task list, the old one stopped, the stop event reset.
    assert len(mod._tasks) == 1
    assert mod._tasks[0] is not first_task
    assert not mod._stopped.is_set()
    # And the module is still alive after a light restart.
    assert not mod._tasks[0].done()
    await mod.shutdown()


def test_holds_external_resources_default_false(bus: AsyncBus):
    assert _PureModule(bus).holds_external_resources() is False
