# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Cycle subsystem: tick collects events, calls syneidesis, broadcasts."""
from __future__ import annotations


import pytest

from kaine.cycle.engine import CognitiveCycle
from kaine.modules import ModuleRegistry
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticGoalScorer,
    StaticThymosModulator,
    Syneidesis,
)

from tests.systems._harness import SubsystemHarness


def _syneidesis():
    return Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=8),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=5,
        publication_threshold=0.0,
    )


@pytest.mark.asyncio
async def test_tick_with_empty_registry_runs_clean():
    async with SubsystemHarness() as h:
        cycle = CognitiveCycle(
            bus=h.bus,
            syneidesis=_syneidesis(),
            registry=ModuleRegistry(),
            processing_rate_hz=10.0,
            experiential_rate_hz=10.0,
        )
        result = await cycle.tick()
        assert result.error is False
        assert result.events_collected == 0


@pytest.mark.asyncio
async def test_tick_collects_from_registered_module_stream():
    async with SubsystemHarness() as h:
        registry = ModuleRegistry()
        from kaine.modules.echo import EchoModule

        echo = EchoModule(h.bus)
        registry.register(echo)
        await echo.initialize()

        cycle = CognitiveCycle(
            bus=h.bus,
            syneidesis=_syneidesis(),
            registry=registry,
            processing_rate_hz=10.0,
            experiential_rate_hz=10.0,
        )

        await echo.publish_one(salience=0.9)
        result = await cycle.tick()
        assert result.events_collected >= 1
        # Workspace broadcast SHOULD have been written.
        raw = await h.bus._client.xrange("workspace.broadcast")
        assert len(raw) == 1
        await echo.shutdown()


@pytest.mark.asyncio
async def test_runtime_rate_control_event_changes_pacing():
    async with SubsystemHarness() as h:
        cycle = CognitiveCycle(
            bus=h.bus,
            syneidesis=_syneidesis(),
            registry=ModuleRegistry(),
            processing_rate_hz=3.0,
            experiential_rate_hz=3.0,
        )
        assert cycle.processing_rate_hz == 3.0
        applied = await cycle.apply_rate_control_event({"processing_rate_hz": 7.0})
        assert applied is True
        assert cycle.processing_rate_hz == 7.0
