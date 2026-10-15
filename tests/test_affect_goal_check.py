# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the affect goal-significance drive-relevance change.

Covers dominant-drive injection, the unsigned drive score, ledger fallback,
method disclosure, and cycle wiring.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.boot.registry import rewire_module
from kaine.boot.wiring import _wire_affect_drive_relevance
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.affect import Affect
from kaine.modules.affect.appraisal import CategoricalEmotion, classify
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry
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
# Drive-relevance scoring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_social_drive_served_by_audition_positive(bus: AsyncBus):
    """Social drive 0.8 + all audition selected events → +0.8."""
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        affect.drives.social_drive.value = 0.8
        scores = affect._score_snapshot(
            _snapshot([_ev(source="audition", type_="perception", salience=0.9, eid="e1")])
        )
        assert scores.goal_significance == pytest.approx(0.8)
        assert affect._goal_method == "drive_relevance_v1"
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_social_drive_ignored_by_interoception_irrelevant(bus: AsyncBus):
    """Social drive 0.8 + only non-serving interoception events → 0.0 (irrelevant)."""
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        affect.drives.social_drive.value = 0.8
        scores = affect._score_snapshot(
            _snapshot([_ev(source="interoception", type_="report", salience=0.9, eid="e1")])
        )
        assert scores.goal_significance == pytest.approx(0.0)
        assert affect._goal_method == "drive_relevance_v1"
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_half_salience_served_yields_half(bus: AsyncBus):
    """Half the salience from serving sources → 0.4 (0.8 × 0.5)."""
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        affect.drives.social_drive.value = 0.8
        events = [
            _ev(source="audition", type_="perception", salience=0.5, eid="e1"),
            _ev(source="interoception", type_="report", salience=0.5, eid="e2"),
        ]
        scores = affect._score_snapshot(_snapshot(events))
        assert scores.goal_significance == pytest.approx(0.4)
        assert affect._goal_method == "drive_relevance_v1"
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_empty_coalition_is_irrelevant(bus: AsyncBus):
    """Curiosity 0.3 with an empty coalition → 0.0."""
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        affect.drives.curiosity.value = 0.3
        scores = affect._score_snapshot(_snapshot([]))
        assert scores.goal_significance == pytest.approx(0.0)
        assert affect._goal_method == "drive_relevance_v1"
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_all_drives_zero_with_table_zero_score(bus: AsyncBus):
    """All drives at 0 → drive score 0.0, but method still disclosed."""
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        scores = affect._score_snapshot(
            _snapshot([_ev(source="audition", type_="perception", salience=0.9, eid="e1")])
        )
        assert scores.goal_significance == pytest.approx(0.0)
        assert affect._goal_method == "drive_relevance_v1"
    finally:
        await affect.shutdown()


# ---------------------------------------------------------------------------
# Fallback / combination behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_idle_coalition_is_not_anger(bus: AsyncBus):
    """A mild unmet curiosity with no serving content is irrelevant, not anger."""
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        affect.drives.curiosity.value = 0.32
        scores = affect._score_snapshot(
            _snapshot([_ev(source="interoception", type_="report", salience=0.9, eid="e1")])
        )
        assert scores.goal_significance == pytest.approx(0.0)
        assert classify(scores) != CategoricalEmotion.ANGER
    finally:
        await affect.shutdown()


