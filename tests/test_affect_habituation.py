# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import math
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.affect import Affect

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


async def test_habituation_values(bus):
    t = [0.0]
    affect = _affect(bus, t)

    assert affect._habituation() == pytest.approx(1.0)

    affect._alert_fast = 0.2
    affect._alert_slow = 0.05
    assert affect._habituation() == pytest.approx(1.0)

    affect._alert_fast = 0.1
    affect._alert_slow = 0.2
    assert affect._habituation() == pytest.approx(math.exp(-20.0), rel=1e-6)

    affect._alert_fast = 0.0
    affect._alert_slow = 0.01
    assert affect._habituation() == pytest.approx(math.exp(-1.0))

    affect._alert_fast = 0.075
    affect._alert_slow = 0.05
    assert affect._habituation() == pytest.approx(0.5)

    affect._alert_fast = 0.1
    affect._alert_slow = 0.05
    assert affect._alert_excess() == pytest.approx(0.5)
    assert affect._habituation() == pytest.approx(1.0)


async def test_base_rate_habituation(bus):
    t = [0.0]
    affect = _affect(bus, t)
    late_hs = []
    late_arousals = []
    for second in range(1, 601):
        t[0] = float(second)
        if second % 5 == 0:
            h = affect._habituation()
            if second > 300:
                late_hs.append(h)
            await affect._handle_peer_event("vision.out", _alert())
        await affect._tick()
        if second >= 450:
            # Base-rate alerts add nothing on top of the relaxation target, which
            # the drives raise (tonic-drive-arousal, paper A.4 item 3).
            late_arousals.append(affect.state.arousal - affect._arousal_target())

    assert all(h < 1e-6 for h in late_hs)
    assert all(abs(a) < 0.01 for a in late_arousals)


async def test_burst_arousal(bus):
    affect, t = await _build_habituated(bus)
    before = affect.state.arousal
    for i in range(5):
        if i > 0:
            t[0] += 0.5
        await affect._handle_peer_event(
            "vision.out",
            _event(
                "vision",
                "vision.report",
                {"alert": True, "normalised_error": 0.99, "normalised_change": 4.0},
            ),
        )
    assert affect.state.arousal - before >= 0.3


async def test_first_alert_arouses(bus):
    t = [0.0]
    affect = _affect(bus, t)
    before = affect.state.arousal
    await affect._handle_peer_event("vision.out", _alert(change=3.0))
    assert affect.state.arousal == pytest.approx(before + 0.15 * 2.0)

    t[0] += 0.5
    before_second = affect.state.arousal
    await affect._handle_peer_event("vision.out", _alert(change=3.0))
    assert affect.state.arousal == pytest.approx(before_second + 0.15 * 2.0)
    assert affect.state.arousal == pytest.approx(affect.baseline.arousal + 0.3 * 2)


async def test_isolated_alert_after_long_quiet(bus):
    affect, t = await _build_habituated(bus)

    for second in range(1, 601):
        t[0] = 600.0 + float(second)
        await affect._tick()
        if second == 4:
            # One base-rate interval after the last alert: fully habituated.
            assert affect._habituation() < 1e-6

    h_before = affect._habituation()
    assert h_before > 0.9

    before = affect.state.arousal
    await affect._handle_peer_event("vision.out", _alert(change=3.0))
    assert affect.state.arousal - before > 0.25


async def test_first_alert_after_sleep_reset(bus):
    affect, t = await _build_habituated(bus)
    await affect.affective_reset()
    before = affect.state.arousal
    await affect._handle_peer_event("vision.out", _alert(change=3.0))
    assert affect.state.arousal == pytest.approx(before + 0.3)


