# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The real forward head on the real NumPy CfC: a seeded broadcast sequence gives a
non-zero temporal prediction error, the error falls as the head adapts to a steady
cadence, and once adapted a timing surprise stands out against the rolling window
the salience is normalised by. At the head's learning rate this takes thousands of
broadcasts (minutes of lived time), so an unadapted head does not alert yet."""

from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.chronos.featurizer import SnapshotFeaturizer
from kaine.modules.chronos.module import Chronos


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _snapshot(tick: int, sources: list[tuple[str, float]]) -> WorkspaceSnapshot:
    events = [
        (
            f"{tick}-{i}",
            Event(
                source=src,
                type=f"{src}.report",
                payload={},
                salience=sal,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        for i, (src, sal) in enumerate(sources)
    ]
    return WorkspaceSnapshot(tick_index=tick, selected_events=events, inhibited=False)


@pytest.mark.asyncio
async def test_real_head_publishes_calibrated_prediction_error(bus: AsyncBus):
    now = {"t": 0.0}
    chronos = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: now["t"]),
        forward_prediction=True,
        reservoir_seed=7,
        clock=lambda: now["t"],
    )
    await chronos.initialize()
    try:
        steady = [("audition", 0.4), ("topos", 0.5), ("soma", 0.3)]
        for tick in range(4000):
            now["t"] += 0.3
            await chronos.on_workspace(_snapshot(tick, steady))
        now["t"] += 6.0
        await chronos.on_workspace(
            _snapshot(4000, [("praxis", 0.95), ("lingua", 0.9), ("nous", 0.9)])
        )
        entries = await bus.read("chronos.out", last_id="0", count=5000)
        errors = [e.payload["temporal_prediction_error"] for _, e in entries]
        assert len(errors) == 4001
        assert errors[0] == 0.0
        assert all(err > 0.0 for err in errors[1:])
        assert errors[-2] < 0.6 * errors[1]
        window = errors[-33:-1]
        surprise = errors[-1]
        assert surprise > 3.0 * (sum(window) / len(window))
        assert entries[-1][1].salience == pytest.approx(0.7)
    finally:
        await chronos.shutdown()
