# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the windowed learning-progress estimator integrated into the affect module (paper A.4)."""

import json
import math
import random
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.modules.affect import Affect
from kaine.modules.affect.learning_progress import WindowedProgress

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


def _audition(err):
    return Event(
        source="audition",
        type="audition.perception",
        payload={"alert": False, "prediction_error": err},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


async def _last_state_payload(bus):
    entries = await bus.read("affect.out", last_id="0", count=500)
    states = [ev.payload for _, ev in entries if ev.type == "affect.state"]
    assert states
    return states[-1]


async def test_default_window_settings(bus):
    affect = Affect(bus)
    assert affect._lp_bin_s == 60.0
    assert affect._lp_max_bins == 90


@pytest.mark.parametrize(
    "span, bin_s",
    [
        (150.0, 60.0),
        (60.0, 60.0),
        (180.0, 60.0),
        (0.0, 60.0),
        (240.0, 0.0),
        (math.nan, 60.0),
        (60.0, math.nan),
        (math.inf, 60.0),
        (60.0, math.inf),
    ],
)
async def test_window_parameter_validation(bus, span, bin_s):
    with pytest.raises(ValueError):
        Affect(bus, learning_progress_span_s=span, learning_progress_bin_s=bin_s)


async def test_curiosity_relief_follows_windows(bus):
    tf = [0.0]
    tc = [0.0]
    fall = Affect(
        bus,
        clock=lambda: tf[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )
    const = Affect(
        bus,
        clock=lambda: tc[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )

    await fall._handle_peer_event("vision.out", _vision(1.0))
    await const._handle_peer_event("vision.out", _vision(1.0))

    for _ in range(240):
        tf[0] += 1.0
        tc[0] += 1.0
        err = 0.5 if tf[0] > 120.0 else 1.0
        await fall._handle_peer_event("vision.out", _vision(err))
        await const._handle_peer_event("vision.out", _vision(1.0))
        await fall._tick()
        await const._tick()

    assert fall._progress()[0] > 0.0
    assert const._progress()[0] == pytest.approx(0.0)
    assert fall._drives.curiosity.value < const._drives.curiosity.value


async def test_progress_matches_fresh_windowed_estimator(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )
    win_v = WindowedProgress(60.0, 4)
    win_a = WindowedProgress(60.0, 4)

    await affect._handle_peer_event("vision.out", _vision(1.0))
    await affect._handle_peer_event("audition.out", _audition(1.0))
    win_v.add(0.0, 1.0)
    win_a.add(0.0, 1.0)

    for _ in range(240):
        t[0] += 1.0
        err = 0.5 if t[0] > 120.0 else 1.0
        await affect._handle_peer_event("vision.out", _vision(err))
        await affect._handle_peer_event("audition.out", _audition(err))
        win_v.add(t[0], err)
        win_a.add(t[0], err)
        await affect._tick()

    v = win_v.value(t[0])
    a = win_a.value(t[0])
    lp = (v + a) / 2.0 if v is not None and a is not None else 0.0
    floor = affect._learning_progress_floor
    expected = max(0.0, lp - floor) / (1.0 - floor)
    assert affect._progress()[0] == pytest.approx(expected)


async def test_error_dynamics_matches_hand_computation(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )

    await affect._handle_peer_event("vision.out", _vision(1.0))
    await affect._handle_peer_event("audition.out", _audition(2.0))
    t[0] = 5.0
    await affect._handle_peer_event("vision.out", _vision(0.4))
    await affect._handle_peer_event("audition.out", _audition(2.0))
    await affect._tick()

    tau_f = affect._fast_time_constant_s
    tau_s = affect._slow_time_constant_s
    df = math.exp(-5.0 / tau_f)
    ds = math.exp(-5.0 / tau_s)

    vision_fast = (df * 1.0 + 0.4) / (df + 1.0)
    vision_slow = (ds * 1.0 + 0.4) / (ds + 1.0)
    g_v = max(-1.0, min(1.0, (vision_slow - vision_fast) / vision_slow))

    audition_fast = (df * 2.0 + 2.0) / (df + 1.0)
    audition_slow = (ds * 2.0 + 2.0) / (ds + 1.0)
    g_a = max(-1.0, min(1.0, (audition_slow - audition_fast) / audition_slow))

    g = (g_v + g_a) / 2.0
    assert affect._progress()[1] == pytest.approx(g)


async def test_error_dynamics_unchanged_by_window_settings(bus):
    t1 = [0.0]
    t2 = [0.0]
    a1 = Affect(
        bus,
        clock=lambda: t1[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )
    a2 = Affect(
        bus,
        clock=lambda: t2[0],
        publish_interval_s=1.0,
        learning_progress_span_s=480.0,
        learning_progress_bin_s=120.0,
    )

    random.seed(7)
    seq = [random.random() for _ in range(200)]
    for val in seq:
        t1[0] += 1.0
        t2[0] += 1.0
        await a1._handle_peer_event("vision.out", _vision(val))
        await a2._handle_peer_event("vision.out", _vision(val))
        await a1._handle_peer_event("audition.out", _audition(val))
        await a2._handle_peer_event("audition.out", _audition(val))
        await a1._tick()
        await a2._tick()

    assert a1._progress()[1] == pytest.approx(a2._progress()[1])
    g = a1._progress()[1]
    assert a1._valence_target(g) == pytest.approx(a2._valence_target(g))


async def test_no_positive_error_undefined_progress(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )

    for _ in range(10):
        t[0] += 1.0
        await affect._handle_peer_event("vision.out", _vision(0.0))
        await affect._tick()

    per_source, lp = affect._learning_progress_terms(t[0])
    assert "vision" in per_source
    assert per_source["vision"] is None
    assert lp == 0.0
    assert affect._progress()[0] == 0.0


async def test_payload_carries_windowed_learning_progress(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )
    win = WindowedProgress(60.0, 4)

    await affect._handle_peer_event("vision.out", _vision(1.0))
    win.add(0.0, 1.0)

    for _ in range(240):
        t[0] += 1.0
        err = 0.5 if t[0] > 120.0 else 1.0
        await affect._handle_peer_event("vision.out", _vision(err))
        win.add(t[0], err)
        await affect._tick()

    await affect._maybe_publish_state()
    p = await _last_state_payload(bus)

    expected_value = win.value(t[0])
    expected_lp_plus = max(0.0, expected_value - affect._learning_progress_floor) / (
        1.0 - affect._learning_progress_floor
    )

    assert p["vision_learning_progress"] == pytest.approx(expected_value)
    assert p["audition_learning_progress"] is None
    assert p["signed_learning_progress"] == pytest.approx(expected_value)
    assert p["learning_progress"] == pytest.approx(expected_lp_plus)
    assert affect._progress()[0] == pytest.approx(expected_lp_plus)


async def test_serialize_deserialize_round_trip(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )

    await affect._handle_peer_event("vision.out", _vision(1.0))
    await affect._handle_peer_event("audition.out", _audition(1.0))
    for _ in range(240):
        t[0] += 1.0
        err = 0.5 if t[0] > 120.0 else 1.0
        await affect._handle_peer_event("vision.out", _vision(err))
        await affect._handle_peer_event("audition.out", _audition(err))
        await affect._tick()

    progress_before = affect._progress()
    terms_before = affect._learning_progress_terms(t[0])
    snapshot = affect.serialize()
    assert "learning_progress_bins" in snapshot
    assert frozenset(snapshot["learning_progress_bins"].keys()) == {"vision", "audition"}
    json.dumps(snapshot["learning_progress_bins"])

    fresh = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )
    fresh.deserialize(snapshot)

    assert fresh._progress()[0] == pytest.approx(progress_before[0])
    assert fresh._progress()[1] == pytest.approx(progress_before[1])
    terms_after = fresh._learning_progress_terms(t[0])
    assert terms_after[0]["vision"] == pytest.approx(terms_before[0]["vision"])
    assert terms_after[0]["audition"] == pytest.approx(terms_before[0]["audition"])
    assert terms_after[1] == pytest.approx(terms_before[1])


async def test_restore_keeps_current_bin_time(bus):
    t = [0.0]
    m1 = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )

    for _ in range(150):
        t[0] += 1.0
        err = 0.5 if t[0] > 90.0 else 1.0
        await m1._handle_peer_event("vision.out", _vision(err))
        await m1._tick()

    snap = m1.serialize()
    m2 = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )
    m2.deserialize(snap)

    for _ in range(90):
        t[0] += 1.0
        err = 0.5
        await m1._handle_peer_event("vision.out", _vision(err))
        await m2._handle_peer_event("vision.out", _vision(err))
        await m1._tick()
        await m2._tick()

    assert m1._progress()[0] == pytest.approx(m2._progress()[0])
    v1, lp1 = m1._learning_progress_terms(t[0])
    v2, lp2 = m2._learning_progress_terms(t[0])
    assert v1["vision"] == pytest.approx(v2["vision"])
    assert lp1 == pytest.approx(lp2)


async def test_old_snapshot_without_bins_restarts_bins(bus):
    t = [0.0]
    m1 = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )

    await m1._handle_peer_event("vision.out", _vision(1.0))
    t[0] = 5.0
    await m1._handle_peer_event("vision.out", _vision(0.5))
    snap = m1.serialize()
    snap.pop("learning_progress_bins", None)

    m2 = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )
    m2.deserialize(snap)

    assert "vision" in m2._err_slow_count
    assert m2._lp_windows == {}


