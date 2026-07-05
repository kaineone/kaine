# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phase 7.3: module shedding — graceful degradation under arbitrary
subsets of the twelve canonical modules.

Runs against fakeredis. The point is to prove the cycle/registry/
Syneidesis composition tolerates absent modules — the real per-module
behavior is covered by each module's own test file.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle import CognitiveCycle
from kaine.modules import ModuleRegistry
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticGoalScorer,
    StaticThymosModulator,
    Syneidesis,
)

from tests._module_shedding import (
    CANONICAL_MODULE_NAMES,
    build_fakes,
)


async def _make_stack(names):
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    syneidesis = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=8),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=20,
        publication_threshold=0.0,
    )
    registry = ModuleRegistry()
    modules = build_fakes(names, bus)
    for module in modules.values():
        registry.register(module)
        await module.initialize()
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syneidesis,
        registry=registry,
        processing_rate_hz=20.0,
        experiential_rate_hz=20.0,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    )
    return bus, cycle, registry, modules


async def _teardown(bus, modules):
    for module in modules.values():
        await module.shutdown()
    await bus.close()


async def _run(names):
    bus, cycle, registry, modules = await _make_stack(names)
    try:
        for tick in range(10):
            for module in modules.values():
                await module.publish_one(salience=0.5 + 0.01 * tick)
            result = await cycle.tick()
            assert result.error is False, f"tick {tick} errored: {result.error_message}"
            if names:
                assert result.events_collected >= len(modules), (
                    f"tick {tick}: expected ≥{len(modules)} events, got "
                    f"{result.events_collected}"
                )
            await asyncio.sleep(0.005)
        # Let background workspace consumers drain.
        await asyncio.sleep(0.1)
        assert cycle.error_counts == {}, cycle.error_counts
        return modules
    finally:
        await _teardown(bus, modules)


@pytest.mark.asyncio
async def test_full_stack_degrades_gracefully():
    modules = await _run(CANONICAL_MODULE_NAMES)
    # At least one module should have observed at least one broadcast.
    assert any(m.snapshots for m in modules.values())


@pytest.mark.asyncio
async def test_no_lingua_combination():
    names = [n for n in CANONICAL_MODULE_NAMES if n != "lingua"]
    await _run(names)


@pytest.mark.asyncio
async def test_no_topos_combination():
    names = [n for n in CANONICAL_MODULE_NAMES if n != "topos"]
    await _run(names)


@pytest.mark.asyncio
async def test_cognition_only_combination():
    await _run(["nous", "mnemos", "eidolon"])


@pytest.mark.asyncio
async def test_perception_only_combination():
    await _run(["soma", "chronos", "topos"])


@pytest.mark.asyncio
async def test_lone_soma_combination():
    await _run(["soma"])


@pytest.mark.asyncio
async def test_empty_registry_runs_clean():
    bus, cycle, registry, modules = await _make_stack([])
    try:
        for _ in range(10):
            result = await cycle.tick()
            assert result.error is False
            assert result.events_collected == 0
        assert cycle.error_counts == {}
    finally:
        await _teardown(bus, modules)


@pytest.mark.asyncio
async def test_syneidesis_never_selects_unregistered_source():
    names = ["nous", "mnemos", "eidolon"]
    bus, cycle, registry, modules = await _make_stack(names)
    try:
        for module in modules.values():
            await module.publish_one(salience=0.9)
        await cycle.tick()
        await asyncio.sleep(0.05)
        # Every selected event's source should be one we registered.
        for module in modules.values():
            for snap in module.snapshots:
                for _, event in snap.selected_events:
                    assert event.source in set(names) | {"syneidesis"}, (
                        f"unregistered source leaked into broadcast: {event.source}"
                    )
    finally:
        await _teardown(bus, modules)


@pytest.mark.asyncio
async def test_shed_mid_run_drops_within_one_tick():
    names = ["soma", "chronos"]
    bus, cycle, registry, modules = await _make_stack(names)
    try:
        await modules["soma"].publish_one(salience=0.8)
        await modules["chronos"].publish_one(salience=0.8)
        result = await cycle.tick()
        assert result.events_collected >= 2

        # Shed chronos: shutdown its background task + unregister.
        await modules["chronos"].shutdown()
        registry.unregister("chronos")
        modules.pop("chronos")

        await modules["soma"].publish_one(salience=0.8)
        await cycle.tick()
        await asyncio.sleep(0.05)

        # The most recent broadcast that soma sees should contain only soma
        # events (cycle reads from active streams now, which excludes
        # chronos.out).
        if modules["soma"].snapshots:
            latest = modules["soma"].snapshots[-1]
            for _, event in latest.selected_events:
                assert event.source == "soma", (
                    f"shed module's event still selected: {event.source}"
                )
    finally:
        await _teardown(bus, modules)
