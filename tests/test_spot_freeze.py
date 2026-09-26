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


class _HungMod(BaseModule):
    """A module whose task is still running but whose heartbeat is stale."""

    name = "hungmod"

    def heartbeat_age(self) -> float:
        return 1e9


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


async def test_gestation_only_freeze_crashed_module_recovered(bus, tmp_path, monkeypatch):
    # A crashed module under a gestation-only freeze is restarted by Spot.
    # Spot pushes and later pops only its own freeze entry.
    mod = _LightMod(bus)

    async def _boom():
        raise RuntimeError("crash")

    mod._tasks = [await _finished_task(_boom())]
    registry = ModuleRegistry()
    registry.register(mod)
    fm = ForkManager(tmp_path / "forks")
    spot = _spot(registry, fm, bus)

    calls = []
    orig_freeze = control_state.freeze
    spot_pushed_on_top = False

    def freeze_recorder(*args, **kwargs):
        nonlocal spot_pushed_on_top
        result = orig_freeze(*args, **kwargs)
        calls.append((args, kwargs.copy()))
        if kwargs.get("source") == "spot":
            stack = control_state.read_control().stack
            if stack and stack[-1].get("source") == "spot":
                spot_pushed_on_top = True
        return result

    monkeypatch.setattr(control_state, "freeze", freeze_recorder)

    control_state.freeze(reason="gestation hold", source="gestation")

    stop = asyncio.Event()
    await spot._poll_once(stop)

    control = control_state.read_control()
    assert control.frozen is True
    assert control.source == "gestation"
    assert len(control.stack) == 1
    assert control.stack[0].get("source") == "gestation"
    assert "light" not in spot._incidents
    assert spot_pushed_on_top is True
    await registry.get("light").shutdown()


async def test_gestation_only_freeze_hung_module_spot_ignores(bus, tmp_path, monkeypatch):
    # A hung module under a gestation-only freeze is left alone: heartbeats are
    # unreliable while perception is paused.
    mod = _HungMod(bus)
    hang_event = asyncio.Event()
    mod._tasks = [asyncio.create_task(hang_event.wait())]
    await asyncio.sleep(0)

    registry = ModuleRegistry()
    registry.register(mod)
    fm = ForkManager(tmp_path / "forks")
    spot = _spot(registry, fm, bus)
    monkeypatch.setattr(spot, "_hypnos_sleeping", lambda: False)

    control_state.freeze(reason="gestation hold", source="gestation")
    pre_stack = tuple(control_state.read_control().stack)

    freeze_calls = []
    orig_freeze = control_state.freeze

    def freeze_recorder(*args, **kwargs):
        freeze_calls.append((args, kwargs.copy()))
        return orig_freeze(*args, **kwargs)

    monkeypatch.setattr(control_state, "freeze", freeze_recorder)

    stop = asyncio.Event()
    await spot._poll_once(stop)

    assert "hungmod" not in spot._incidents
    assert control_state.read_control().stack == pre_stack
    assert freeze_calls == []

    hang_event.set()
    mod._tasks[0].cancel()


async def test_welfare_plus_gestation_freeze_spot_stays_out(bus, tmp_path, monkeypatch):
    # A mixed stack containing welfare (or operator) keeps Spot out, even when
    # a gestation freeze is also present.
    mod = _LightMod(bus)

    async def _boom():
        raise RuntimeError("crash")

    mod._tasks = [await _finished_task(_boom())]
    registry = ModuleRegistry()
    registry.register(mod)
    fm = ForkManager(tmp_path / "forks")
    spot = _spot(registry, fm, bus)

    control_state.push_freeze(
        reason="welfare hold", path=control_state.CONTROL_PATH, source="welfare"
    )
    control_state.push_freeze(
        reason="gestation hold", path=control_state.CONTROL_PATH, source="gestation"
    )
    pre_stack = tuple(control_state.read_control().stack)

    freeze_calls = []
    orig_freeze = control_state.freeze

    def freeze_recorder(*args, **kwargs):
        freeze_calls.append((args, kwargs.copy()))
        return orig_freeze(*args, **kwargs)

    monkeypatch.setattr(control_state, "freeze", freeze_recorder)

    stop = asyncio.Event()
    await spot._poll_once(stop)

    assert "light" not in spot._incidents
    assert control_state.read_control().stack == pre_stack
    assert freeze_calls == []
    assert control_state.read_control().source == "gestation"
    await mod.shutdown()


async def test_hung_module_is_really_hung_without_a_freeze(bus, tmp_path, monkeypatch):
    # Control for the hung-module tests: with no freeze at all, the same module
    # does read as hung and Spot opens an incident, so "Spot ignores it" in the
    # gestation cases is a real decision, not a module that never looked hung.
    mod = _HungMod(bus)
    hang_event = asyncio.Event()
    mod._tasks = [asyncio.create_task(hang_event.wait())]
    await asyncio.sleep(0)
    registry = ModuleRegistry()
    registry.register(mod)
    spot = _spot(registry, ForkManager(tmp_path / "forks"), bus)
    monkeypatch.setattr(spot, "_hypnos_sleeping", lambda: False)

    assert spot.assess(mod).state == "hung"
    await spot._poll_once(asyncio.Event())
    assert "hungmod" in spot._incidents

    hang_event.set()
    mod._tasks[0].cancel()


async def test_hung_module_ignored_while_spot_entry_sits_on_gestation(
    bus, tmp_path, monkeypatch
):
    # Spot's own entry on top of a gestation freeze: the cycle is still paused
    # for the lost womb, so a stale heartbeat is still no signal.
    mod = _HungMod(bus)
    hang_event = asyncio.Event()
    mod._tasks = [asyncio.create_task(hang_event.wait())]
    await asyncio.sleep(0)
    registry = ModuleRegistry()
    registry.register(mod)
    spot = _spot(registry, ForkManager(tmp_path / "forks"), bus)
    monkeypatch.setattr(spot, "_hypnos_sleeping", lambda: False)

    control_state.push_freeze(reason="womb lost", source="gestation")
    control_state.push_freeze(reason="spot: other crashed", source="spot")
    pre_stack = tuple(control_state.read_control().stack)

    await spot._poll_once(asyncio.Event())
    assert "hungmod" not in spot._incidents
    assert tuple(control_state.read_control().stack) == pre_stack

    hang_event.set()
    mod._tasks[0].cancel()
