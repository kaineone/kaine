# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Research-affect tests for Thymos.

Validates the drive/relief dynamics and the valence/appraisal rules described
in the 2026-10-08 OpenSpec proposal.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

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
    thymos = Thymos(bus, clock=lambda: fake_now[0], publish_interval_s=999.0)
    await thymos.initialize()
    try:
        thymos.drives.curiosity.value = 0.6
        for i in range(50):
            r = 3.0 - (2.0 * i / 49)  # 3.0 down to 1.0
            await thymos._handle_peer_event(
                "topos.out",
                Event(
                    source="topos",
                    type="topos.report",
                    payload={"normalised_error": r},
                    salience=0.5,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        assert thymos.drives.curiosity.value < 0.6
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_boredom_relief_on_perceptual_alert(bus: AsyncBus):
    fake_now = [0.0]
    thymos = Thymos(bus, clock=lambda: fake_now[0], publish_interval_s=999.0)
    await thymos.initialize()
    try:
        thymos.drives.boredom.value = 0.8
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
        # Falling errors -> positive learning progress -> positive valence.
        for r in [3.0, 2.5, 2.0, 1.5, 1.0, 1.0, 1.0]:
            await thymos._handle_peer_event(
                "topos.out",
                Event(
                    source="topos",
                    type="topos.report",
                    payload={"normalised_error": r},
                    salience=0.5,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        fake_now[0] = 60.0
        await thymos.on_workspace(_snapshot())
        assert thymos.state.valence > 0.0, thymos.state.valence

        # Rising errors -> negative learning progress -> negative valence.
        # The slow error average has weight 0.02 (~50 reports), so send 60
        # rising reports to flip the sign of learning progress.
        for _ in range(60):
            await thymos._handle_peer_event(
                "topos.out",
                Event(
                    source="topos",
                    type="topos.report",
                    payload={"normalised_error": 5.0},
                    salience=0.5,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        fake_now[0] = 120.0
        await thymos.on_workspace(_snapshot())
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

    thymos = Thymos(
        bus,
        drift_rate_per_s=0.0,
        publish_interval_s=999.0,
    )
    await thymos.initialize()
    try:
        for i in range(40):
            topos_err = 1.0 - 0.8 * i / 39
            await thymos._handle_peer_event(
                "topos",
                _report("topos", "topos.report", topos_err),
            )
            await thymos._handle_peer_event(
                "audition",
                _report("audition", "audition.perception", 0.5),
            )

        mixed_signed = thymos._progress()[1]
        assert mixed_signed > 0.0

        topos_only = Thymos(
            bus,
            drift_rate_per_s=0.0,
            publish_interval_s=999.0,
        )
        await topos_only.initialize()
        try:
            for i in range(40):
                topos_err = 1.0 - 0.8 * i / 39
                await topos_only._handle_peer_event(
                    "topos",
                    _report("topos", "topos.report", topos_err),
                )
            topos_signed = topos_only._progress()[1]
            assert mixed_signed < topos_signed
        finally:
            await topos_only.shutdown()
    finally:
        await thymos.shutdown()
