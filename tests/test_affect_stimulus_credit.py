# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Novelty after the entity's own stimulus act is its own response (D5).

Boredom relief by alert excess within Delta_resp (the affect module's
``goal_response_window_s``) after a realized stimulus act is credited ``own``;
outside the window, after a failed act, after another effector's act, or with
stimulus control off, the credit rule is unchanged.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.bus.streams import EFFECTORS_STREAM
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


def _action(effector="stimulus", success=True):
    return Event(
        source="effectors",
        type="effectors.action",
        payload={"effector": effector, "success": success, "elapsed_ms": 0.1, "error": None,
                 "blocked": False, "alert": not success},
        salience=0.3,
        timestamp=datetime.now(timezone.utc),
    )


async def _end_boredom_by_novelty(affect, t, *, act=None, act_at=None, relief_at=None):
    """Open a boredom crossing and end it by alert excess alone (no learning progress)."""
    boredom = affect.drives.boredom
    boredom.value = 0.75
    boredom._has_fired = True
    if act is not None:
        t[0] = act_at
        await affect._handle_peer_event(EFFECTORS_STREAM, act)
    t[0] = (relief_at if relief_at is not None else t[0]) + 1.0
    affect._last_tick_at = t[0] - 1.0
    for _ in range(200):
        if not boredom._has_fired:
            break
        # A burst of scene cuts: alerts well above the habituated rate.
        affect._alert_fast = 1.0
        affect._alert_slow = 0.05
        t[0] += 0.5
        await affect._tick()
    assert not boredom._has_fired, "boredom never ended"
    return boredom.own_ends, boredom.other_ends


async def test_off_alert_excess_is_not_the_entitys_own(bus):
    t = [100.0]
    affect = Affect(bus, clock=lambda: t[0], goal_response_window_s=10.0)
    own, other = await _end_boredom_by_novelty(affect, t, act=_action(), act_at=100.0)
    assert (own, other) == (0, 1)


async def test_on_novelty_within_the_window_after_an_own_act_is_own(bus):
    t = [100.0]
    affect = Affect(bus, clock=lambda: t[0], goal_response_window_s=10.0)
    samples = []
    affect.set_stimulus_credit(lambda dt, **kw: samples.append(kw))
    own, other = await _end_boredom_by_novelty(affect, t, act=_action(), act_at=100.0)
    assert (own, other) == (1, 0)
    assert any(s["in_window"] for s in samples)


async def test_on_outside_the_window_the_rule_is_unchanged(bus):
    t = [100.0]
    affect = Affect(bus, clock=lambda: t[0], goal_response_window_s=10.0)
    affect.set_stimulus_credit()
    # The act was 30 s before the relief begins: the window has closed.
    own, other = await _end_boredom_by_novelty(
        affect, t, act=_action(), act_at=70.0, relief_at=100.0
    )
    assert (own, other) == (0, 1)


@pytest.mark.parametrize("act", [_action(success=False), _action(effector="notify")])
async def test_on_a_failed_or_other_act_opens_no_window(bus, act):
    t = [100.0]
    affect = Affect(bus, clock=lambda: t[0], goal_response_window_s=10.0)
    affect.set_stimulus_credit()
    own, other = await _end_boredom_by_novelty(affect, t, act=act, act_at=100.0)
    assert (own, other) == (0, 1)


async def test_the_window_closes_at_delta_resp(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], goal_response_window_s=10.0)
    affect.set_stimulus_credit()
    await affect._handle_peer_event(EFFECTORS_STREAM, _action())
    assert affect._in_stimulus_window(10.0)
    assert not affect._in_stimulus_window(10.001)
    assert not affect._in_stimulus_window(-0.5)


async def test_off_reads_no_effectors_stream_and_on_does(bus):
    off = Affect(bus, clock=lambda: 0.0)
    await off.initialize()
    try:
        assert EFFECTORS_STREAM not in off._cursors
    finally:
        await off.shutdown()
    on = Affect(bus, clock=lambda: 0.0)
    on.set_stimulus_credit()
    await on.initialize()
    try:
        assert EFFECTORS_STREAM in on._cursors
    finally:
        await on.shutdown()


