# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for max-pooled learning progress and audition bin restarts (paper A.4)."""

import asyncio
from datetime import datetime, timezone

import pytest

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


def _audition(err):
    return Event(
        source="audition",
        type="audition.perception",
        payload={"alert": False, "prediction_error": err},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


def _hearing(stage, previous):
    return Event(
        source="development",
        type="development.hearing_stage",
        payload={
            "stage": stage,
            "previous_stage": previous,
            "low_hz": 100.0,
            "high_hz": 8000.0,
            "awake_seconds": 0.0,
        },
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


async def test_pooled_learning_progress_is_largest_defined(bus):
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
        await affect._handle_peer_event("audition.out", _audition(1.0))
        await affect._tick()

    per_source, lp = affect._learning_progress_terms(t[0])
    assert per_source["vision"] == pytest.approx(0.5, abs=0.01)
    assert per_source["audition"] == pytest.approx(0.0)
    assert lp == pytest.approx(per_source["vision"])
    floor = affect._learning_progress_floor
    assert affect._progress()[0] == pytest.approx(
        max(0.0, lp - floor) / (1.0 - floor)
    )

    t2 = [0.0]
    affect2 = Affect(
        bus,
        clock=lambda: t2[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )
    await affect2._handle_peer_event("vision.out", _vision(1.0))
    await affect2._handle_peer_event("audition.out", _audition(1.0))
    for _ in range(240):
        t2[0] += 1.0
        err = 0.5 if t2[0] > 120.0 else 1.0
        await affect2._handle_peer_event("vision.out", _vision(1.0))
        await affect2._handle_peer_event("audition.out", _audition(err))
        await affect2._tick()

    per_source2, lp2 = affect2._learning_progress_terms(t2[0])
    assert lp2 == pytest.approx(per_source2["audition"])

    t3 = [0.0]
    affect3 = Affect(
        bus,
        clock=lambda: t3[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )
    await affect3._handle_peer_event("vision.out", _vision(1.0))
    for _ in range(240):
        t3[0] += 1.0
        err = 0.5 if t3[0] > 120.0 else 1.0
        await affect3._handle_peer_event("vision.out", _vision(err))
        await affect3._tick()

    _, lp3 = affect3._learning_progress_terms(t3[0])
    assert lp3 == pytest.approx(affect3._learning_progress_terms(t3[0])[0]["vision"])

    affect4 = Affect(
        bus,
        clock=lambda: 0.0,
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )
    _, lp4 = affect4._learning_progress_terms(0.0)
    assert lp4 == 0.0
    assert affect4._progress()[0] == 0.0


async def test_error_dynamics_stays_a_mean(bus):
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
        vision_err = 0.5 if t[0] > 120.0 else 1.0
        await affect._handle_peer_event("vision.out", _vision(vision_err))
        await affect._handle_peer_event("audition.out", _audition(1.0))
        await affect._tick()

    g_v = affect._source_error_terms("vision")[2]
    g_a = affect._source_error_terms("audition")[2]
    assert g_v is not None
    assert g_a is not None
    assert abs(g_a - g_v) > 0.05
    assert affect._progress()[1] == pytest.approx((g_v + g_a) / 2.0)
    assert affect._progress()[1] != pytest.approx(max(g_v, g_a))


async def test_band_step_restarts_audition_only(bus):
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

    assert "audition" in affect._lp_windows
    vision_before = affect._learning_progress_terms(t[0])[0]["vision"]

    await affect._handle_peer_event("development.out", _hearing(0, None))
    assert affect._hearing_stage == 0
    assert "audition" in affect._lp_windows

    await affect._handle_peer_event("development.out", _hearing(1, 0))
    assert affect._hearing_stage == 1
    assert "audition" not in affect._lp_windows
    per_source, lp = affect._learning_progress_terms(t[0])
    assert per_source.get("audition") is None
    assert per_source["vision"] == pytest.approx(vision_before)

    for _ in range(240):
        t[0] += 1.0
        await affect._handle_peer_event("audition.out", _audition(0.5))
        await affect._tick()

    per_source, lp = affect._learning_progress_terms(t[0])
    assert per_source.get("audition") is not None
    assert per_source["audition"] == pytest.approx(0.0)


@pytest.mark.parametrize(
    "event",
    [
        lambda: _hearing(0, None),
        lambda: _hearing(-1, None),
        lambda: _hearing(5, None),
        lambda: Event(
            source="development",
            type="development.hearing_stage",
            payload={"stage": True, "previous_stage": None},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        ),
        lambda: Event(
            source="development",
            type="development.hearing_stage",
            payload={"stage": "2", "previous_stage": None},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        ),
        lambda: Event(
            source="development",
            type="development.hearing_stage",
            payload={"stage": 2.0, "previous_stage": None},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        ),
        lambda: Event(
            source="development",
            type="development.hearing_stage",
            payload={"previous_stage": None},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        ),
        lambda: Event(
            source="development",
            type="development.stimulus_source",
            payload={"source": "audition"},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        ),
    ],
)
async def test_invalid_or_stale_hearing_stage_ignored(bus, event):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )

    await affect._handle_peer_event("audition.out", _audition(1.0))
    for _ in range(60):
        t[0] += 1.0
        await affect._handle_peer_event("audition.out", _audition(1.0))
        await affect._tick()

    await affect._handle_peer_event("development.out", _hearing(2, None))
    assert affect._hearing_stage == 2
    assert "audition" in affect._lp_windows

    await affect._handle_peer_event("development.out", event())
    assert affect._hearing_stage == 2
    assert "audition" in affect._lp_windows


async def test_serialize_deserialize_hearing_stage(bus):
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

    await affect._handle_peer_event("development.out", _hearing(1, None))
    snapshot = affect.serialize()
    assert snapshot["hearing_stage"] == 1

    fresh = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )
    fresh.deserialize(snapshot)
    assert fresh._hearing_stage == 1
    assert "audition" in fresh._lp_windows

    await fresh._handle_peer_event("development.out", _hearing(2, None))
    assert fresh._hearing_stage == 2
    assert "audition" not in fresh._lp_windows

    stage2 = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )
    stage2.deserialize(snapshot)
    stage2._hearing_stage = 2
    stage2_snap = stage2.serialize()
    same = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
        learning_progress_bin_s=60.0,
    )
    same.deserialize(stage2_snap)
    assert same._hearing_stage == 2
    assert "audition" in same._lp_windows
    await same._handle_peer_event("development.out", _hearing(2, None))
    assert same._hearing_stage == 2
    assert "audition" in same._lp_windows

    for bad in ("2", True, 7, -1, 2.0):
        malformed = dict(snapshot)
        malformed["hearing_stage"] = bad
        m = Affect(
            bus,
            clock=lambda: t[0],
            publish_interval_s=1.0,
            learning_progress_span_s=240.0,
            learning_progress_bin_s=60.0,
        )
        m.deserialize(malformed)
        assert m._hearing_stage is None


