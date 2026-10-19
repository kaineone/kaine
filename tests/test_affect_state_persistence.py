# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.affect import Affect

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _report(payload):
    return Event(
        source="vision",
        type="vision.report",
        payload=payload,
        salience=0.8,
        timestamp=datetime.now(timezone.utc),
    )


async def _feed_vision(affect, t, *, duration, alert_every=5, error_start=1.0, error_end=0.4):
    denom = max(1, duration - 1)
    for i in range(duration):
        e = error_start + (error_end - error_start) * i / denom
        alert = (i % alert_every == 0)
        payload = {
            "prediction_error": e,
            "alert": alert,
            "normalised_error": 1.0,
            "normalised_change": 2.5 if alert else 1.0,
        }
        await affect._handle_peer_event("vision.out", _report(payload))
        await affect._tick()
        t[0] += 1.0


async def test_affect_state_round_trip(bus):
    t = [0.0]
    affect = Affect(bus, publish_interval_s=999.0, clock=lambda: t[0])
    await _feed_vision(affect, t, duration=120)

    affect._intent_rate = 0.3
    affect._wellness = 0.8
    affect._interaction_seen = True

    state = affect.serialize()

    t2 = [0.0]
    affect2 = Affect(bus, publish_interval_s=999.0, clock=lambda: t2[0])
    affect2.deserialize(state)

    assert affect2._alert_fast == pytest.approx(affect._alert_fast)
    assert affect2._alert_slow == pytest.approx(affect._alert_slow)
    assert affect2._err_fast_sum == pytest.approx(affect._err_fast_sum)
    assert affect2._err_fast_count == pytest.approx(affect._err_fast_count)
    assert affect2._err_slow_sum == pytest.approx(affect._err_slow_sum)
    assert affect2._err_slow_count == pytest.approx(affect._err_slow_count)
    assert affect2._err_last_at["vision"] == 0.0
    assert affect2._intent_rate == pytest.approx(0.3)
    assert affect2._wellness == pytest.approx(0.8)
    assert affect2._interaction_seen is True
    assert affect2._progress() == pytest.approx(affect._progress())
    assert affect2._alert_excess() == pytest.approx(affect._alert_excess())


async def test_restore_does_not_relieve_boredom(bus):
    """Without the saved rates the slow rate restarts at its floor and boredom falls below its re-arm band within seconds."""
    t = [0.0]
    affect = Affect(bus, publish_interval_s=999.0, clock=lambda: t[0])
    # A constant error carries no learning progress, which would now relieve boredom
    # as the entity's own (paper A.4), so only the restored alert rates are tested.
    await _feed_vision(affect, t, duration=600, error_start=0.5, error_end=0.5)

    affect.drives.boredom.value = 0.9
    await affect._tick()
    goal = affect.goals.active_for_drive("boredom")
    assert goal is not None

    state = affect.serialize()

    t2 = [0.0]
    affect2 = Affect(bus, publish_interval_s=999.0, clock=lambda: t2[0])
    affect2.deserialize(state)

    goal_id = goal.id
    for i in range(60):
        alert = (i % 5 == 0)
        payload = {
            "prediction_error": 0.5,
            "alert": alert,
            "normalised_error": 1.0,
            "normalised_change": 2.5 if alert else 1.0,
        }
        await affect2._handle_peer_event("vision.out", _report(payload))
        await affect2._tick()
        assert affect2._alert_excess() == 0.0
        assert affect2.drives.boredom.value >= 0.85
        t2[0] += 1.0

    assert affect2.goals.active_for_drive("boredom").id == goal_id


async def test_affect_state_older_state_defaults(bus):
    t = [0.0]
    affect = Affect(bus, publish_interval_s=999.0, clock=lambda: t[0])
    await _feed_vision(affect, t, duration=120)

    state = affect.serialize()
    for key in ("alert_rates", "error_means", "intent_rate", "wellness", "interaction_seen"):
        state.pop(key, None)

    t2 = [0.0]
    affect2 = Affect(bus, publish_interval_s=999.0, clock=lambda: t2[0])
    affect2.deserialize(state)

    assert affect2.drives.to_dict() == state["drives"]
    assert affect2._alert_fast == 0.0
    assert affect2._alert_slow == 0.0
    assert affect2._err_fast_sum == {}
    assert affect2._err_fast_count == {}
    assert affect2._err_slow_sum == {}
    assert affect2._err_slow_count == {}
    assert affect2._err_last_at == {}
    assert affect2._intent_rate == 0.0
    assert affect2._wellness == 0.5
    assert affect2._interaction_seen is False


async def test_affect_state_invalid_values(bus):
    t = [0.0]
    affect = Affect(bus, publish_interval_s=999.0, clock=lambda: t[0])

    affect.deserialize({
        "alert_rates": {"fast": "x", "slow": -1.0},
        "error_means": {
            "vision": {"fast_sum": 1.0, "fast_count": 0.0, "slow_sum": 1.0, "slow_count": 1.0},
            "audition": "bad",
            3: {},
        },
        "intent_rate": 2.0,
        "wellness": float("nan"),
        "interaction_seen": "yes",
    })

    assert affect._alert_fast == 0.0
    assert affect._alert_slow == 0.0
    assert affect._err_fast_sum == {}
    assert affect._err_fast_count == {}
    assert affect._err_slow_sum == {}
    assert affect._err_slow_count == {}
    assert affect._err_last_at == {}
    assert affect._intent_rate == 0.0
    assert affect._wellness == 0.5
    assert affect._interaction_seen is False

    affect.deserialize({"alert_rates": {"fast": True, "slow": 0.2}})
    assert affect._alert_fast == 0.0
    assert affect._alert_slow == 0.2


async def test_affect_state_json_serializable(bus):
    t = [0.0]
    affect = Affect(bus, publish_interval_s=999.0, clock=lambda: t[0])
    await _feed_vision(affect, t, duration=120)
    state = affect.serialize()
    assert json.dumps(state) is not None
