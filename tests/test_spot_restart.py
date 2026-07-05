# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Spot restart ladder — light recreate vs heavy rebuild/replace/restore."""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.spot import Spot, SpotConfig
from kaine.lifecycle.manager import ForkManager
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry


class _LightMod(BaseModule):
    name = "light"

    def __init__(self, bus):
        super().__init__(bus)
        self.restart_calls = 0

    async def restart(self) -> None:
        self.restart_calls += 1
        await super().restart()


class _HeavyMod(BaseModule):
    name = "heavy"

    def __init__(self, bus, *, marker=0):
        super().__init__(bus)
        self.marker = marker
        self.shutdown_calls = 0
        self._restored = None

    def holds_external_resources(self) -> bool:
        return True

    async def shutdown(self) -> None:
        self.shutdown_calls += 1
        await super().shutdown()

    def serialize(self):
        return {"marker": self.marker}

    def deserialize(self, state):
        self._restored = state


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _spot(registry, fork_manager, rebuild):
    return Spot(
        registry=registry,
        fork_manager=fork_manager,
        kaine_config={},
        config=SpotConfig(enabled=True),
        rebuild_module=rebuild,
        bus=object(),
    )


async def test_light_restart_path(bus, tmp_path):
    mod = _LightMod(bus)
    registry = ModuleRegistry()
    registry.register(mod)
    await mod.initialize()
    try:
        fm = ForkManager(tmp_path / "forks")

        def _rebuild(name):
            raise AssertionError("light path must not rebuild")

        spot = _spot(registry, fm, _rebuild)
        ok = (await spot._restart_module("light")).ok
        assert ok is True
        assert mod.restart_calls == 1
        # Same instance is reused on the light path.
        assert registry.get("light") is mod
    finally:
        await registry.get("light").shutdown()


async def test_heavy_restart_swaps_rebuilds_and_restores(bus, tmp_path):
    old = _HeavyMod(bus, marker=1)
    registry = ModuleRegistry()
    registry.register(old)
    await old.initialize()

    fm = ForkManager(tmp_path / "forks")
    # Pre-restart snapshot of the OLD instance (marker=1) becomes last_good.
    snap = fm.snapshot(registry, label="pre")
    new_holder = {}

    def _rebuild(name):
        assert name == "heavy"
        new = _HeavyMod(bus, marker=2)
        new_holder["new"] = new
        return new

    spot = _spot(registry, fm, _rebuild)
    # Seed the incident with a known last_good snapshot so restore runs.
    from kaine.cycle.spot import _Incident

    spot._incidents["heavy"] = _Incident(attempts=1, last_good=snap.id)

    ok = (await spot._restart_module("heavy")).ok
    assert ok is True
    # Old instance shut down.
    assert old.shutdown_calls >= 1
    # New instance is the one rebuilt and swapped into the registry.
    new = new_holder["new"]
    assert registry.get("heavy") is new
    assert new is not old
    # Restore reseeded the new instance from the last-good snapshot (marker=1).
    assert new._restored == {"marker": 1}
    await registry.get("heavy").shutdown()


async def test_heavy_restart_without_last_good_skips_restore(bus, tmp_path):
    old = _HeavyMod(bus, marker=1)
    registry = ModuleRegistry()
    registry.register(old)
    await old.initialize()
    fm = ForkManager(tmp_path / "forks")

    def _rebuild(name):
        return _HeavyMod(bus, marker=9)

    spot = _spot(registry, fm, _rebuild)
    ok = (await spot._restart_module("heavy")).ok
    assert ok is True
    # No incident -> no last_good -> no restore.
    assert registry.get("heavy")._restored is None
    await registry.get("heavy").shutdown()


async def test_heavy_restart_returns_false_on_rebuild_failure(bus, tmp_path):
    old = _HeavyMod(bus, marker=1)
    registry = ModuleRegistry()
    registry.register(old)
    await old.initialize()
    fm = ForkManager(tmp_path / "forks")

    def _rebuild(name):
        raise RuntimeError("rebuild boom")

    spot = _spot(registry, fm, _rebuild)
    ok = (await spot._restart_module("heavy")).ok
    assert ok is False
    await registry.get("heavy").shutdown()
