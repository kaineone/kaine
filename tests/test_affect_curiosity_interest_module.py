# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Curiosity as heterostatic interest in the affect module (paper A.4)."""

import math

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.affect import Affect

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _make_affect(bus):
    t = [0.0]
    return Affect(bus, clock=lambda: t[0], publish_interval_s=1.0), t


async def test_no_progress_no_interest(bus):
    affect, t = _make_affect(bus)
    affect._progress = lambda: (0.0, 0.0)
    for _ in range(3600):
        t[0] += 1.0
        await affect._tick()
    assert affect.drives.curiosity.value == 0.0
    entries = await bus.read("affect.out", last_id="0", count=5000)
    assert entries  # the module published its state, so the stream was read
    curiosity_events = [
        e
        for _eid, e in entries
        if e.type == "affect.drive" and getattr(e, "payload", {}).get("drive") == "curiosity"
    ]
    assert curiosity_events == []


async def test_progress_niche_publishes_crossing_without_goal(bus):
    affect, t = _make_affect(bus)
    affect._progress = lambda: (0.1, 0.0)
    for _ in range(600):
        t[0] += 1.0
        await affect._tick()
    entries = await bus.read("affect.out", last_id="0", count=5000)
    curiosity_events = [
        e
        for _eid, e in entries
        if e.type == "affect.drive"
        and getattr(e, "payload", {}).get("drive") == "curiosity"
        and getattr(e, "payload", {}).get("alert")
    ]
    assert curiosity_events
    assert affect.goals.active_for_drive("curiosity") is None
    affect._progress = lambda: (0.0, 0.0)
    for _ in range(4000):
        t[0] += 1.0
        await affect._tick()
    assert affect.drives.curiosity.value < 0.63
    assert affect.drives.curiosity.own_ends == 0
    assert affect.drives.curiosity.other_ends == 0


async def test_learning_relieves_boredom_as_own(bus):
    affect, t = _make_affect(bus)
    affect.drives.boredom.value = 0.9
    affect.drives.boredom.consume_crossing()
    affect._progress = lambda: (0.3, 0.0)
    affect._alert_excess = lambda: 0.0
    for _ in range(300):
        t[0] += 1.0
        await affect._tick()
        if affect.drives.boredom.value < 0.63:
            break
    assert affect.drives.boredom.value < 0.63
    assert affect.drives.boredom.own_ends == 1
    assert affect.drives.boredom.other_ends == 0


async def test_alert_excess_relief_is_not_own(bus):
    affect, t = _make_affect(bus)
    affect.drives.boredom.value = 0.9
    affect.drives.boredom.consume_crossing()
    affect._progress = lambda: (0.0, 0.0)
    affect._alert_excess = lambda: 0.3
    for _ in range(300):
        t[0] += 1.0
        await affect._tick()
        if affect.drives.boredom.value < 0.63:
            break
    assert affect.drives.boredom.value < 0.63
    assert affect.drives.boredom.own_ends == 0
    assert affect.drives.boredom.other_ends == 1


async def test_arousal_target_ignores_curiosity(bus):
    affect, _t = _make_affect(bus)
    baseline = affect.baseline.arousal
    affect.drives.curiosity.value = 0.9
    for deficit in affect.drives.deficits():
        deficit.value = 0.0
    assert affect._arousal_target() == baseline
    affect.drives.boredom.value = 0.9
    assert affect._arousal_target() > baseline


async def test_sleep_keeps_interest(bus):
    affect, _t = _make_affect(bus)
    affect.drives.curiosity.value = 0.8
    affect.drives.curiosity.consume_crossing()
    affect.drives.boredom.value = 0.8
    await affect.affective_reset()
    assert affect.drives.curiosity.value == 0.8
    assert affect.drives.curiosity._has_fired is True
    assert affect.drives.boredom.value == 0.0


async def test_state_carries_scheme_and_round_trips(bus):
    affect, _t = _make_affect(bus)
    affect.drives.curiosity.value = 0.8
    affect.drives.curiosity.consume_crossing()
    s = affect.serialize()
    assert s["curiosity_scheme"] == 2
    affect2, _t2 = _make_affect(bus)
    affect2.deserialize(s)
    assert affect2.drives.curiosity.value == 0.8
    assert affect2.drives.curiosity._has_fired is True


async def test_old_state_migrates_curiosity(bus):
    affect, _t = _make_affect(bus)
    affect.drives.curiosity.value = 0.9
    affect.drives.curiosity.consume_crossing()
    affect.drives.curiosity.own_ends = 3
    affect.drives.boredom.value = 0.85
    affect.drives.boredom.consume_crossing()
    affect.drives.boredom.own_ends = 2
    affect.goals.add("relieve curiosity", priority=0.9, drive="curiosity")
    affect.goals.add("relieve boredom", priority=0.9, drive="boredom")
    s = affect.serialize()
    del s["curiosity_scheme"]

    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client2 = fakeredis.FakeRedis(decode_responses=True)
    bus2 = AsyncBus(BusConfig(password="x", audit_required=False), client=client2)
    try:
        affect2, _t2 = _make_affect(bus2)
        affect2.deserialize(s)
        assert affect2.drives.curiosity.value == 0.0
        assert affect2.drives.curiosity._has_fired is False
        assert affect2.drives.curiosity.own_ends == 0
        assert affect2.drives.curiosity.other_ends == 0
        assert affect2.goals.active_for_drive("curiosity") is None
        assert affect2.drives.boredom.value == 0.85
        assert affect2.drives.boredom._has_fired is True
        assert affect2.drives.boredom.own_ends == 2
        assert affect2.goals.active_for_drive("boredom") is not None
        entries = await bus2.read("affect.goal", last_id="0", count=100)
        assert entries == []
    finally:
        await bus2.close()


async def test_dynamics_of_deficits_unchanged_without_progress(bus):
    affect, t = _make_affect(bus)
    affect._progress = lambda: (0.0, 0.0)
    affect._alert_excess = lambda: 0.0
    for drive in affect.drives.all():
        drive.value = 0.0
    for _ in range(120):
        t[0] += 1.0
        await affect._tick()
    build = 0.04
    decay = 0.0045
    expected = build / (build + decay) * (1.0 - math.exp(-(build + decay) * 120.0))
    assert math.isclose(affect.drives.boredom.value, expected, abs_tol=1e-9)


async def test_fall_explained_only_by_learning_progress_is_own(bus):
    # Relief by lp+ = 0.9 over one second leaves boredom just above its re-arm
    # band (0.63); the build step at u = 1 - lp+ = 0.1 then takes it below. At
    # the no-response input 1 - exc = 1 it would have risen, so the fall is the
    # entity's own (paper A.4 credit rule).
    affect, t = _make_affect(bus)
    affect._progress = lambda: (0.9, 0.0)
    affect._alert_excess = lambda: 0.0
    t[0] += 1.0
    await affect._tick()  # sync the update clock
    b = affect.drives.boredom
    b.value = (0.63 + 1e-4) / math.exp(-b.relief_gain * 0.9 * 1.0)
    b._has_fired = True
    own0, other0 = b.own_ends, b.other_ends
    t[0] += 1.0
    await affect._tick()
    assert b.value < 0.63
    assert (b.own_ends - own0, b.other_ends - other0) == (1, 0)
