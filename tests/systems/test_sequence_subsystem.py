# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The sequence subsystem: workspace broadcasts → temporal-context events."""
from __future__ import annotations

import pytest

from kaine.modules.sequence.module import Sequence
from tests.systems._harness import SubsystemHarness


@pytest.mark.asyncio
async def test_sequence_publishes_on_workspace_broadcast():
    async with SubsystemHarness() as h:
        sequence = Sequence(h.bus, baseline_salience=0.2, alert_salience=0.7)
        await h.register(sequence)
        # Feed a sequence of broadcasts so the featurizer has history.
        for tick in range(5):
            await h.broadcast_workspace(
                {
                    "tick_index": tick,
                    "selected": [
                        {"source": "interoception", "type": "interoception.tick", "salience": 0.5, "payload": {}}
                    ],
                    "salience_scores": {f"x-{tick}": 0.5},
                }
            )
        events = await h.collect("sequence.out", count=1, timeout=2.0)
        assert events, "Sequence should have published a context event"


@pytest.mark.asyncio
async def test_sequence_serializes_state():
    async with SubsystemHarness() as h:
        sequence = Sequence(h.bus)
        await h.register(sequence)
        state = sequence.serialize()
        assert isinstance(state, dict)
