# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Research-affect tests for Thymos.

Validates the drive/relief dynamics and the valence/appraisal rules described
in the 2026-10-08 OpenSpec proposal.
"""
from __future__ import annotations

import math
import random
import tomllib
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.thymos import CategoricalEmotion, Thymos
from kaine.modules.thymos.appraisal import classify
from kaine.modules.thymos.drives import Drive, DriveSet


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _event(source="soma", type_="t", salience=0.5, eid="e0", **payload) -> tuple:
    return eid, Event(
        source=source,
        type=type_,
        payload=payload or {"k": "v"},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(events=None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=events or [],
        inhibited=False,
    )


def test_drive_tick_exact_solution():
    d = Drive(name="x", build_rate=0.5, decay_rate=0.2, value=0.2)
    dt = 2.0
    signal = 0.8
    u = 0.8
    r = 0.5 * u + 0.2
    eq = 0.5 * u / r
    expected = eq + (0.2 - eq) * math.exp(-r * dt)
    d.tick(dt, signal)
    assert d.value == pytest.approx(expected)

    # Sustained full signal never exceeds the equilibrium build/(build+decay).
    d2 = Drive(name="y", build_rate=0.5, decay_rate=0.2, value=0.0)
    for _ in range(3600):
        d2.tick(1.0, 1.0)
    eq_max = 0.5 / (0.5 + 0.2)
    assert d2.value <= eq_max + 1e-9
    assert d2.value == pytest.approx(eq_max, abs=1e-3)


def test_drive_relieve_and_from_config_and_defaults():
    d = Drive(name="x", value=0.8, relief_gain=0.5)
    d.relieve(1.0)
    assert d.value == pytest.approx(0.4)

    with pytest.raises(ValueError):
        DriveSet.from_config({"curiosity": {"unknown": 1.0}})

    ds = DriveSet()
    assert ds.curiosity.relief_gain == 0.5
    assert ds.boredom.relief_gain == 0.3
    assert ds.social_drive.relief_gain == 0.8
    assert ds.restlessness.relief_gain == 0.5
    assert ds.curiosity.build_rate == 0.05
    assert ds.boredom.build_rate == 0.04
    assert ds.social_drive.build_rate == 0.01
    assert ds.restlessness.build_rate == 0.03


@pytest.mark.asyncio
async def test_curiosity_relief_from_falling_errors(bus: AsyncBus):
    fake_now = [0.0]
    thymos = Thymos(
        bus,
        clock=lambda: fake_now[0],
        drift_rate_per_s=0.0,
        publish_interval_s=999.0,
    )
    await thymos.initialize()
    try:
        # 60 s of steady error gives the averages a history (a fresh tracker
        # reports no progress), then the error falls from 3.0 to 1.0 over 20 s.
        for i in range(800):
            fake_now[0] = i * 0.1
            if i == 600:
                thymos.drives.curiosity.value = 0.6
            r = 3.0 if i < 600 else 3.0 - (2.0 * (i - 600) / 199)
            await thymos._handle_peer_event(
                "topos.out",
                Event(
                    source="topos",
                    type="topos.report",
                    payload={"prediction_error": r},
                    salience=0.5,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
            if i >= 600 and (i + 1) % 3 == 0:
                await thymos._tick()
        fake_now[0] = 80.0
        await thymos._tick()
        assert thymos.drives.curiosity.value < 0.6
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_boredom_relief_on_perceptual_alert(bus: AsyncBus):
    fake_now = [0.0]
    thymos = Thymos(
        bus,
        clock=lambda: fake_now[0],
        drift_rate_per_s=0.0,
        publish_interval_s=999.0,
    )
    await thymos.initialize()
    try:
        thymos.drives.boredom.value = 0.8
        fake_now[0] = 0.1
        await thymos._handle_peer_event(
            "audition.out",
            Event(
                source="audition",
                type="audition.perception",
                payload={"alert": True, "normalised_error": 5.0},
                salience=0.8,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        await thymos._tick()
        assert thymos.drives.boredom.value < 0.8
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_social_drive_relief_on_new_interaction(bus: AsyncBus):
    fake_now = [0.0]
    thymos = Thymos(bus, clock=lambda: fake_now[0], publish_interval_s=999.0)
    await thymos.initialize()
    try:
        thymos.drives.social_drive.value = 0.8
        await thymos._handle_peer_event(
            "chronos.out",
            Event(
                source="chronos",
                type="chronos.report",
                payload={"time_since_last_interaction_s": 10},
                salience=0.1,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        assert thymos._interaction_seen
        after_first = thymos.drives.social_drive.value
        # Longer alone: no relief.
        await thymos._handle_peer_event(
            "chronos.out",
            Event(
                source="chronos",
                type="chronos.report",
                payload={"time_since_last_interaction_s": 20},
                salience=0.1,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        after_second = thymos.drives.social_drive.value
        # A new interaction resets the idle clock and relieves the drive.
        await thymos._handle_peer_event(
            "chronos.out",
            Event(
                source="chronos",
                type="chronos.report",
                payload={"time_since_last_interaction_s": 2},
                salience=0.1,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        assert thymos.drives.social_drive.value < after_second
        assert thymos.drives.social_drive.value < after_first
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_restlessness_relief_on_intent(bus: AsyncBus):
    fake_now = [0.0]
    thymos = Thymos(bus, clock=lambda: fake_now[0], publish_interval_s=999.0)
    await thymos.initialize()
    try:
        thymos.drives.restlessness.value = 0.8
        await thymos._handle_peer_event(
            "volition.out",
            Event(
                source="volition",
                type="intent.think",
                payload={},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        assert thymos.drives.restlessness.value < 0.8
        assert thymos._intents_since_broadcast == 1
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_valence_follows_learning_progress(bus: AsyncBus):
    fake_now = [0.0]
    thymos = Thymos(
        bus,
        clock=lambda: fake_now[0],
        drift_rate_per_s=0.0,
        publish_interval_s=999.0,
    )
    await thymos.initialize()
    try:
        step = 0.1

        # Falling errors -> positive learning progress -> positive valence.
        for i in range(1201):
            t = i * step
            fake_now[0] = t
            r = 3.0 - 2.0 * t / 120.0
            await thymos._handle_peer_event(
                "topos.out",
                Event(
                    source="topos",
                    type="topos.report",
                    payload={"prediction_error": r},
                    salience=0.5,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
            if i % 3 == 0:
                await thymos._tick()
        fake_now[0] = 120.0
        await thymos._tick()
        assert thymos.state.valence > 0.0, thymos.state.valence

        # Rising errors -> negative learning progress -> negative valence.
        for i in range(1201, 2401):
            t = i * step
            fake_now[0] = t
            await thymos._handle_peer_event(
                "topos.out",
                Event(
                    source="topos",
                    type="topos.report",
                    payload={"prediction_error": 5.0},
                    salience=0.5,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
            if i % 3 == 0:
                await thymos._tick()
        fake_now[0] = 240.0
        await thymos._tick()
        assert thymos.state.valence < 0.0, thymos.state.valence
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_score_snapshot_novelty_and_surprise(bus: AsyncBus):
    thymos = Thymos(bus)
    snap = _snapshot(
        [
            _event(
                source="topos",
                type_="topos.report",
                salience=0.5,
                eid="e0",
                normalised_error=3.0,
            )
        ]
    )
    scores = thymos._score_snapshot(snap)
    assert scores.novelty == pytest.approx(1.0)
    assert scores.intrinsic_pleasantness == pytest.approx(0.0)
    assert scores.goal_significance == pytest.approx(0.0)
    emotion = classify(scores)
    assert emotion == CategoricalEmotion.SURPRISE


@pytest.mark.asyncio
async def test_on_workspace_does_not_nudge_arousal(bus: AsyncBus):
    fake_now = [0.0]
    thymos = Thymos(
        bus,
        clock=lambda: fake_now[0],
        drift_rate_per_s=0.0,
        publish_interval_s=999.0,
    )
    await thymos.initialize()
    try:
        base = thymos.state.arousal
        events = [
            _event(salience=0.1, eid="e0"),
            _event(salience=0.9, eid="e1"),
            _event(salience=0.2, eid="e2"),
            _event(salience=0.8, eid="e3"),
        ]
        fake_now[0] = 1.0
        await thymos.on_workspace(_snapshot(events))
        assert thymos.state.arousal == pytest.approx(base)
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_learning_progress_averaged_over_sources(bus):
    from types import SimpleNamespace

    def _report(source: str, type_: str, prediction_error: float):
        return SimpleNamespace(
            source=source,
            type=type_,
            payload={"prediction_error": prediction_error},
        )

    fake_now = [0.0]
    thymos = Thymos(
        bus,
        clock=lambda: fake_now[0],
        drift_rate_per_s=0.0,
        publish_interval_s=999.0,
    )
    await thymos.initialize()
    try:
        for i in range(40):
            fake_now[0] = i * 0.1
            topos_err = 1.0 - 0.8 * i / 39
            await thymos._handle_peer_event(
                "topos.out",
                _report("topos", "topos.report", topos_err),
            )
            await thymos._handle_peer_event(
                "audition.out",
                _report("audition", "audition.perception", 0.5),
            )
            if (i + 1) % 3 == 0:
                await thymos._tick()
        fake_now[0] = 4.0
        await thymos._tick()

        mixed_signed = thymos._progress()[1]
        assert mixed_signed > 0.0

        topos_only = Thymos(
            bus,
            clock=lambda: fake_now[0],
            drift_rate_per_s=0.0,
            publish_interval_s=999.0,
        )
        await topos_only.initialize()
        try:
            for i in range(40):
                fake_now[0] = i * 0.1
                topos_err = 1.0 - 0.8 * i / 39
                await topos_only._handle_peer_event(
                    "topos.out",
                    _report("topos", "topos.report", topos_err),
                )
                if (i + 1) % 3 == 0:
                    await topos_only._tick()
            fake_now[0] = 4.0
            await topos_only._tick()
            topos_signed = topos_only._progress()[1]
            assert mixed_signed < topos_signed
        finally:
            await topos_only.shutdown()
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_soma_report_without_wellness_keeps_prior(bus: AsyncBus):
    fake_now = [0.0]
    thymos = Thymos(bus, clock=lambda: fake_now[0], publish_interval_s=999.0)
    await thymos.initialize()
    try:
        assert thymos._wellness == 0.5
        await thymos._handle_peer_event(
            "soma.out",
            Event(
                source="soma",
                type="soma.report",
                payload={},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        assert thymos._wellness == 0.5

        await thymos._handle_peer_event(
            "soma.out",
            Event(
                source="soma",
                type="soma.report",
                payload={"wellness": 0.8},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        assert thymos._wellness == 0.8
    finally:
        await thymos.shutdown()


def test_default_drives_can_cross_threshold():
    s = DriveSet()
    for d in s.all():
        equilibrium = d.build_rate / (d.build_rate + d.decay_rate)
        assert equilibrium > d.threshold / 0.85
        d.reset()
        fired = False
        for _ in range(200):
            d.tick(dt=1.0, signal=1.0)
            if d.consume_crossing():
                fired = True
                break
        assert fired, f"{d.name} did not cross threshold within 200s"


def test_from_config_rejects_unknown_drive():
    with pytest.raises(ValueError):
        DriveSet.from_config({"hunger": {}})


def test_shipped_config_drives_can_cross_threshold():
    config_path = Path(__file__).resolve().parents[1] / "config" / "kaine.toml"
    with open(config_path, "rb") as f:
        cfg = tomllib.load(f)
    s = DriveSet.from_config(cfg["thymos"]["drives"])
    for d in s.all():
        equilibrium = d.build_rate / (d.build_rate + d.decay_rate)
        assert equilibrium > 0.85, f"{d.name} equilibrium {equilibrium:.3f} is not above 0.85"


@pytest.mark.asyncio
async def test_rest_intent_does_not_relieve_restlessness(bus: AsyncBus):
    fake_now = [0.0]
    thymos = Thymos(bus, clock=lambda: fake_now[0], publish_interval_s=999.0)
    await thymos.initialize()
    try:
        thymos.drives.restlessness.value = 0.8
        await thymos._handle_peer_event(
            "volition.out",
            Event(
                source="volition",
                type="intent.rest",
                payload={},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        assert thymos.drives.restlessness.value == pytest.approx(0.8)
        assert thymos._intents_since_broadcast == 0
        await thymos._handle_peer_event(
            "volition.out",
            Event(
                source="volition",
                type="intent.act",
                payload={},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        assert thymos.drives.restlessness.value < 0.8
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_zero_first_error_does_not_seed_progress(bus: AsyncBus):
    fake_now = [0.0]
    thymos = Thymos(
        bus,
        clock=lambda: fake_now[0],
        drift_rate_per_s=0.0,
        publish_interval_s=999.0,
    )
    await thymos.initialize()
    try:
        await thymos._handle_peer_event(
            "topos.out",
            Event(
                source="topos",
                type="topos.report",
                payload={"prediction_error": 0.0},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        fake_now[0] = 0.1
        await thymos._handle_peer_event(
            "topos.out",
            Event(
                source="topos",
                type="topos.report",
                payload={"prediction_error": 1.0},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        fake_now[0] = 0.2
        await thymos._handle_peer_event(
            "topos.out",
            Event(
                source="topos",
                type="topos.report",
                payload={"prediction_error": 1.0},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        _, signed = thymos._progress()
        assert signed == 0.0
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_drives_build_under_stationary_noise(bus: AsyncBus):
    rng = random.Random(42)
    fake_now = [0.0]
    thymos = Thymos(
        bus,
        clock=lambda: fake_now[0],
        drift_rate_per_s=0.0,
        publish_interval_s=999.0,
    )
    await thymos.initialize()
    try:
        step = 0.1
        total = 600.0
        max_curi = 0.0
        max_bored = 0.0
        for i in range(int(round(total / step)) + 1):
            t = i * step
            fake_now[0] = t
            err = rng.lognormvariate(0.0, 0.3)
            alert = rng.random() < 0.05
            await thymos._handle_peer_event(
                "topos.out",
                Event(
                    source="topos",
                    type="topos.report",
                    payload={
                        "prediction_error": err,
                        "alert": alert,
                        "normalised_error": 2.5 if alert else 1.0,
                    },
                    salience=0.5,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
            if i % 3 == 0:
                await thymos._tick()
                max_curi = max(max_curi, thymos.drives.curiosity.value)
                max_bored = max(max_bored, thymos.drives.boredom.value)
        assert max_curi > 0.7
        assert max_bored > 0.7
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_novelty_burst_relieves_boredom(bus: AsyncBus):
    rng = random.Random(43)
    fake_now = [0.0]
    thymos = Thymos(
        bus,
        clock=lambda: fake_now[0],
        drift_rate_per_s=0.0,
        publish_interval_s=999.0,
    )
    await thymos.initialize()
    try:
        step = 0.1
        built = False

        # 300 s of base-rate stationary noise: boredom should build.
        for i in range(3001):
            t = i * step
            fake_now[0] = t
            err = rng.lognormvariate(0.0, 0.3)
            alert = rng.random() < 0.05
            await thymos._handle_peer_event(
                "topos.out",
                Event(
                    source="topos",
                    type="topos.report",
                    payload={
                        "prediction_error": err,
                        "alert": alert,
                        "normalised_error": 2.5 if alert else 1.0,
                    },
                    salience=0.5,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
            if i % 3 == 0:
                await thymos._tick()
                if thymos.drives.boredom.value > 0.7:
                    built = True
        assert built, "boredom did not build above 0.7 during the base-rate stream"

        # 30 s of alert burst: boredom should be relieved.
        for i in range(3001, 3301):
            t = i * step
            fake_now[0] = t
            err = rng.lognormvariate(0.0, 0.3)
            alert = rng.random() < 0.4
            await thymos._handle_peer_event(
                "topos.out",
                Event(
                    source="topos",
                    type="topos.report",
                    payload={
                        "prediction_error": err,
                        "alert": alert,
                        "normalised_error": 2.5 if alert else 1.0,
                    },
                    salience=0.5,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
            if i % 3 == 0:
                await thymos._tick()
        assert thymos.drives.boredom.value < 0.4
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_falling_errors_relieve_curiosity(bus: AsyncBus):
    rng = random.Random(44)
    fake_now = [0.0]
    thymos = Thymos(
        bus,
        clock=lambda: fake_now[0],
        drift_rate_per_s=0.0,
        publish_interval_s=999.0,
    )
    await thymos.initialize()
    try:
        step = 0.1

        # 300 s of stationary noise to build curiosity above threshold.
        for i in range(3001):
            t = i * step
            fake_now[0] = t
            err = rng.lognormvariate(0.0, 0.3)
            alert = rng.random() < 0.05
            await thymos._handle_peer_event(
                "topos.out",
                Event(
                    source="topos",
                    type="topos.report",
                    payload={
                        "prediction_error": err,
                        "alert": alert,
                        "normalised_error": 2.5 if alert else 1.0,
                    },
                    salience=0.5,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
            if i % 3 == 0:
                await thymos._tick()
        assert thymos.drives.curiosity.value > 0.7

        # 60 s in which the error scale falls linearly to 40 %.
        for i in range(3001, 3601):
            t = i * step
            scale = 1.0 - 0.6 * (t - 300.0) / 60.0
            fake_now[0] = t
            err = rng.lognormvariate(0.0, 0.3) * scale
            alert = rng.random() < 0.05
            await thymos._handle_peer_event(
                "topos.out",
                Event(
                    source="topos",
                    type="topos.report",
                    payload={
                        "prediction_error": err,
                        "alert": alert,
                        "normalised_error": 2.5 if alert else 1.0,
                    },
                    salience=0.5,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
            if i % 3 == 0:
                await thymos._tick()
        assert thymos.drives.curiosity.value < 0.5
        assert thymos.state.valence > 0.0
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_curiosity_relief_is_report_rate_invariant(bus: AsyncBus):
    async def _run(report_interval: float) -> float:
        fake_now = [0.0]
        thymos = Thymos(
            bus,
            clock=lambda: fake_now[0],
            drift_rate_per_s=0.0,
            publish_interval_s=999.0,
        )
        await thymos.initialize()
        try:
            step = 0.1
            total = 160.0
            report_every = int(round(report_interval / step))
            for i in range(int(round(total / step)) + 1):
                t = i * step
                fake_now[0] = t
                if i % report_every == 0:
                    if t < 100.0:
                        err = 1.0
                    else:
                        err = 1.0 - 0.6 * (t - 100.0) / 60.0
                    await thymos._handle_peer_event(
                        "topos.out",
                        Event(
                            source="topos",
                            type="topos.report",
                            payload={"prediction_error": err},
                            salience=0.5,
                            timestamp=datetime.now(timezone.utc),
                        ),
                    )
                if i % 3 == 0:
                    if abs(t - 100.0) < 1e-9:
                        thymos.drives.curiosity.value = 0.8
                    await thymos._tick()
            return thymos.drives.curiosity.value
        finally:
            await thymos.shutdown()

    fast = await _run(0.1)
    slow = await _run(0.2)
    assert abs(fast - slow) < 0.05


@pytest.mark.asyncio
async def test_low_first_error_does_not_depress_valence(bus: AsyncBus):
    fake_now = [0.0]
    thymos = Thymos(
        bus,
        clock=lambda: fake_now[0],
        drift_rate_per_s=0.0,
        publish_interval_s=999.0,
    )
    await thymos.initialize()
    try:
        rng = random.Random(7)
        min_valence = thymos.state.valence
        for i in range(1200):
            fake_now[0] = i * 0.1
            if i == 0:
                e = 0.0  # the forward models report 0 on their first frame
            elif i == 1:
                e = 0.6  # a first positive error well below the steady level
            else:
                e = rng.lognormvariate(0.0, 0.3)
            await thymos._handle_peer_event(
                "topos.out",
                Event(
                    source="topos",
                    type="topos.report",
                    payload={"prediction_error": e},
                    salience=0.5,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
            if i > 0 and i % 3 == 0:
                await thymos._tick()
                min_valence = min(min_valence, thymos.state.valence)
        assert min_valence > -0.2, min_valence
    finally:
        await thymos.shutdown()


def test_drive_rejects_nan_rates():
    with pytest.raises(ValueError):
        Drive(name="x", build_rate=float("nan"))
    with pytest.raises(ValueError):
        Drive(name="x", decay_rate=float("nan"))