# ---------------------------------------------------------------------------
# Fallback / combination behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_table_no_goals_unavailable(bus: AsyncBus):
    """No table and no active goals → 0.0 and method 'unavailable'."""
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        scores = affect._score_snapshot(
            _snapshot([_ev(source="audition", type_="perception", salience=0.9, eid="e1")])
        )
        assert scores.goal_significance == pytest.approx(0.0)
        assert affect._goal_method == "unavailable"
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_no_table_active_goal_token_overlap(bus: AsyncBus):
    """No table but active matching goal → positive token-overlap score."""
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        affect.goals.add("navigate", priority=1.0)
        scores = affect._score_snapshot(
            _snapshot([_ev(source="interoception", type_="navigate_event", salience=0.9, eid="e1", text="navigate")])
        )
        assert scores.goal_significance > 0.0
        assert affect._goal_method == "token_overlap_v1"
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_ledger_unrelated_content_is_irrelevant(bus: AsyncBus):
    """No table with an active goal but unrelated tokens → 0.0 (irrelevant)."""
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        affect.goals.add("navigate", priority=1.0)
        scores = affect._score_snapshot(
            _snapshot([_ev(source="interoception", type_="report", salience=0.9, eid="e1", text="unrelated")])
        )
        assert scores.goal_significance == pytest.approx(0.0)
        assert affect._goal_method == "token_overlap_v1"
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_table_plus_active_goal_max_positive(bus: AsyncBus):
    """Table present + active matching goal with drives zero → max positive."""
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        affect.goals.add("navigate", priority=1.0)
        scores = affect._score_snapshot(
            _snapshot([_ev(source="interoception", type_="navigate_event", salience=0.9, eid="e1", text="navigate")])
        )
        assert scores.goal_significance > 0.0
        assert affect._goal_method == "drive_relevance_v1+token_overlap_v1"
    finally:
        await affect.shutdown()


# ---------------------------------------------------------------------------
# Disclosure in published event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emotion_event_carries_goal_significance_method(bus: AsyncBus):
    """A state-changing appraisal publishes the computed method."""
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    await affect.initialize()
    try:
        affect.set_drive_relevance(DRIVE_SOURCES, dominant_drive)
        affect.drives.social_drive.value = 0.2
        await affect.on_workspace(
            _snapshot([_ev(source="audition", type_="perception", salience=0.9, eid="e1", normalised_error=3.0)])
        )
        entries = await bus.read("affect.out", last_id="0", count=20)
        emotion_events = [e for _, e in entries if e.type == "affect.emotion"]
        assert emotion_events, "expected a affect.emotion event"
        ev = emotion_events[0]
        assert ev.payload.get("goal_significance_method") == "drive_relevance_v1"
    finally:
        await affect.shutdown()


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
        source="interoception",
        type="report",
        payload={},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    assert await scorer.relevance(serving) == pytest.approx(1.0)
    assert await scorer.relevance(non_serving) == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# Boot wiring (build_registry and the supervisor's rewire_module both run it)
# ---------------------------------------------------------------------------


class _Audition(BaseModule):
    """A registered module whose declared drives make Audition serve social_drive."""

    name = "audition"
    relieves_drives = frozenset({"social_drive"})


@pytest.mark.asyncio
async def test_boot_wiring_gives_affect_the_drive_table(bus: AsyncBus):
    registry = ModuleRegistry()
    registry.register(_Audition(bus))
    registry.register(Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0))
    _wire_affect_drive_relevance(registry)
    affect = registry.get("affect")
    affect.drives.social_drive.value = 0.8
    scores = affect._score_snapshot(
        _snapshot([_ev(source="audition", type_="perception", salience=0.9, eid="e1")])
    )
    assert scores.goal_significance == pytest.approx(0.8)
    assert affect._goal_method == "drive_relevance_v1"


@pytest.mark.asyncio
async def test_restarted_affect_is_rewired(bus: AsyncBus):
    registry = ModuleRegistry()
    registry.register(_Audition(bus))
    registry.register(Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0))
    _wire_affect_drive_relevance(registry)
    fresh = Affect(bus, publish_interval_s=5.0, clock=lambda: 0.0)
    registry.replace("affect", fresh)
    rewire_module(registry, "affect", {})
    fresh._score_snapshot(_snapshot([_ev(source="interoception", salience=0.5)]))
    assert fresh._goal_method == "drive_relevance_v1"


def test_boot_wiring_without_affect_is_a_no_op(bus: AsyncBus):
    registry = ModuleRegistry()
    registry.register(_Audition(bus))
    _wire_affect_drive_relevance(registry)
