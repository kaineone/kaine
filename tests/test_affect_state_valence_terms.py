# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The affect state event carries the terms behind the valence target (paper A.4): per-source error means and progress, pooled progress, wellness means and change, pleasantness and target."""

import math
import random
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


async def _last_state_payload(bus):
    entries = await bus.read("affect.out", last_id="0", count=500)
    states = [ev.payload for _, ev in entries if ev.type == "affect.state"]
    assert states
    return states[-1]


EXPECTED_KEYS = frozenset({
    "state",
    "drives",
    "emotion",
    "vision_error_fast",
    "vision_error_slow",
    "vision_progress",
    "vision_learning_progress",
    "audition_error_fast",
    "audition_error_slow",
    "audition_progress",
    "audition_learning_progress",
    "signed_progress",
    "signed_learning_progress",
    "learning_progress",
    "wellness",
    "wellness_fast",
    "wellness_slow",
    "wellness_change",
    "pleasantness",
    "valence_target",
})


async def test_values_match_trackers(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)

    await affect._handle_peer_event("vision.out", _vision(1.0))
    await affect._handle_peer_event("audition.out", _audition(2.0))
    await affect._handle_peer_event("interoception.out", _wellness(0.9))

    t[0] = 5.0
    await affect._handle_peer_event("vision.out", _vision(0.4))
    await affect._handle_peer_event("audition.out", _audition(2.0))
    await affect._handle_peer_event("interoception.out", _wellness(0.6))
    await affect._tick()
    await affect._maybe_publish_state()

    p = await _last_state_payload(bus)

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
    lp = 0.0

    well_fast = (df * 0.9 + 0.6) / (df + 1.0)
    well_slow = (ds * 0.9 + 0.6) / (ds + 1.0)
    change = well_fast - well_slow

    pleasantness = math.tanh(affect._valence_progress_gain * g)
    target = max(-1.0, min(1.0, pleasantness + change))

    assert p["vision_error_fast"] == pytest.approx(vision_fast)
    assert p["vision_error_slow"] == pytest.approx(vision_slow)
    assert p["vision_progress"] == pytest.approx(g_v)
    assert p["vision_learning_progress"] is None
    assert p["audition_error_fast"] == pytest.approx(audition_fast)
    assert p["audition_error_slow"] == pytest.approx(audition_slow)
    assert p["audition_progress"] == pytest.approx(g_a)
    assert p["audition_learning_progress"] is None
    assert p["signed_progress"] == pytest.approx(g)
    assert p["signed_learning_progress"] == pytest.approx(0.0)
    assert p["learning_progress"] == pytest.approx(lp)
    assert p["wellness"] == pytest.approx(0.6)
    assert p["wellness_fast"] == pytest.approx(well_fast)
    assert p["wellness_slow"] == pytest.approx(well_slow)
    assert p["wellness_change"] == pytest.approx(change)
    assert p["pleasantness"] == pytest.approx(pleasantness)
    assert p["valence_target"] == pytest.approx(target)

    assert (p["learning_progress"], p["signed_progress"]) == pytest.approx(affect._progress())
    assert p["valence_target"] == pytest.approx(affect._valence_target(affect._progress()[1]))


async def test_absent_source_is_null(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)

    await affect._handle_peer_event("vision.out", _vision(1.0))
    t[0] = 5.0
    await affect._handle_peer_event("vision.out", _vision(0.5))
    await affect._tick()
    await affect._maybe_publish_state()

    p = await _last_state_payload(bus)
    for k in ("audition_error_fast", "audition_error_slow", "audition_progress", "audition_learning_progress"):
        assert p[k] is None
    for k in ("vision_error_fast", "vision_error_slow", "vision_progress"):
        assert isinstance(p[k], float)
    assert frozenset(p.keys()) == EXPECTED_KEYS


