# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.boot.factories.affect import make_affect
from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.affect import Affect
from kaine.modules.affect.state import DimensionalState

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _set_drives(affect, **values):
    for d in affect.drives.all():
        d.value = values.get(d.name, 0.0)


def _alert(change=3.0):
    return Event(
        source="vision",
        type="vision.report",
        payload={"alert": True, "normalised_error": 0.99, "normalised_change": change},
        salience=0.8,
        timestamp=datetime.now(timezone.utc),
    )


def _make(bus, **kwargs):
    t = [0.0]
    return Affect(
        bus,
        publish_interval_s=999.0,
        clock=lambda: t[0],
        **kwargs,
    ), t


async def test_arousal_target_values(bus):
    affect, _ = _make(bus)
    _set_drives(affect, curiosity=0.0, boredom=0.0, social_drive=0.0, restlessness=0.0)
    assert affect._arousal_target() == pytest.approx(0.3)

    _set_drives(affect, curiosity=0.0, boredom=0.9, social_drive=0.0, restlessness=0.0)
    assert affect._arousal_target() == pytest.approx(0.3 + 0.2 * 0.7 * 0.9)

    # Curiosity is heterostatic and no longer contributes to tonic arousal.
    _set_drives(affect, curiosity=0.7, boredom=0.5, social_drive=0.0, restlessness=0.0)
    assert affect._arousal_target() == pytest.approx(0.3 + 0.2 * 0.7 * 0.5)

    affect_gain, _ = _make(bus, drive_arousal_gain=0.5)
    _set_drives(affect_gain, curiosity=0.0, boredom=0.0, social_drive=0.0, restlessness=1.0)
    assert affect_gain._arousal_target() == pytest.approx(0.65)


async def test_deprived_rest(bus):
    affect, t = _make(bus)
    _set_drives(affect, boredom=0.9)
    t[0] += 300.0
    await affect._tick()
    assert affect.state.arousal == pytest.approx(0.426, abs=0.005)


async def test_satisfied_rest(bus):
    affect, t = _make(bus)
    affect._state = DimensionalState(valence=0.0, arousal=0.8, dominance=0.0)
    _set_drives(affect, curiosity=0.0, boredom=0.0, social_drive=0.0, restlessness=0.0)
    t[0] += 300.0
    await affect._tick()
    assert affect.state.arousal == pytest.approx(0.3, abs=0.005)


async def test_target_uses_start_of_tick_dominant_drive(bus):
    affect, t = _make(bus)
    _set_drives(affect, boredom=0.9)
    t[0] += 1.0
    await affect._tick()
    target = 0.3 + 0.2 * 0.7 * 0.9
    expected = 0.3 + (target - 0.3) * 0.05
    assert affect.state.arousal == pytest.approx(expected)


async def test_phasic_steps_unchanged(bus):
    affect, t = _make(bus)
    for _ in range(300):
        _set_drives(affect, boredom=0.9)
        t[0] += 1.0
        await affect._tick()
    assert affect.state.arousal == pytest.approx(0.426, abs=0.005)
    await affect._handle_peer_event("vision.out", _alert(change=3.0))
    assert affect.state.arousal == pytest.approx(0.426 + 0.15 * 2.0)


async def test_sleep_reset(bus):
    affect, t = _make(bus)
    _set_drives(affect, boredom=0.9)
    t[0] += 300.0
    await affect._tick()
    await affect.affective_reset()
    assert affect.state.arousal == 0.3
    for d in affect.drives.all():
        assert d.value == 0.0
    assert affect._arousal_target() == 0.3


async def test_gain_zero_equals_old_rule(bus):
    affect, t = _make(bus, drive_arousal_gain=0.0)
    affect._state = DimensionalState(valence=0.0, arousal=0.8, dominance=0.0)
    a = 0.8
    for _ in range(50):
        _set_drives(affect, boredom=0.9)
        t[0] += 1.0
        await affect._tick()
        a = a + (0.3 - a) * min(1.0, 0.05 * 1.0)
        assert affect.state.arousal == a


async def test_drive_arousal_gain_validation(bus):
    with pytest.raises(ValueError):
        Affect(bus, drive_arousal_gain=-0.1, publish_interval_s=999.0)
    with pytest.raises(ValueError):
        Affect(bus, drive_arousal_gain=1.5, publish_interval_s=999.0)
    with pytest.raises(ValueError):
        Affect(bus, drive_arousal_gain=float("nan"), publish_interval_s=999.0)


async def test_dominance_relaxes_to_baseline(bus):
    affect, t = _make(bus)
    affect._state = DimensionalState(valence=0.0, arousal=0.3, dominance=0.5)
    _set_drives(affect, boredom=0.9)
    t[0] += 1.0
    await affect._tick()
    assert affect.state.dominance == pytest.approx(0.5 - 0.5 * 0.05)


async def test_config_wiring(bus):
    assert make_affect(bus, {"drive_arousal_gain": 0.35})._drive_arousal_gain == 0.35
    assert make_affect(bus, {})._drive_arousal_gain == 0.2
