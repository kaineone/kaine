# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Hypnos subsystem: phase functions + scheduler smoke."""
from __future__ import annotations

import pytest

from kaine.modules.hypnos.module import Hypnos
from kaine.modules.hypnos.phases import (
    consolidate_memory,
    reset_affect,
    revise_beliefs,
)

from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_phase_consolidate_memory_runs_clean_without_collaborator():
    result = await consolidate_memory(None)
    assert result.success is True
    assert "skipped" in result.metadata


@pytest.mark.asyncio
async def test_phase_reset_affect_calls_thymos():
    class FakeThymos:
        def __init__(self):
            self.calls = 0

        async def affective_reset(self):
            self.calls += 1

    t = FakeThymos()
    result = await reset_affect(t)
    assert result.success is True
    assert t.calls == 1


@pytest.mark.asyncio
async def test_hypnos_constructs_and_serializes():
    async with SubsystemHarness() as h:
        hypnos = Hypnos(h.bus, interval_seconds=3600.0)
        await h.register(hypnos)
        state = hypnos.serialize()
        assert isinstance(state, dict)
