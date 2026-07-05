# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Chronos subsystem: workspace broadcasts → temporal-context events."""
from __future__ import annotations

import asyncio

import pytest

from kaine.modules.chronos.module import Chronos

from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_chronos_publishes_on_workspace_broadcast():
    async with SubsystemHarness() as h:
        chronos = Chronos(h.bus, baseline_salience=0.2, alert_salience=0.7)
        await h.register(chronos)
        # Feed a sequence of broadcasts so the featurizer has history.
        for tick in range(5):
            await h.broadcast_workspace(
                {
                    "tick_index": tick,
                    "selected": [
                        {"source": "soma", "type": "soma.tick", "salience": 0.5, "payload": {}}
                    ],
                    "salience_scores": {f"x-{tick}": 0.5},
                }
            )
        events = await h.collect("chronos.out", count=1, timeout=2.0)
        assert events, "Chronos should have published a context event"


@pytest.mark.asyncio
async def test_chronos_serializes_state():
    async with SubsystemHarness() as h:
        chronos = Chronos(h.bus)
        await h.register(chronos)
        state = chronos.serialize()
        assert isinstance(state, dict)