async def test_mismatched_bin_width_restarts_bins(bus):
    t = [0.0]
    m1 = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )

    await m1._handle_peer_event("vision.out", _vision(1.0))
    for _ in range(120):
        t[0] += 1.0
        await m1._handle_peer_event("vision.out", _vision(0.5))
        await m1._tick()

    snap = m1.serialize()
    m2 = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=30.0,
    )
    m2.deserialize(snap)

    assert m2._lp_windows == {}


async def test_invalid_bin_entry_skipped(bus):
    t = [0.0]
    m1 = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )

    await m1._handle_peer_event("vision.out", _vision(1.0))
    await m1._handle_peer_event("audition.out", _audition(1.0))
    t[0] = 5.0
    await m1._handle_peer_event("vision.out", _vision(0.5))
    await m1._handle_peer_event("audition.out", _audition(0.5))
    snap = m1.serialize()
    snap["learning_progress_bins"]["audition"]["current"][0] = -1.0

    m2 = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )
    m2.deserialize(snap)

    assert "vision" in m2._lp_windows
    assert "audition" not in m2._lp_windows


async def test_affective_reset_keeps_windows(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )

    await affect._handle_peer_event("vision.out", _vision(1.0))
    for _ in range(180):
        t[0] += 1.0
        err = 0.5 if t[0] > 120.0 else 1.0
        await affect._handle_peer_event("vision.out", _vision(err))
        await affect._tick()

    windows_before = dict(affect._lp_windows)
    progress_before = affect._progress()[0]
    assert windows_before
    await affect.affective_reset()
    assert affect._lp_windows == windows_before
    assert affect._progress()[0] == pytest.approx(progress_before)
