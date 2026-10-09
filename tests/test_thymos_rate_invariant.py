# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.thymos import Thymos


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _event(source="soma", type_="t", salience=0.5, eid="e0", **payload) -> tuple:
    return eid, Event(
        source=source,
        type=type_,
        payload=payload or {"k": "v"},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(events=None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=events or [],
        inhibited=False,
    )


class _NoOpRegulation:
    async def suggest(self, state):
        return SimpleNamespace(valence=0.0, arousal=0.0, dominance=0.0)


@pytest.mark.asyncio
async def test_appraisal_rate_invariance(bus: AsyncBus):
    # Rewritten for research affect: the per-broadcast arousal nudge is removed,
    # so arousal no longer depends on broadcast rate or coalition variance.
    events = [
        _event(salience=0.8),
        _event(salience=0.1),
        _event(salience=0.1),
        _event(salience=0.2),
        _event(salience=0.4),
    ]
    snapshot = _snapshot(events)

    async def run(step_s: float) -> float:
        fake_now = [0.0]
        thymos = Thymos(
            bus,
            drift_rate_per_s=0.0,
            clock=lambda: fake_now[0],
            regulation=_NoOpRegulation(),
        )
        await thymos.initialize()
        try:
            total = 10.0
            n_steps = int(total / step_s)
            for i in range(1, n_steps + 1):
                fake_now[0] = i * step_s
                await thymos.on_workspace(snapshot)
            return thymos.state.arousal
        finally:
            await thymos.shutdown()

    arousal_slow = await run(0.3)
    arousal_fast = await run(0.1)
    # Arousal should stay at the baseline because neither drift nor appraisal nudges it.
    assert arousal_slow == pytest.approx(0.3)
    assert arousal_fast == pytest.approx(0.3)
    assert arousal_slow == pytest.approx(arousal_fast)


@pytest.mark.asyncio
async def test_timer_publishes_state(bus: AsyncBus):
    thymos = Thymos(bus, publish_interval_s=0.05)
    await thymos.initialize()
    try:
        await asyncio.sleep(0.25)
        entries = await bus.read("thymos.out", last_id="0", count=20)
        state_events = [e for _, e in entries if e.type == "thymos.state"]
        assert len(state_events) >= 2
    finally:
        await thymos.shutdown()
