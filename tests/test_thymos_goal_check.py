# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the Thymos goal-significance drive-relevance change.

Covers dominant-drive injection, the signed drive score, ledger fallback,
method disclosure, and cycle wiring.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.boot.registry import rewire_module
from kaine.boot.wiring import _wire_thymos_drive_relevance
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry
from kaine.modules.thymos import Thymos
from kaine.workspace.strategies import (
    DriveRelevanceGoalScorer,
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


def _ev(source="soma", type_="t", salience=0.5, eid="e0", **payload):
    return eid, Event(
        source=source,
        type=type_,
        payload=payload or {"k": "v"},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


DRIVE_SOURCES = {
    "social_drive": frozenset({"audition"}),
    "curiosity": frozenset({"topos"}),
    "boredom": frozenset(),
    "restlessness": frozenset(),
}


# ---------------------------------------------------------------------------
# Drive-relevance scoring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_social_drive_served_by_audition_positive(bus: AsyncBus):
    """Social drive 0.8 + all audition selected events → +0.8."""
    thymos = Thymos(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await thymos.initialize()
    try:
        thymos.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        thymos.drives.social_drive.value = 0.8
        scores = thymos._score_snapshot(
            _snapshot([_ev(source="audition", type_="perception", salience=0.9, eid="e1")])
        )
        assert scores.goal_significance == pytest.approx(0.8)
        assert thymos._goal_method == "drive_relevance_v1"
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_social_drive_ignored_by_soma_negative(bus: AsyncBus):
    """Social drive 0.8 + only non-serving soma events → -0.8."""
    thymos = Thymos(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await thymos.initialize()
    try:
        thymos.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        thymos.drives.social_drive.value = 0.8
        scores = thymos._score_snapshot(
            _snapshot([_ev(source="soma", type_="report", salience=0.9, eid="e1")])
        )
        assert scores.goal_significance == pytest.approx(-0.8)
        assert thymos._goal_method == "drive_relevance_v1"
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_half_salience_served_yields_zero(bus: AsyncBus):
    """Equal salience from serving and non-serving sources → 0.0."""
    thymos = Thymos(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await thymos.initialize()
    try:
        thymos.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        thymos.drives.social_drive.value = 0.8
        events = [
            _ev(source="audition", type_="perception", salience=0.5, eid="e1"),
            _ev(source="soma", type_="report", salience=0.5, eid="e2"),
        ]
        scores = thymos._score_snapshot(_snapshot(events))
        assert scores.goal_significance == pytest.approx(0.0)
        assert thymos._goal_method == "drive_relevance_v1"
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_all_drives_zero_with_table_zero_score(bus: AsyncBus):
    """All drives at 0 → drive score 0.0, but method still disclosed."""
    thymos = Thymos(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await thymos.initialize()
    try:
        thymos.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        scores = thymos._score_snapshot(
            _snapshot([_ev(source="audition", type_="perception", salience=0.9, eid="e1")])
        )
        assert scores.goal_significance == pytest.approx(0.0)
        assert thymos._goal_method == "drive_relevance_v1"
    finally:
        await thymos.shutdown()


# ---------------------------------------------------------------------------
# Fallback / combination behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_table_no_goals_unavailable(bus: AsyncBus):
    """No table and no active goals → 0.0 and method 'unavailable'."""
    thymos = Thymos(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await thymos.initialize()
    try:
        scores = thymos._score_snapshot(
            _snapshot([_ev(source="audition", type_="perception", salience=0.9, eid="e1")])
        )
        assert scores.goal_significance == pytest.approx(0.0)
        assert thymos._goal_method == "unavailable"
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_no_table_active_goal_token_overlap(bus: AsyncBus):
    """No table but active matching goal → positive token-overlap score."""
    thymos = Thymos(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await thymos.initialize()
    try:
        thymos.goals.add("navigate", priority=1.0)
        scores = thymos._score_snapshot(
            _snapshot([_ev(source="soma", type_="navigate_event", salience=0.9, eid="e1", text="navigate")])
        )
        assert scores.goal_significance > 0.0
        assert thymos._goal_method == "token_overlap_v1"
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_table_plus_active_goal_max_positive(bus: AsyncBus):
    """Table present + active matching goal with drives zero → max positive."""
    thymos = Thymos(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await thymos.initialize()
    try:
        thymos.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        thymos.goals.add("navigate", priority=1.0)
        scores = thymos._score_snapshot(
            _snapshot([_ev(source="soma", type_="navigate_event", salience=0.9, eid="e1", text="navigate")])
        )
        assert scores.goal_significance > 0.0
        assert thymos._goal_method == "drive_relevance_v1+token_overlap_v1"
    finally:
        await thymos.shutdown()


# ---------------------------------------------------------------------------
# Disclosure in published event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emotion_event_carries_goal_significance_method(bus: AsyncBus):
    """A state-changing appraisal publishes the computed method."""
    thymos = Thymos(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await thymos.initialize()
    try:
        thymos.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        thymos.drives.social_drive.value = 0.8
        await thymos.on_workspace(
            _snapshot([_ev(source="audition", type_="perception", salience=0.9, eid="e1")])
        )
        entries = await bus.read("thymos.out", last_id="0", count=20)
        emotion_events = [e for _, e in entries if e.type == "thymos.emotion"]
        assert emotion_events, "expected a thymos.emotion event"
        ev = emotion_events[0]
        assert ev.payload.get("goal_significance_method") == "drive_relevance_v1"
    finally:
        await thymos.shutdown()


# ---------------------------------------------------------------------------
# Pure helper + preserved DriveRelevanceGoalScorer behavior
# ---------------------------------------------------------------------------


def test_dominant_drive_empty_is_none():
    assert dominant_drive({}) is None


def test_dominant_drive_tie_breaks_by_name():
    assert dominant_drive({"a": 0.5, "b": 0.5}) == ("b", 0.5)
    assert dominant_drive({"a": 0.9, "b": 0.5}) == ("a", 0.9)


@pytest.mark.asyncio
async def test_drive_relevance_goal_scorer_results_unchanged():
    scorer = DriveRelevanceGoalScorer(
        lambda: {
            "social_drive": 0.8,
            "curiosity": 0.0,
            "boredom": 0.0,
            "restlessness": 0.0,
        },
        drive_sources=DRIVE_SOURCES,
        attenuation=0.5,
    )
    serving = Event(
        source="audition",
        type="perception",
        payload={},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    non_serving = Event(
        source="soma",
        type="report",
        payload={},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    assert await scorer.relevance(serving) == pytest.approx(1.0)
    assert await scorer.relevance(non_serving) == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# Boot wiring (build_registry and Spot's rewire_module both run it)
# ---------------------------------------------------------------------------


class _Audition(BaseModule):
    """A registered module whose declared drives make Audition serve social_drive."""

    name = "audition"
    relieves_drives = frozenset({"social_drive"})


@pytest.mark.asyncio
async def test_boot_wiring_gives_thymos_the_drive_table(bus: AsyncBus):
    registry = ModuleRegistry()
    registry.register(_Audition(bus))
    registry.register(Thymos(bus, publish_interval_s=5.0, clock=lambda: 0.0))
    _wire_thymos_drive_relevance(registry)
    thymos = registry.get("thymos")
    thymos.drives.social_drive.value = 0.8
    scores = thymos._score_snapshot(
        _snapshot([_ev(source="audition", type_="perception", salience=0.9, eid="e1")])
    )
    assert scores.goal_significance == pytest.approx(0.8)
    assert thymos._goal_method == "drive_relevance_v1"


@pytest.mark.asyncio
async def test_restarted_thymos_is_rewired(bus: AsyncBus):
    registry = ModuleRegistry()
    registry.register(_Audition(bus))
    registry.register(Thymos(bus, publish_interval_s=5.0, clock=lambda: 0.0))
    _wire_thymos_drive_relevance(registry)
    fresh = Thymos(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    registry.replace("thymos", fresh)
    rewire_module(registry, "thymos", {})
    fresh._score_snapshot(_snapshot([_ev(source="soma", salience=0.5)]))
    assert fresh._goal_method == "drive_relevance_v1"


def test_boot_wiring_without_thymos_is_a_no_op(bus: AsyncBus):
    registry = ModuleRegistry()
    registry.register(_Audition(bus))
    _wire_thymos_drive_relevance(registry)