async def test_hearing_stage_end_to_end_via_bus(bus):
    affect = Affect(bus)
    await affect.initialize()
    try:
        await bus.publish(_hearing(3, None))
        deadline = asyncio.get_event_loop().time() + 3.0
        while asyncio.get_event_loop().time() < deadline:
            if affect._hearing_stage == 3:
                break
            await asyncio.sleep(0.05)
        assert affect._hearing_stage == 3
    finally:
        await affect.shutdown()


async def test_hearing_stage_literals_match_publisher(bus):
    import kaine.bus.streams
    import kaine.cycle.hearing_stage_watch

    affect = Affect(bus)
    assert affect._hearing_stage_type == kaine.cycle.hearing_stage_watch.HEARING_STAGE_TYPE
    assert affect._development_stream == kaine.bus.streams.DEVELOPMENT_STREAM


async def test_audition_learning_progress_gated_on_stage_and_window(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1.0,
        learning_progress_span_s=240.0,
    )
    # No stage seen yet: no reading, even for stage 0.
    assert affect.audition_learning_progress(0) is None

    await affect._handle_peer_event("development.out", _hearing(0, None))
    # Stage seen but no audition window yet.
    assert affect.audition_learning_progress(0) is None

    await affect._handle_peer_event("audition.out", _audition(1.0))
    for _ in range(240):
        t[0] += 1.0
        err = 0.5 if t[0] > 120.0 else 1.0
        await affect._handle_peer_event("audition.out", _audition(err))
        await affect._tick()
    value = affect.audition_learning_progress(0)
    assert value is not None and value > 0.0

    # The watch moves to stage 1 first; the stale stage-0 reading is not served
    # for stage 1 until the affect module has seen the event and restarted its bins.
    assert affect.audition_learning_progress(1) is None
    await affect._handle_peer_event("development.out", _hearing(1, 0))
    assert affect.audition_learning_progress(1) is None
    assert affect.audition_learning_progress(0) is None
