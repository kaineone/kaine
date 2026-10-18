# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Valence follows error dynamics: the fall or rise of prediction errors and the change in wellness (paper 3.5, A.4)."""

import math
import random
from datetime import datetime, timezone

import pytest

from kaine.boot.factories.affect import make_affect
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.modules.affect import Affect

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _vision(err):
    return Event(
        source="vision",
        type="vision.report",
        payload={"alert": False, "prediction_error": err},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


def _wellness(w):
    return Event(
        source="interoception",
        type="interoception.report",
        payload={"wellness": w, "alerts": []},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


async def _run(affect, t, seconds, err=None, well=None, step=1.0):
    """Advance `seconds` of entity time in `step` ticks; `err` and `well` map elapsed s to a value."""
    n = int(round(seconds / step))
    start = t[0]
    for _ in range(n):
        t[0] += step
        if err is not None:
            await affect._handle_peer_event("vision.out", _vision(err(t[0] - start)))
        if well is not None:
            await affect._handle_peer_event("interoception.out", _wellness(well(t[0] - start)))
        await affect._tick()


async def test_falling_error_raises_valence(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=999.0)
    await _run(
        affect,
        t,
        260.0,
        err=lambda e: 1.0 if e <= 200.0 else max(0.2, 1.0 - (e - 200.0) / 60.0 * 0.8),
        well=lambda _: 0.9,
    )
    assert affect.state.valence > 0.05


async def test_rising_error_lowers_valence(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=999.0)
    await _run(
        affect,
        t,
        260.0,
        err=lambda e: 1.0 if e <= 200.0 else 1.0 + (e - 200.0) / 60.0 * 2.0,
        well=lambda _: 0.9,
    )
    assert affect.state.valence < -0.05


async def test_steady_healthy_host_is_neutral(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=999.0)
    await _run(affect, t, 600.0, err=lambda _: 1.0, well=lambda _: 0.9)
    assert abs(affect.state.valence) < 0.01

    t = [0.0]
    affect_level = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=999.0,
        valence_rule="wellness_level",
    )
    await _run(affect_level, t, 600.0, err=lambda _: 1.0, well=lambda _: 0.9)
    assert affect_level.state.valence > 0.3


async def test_falling_wellness_lowers_valence(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=999.0)
    await _run(
        affect,
        t,
        330.0,
        err=lambda _: 1.0,
        well=lambda e: 0.9 if e <= 300.0 else max(0.5, 0.9 - (e - 300.0) / 30.0 * 0.4),
    )
    assert affect.state.valence < -0.05

    await _run(affect, t, 600.0, err=lambda _: 1.0, well=lambda _: 0.5)
    assert abs(affect.state.valence) < 0.02


async def test_valence_stays_bounded_with_random_inputs(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=999.0)
    rng = random.Random(7)
    for i in range(2000):
        t[0] += 1.0
        err = 10.0 ** rng.uniform(-6.0, 2.0)
        wellness = float(rng.choice([0.0, 1.0]))
        if i % 73 == 0:
            wellness = float("nan")
        if i % 89 == 0:
            wellness = -1.0
        await affect._handle_peer_event("vision.out", _vision(err))
        await affect._handle_peer_event("interoception.out", _wellness(wellness))
        await affect._tick()
        assert -1.0 <= affect.state.valence <= 1.0
        assert math.isfinite(affect.state.valence)


async def test_wellness_change_is_zero_before_and_after_first_report(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=999.0)
    assert affect._wellness_change() == 0.0
    await affect._handle_peer_event("interoception.out", _wellness(0.8))
    assert affect._wellness_change() == 0.0


async def test_wellness_level_rule_matches_old_formula(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=999.0,
        valence_rule="wellness_level",
    )
    for _ in range(50):
        t[0] += 1.0
        await affect._handle_peer_event("vision.out", _vision(1.0))
        await affect._handle_peer_event("interoception.out", _wellness(0.7))
        g = affect._progress()[1]
        v = affect.state.valence
        p = affect._pleasantness(g)
        target = max(-1.0, min(1.0, p + 0.7 - 0.5))
        expected = v + (target - v) * (1.0 - math.exp(-1.0 / 30.0))
        await affect._tick()
        assert abs(affect.state.valence - expected) < 1e-12
    assert affect._well_last_at is None
    assert "wellness_means" not in affect.serialize()


async def test_sleep_keeps_wellness_means(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=999.0)
    await _run(
        affect,
        t,
        100.0,
        err=lambda _: 1.0,
        well=lambda e: 0.6 + 0.2 * math.sin(e / 10.0),
    )
    fast_sum = affect._well_fast_sum
    fast_count = affect._well_fast_count
    slow_sum = affect._well_slow_sum
    slow_count = affect._well_slow_count
    await affect.affective_reset()
    assert affect._well_fast_sum == fast_sum
    assert affect._well_fast_count == fast_count
    assert affect._well_slow_sum == slow_sum
    assert affect._well_slow_count == slow_count
    assert affect.state.valence == 0.0


async def test_persistence_of_wellness_means(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=999.0)
    await _run(
        affect,
        t,
        120.0,
        err=lambda _: 1.0,
        well=lambda e: 0.4 + 0.3 * math.sin(e / 15.0),
    )
    original_change = affect._wellness_change()
    state = affect.serialize()

    fresh = Affect(bus, clock=lambda: t[0], publish_interval_s=999.0)
    fresh.deserialize(state)
    assert fresh._wellness_change() == original_change

    corrupt_cases = [
        {"wellness_means": {"fast_sum": 1.0, "fast_count": -1.0, "slow_sum": 1.0, "slow_count": 1.0}},
        {"wellness_means": {"fast_sum": 1.0, "fast_count": 1.0, "slow_sum": float("nan"), "slow_count": 1.0}},
        {"wellness_means": {"fast_sum": 2.0, "fast_count": 1.0, "slow_sum": 0.5, "slow_count": 1.0}},
        {"wellness_means": "not-a-dict"},
    ]
    for corrupt in corrupt_cases:
        corrupted_state = {**state, **corrupt}
        module = Affect(bus, clock=lambda: t[0], publish_interval_s=999.0)
        module.deserialize(corrupted_state)
        assert module._well_last_at is None

    old_rule = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=999.0,
        valence_rule="wellness_level",
    )
    old_rule.deserialize(state)
    assert old_rule._well_last_at is None
    assert old_rule._well_fast_count == 0.0


async def test_valence_rule_validation(bus):
    t = [0.0]
    with pytest.raises(ValueError):
        Affect(
            bus,
            clock=lambda: t[0],
            publish_interval_s=999.0,
            valence_rule="other",
        )
    Affect(bus, clock=lambda: t[0], publish_interval_s=999.0, valence_rule="error_dynamics")
    Affect(bus, clock=lambda: t[0], publish_interval_s=999.0, valence_rule="wellness_level")


async def test_config_wiring(bus):
    affect = make_affect(bus, {"valence_rule": "wellness_level"})
    assert affect._valence_rule == "wellness_level"
    affect_default = make_affect(bus, {})
    assert affect_default._valence_rule == "error_dynamics"
