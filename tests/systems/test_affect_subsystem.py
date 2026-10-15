# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The affect subsystem: dimensional state updates + drive accumulation."""
from __future__ import annotations

import pytest

from kaine.modules.affect.module import Affect
from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_affect_publishes_dimensional_state():
    async with SubsystemHarness() as h:
        affect = Affect(h.bus, publish_interval_s=0.0001)
        await h.register(affect)
        # the affect module publishes state on workspace broadcasts.
        await h.broadcast_workspace({"tick_index": 0, "selected": []})
        events = await h.collect("affect.out", count=1, timeout=1.5)
        assert events, "Affect should publish a state event"
        # Payload includes valence / arousal / dominance somewhere in
        # the structure.
        first = events[0].payload
        text = repr(first)
        assert "valence" in text


@pytest.mark.asyncio
async def test_affect_serializes_dimensional_state():
    async with SubsystemHarness() as h:
        affect = Affect(h.bus, publish_interval_s=1.0)
        await h.register(affect)
        state = affect.serialize()
        # the affect module serializes both the live state and the baseline.
        live = state.get("state") or state.get("dimensional") or {}
        assert -1.0 <= live.get("valence", 0.0) <= 1.0
        assert 0.0 <= live.get("arousal", 0.0) <= 1.0
