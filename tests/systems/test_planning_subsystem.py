# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The planning subsystem: workspace broadcast → active-inference belief + policy.

Uses :class:`FakeEngine` (no pymdp / no JAX) so the subsystem suite is green
without the reasoning extra. An opt-in real-pymdp check runs only when
``KAINE_PLANNING_RUN_REAL_PYMDP=1`` and the extra is installed.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from kaine.modules.planning import FakeEngine, Planning
from tests.systems._harness import SubsystemHarness


def _selected_event(source="interoception", type_="interoception.report", salience=0.9):
    return {
        "entry_id": "e1",
        "source": source,
        "type": type_,
        "salience": salience,
        "payload": {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "causal_parent": None,
    }


@pytest.mark.asyncio
async def test_planning_constructs_with_fake_engine():
    async with SubsystemHarness() as h:
        planning = Planning(h.bus, engine=FakeEngine())
        await h.register(planning)
        assert planning.name == "planning"
        assert isinstance(planning.serialize(), dict)


@pytest.mark.asyncio
async def test_planning_publishes_belief_and_policy_on_broadcast():
    async with SubsystemHarness() as h:
        planning = Planning(h.bus, engine=FakeEngine(policy_efe=[0.9, 0.05, 0.5, 0.7]))
        await h.register(planning)
        await h.broadcast_workspace(
            {"tick_index": 0, "selected": [_selected_event()]}
        )
        beliefs = await h.collect(
            "planning.out", count=1, timeout=1.0, filter_type="planning.belief"
        )
        assert len(beliefs) == 1
        assert beliefs[0].payload["kind"] == "belief"


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.environ.get("KAINE_PLANNING_RUN_REAL_PYMDP") not in ("1", "true", "TRUE"),
    reason="KAINE_PLANNING_RUN_REAL_PYMDP not set; live pymdp contract test skipped",
)
async def test_planning_against_real_pymdp_engine():
    async with SubsystemHarness() as h:
        planning = Planning(h.bus)
        await h.register(planning)
        await h.broadcast_workspace(
            {"tick_index": 0, "selected": [_selected_event()]}
        )
        beliefs = await h.collect(
            "planning.out", count=1, timeout=2.0, filter_type="planning.belief"
        )
        assert len(beliefs) == 1
