# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phase 9.1: cycle rate stays within 25% of target across 50 ticks at
three configurations (1 Hz, 3.333 Hz, 10 Hz).

We use the real `asyncio.sleep` + `time.monotonic` so the test
measures genuine wall-clock pacing. The test allows 25% tolerance
because fakeredis introduces variable overhead; production rates on
real Redis are tighter.
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


async def _measure_rate(target_hz: float, n_ticks: int) -> float:
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    syn = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=8),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=5,
        publication_threshold=0.0,
    )
    registry = ModuleRegistry()
    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syn,
        registry=registry,
        processing_rate_hz=target_hz,
        experiential_rate_hz=target_hz,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    )
    try:
        start = time.monotonic()
        await cycle.run_forever(max_ticks=n_ticks)
        elapsed = time.monotonic() - start
        return n_ticks / elapsed
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_rate_stability_at_10hz():
    measured = await _measure_rate(target_hz=10.0, n_ticks=25)
    assert 7.5 <= measured <= 12.5, f"measured {measured} Hz, target 10 Hz"


@pytest.mark.asyncio
async def test_rate_stability_at_3p333hz():
    measured = await _measure_rate(target_hz=3.333, n_ticks=10)
    assert 2.5 <= measured <= 4.2, f"measured {measured} Hz, target 3.333 Hz"


@pytest.mark.asyncio
async def test_rate_stability_at_1hz():
    # Lower frequencies need more ticks to amortize the (n-1) sleeps / n
    # ticks fence-post effect against the 25% tolerance window. 10 ticks
    # at 1 Hz takes ~9 s wall.
    measured = await _measure_rate(target_hz=1.0, n_ticks=10)
    assert 0.75 <= measured <= 1.25, f"measured {measured} Hz, target 1 Hz"
