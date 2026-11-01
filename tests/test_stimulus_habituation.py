# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Habituation damps compulsive skipping (stimulus-control-act, design D6).

The offline synthetic check behind docs/records/shakedowns/2026-10-31-stimulus-
control-habituation.md, on the affect module's own alert-rate trackers: a
programme with a scene cut every 20 s, and a skip at the command interval
(30 s) bringing three extra alerts each. Boredom's relief by novelty is the
alert excess ``r_f / max(r_s, r_0) - 1 - m_B``; sustained skipping raises the
slow rate ``r_s`` too, so the excess each skip buys falls well below the first
skip's. It settles at a floor rather than zero, which is why the command
interval and the per-awake-hour seek cap bound the rest.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.modules.affect import Affect


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    b = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=fakeredis.FakeRedis(decode_responses=True),
    )
    yield b
    await b.close()


def _alert():
    return Event(
        source="vision",
        type="vision.report",
        payload={"prediction_error": None, "alert": True, "normalised_error": 1.0, "normalised_change": 1.0},
        salience=0.7,
        timestamp=datetime.now(timezone.utc),
    )


async def _per_skip_excess(bus, *, skip_period_s, alerts_per_skip, base_period_s, seconds, step_s=0.5):
    """Mean alert excess over each inter-skip interval, in order."""
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    cycles: list[float] = []
    acc = 0.0
    next_skip = 0.0
    next_cut = 0.0
    for i in range(int(seconds / step_s)):
        t[0] = i * step_s
        if t[0] >= next_cut:
            await affect._handle_peer_event("vision.out", _alert())
            next_cut += base_period_s
        if t[0] >= next_skip:
            if next_skip > 0:
                cycles.append(acc / skip_period_s)
                acc = 0.0
            for _ in range(alerts_per_skip):
                await affect._handle_peer_event("vision.out", _alert())
            next_skip += skip_period_s
        await affect._tick()
        acc += affect._alert_excess() * step_s
    return cycles


async def test_sustained_skipping_buys_ever_less_novelty(bus):
    cycles = await _per_skip_excess(
        bus, skip_period_s=30.0, alerts_per_skip=3, base_period_s=20.0, seconds=1800.0
    )
    first, settled = cycles[0], sum(cycles[-10:]) / 10
    assert first > 0.3
    assert settled < first / 3, (first, settled)
    assert settled > 0.0  # a floor, not zero: the rate bounds limit the rest


async def test_skips_at_the_hourly_cap_spacing_habituate_less(bus):
    # Twenty seeks per awake hour, evenly spaced, is one every 180 s.
    spaced = await _per_skip_excess(
        bus, skip_period_s=180.0, alerts_per_skip=3, base_period_s=20.0, seconds=3600.0
    )
    rapid = await _per_skip_excess(
        bus, skip_period_s=30.0, alerts_per_skip=3, base_period_s=20.0, seconds=3600.0
    )
    assert sum(spaced[-3:]) / 3 < spaced[0]
    # Per skip, rapid skipping buys less novelty than spaced skipping.
    assert sum(rapid[-10:]) / 10 * 30.0 < sum(spaced[-3:]) / 3 * 180.0