async def test_a_realized_act_on_the_bus_opens_the_window(bus):
    import asyncio

    t = [50.0]
    affect = Affect(bus, clock=lambda: t[0], goal_response_window_s=10.0)
    affect.set_stimulus_credit()
    await affect.initialize()
    try:
        await bus.publish(_action())
        for _ in range(100):
            if affect._stimulus_act_at is not None:
                break
            await asyncio.sleep(0.02)
        assert affect._stimulus_act_at == 50.0
    finally:
        await affect.shutdown()


async def _end_in_the_build_step(affect, t, *, credit_on):
    """Leave boredom just above its re-fire band after the relief step, so the
    crossing ends in the build step (pure decay while novelty saturates)."""
    if credit_on:
        affect.set_stimulus_credit()
    t[0] = 10.0
    await affect._handle_peer_event(EFFECTORS_STREAM, _action())
    boredom = affect.drives.boredom
    band = boredom.threshold * boredom.hysteresis_fraction
    import math

    boredom.value = band * (1.0 + 1e-4) / math.exp(-boredom.relief_gain * 1.0)
    boredom._has_fired = True
    affect._alert_fast = 50.0  # alert excess saturates at 1 after this update's decay
    affect._alert_slow = 0.05
    affect._last_tick_at = 10.0
    t[0] = 11.0
    await affect._tick()
    assert not boredom._has_fired
    return boredom.own_ends, boredom.other_ends


async def test_a_fall_in_the_build_step_within_the_window_counts_own(bus):
    t = [0.0]
    on = Affect(bus, clock=lambda: t[0], goal_response_window_s=10.0)
    ends = await _end_in_the_build_step(on, t, credit_on=True)
    assert ends == (1, 0)


async def test_a_fall_in_the_build_step_with_credit_off_is_not_own(bus):
    t = [0.0]
    off = Affect(bus, clock=lambda: t[0], goal_response_window_s=10.0)
    ends = await _end_in_the_build_step(off, t, credit_on=False)
    assert ends == (0, 1)


async def test_an_end_the_window_alone_credits_is_counted_for_the_readout(bus):
    t = [100.0]
    affect = Affect(bus, clock=lambda: t[0], goal_response_window_s=10.0)
    samples = []
    affect.set_stimulus_credit(lambda dt, **kw: samples.append(kw))
    ends = await _end_boredom_by_novelty(affect, t, act=_action(), act_at=100.0)
    assert ends == (1, 0)
    assert sum(s["window_credited_end"] for s in samples) == 1


async def test_an_end_outside_the_window_is_not_counted_as_the_windows(bus):
    t = [100.0]
    affect = Affect(bus, clock=lambda: t[0], goal_response_window_s=10.0)
    samples = []
    affect.set_stimulus_credit(lambda dt, **kw: samples.append(kw))
    await _end_boredom_by_novelty(affect, t, act=_action(), act_at=70.0, relief_at=100.0)
    assert not any(s["window_credited_end"] for s in samples)


async def test_an_end_learning_progress_credits_anyway_is_not_the_windows(bus):
    """Inside the window, an end the plain rule already credits as own (learning
    progress, no novelty) is not counted as credited by the window."""
    t = [10.0]
    affect = Affect(bus, clock=lambda: t[0], goal_response_window_s=10.0)
    samples = []
    affect.set_stimulus_credit(lambda dt, **kw: samples.append(kw))
    await affect._handle_peer_event(EFFECTORS_STREAM, _action())
    affect._progress = lambda: (0.9, 0.0)
    boredom = affect.drives.boredom
    boredom.value = boredom.threshold * boredom.hysteresis_fraction * 1.001
    boredom._has_fired = True
    affect._last_tick_at = 10.0
    t[0] = 11.0
    await affect._tick()
    assert not boredom._has_fired and boredom.own_ends == 1
    assert samples and samples[-1]["in_window"] is True
    assert not any(s["window_credited_end"] for s in samples)
