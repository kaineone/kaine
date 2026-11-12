# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Supervisor loading awareness (residency task 5.2).

A module whose model is loading within its measured bound is alive.
An over-bound load is a residency failure, not a supervisor restart.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.supervisor import Supervisor, SupervisorConfig
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry
from kaine.residency.ledger import Ledger, State


class _Mod(BaseModule):
    name = "m"


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _make_supervisor(registry, clock, *, ledger=None, loading_timeout_s=120.0):
    return Supervisor(
        registry=registry,
        fork_manager=object(),
        kaine_config={},
        config=SupervisorConfig(
            enabled=True,
            heartbeat_timeout_s=60.0,
            loading_timeout_s=loading_timeout_s,
        ),
        rebuild_module=lambda name: None,
        bus=object(),
        clock=clock,
        ledger=ledger,
    )


@pytest.mark.asyncio
async def test_loading_within_bound_suppresses_hung(bus):
    """A stale heartbeat during a loading model is alive, not hung."""
    mod = _Mod(bus)
    await mod.initialize()
    try:
        mod._last_heartbeat -= 1000.0

        ledger = Ledger(budget_bytes=8_000_000_000)
        ledger.register("stt_engine", footprint_bytes=500_000_000)
        await ledger.try_admit("stt_engine", 500_000_000)
        entry = ledger.get("stt_engine")
        assert entry.state == State.LOADING

        supervisor = _make_supervisor(ModuleRegistry(), lambda: 0.0, ledger=ledger)
        assert supervisor.assess(mod).state == "alive"
    finally:
        await mod.shutdown()


@pytest.mark.asyncio
async def test_loading_over_bound_is_residency_failure(bus):
    """A load that exceeds the measured bound is a residency failure."""
    mod = _Mod(bus)
    await mod.initialize()
    try:
        mod._last_heartbeat -= 1000.0

        ledger = Ledger(budget_bytes=8_000_000_000)
        ledger.register("stt_engine", footprint_bytes=500_000_000, measured_load_seconds=30.0)
        await ledger.try_admit("stt_engine", 500_000_000)
        entry = ledger.get("stt_engine")
        entry.load_started_at = time.monotonic() - 60.0

        supervisor = _make_supervisor(ModuleRegistry(), lambda: 0.0, ledger=ledger)
        assert supervisor.assess(mod).state == "residency_failure"
    finally:
        await mod.shutdown()


@pytest.mark.asyncio
async def test_loading_over_default_timeout_is_residency_failure(bus):
    """When measured bound is 0 (unmeasured), the config timeout applies."""
    mod = _Mod(bus)
    await mod.initialize()
    try:
        mod._last_heartbeat -= 1000.0

        ledger = Ledger(budget_bytes=8_000_000_000)
        ledger.register("stt_engine", footprint_bytes=500_000_000)
        await ledger.try_admit("stt_engine", 500_000_000)
        entry = ledger.get("stt_engine")
        entry.load_started_at = time.monotonic() - 200.0

        supervisor = _make_supervisor(
            ModuleRegistry(), lambda: 0.0, ledger=ledger, loading_timeout_s=120.0
        )
        assert supervisor.assess(mod).state == "residency_failure"
    finally:
        await mod.shutdown()


@pytest.mark.asyncio
async def test_no_ledger_falls_through_to_hung(bus):
    """Without a ledger, a stale module with running tasks is hung as before."""
    mod = _Mod(bus)
    await mod.initialize()
    try:
        mod._last_heartbeat -= 1000.0
        supervisor = _make_supervisor(ModuleRegistry(), lambda: 0.0)
        assert supervisor.assess(mod).state == "hung"
    finally:
        await mod.shutdown()


@pytest.mark.asyncio
async def test_ledger_no_loading_entries_falls_through_to_hung(bus):
    """A ledger with no loading entries does not suppress hung."""
    mod = _Mod(bus)
    await mod.initialize()
    try:
        mod._last_heartbeat -= 1000.0

        ledger = Ledger(budget_bytes=8_000_000_000)
        ledger.register("stt_engine", footprint_bytes=500_000_000)

        supervisor = _make_supervisor(ModuleRegistry(), lambda: 0.0, ledger=ledger)
        assert supervisor.assess(mod).state == "hung"
    finally:
        await mod.shutdown()


@pytest.mark.asyncio
async def test_residency_failure_does_not_trigger_restart(bus):
    """_poll_once surfaces a residency failure but does not restart the module."""
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    poll_bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    mod = _Mod(poll_bus)
    await mod.initialize()
    try:
        mod._last_heartbeat -= 1000.0

        ledger = Ledger(budget_bytes=8_000_000_000)
        ledger.register("stt_engine", footprint_bytes=500_000_000, measured_load_seconds=5.0)
        await ledger.try_admit("stt_engine", 500_000_000)
        entry = ledger.get("stt_engine")
        entry.load_started_at = time.monotonic() - 60.0

        registry = ModuleRegistry()
        registry.register(mod)

        published: list[dict] = []

        class _CaptureBus:
            async def publish(self, event=None):
                if event is not None:
                    published.append(event)
                return "0-0"

        supervisor = Supervisor(
            registry=registry,
            fork_manager=object(),
            kaine_config={},
            config=SupervisorConfig(
                enabled=True,
                heartbeat_timeout_s=60.0,
                loading_timeout_s=120.0,
            ),
            rebuild_module=lambda name: None,
            bus=_CaptureBus(),
            ledger=ledger,
        )

        stop = asyncio.Event()
        await supervisor._poll_once(stop)

        assert not supervisor.escalated
        assert not stop.is_set()
        log_events = [e for e in published if getattr(e, "type", None) == "supervisor.log"]
        assert any(
            "residency failure" in getattr(e, "payload", {}).get("message", "") for e in log_events
        )
    finally:
        await mod.shutdown()
        await poll_bus.close()


@pytest.mark.asyncio
async def test_loading_entries_ledger_method():
    """Ledger.loading_entries returns tuples for entries in LOADING state."""
    ledger = Ledger(budget_bytes=8_000_000_000)
    ledger.register("a", footprint_bytes=100, measured_load_seconds=10.0)
    ledger.register("b", footprint_bytes=200)

    assert ledger.loading_entries() == []

    await ledger.try_admit("a", 100)
    entries = ledger.loading_entries()
    assert len(entries) == 1
    name, elapsed, bound = entries[0]
    assert name == "a"
    assert elapsed >= 0
    assert bound == 10.0

    ledger.mark_resident("a")
    assert ledger.loading_entries() == []
