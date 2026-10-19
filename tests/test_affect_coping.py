# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for coping potential: relevance gate and success ratio (paper A.4)."""
from __future__ import annotations

import dataclasses
import math
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.affect import Affect
from kaine.modules.affect.appraisal import AppraisalScores, CategoricalEmotion, classify
from kaine.modules.affect.drives import Drive, DriveSet
from kaine.modules.affect.state import DimensionalState
from kaine.workspace.strategies import (
    dominant_drive,
)

# ---------------------------------------------------------------------------
# Shared fixtures / helpers (copied from test_affect_memory_honesty)
# ---------------------------------------------------------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _snapshot(events=None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=events or [],
        inhibited=False,
    )


def _ev(source="interoception", type_="t", salience=0.5, eid="e0", **payload):
    return eid, Event(
        source=source,
        type=type_,
        payload=payload or {"k": "v"},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


DRIVE_SOURCES = {
    "social_drive": frozenset({"audition"}),
    "curiosity": frozenset({"vision"}),
    "boredom": frozenset(),
    "restlessness": frozenset(),
}


# ---------------------------------------------------------------------------
# Drive outcome counters
# ---------------------------------------------------------------------------


def test_own_relief_counts_as_own():
    d = Drive(
        name="x",
        build_rate=0.1,
        decay_rate=0.0,
        threshold=0.5,
        relief_gain=1.0,
    )
    d.value = 0.9
    assert d.consume_crossing() is True
    d.relieve(1.0, own=True)
    assert d.own_ends == 1
    assert d.other_ends == 0


def test_external_relief_counts_as_other():
    d = Drive(
        name="x",
        build_rate=0.1,
        decay_rate=0.0,
        threshold=0.5,
        relief_gain=1.0,
    )
    d.value = 0.9
    assert d.consume_crossing() is True
    d.relieve(1.0, own=False)
    assert d.other_ends == 1
    assert d.own_ends == 0


def test_decay_alone_counts_as_other():
    d = Drive(
        name="x",
        build_rate=0.0,
        decay_rate=1.0,
        threshold=0.5,
        relief_gain=0.5,
    )
    d.value = 0.9
    assert d.consume_crossing() is True
    d.tick(100.0, 0.0)
    assert d.other_ends == 1
    assert d.own_ends == 0


def test_held_down_build_counts_as_own():
    d = Drive(
        name="x",
        build_rate=1.0,
        decay_rate=1.0,
        threshold=0.5,
        relief_gain=0.5,
    )
    d.value = 0.9
    d.consume_crossing()
    d.tick(1.0, 0.0, no_response_signal=1.0)
    assert d.own_ends == 1
    assert d.other_ends == 0
    assert d.value == pytest.approx(0.9 * math.exp(-1.0), rel=1e-6)


def test_fall_that_would_happen_anyway_counts_as_other():
    d = Drive(
        name="x",
        build_rate=0.1,
        decay_rate=1.0,
        threshold=0.5,
        relief_gain=0.5,
    )
    d.value = 0.9
    d.consume_crossing()
    d.tick(10.0, 0.0, no_response_signal=1.0)
    assert d.other_ends == 1
    assert d.own_ends == 0


def test_reset_counts_as_neither():
    d = Drive(
        name="x",
        build_rate=0.1,
        decay_rate=0.0,
        threshold=0.5,
        relief_gain=1.0,
    )
    d.value = 0.9
    assert d.consume_crossing() is True
    d.reset()
    assert d.own_ends == 0
    assert d.other_ends == 0


def test_power_laplace():
    d = Drive(name="x", threshold=0.5)
    assert d.power() == pytest.approx(0.5)
    d.own_ends = 2
    d.other_ends = 0
    assert d.power() == pytest.approx(0.75)
    d.own_ends = 0
    d.other_ends = 2
    assert d.power() == pytest.approx(0.25)


def test_driveset_attribution():
    ds = DriveSet()
    for d in ds.all():
        d.value = 0.95
        d.consume_crossing()
    ds.relieve_rate("boredom", 1.0, 100.0, own=True)
    ds.relieve_rate("social_drive", 1.0, 100.0, own=False)
    ds.relieve("restlessness", 1.0, own=True)
    # Curiosity is heterostatic: nothing relieves it and its ends count neither.
    ds.relieve_rate("curiosity", 1.0, 100.0, own=True)
    assert ds.boredom.own_ends == 1
    assert ds.restlessness.own_ends == 1
    assert ds.social_drive.other_ends == 1
    assert ds.curiosity.own_ends == 0
    assert ds.curiosity.other_ends == 0


def test_driveset_tick_credits_only_own_inputs():
    # Learning progress and alert excess both hold boredom's build input at 0.
    # Without learning progress boredom would have kept building (no-response
    # input 1 - exc = 1), so its fall is the entity's; when alert excess alone
    # would have held the input down (no-response input 0), the fall is not.
    # Curiosity is heterostatic: its crossing ends count neither.
    own = DriveSet()
    other = DriveSet()
    for ds in (own, other):
        ds.boredom.value = ds.boredom.threshold
        assert ds.boredom.consume_crossing() is True
        ds.curiosity.value = ds.curiosity.threshold
        assert ds.curiosity.consume_crossing() is True
    own.tick(60.0, progress_signal=0.0, activity_signal=0.0, boredom_no_response_signal=1.0)
    other.tick(60.0, progress_signal=0.0, activity_signal=0.0, boredom_no_response_signal=0.0)
    assert (own.boredom.own_ends, own.boredom.other_ends) == (1, 0)
    assert (other.boredom.own_ends, other.boredom.other_ends) == (0, 1)
    for ds in (own, other):
        assert (ds.curiosity.own_ends, ds.curiosity.other_ends) == (0, 0)


def test_relieve_requires_own():
    d = Drive(name="x", threshold=0.5)
    with pytest.raises(TypeError):
        d.relieve(1.0)


# ---------------------------------------------------------------------------
# Relevance gate and score computation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_irrelevant_coalition_makes_coping_unavailable(bus: AsyncBus):
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        affect.drives.curiosity.value = 0.3
        scores = affect._score_snapshot(_snapshot([]))
        assert scores.coping_available is False
        assert scores.coping_potential == pytest.approx(0.0)
    finally:
        await affect.shutdown()


def test_classify_skips_fear_anger_sadness_without_coping():
    fear = AppraisalScores(
        novelty=0.7,
        intrinsic_pleasantness=-0.6,
        goal_significance=-0.5,
        coping_potential=-0.5,
        norm_compatibility=0.0,
        coping_available=False,
    )
    anger = AppraisalScores(
        novelty=0.0,
        intrinsic_pleasantness=-0.3,
        goal_significance=-0.5,
        coping_potential=0.4,
        norm_compatibility=0.0,
        coping_available=False,
    )
    sadness = AppraisalScores(
        novelty=0.1,
        intrinsic_pleasantness=-0.5,
        goal_significance=0.0,
        coping_potential=-0.2,
        norm_compatibility=0.0,
        coping_available=False,
    )
    assert classify(fear) is not CategoricalEmotion.FEAR
    assert classify(anger) is not CategoricalEmotion.ANGER
    assert classify(sadness) is not CategoricalEmotion.SADNESS

    assert classify(dataclasses.replace(fear, coping_available=True)) == CategoricalEmotion.FEAR
    assert classify(dataclasses.replace(anger, coping_available=True)) == CategoricalEmotion.ANGER
    assert classify(dataclasses.replace(sadness, coping_available=True)) == CategoricalEmotion.SADNESS


@pytest.mark.asyncio
async def test_no_history_gives_zero_coping(bus: AsyncBus):
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        affect.drives.social_drive.value = 0.8
        scores = affect._score_snapshot(
            _snapshot([_ev(source="audition", type_="perception", salience=0.9, eid="e1")])
        )
        assert scores.coping_available is True
        assert scores.coping_potential == pytest.approx(0.0)
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_other_ends_lower_coping(bus: AsyncBus):
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        affect.drives.social_drive.value = 0.8
        affect.drives.social_drive.other_ends = 2
        scores = affect._score_snapshot(
            _snapshot([_ev(source="audition", type_="perception", salience=0.9, eid="e1")])
        )
        assert scores.coping_potential == pytest.approx(-0.5)
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_own_ends_raise_coping(bus: AsyncBus):
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        affect.drives.social_drive.value = 0.8
        affect.drives.social_drive.own_ends = 2
        scores = affect._score_snapshot(
            _snapshot([_ev(source="audition", type_="perception", salience=0.9, eid="e1")])
        )
        assert scores.coping_potential == pytest.approx(0.5)
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_ledger_supplies_power_when_it_sets_the_score(bus: AsyncBus):
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        g1 = affect._goals.add("find the red ball")
        g2 = affect._goals.add("learn a song")
        g3 = affect._goals.add("draw a map")
        g4 = affect._goals.add("watch the sky")
        affect._goals.complete(g1.id)
        affect._goals.abandon(g2.id)
        affect._goals.abandon(g3.id)
        affect._goals.abandon(g4.id)
        affect._goals.add("hear the operator voice")

        scores = affect._score_snapshot(
            _snapshot(
                [
                    _ev(
                        source="audition",
                        type_="transcription",
                        salience=0.9,
                        eid="e1",
                        text="operator voice",
                    )
                ]
            )
        )
        assert scores.goal_significance > 0.0
        assert scores.coping_available is True
        assert scores.coping_potential == pytest.approx(2.0 * (2.0 / 6.0) - 1.0)
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_arousal_does_not_move_coping(bus: AsyncBus):
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        affect.drives.social_drive.value = 0.8
        affect.drives.social_drive.own_ends = 1

        affect._state = DimensionalState(valence=0.0, arousal=0.1, dominance=0.0)
        low_arousal = affect._score_snapshot(
            _snapshot([_ev(source="audition", type_="perception", salience=0.9, eid="e1")])
        ).coping_potential

        affect._state = DimensionalState(valence=-0.8, arousal=0.9, dominance=0.0)
        high_arousal = affect._score_snapshot(
            _snapshot([_ev(source="audition", type_="perception", salience=0.9, eid="e1")])
        ).coping_potential

        assert low_arousal == pytest.approx(high_arousal)
        assert low_arousal == pytest.approx(1.0 / 3.0)
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_drive_outcomes_survive_serialize(bus: AsyncBus):
    affect1 = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect1.initialize()
    try:
        affect1.drives.social_drive.own_ends = 3
        affect1.drives.social_drive.other_ends = 1

        state = affect1.serialize()
        affect2 = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
        await affect2.initialize()
        try:
            affect2.deserialize(state)
            assert affect2.drives.social_drive.own_ends == 3
            assert affect2.drives.social_drive.other_ends == 1
        finally:
            await affect2.shutdown()
    finally:
        await affect1.shutdown()


def test_load_outcomes_ignores_bad_values():
    ds = DriveSet()
    ds.load_outcomes(
        {
            "social_drive": {"own": -1, "other": True},
            "nope": {"own": 2},
            "curiosity": "x",
        }
    )
    for d in ds.all():
        assert d.own_ends == 0
        assert d.other_ends == 0

    ds.load_outcomes("junk")
    for d in ds.all():
        assert d.own_ends == 0
        assert d.other_ends == 0
