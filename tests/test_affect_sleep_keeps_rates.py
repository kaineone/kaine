# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.affect import Affect, CategoricalEmotion

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _event(source, type_, payload):
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.8,
        timestamp=datetime.now(timezone.utc),
    )


def _alert(change=3.0):
    return _event(
        "vision",
        "vision.report",
        {"alert": True, "normalised_error": 0.99, "normalised_change": change},
    )


def _affect(bus, t):
    return Affect(bus, publish_interval_s=999.0, clock=lambda: t[0])


async def _build_habituated(bus):
    t = [0.0]
    affect = _affect(bus, t)
    for second in range(1, 601):
        t[0] = float(second)
        if second % 5 == 0:
            await affect._handle_peer_event("vision.out", _alert())
        await affect._tick()
    return affect, t


async def test_estimates_survive_reset(bus):
    t = [0.0]
    affect = _affect(bus, t)
    await affect.initialize()
    try:
        for i in range(60):
            t[0] = float(i)
            e = 1.0 - 0.5 * (i / 59.0)
            alert = (i + 1) % 5 == 0
            await affect._handle_peer_event(
                "vision.out",
                _event(
                    "vision",
                    "vision.report",
                    {
                        "prediction_error": e,
                        "alert": alert,
                        "normalised_error": 1.0,
                        "normalised_change": 1.0,
                    },
                ),
            )
            await affect._tick()

        affect._intent_rate = 0.4
        affect._intents_since_broadcast = 1

        before_alert_fast = affect._alert_fast
        before_alert_slow = affect._alert_slow
        before_intent_rate = affect._intent_rate
        before_intents_since_broadcast = affect._intents_since_broadcast
        before_err_fast_sum = dict(affect._err_fast_sum)
        before_err_fast_count = dict(affect._err_fast_count)
        before_err_slow_sum = dict(affect._err_slow_sum)
        before_err_slow_count = dict(affect._err_slow_count)
        before_err_last_at = dict(affect._err_last_at)

        await affect.affective_reset()

        assert affect._alert_fast == before_alert_fast
        assert affect._alert_slow == before_alert_slow
        assert affect._intent_rate == before_intent_rate
        assert affect._intents_since_broadcast == before_intents_since_broadcast
        assert dict(affect._err_fast_sum) == before_err_fast_sum
        assert dict(affect._err_fast_count) == before_err_fast_count
        assert dict(affect._err_slow_sum) == before_err_slow_sum
        assert dict(affect._err_slow_count) == before_err_slow_count
        assert dict(affect._err_last_at) == before_err_last_at

        assert affect.state.valence == affect.baseline.valence
        assert affect.state.arousal == affect.baseline.arousal
        assert affect.state.dominance == affect.baseline.dominance
        for d in affect.drives.all():
            assert d.value == 0.0
        assert affect.last_emotion == CategoricalEmotion.NEUTRAL
    finally:
        await affect.shutdown()


async def test_reset_does_not_relieve_boredom(bus):
    affect, t = await _build_habituated(bus)
    affect.drives.boredom.value = 0.9
    for second in range(1, 5):
        t[0] = 600.0 + float(second)
        await affect._tick()
    await affect.affective_reset()
    affect.drives.boredom.value = 0.9
    for second in range(1, 61):
        t[0] = 604.0 + float(second)
        if second % 5 == 0:
            await affect._handle_peer_event("vision.out", _alert())
        await affect._tick()
        assert affect._alert_excess() == pytest.approx(0.0)
        assert affect.drives.boredom.value >= 0.85


async def test_long_quiet_restores_first_presentation_response(bus):
    affect, t = await _build_habituated(bus)
    await affect.affective_reset()
    for second in range(1, 601):
        t[0] = 600.0 + float(second)
        await affect._tick()
    assert affect._habituation() > 0.9
    before = affect.state.arousal
    await affect._handle_peer_event("vision.out", _alert(change=3.0))
    assert affect.state.arousal - before > 0.25


async def test_error_means_reweighted_after_sleep(bus):
    t = [0.0]
    affect = _affect(bus, t)
    await affect.initialize()
    try:
        for i in range(60):
            t[0] = float(i)
            await affect._handle_peer_event(
                "vision.out",
                _event("vision", "vision.report", {"prediction_error": 1.0}),
            )
            await affect._tick()
        await affect.affective_reset()
        for i in range(60):
            t[0] = 60.0 + float(i)
            await affect._tick()
        t[0] = 120.0
        await affect._handle_peer_event(
            "vision.out",
            _event("vision", "vision.report", {"prediction_error": 0.2}),
        )
        fast_mean = affect._err_fast_sum["vision"] / affect._err_fast_count["vision"]
        slow_mean = affect._err_slow_sum["vision"] / affect._err_slow_count["vision"]
        assert 0.2 < fast_mean < 0.25
        assert slow_mean > 0.9
        assert affect._progress()[1] > 0.5
    finally:
        await affect.shutdown()


async def test_intent_rate_decays_through_sleep(bus):
    t = [0.0]
    affect = _affect(bus, t)
    await affect.initialize()
    try:
        affect._intent_rate = 0.5
        await affect.affective_reset()
        await affect._appraise_snapshot(
            WorkspaceSnapshot(tick_index=1, selected_events=[])
        )
        assert affect._intent_rate == pytest.approx(0.5 + 0.05 * (0 - 0.5))
        assert affect._intents_since_broadcast == 0
    finally:
        await affect.shutdown()
