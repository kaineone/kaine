# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phase 9.1: full-stack integration test without entity-state boot.

All twelve canonical module names are registered via the same fakes
the module-shedding tests use. The cycle runs 50 ticks against
fakeredis, Syneidesis composes broadcasts, ForkManager snapshots and
restores the whole registry, and every check stays within fakeredis —
no real Redis, no real services, no module entity-state init.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle import CognitiveCycle
from kaine.lifecycle.manager import ForkManager
from kaine.modules import ModuleRegistry
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticGoalScorer,
    StaticThymosModulator,
    Syneidesis,
)

from tests._module_shedding import CANONICAL_MODULE_NAMES, build_fakes


@pytest.mark.asyncio
async def test_full_stack_unbooted_runs_50_ticks_and_round_trips_snapshot(tmp_path):
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
    modules = build_fakes(CANONICAL_MODULE_NAMES, bus)
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

    any_experiential_broadcast = False
    try:
        for tick in range(50):
            for module in modules.values():
                await module.publish_one(salience=0.4 + 0.005 * tick)
            result = await cycle.tick()
            assert result.error is False, result.error_message
            if result.is_experiential and result.events_collected > 0:
                any_experiential_broadcast = True
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.1)

        assert cycle.error_counts == {}, cycle.error_counts
        assert any_experiential_broadcast

        # Snapshot the full unbooted registry and restore into fresh instances.
        fm = ForkManager(tmp_path)
        snap = fm.snapshot(registry, label="phase-9 unbooted")
        assert set(snap.modules) == set(CANONICAL_MODULE_NAMES)

        fresh_registry = ModuleRegistry()
        fresh_modules = build_fakes(CANONICAL_MODULE_NAMES, bus)
        for module in fresh_modules.values():
            fresh_registry.register(module)
        # Restore loads serialized state back via deserialize.
        loaded = fm.restore(snap.id, fresh_registry)
        assert loaded.id == snap.id
    finally:
        for module in modules.values():
            await module.shutdown()
        await bus.close()


@pytest.mark.asyncio
async def test_full_stack_with_nexus_co_existence(tmp_path):
    """Cycle + Nexus on the same fakeredis. Nexus bridge reads streams
    without disrupting the cycle's reads."""
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.nexus.bridge import BusBridge
    from kaine.nexus.privacy import PrivacyFilter

    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    syneidesis = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=8),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=10,
        publication_threshold=0.0,
    )
    registry = ModuleRegistry()
    modules = build_fakes(["soma", "chronos", "lingua"], bus)
    for module in modules.values():
        registry.register(module)
        await module.initialize()

    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syneidesis,
        registry=registry,
        processing_rate_hz=20.0,
        experiential_rate_hz=20.0,
    )

    bridge = BusBridge(
        bus,
        PrivacyFilter(),
        streams=["lingua.out"],
        poll_interval_s=0.01,
    )
    bridge._cursors["lingua.out"] = "0"
    diag_client = bridge.add_client("diagnostics")
    await bridge.start()
    try:
        for _ in range(5):
            for m in modules.values():
                await m.publish_one(salience=0.7)
            result = await cycle.tick()
            assert result.error is False
            await asyncio.sleep(0.01)
        # Nexus diagnostics SSE saw at least one event from lingua.out
        # (scrubbed of content fields, but the event itself surfaced).
        assert diag_client.queue.qsize() > 0
    finally:
        await bridge.stop()
        for m in modules.values():
            await m.shutdown()
        await bus.close()