async def test_alert_uses_habituation_before_own_increment(bus):
    t = [0.0]
    affect = _affect(bus, t)
    affect._alert_fast = 0.0
    affect._alert_slow = 0.2
    before = affect.state.arousal
    await affect._handle_peer_event(
        "vision.out",
        _event(
            "vision",
            "vision.report",
            {"alert": True, "normalised_error": 0.99, "normalised_change": 10.0},
        ),
    )
    assert abs(affect.state.arousal - before) < 1e-6

    affect = _affect(bus, t)
    before = affect.state.arousal
    await affect._handle_peer_event(
        "vision.out",
        _event(
            "vision",
            "vision.report",
            {"alert": True, "normalised_error": 0.99, "normalised_change": 10.0},
        ),
    )
    assert affect.state.arousal == pytest.approx(before + 0.15 * 4.0)


async def test_novelty_change_burst_and_habituated(bus):
    t = [0.0]
    affect = _affect(bus, t)
    affect._alert_fast = 0.2
    affect._alert_slow = 0.05

    ev = _event(
        "vision",
        "vision.report",
        {"normalised_error": 0.99, "normalised_change": 3.0, "alert": True},
    )
    snapshot = WorkspaceSnapshot(tick_index=1, selected_events=[("vision.out:1-0", ev)])
    scores = affect._score_snapshot(snapshot)
    assert scores.novelty == pytest.approx(1.0)

    affect._alert_fast = 0.1
    affect._alert_slow = 0.2
    scores = affect._score_snapshot(snapshot)
    assert scores.novelty == pytest.approx(0.0, abs=1e-6)


async def test_novelty_not_discounted_for_other_processors(bus):
    t = [0.0]
    affect = _affect(bus, t)
    affect._alert_fast = 0.1
    affect._alert_slow = 0.2

    ev = _event("sequence", "sequence.report", {"normalised_error": 3.0})
    snapshot = WorkspaceSnapshot(tick_index=1, selected_events=[("sequence.out:1-0", ev)])
    scores = affect._score_snapshot(snapshot)
    assert scores.novelty == pytest.approx(1.0)


async def test_novelty_larger_ratio_wins_and_invalid_ignored(bus):
    t = [0.0]
    affect = _affect(bus, t)
    affect._alert_fast = 0.2
    affect._alert_slow = 0.05

    ev = _event(
        "vision",
        "vision.report",
        {"normalised_error": 3.0, "normalised_change": "x"},
    )
    snapshot = WorkspaceSnapshot(tick_index=1, selected_events=[("vision.out:1-0", ev)])
    scores = affect._score_snapshot(snapshot)
    assert scores.novelty == pytest.approx(1.0)

    ev = _event(
        "vision",
        "vision.report",
        {"normalised_error": 0.0, "normalised_change": float("inf")},
    )
    snapshot = WorkspaceSnapshot(tick_index=1, selected_events=[("vision.out:1-0", ev)])
    scores = affect._score_snapshot(snapshot)
    assert scores.novelty == pytest.approx(0.0)

    ev = _event("vision", "vision.report", {"normalised_error": 3.0 ** 0.5})
    snapshot = WorkspaceSnapshot(tick_index=1, selected_events=[("vision.out:1-0", ev)])
    scores = affect._score_snapshot(snapshot)
    assert scores.novelty == pytest.approx(0.5)


async def test_novelty_audition_discounted(bus):
    t = [0.0]
    affect = _affect(bus, t)
    affect._alert_fast = 0.1
    affect._alert_slow = 0.2

    ev = _event("audition", "audition.perception", {"normalised_change": 3.0})
    snapshot = WorkspaceSnapshot(tick_index=1, selected_events=[("audition.out:1-0", ev)])
    scores = affect._score_snapshot(snapshot)
    assert scores.novelty == pytest.approx(0.0, abs=1e-6)


async def test_novelty_fresh_module_full(bus):
    t = [0.0]
    affect = _affect(bus, t)

    ev = _event(
        "vision",
        "vision.report",
        {"normalised_change": 3.0},
    )
    snapshot = WorkspaceSnapshot(tick_index=1, selected_events=[("vision.out:1-0", ev)])
    scores = affect._score_snapshot(snapshot)
    assert scores.novelty == pytest.approx(1.0)
