# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Spot escalation — exhaust restart budget, save state, shutdown all, halt."""
from __future__ import annotations

import asyncio
import json

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle import control_state, escalation_state
from kaine.cycle.spot import Spot, SpotConfig
from kaine.lifecycle.manager import ForkManager
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry


class _HeavyDeadMod(BaseModule):
    """Holds external resources (heavy path) and is permanently dead: its only
    task is an exited coroutine while not stopping."""

    name = "heavy"

    def holds_external_resources(self) -> bool:
        return True

    def __init__(self, bus):
        super().__init__(bus)
        self.shutdown_calls = 0

    async def _spawn_dead_task(self) -> None:
        async def _boom():
            raise RuntimeError("organ crashed")

        t = asyncio.create_task(_boom())
        await asyncio.gather(t, return_exceptions=True)
        self._tasks.append(t)

    async def shutdown(self) -> None:
        self.shutdown_calls += 1
        await super().shutdown()
        # This organ is broken: even after teardown it crashes on respawn, so it
        # keeps reading "dead" across polls (a crash overrides the stop state).
        await self._spawn_dead_task()

    async def initialize(self) -> None:
        await self._spawn_dead_task()


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.fixture(autouse=True)
def _state_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")
    monkeypatch.setattr(
        escalation_state, "ESCALATION_PATH", tmp_path / "escalation.json"
    )
    yield


async def test_escalation_after_max_attempts(bus, tmp_path):
    mod = _HeavyDeadMod(bus)
    await mod.initialize()
    registry = ModuleRegistry()
    registry.register(mod)

    snapshots: list[str] = []
    fm = ForkManager(tmp_path / "forks")
    real_snapshot = fm.snapshot

    def _tracking_snapshot(*a, **kw):
        snap = real_snapshot(*a, **kw)
        snapshots.append(kw.get("label", ""))
        return snap

    fm.snapshot = _tracking_snapshot  # type: ignore[assignment]

    rebuild_calls = {"n": 0}

    def _rebuild(name):
        rebuild_calls["n"] += 1
        raise RuntimeError("rebuild keeps failing")

    halted = {"v": False}
    stop = asyncio.Event()

    spot = Spot(
        registry=registry,
        fork_manager=fm,
        kaine_config={},
        config=SpotConfig(
            enabled=True, max_restart_attempts=5, restart_backoff_s=0.0
        ),
        rebuild_module=_rebuild,
        bus=bus,
        on_halt=lambda: halted.__setitem__("v", True),
    )

    # Poll until escalation (one incident attempt per poll). Cap iterations so a
    # bug can't loop forever.
    for _ in range(20):
        await spot._poll_once(stop)
        if spot.escalated:
            break

    assert spot.escalated is True
    assert stop.is_set()
    assert halted["v"] is True

    # Exactly max_restart_attempts restart attempts were made.
    assert rebuild_calls["n"] == 5

    # A pre-restart snapshot AND an escalation snapshot were taken.
    assert any(lbl.startswith("spot-pre-restart:") for lbl in snapshots)
    assert any(lbl.startswith("spot-escalation:") for lbl in snapshots)

    # Every module was shut down at escalation.
    assert mod.shutdown_calls >= 1

    # escalation.json written with the right fields.
    rec = escalation_state.read_escalation()
    assert rec.escalated is True
    assert rec.module == "heavy"
    assert rec.attempts == 5
    assert rec.snapshot_id is not None
    assert rec.escalated_at is not None
    assert "Do NOT auto-retry" in rec.message

    # On-disk file holds only operational keys (no sensory content).
    raw = json.loads((tmp_path / "escalation.json").read_text())
    assert set(raw) == {
        "escalated",
        "module",
        "attempts",
        "snapshot_id",
        "escalated_at",
        "message",
    }


async def test_run_loop_halts_on_internal_error(bus, tmp_path):
    # If a poll raises unexpectedly, run() must halt loudly (escalated + stop).
    registry = ModuleRegistry()
    fm = ForkManager(tmp_path / "forks")
    halted = {"v": False}
    spot = Spot(
        registry=registry,
        fork_manager=fm,
        kaine_config={},
        config=SpotConfig(enabled=True, poll_interval_s=0.01),
        rebuild_module=lambda name: None,
        bus=bus,
        on_halt=lambda: halted.__setitem__("v", True),
    )

    async def _boom(stop):
        raise RuntimeError("internal spot error")

    spot._poll_once = _boom  # type: ignore[assignment]
    stop = asyncio.Event()
    await asyncio.wait_for(spot.run(stop), timeout=2.0)
    assert spot.escalated is True
    assert stop.is_set()
    assert halted["v"] is True
