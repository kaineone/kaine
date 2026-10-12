# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The sleep subsystem: phase functions + scheduler smoke."""
from __future__ import annotations

import pytest

from kaine.modules.sleep.module import Sleep
from kaine.modules.sleep.phases import (
    consolidate_memory,
    reset_affect,
)
from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_phase_consolidate_memory_runs_clean_without_collaborator():
    result = await consolidate_memory(None)
    assert result.success is True
    assert "skipped" in result.metadata


@pytest.mark.asyncio
async def test_phase_reset_affect_calls_affect():
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
async def test_sleep_constructs_and_serializes():
    async with SubsystemHarness() as h:
        sleep = Sleep(h.bus, interval_seconds=3600.0)
        await h.register(sleep)
        state = sleep.serialize()
        assert isinstance(state, dict)
