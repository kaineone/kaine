# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Spot freeze integration — source attribution, operator-freeze short-circuit."""
from __future__ import annotations

import asyncio

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle import control_state
from kaine.cycle.spot import Spot, SpotConfig
from kaine.lifecycle.manager import ForkManager
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry


class _LightMod(BaseModule):
    name = "light"


class _AlwaysDeadMod(BaseModule):
    """A module whose workspace task exits immediately while not stopping, so it
    re-reads as dead even after a light restart."""

    name = "deadmod"

    async def initialize(self) -> None:
        async def _exits_immediately():
            return None

        self._tasks.append(asyncio.create_task(_exits_immediately()))
        await asyncio.sleep(0)  # let it finish


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.fixture(autouse=True)
def _control_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(
        control_state, "CONTROL_PATH", tmp_path / "control.json"
    )
    yield


async def _finished_task(coro):
    t = asyncio.create_task(coro)
    await asyncio.gather(t, return_exceptions=True)
    return t


def _spot(registry, fork_manager, bus):
    return Spot(
        registry=registry,
        fork_manager=fork_manager,
        kaine_config={},
        config=SpotConfig(enabled=True, restart_backoff_s=0.0),
        rebuild_module=lambda name: None,
        bus=bus,
    )


async def test_incident_writes_control_with_spot_source(bus, tmp_path):
    # A module that stays dead even after a light restart, so Spot's freeze
    # persists with source="spot" (it never recovers on this single poll).
    mod = _AlwaysDeadMod(bus)
    await mod.initialize()
    registry = ModuleRegistry()
    registry.register(mod)
    fm = ForkManager(tmp_path / "forks")
    spot = _spot(registry, fm, bus)

    stop = asyncio.Event()
    await spot._poll_once(stop)
    control = control_state.read_control()
    assert control.frozen is True
    assert control.source == "spot"
    assert spot._incidents["deadmod"].attempts == 1
    await registry.get("deadmod").shutdown()


async def test_operator_freeze_short_circuits_spot(bus, tmp_path):
    mod = _LightMod(bus)

    async def _boom():
        raise RuntimeError("crash")

    crashed = await _finished_task(_boom())
    mod._tasks = [crashed]
    registry = ModuleRegistry()
    registry.register(mod)
    fm = ForkManager(tmp_path / "forks")
    spot = _spot(registry, fm, bus)

    # Operator owns the freeze.
    control_state.freeze(reason="operator repair", source="operator")
    stop = asyncio.Event()
    await spot._poll_once(stop)

    # Spot took no action: the module's crashed task is untouched, no incident.
    control = control_state.read_control()
    assert control.source == "operator"
    assert "light" not in spot._incidents
    await mod.shutdown()


async def test_spot_unfreezes_only_its_own_freeze_on_recovery(bus, tmp_path):
    # A pure module whose only task crashed; a light restart recreates a healthy
    # workspace task, so Spot recovers and clears its OWN freeze.
    mod = _LightMod(bus)

    async def _boom():
        raise RuntimeError("crash")

    mod._tasks = [await _finished_task(_boom())]
    registry = ModuleRegistry()
    registry.register(mod)
    fm = ForkManager(tmp_path / "forks")
    spot = _spot(registry, fm, bus)

    stop = asyncio.Event()
    await spot._poll_once(stop)
    # Light restart gives a fresh, alive workspace task -> recovered -> unfrozen.
    control = control_state.read_control()
    assert control.frozen is False
    assert "light" not in spot._incidents
    await registry.get("light").shutdown()