async def test_no_data(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    t[0] = 1.0
    await affect._tick()
    await affect._maybe_publish_state()

    p = await _last_state_payload(bus)
    for source in ("vision", "audition"):
        assert p[f"{source}_error_fast"] is None
        assert p[f"{source}_error_slow"] is None
        assert p[f"{source}_progress"] is None
        assert p[f"{source}_learning_progress"] is None
    assert p["signed_progress"] == 0.0
    assert p["signed_learning_progress"] == 0.0
    assert p["learning_progress"] == 0.0
    assert p["wellness"] == 0.5
    assert p["wellness_fast"] is None
    assert p["wellness_slow"] is None
    assert p["wellness_change"] == 0.0
    assert p["pleasantness"] == pytest.approx(affect._pleasantness(0.0))
    assert p["valence_target"] == pytest.approx(affect._valence_target(0.0))
    assert frozenset(p.keys()) == EXPECTED_KEYS


async def test_unlisted_source_adds_no_keys(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)

    def _camera(err):
        return Event(
            source="camera2",
            type="vision.report",
            payload={"alert": False, "prediction_error": err},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )

    await affect._handle_peer_event("vision.out", _camera(1.0))
    t[0] = 5.0
    await affect._handle_peer_event("vision.out", _camera(0.5))
    await affect._tick()
    await affect._maybe_publish_state()

    p = await _last_state_payload(bus)
    assert frozenset(p.keys()) == EXPECTED_KEYS
    assert p["signed_progress"] == pytest.approx(affect._progress()[1])
    assert p["signed_progress"] != 0.0


async def test_degenerate_slow_mean_gives_null_progress(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)

    await affect._handle_peer_event("vision.out", _vision(1.0))
    affect._err_slow_sum["vision"] = 0.0
    affect._err_fast_sum["vision"] = 0.0

    t[0] = 1.0
    await affect._tick()
    await affect._maybe_publish_state()

    p = await _last_state_payload(bus)
    assert p["vision_error_slow"] == 0.0
    assert p["vision_progress"] is None
    assert p["vision_learning_progress"] is None
    assert p["signed_progress"] == 0.0
    assert p["signed_learning_progress"] == 0.0
    assert frozenset(p.keys()) == EXPECTED_KEYS


async def test_all_values_finite_or_none(bus):
    random.seed(12345)
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)

    for _ in range(200):
        t[0] += 1.0
        await affect._handle_peer_event("vision.out", _vision(random.random()))
        await affect._handle_peer_event("audition.out", _audition(random.random()))
        await affect._handle_peer_event("interoception.out", _wellness(random.random()))
        await affect._tick()

    await affect._maybe_publish_state()
    p = await _last_state_payload(bus)

    term_keys = [k for k in EXPECTED_KEYS if k not in ("state", "drives", "emotion")]
    for k in term_keys:
        v = p[k]
        assert v is None or (isinstance(v, float) and not isinstance(v, bool) and math.isfinite(v))


async def test_wellness_level_rule_target(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0, valence_rule="wellness_level")

    await affect._handle_peer_event("interoception.out", _wellness(0.8))
    t[0] = 1.0
    await affect._tick()
    await affect._maybe_publish_state()

    p = await _last_state_payload(bus)
    assert p["wellness_fast"] is None
    assert p["wellness_slow"] is None
    assert p["wellness_change"] == 0.0

    g = affect._progress()[1]
    target = max(-1.0, min(1.0, math.tanh(affect._valence_progress_gain * g) + (0.8 - 0.5)))
    assert p["valence_target"] == pytest.approx(target)


async def test_reset_payload_carries_terms(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)

    await affect._handle_peer_event("vision.out", _vision(1.0))
    await affect._tick()
    await affect.affective_reset()

    entries = await bus.read("affect.out", last_id="0", count=500)
    reset_payloads = [ev.payload for _, ev in entries if ev.type == "affect.state" and ev.payload.get("reset")]
    assert reset_payloads
    p = reset_payloads[-1]

    term_keys = [k for k in EXPECTED_KEYS if k not in ("state", "drives", "emotion")]
    for k in term_keys:
        assert k in p


async def test_dynamics_unchanged(bus):
    t1 = [0.0]
    a1 = Affect(bus, clock=lambda: t1[0], publish_interval_s=1.0)
    t2 = [0.0]
    a2 = Affect(bus, clock=lambda: t2[0], publish_interval_s=1.0)

    random.seed(42)
    seq = [random.random() for _ in range(120)]
    for val in seq:
        t1[0] += 1.0
        t2[0] += 1.0
        await a1._handle_peer_event("vision.out", _vision(val))
        await a2._handle_peer_event("vision.out", _vision(val))
        await a1._handle_peer_event("audition.out", _audition(val))
        await a2._handle_peer_event("audition.out", _audition(val))
        await a1._handle_peer_event("interoception.out", _wellness(val))
        await a2._handle_peer_event("interoception.out", _wellness(val))
        a1._valence_terms()
        await a1._tick()
        await a2._tick()

    assert a1._progress() == a2._progress()
    assert a1.state.valence == a2.state.valence
    assert a1.state.arousal == a2.state.arousal
