# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Regression tests for the affect-related research log allowlist.

These tests verify that real affect module payloads are preserved in
privacy-filtered research records, that free-text fields are dropped, and that
the corresponding log_schema ranges exist.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.evaluation.observers.research_event_observer import (
    ResearchEventObserver,
    _workspace_metadata_record,
)
from kaine.experiment.log_schema import NONNEG, UNIT, _bound_for
from kaine.modules.affect import Affect
from kaine.modules.affect.appraisal import CategoricalEmotion
from kaine.modules.affect.regulation import RegulationConfig, ThreeTierRegulation
from kaine.modules.affect.state import DimensionalState
from tests.test_research_event_log import FakeBus, FakeSink

fakeredis_aioredis = pytest.importorskip("fakeredis.aioredis")


def _snapshot(events=None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=0, selected_events=events or [], inhibited=False
    )


def _ev(source="interoception", type_="t", salience=0.5, eid="e0", **payload):
    return (
        eid,
        Event(
            source=source,
            type=type_,
            payload=payload or {"k": "v"},
            salience=salience,
            timestamp=datetime.now(timezone.utc),
        ),
    )


def _pleasantness_value(negative: bool) -> float:
    return -0.4 if negative else 0.2


async def _drive(affect, t, seconds, *, valence=-0.8, negative=True):
    affect._pleasantness = lambda g: _pleasantness_value(negative)
    for _ in range(seconds):
        t[0] += 1.0
        affect._state = DimensionalState(
            valence=valence,
            arousal=affect.state.arousal,
            dominance=affect.state.dominance,
        )
        await affect.on_workspace(
            _snapshot(
                [
                    _ev("vision", salience=0.7, eid="v"),
                    _ev("audition", salience=0.3, eid="a"),
                ]
            )
        )


async def _read_affect_events(bus):
    entries = await bus.read("affect.out", last_id="0", count=500)
    return [event for _, event in entries]


def _fresh_bus():
    client = fakeredis_aioredis.FakeRedis(decode_responses=True)
    return AsyncBus(
        BusConfig(password="x", audit_required=False), client=client
    )


@pytest.fixture
async def bus():
    b = _fresh_bus()
    yield b
    await b.close()


@pytest.mark.asyncio
async def test_goal_added_real_producer(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    affect.drives.boredom.own_ends = 1
    affect.drives.boredom.value = 0.75
    await affect._tick()

    events = [e for e in await _read_affect_events(bus) if e.type == "affect.goal"]
    assert len(events) == 1
    ev = events[0]
    assert ev.payload["action"] == "added"

    obs = ResearchEventObserver(FakeBus(), FakeSink())
    record = obs._build_record(ev)
    payload = ev.payload

    for key in ("action", "id", "drive", "priority", "likelihood"):
        assert record[key] == payload[key], key
    assert "description" not in record
    assert "goal_id" not in record
    assert record["source"] == "affect"


@pytest.mark.asyncio
async def test_goal_end_real_producer(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    affect.drives.boredom.own_ends = 1
    affect.drives.boredom.value = 0.75
    await affect._tick()

    goal_id = affect.goals.active()[0].id
    payload = affect._end_goal(goal_id, "abandoned", "stalled")
    assert payload is not None

    ev = Event(
        source="affect",
        type="affect.goal",
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    obs = ResearchEventObserver(FakeBus(), FakeSink())
    record = obs._build_record(ev)

    assert record["action"] == "abandoned"
    assert record["id"] == goal_id
    assert record["drive"] == "boredom"
    assert record["reason"] == "stalled"
    assert "description" not in record
    assert record["source"] == "affect"


# Payload keys reviewed and deliberately kept out of the research log, per event
# type. A key here must be absent from the record.
_EXCLUDED_KEYS: dict[str, frozenset[str]] = {
    "affect.goal": frozenset({"description"}),
}


@pytest.mark.asyncio
async def test_drift_guard_allowlist(bus):
    # Goal-producing setup on the function-scoped bus fixture.
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    affect.drives.boredom.own_ends = 1
    affect.drives.boredom.value = 0.75
    await affect._tick()
    goal_events = [
        e for e in await _read_affect_events(bus) if e.type == "affect.goal"
    ]

    # Regulation-producing setup on a second, manually managed bus.
    bus2 = _fresh_bus()
    try:
        t2 = [0.0]
        affect2 = Affect(
            bus2,
            clock=lambda: t2[0],
            regulation=ThreeTierRegulation(RegulationConfig()),
            publish_interval_s=1000.0,
        )
        affect2._last_emotion = CategoricalEmotion.FEAR
        await _drive(affect2, t2, 95, valence=-0.8, negative=True)
        await affect2.affective_reset()
        reg_events = [
            e
            for e in await _read_affect_events(bus2)
            if e.type in {"affect.emotion", "affect.regulation", "affect.state"}
        ]
    finally:
        await bus2.close()

    all_events = goal_events + reg_events
    assert all_events

    missing: list[str] = []
    if not any(e.type == "affect.goal" for e in all_events):
        missing.append("affect.goal")
    if not any(e.type == "affect.emotion" for e in all_events):
        missing.append("affect.emotion")
    if not any(e.type == "affect.regulation" for e in all_events):
        missing.append("affect.regulation")
    if not any(
        e.type == "affect.state" and e.payload.get("reset") for e in all_events
    ):
        missing.append("affect.state with reset=True")
    assert not missing, f"Missing event kinds: {', '.join(missing)}"

    obs = ResearchEventObserver(FakeBus(), FakeSink())
    failures: list[str] = []

    for ev in all_events:
        # This guard covers only goal, emotion, regulation and reset-state
        # events. affect.drive and periodic affect.state events without reset
        # are outside the scope of this change.
        if ev.type == "affect.drive":
            continue
        if ev.type == "affect.state" and not ev.payload.get("reset"):
            continue
        record = obs._build_record(ev)
        if record is None:
            failures.append(f"{ev.type} produced no record")
            continue
        for key, value in ev.payload.items():
            if key in _EXCLUDED_KEYS.get(ev.type, frozenset()):
                if key in record:
                    failures.append(f"{ev.type} record leaked excluded key {key}")
            elif ev.type == "affect.regulation" and key == "source":
                if record.get("target_source") != value:
                    failures.append(
                        f"affect.regulation target_source mismatch: {record.get('target_source')} != {value}"
                    )
                if record.get("source") != "affect":
                    failures.append(
                        f"affect.regulation record source overwritten: {record.get('source')}"
                    )
            else:
                if key not in record:
                    failures.append(
                        f"{ev.type}: payload key {key!r} is not in the research record. "
                        f"Review it: allowlist it in _TAXONOMY only if it is a content-free number, "
                        f"flag, fixed code or opaque id; otherwise add it to _EXCLUDED_KEYS."
                    )

    assert not failures, "\n".join(failures)


@pytest.mark.asyncio
async def test_regulation_real_producer(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        regulation=ThreeTierRegulation(RegulationConfig()),
        publish_interval_s=1000.0,
    )
    await _drive(affect, t, 95, valence=-0.8, negative=True)

    events = [
        e for e in await _read_affect_events(bus) if e.type == "affect.regulation"
    ]
    assert len(events) == 3

    obs = ResearchEventObserver(FakeBus(), FakeSink())
    records = [obs._build_record(e) for e in events]

    r1 = records[0]
    assert r1["tier"] == 1
    assert r1["action"] == "attentional_deployment"
    assert r1["target_source"] == "vision"
    assert r1["source"] == "affect"
    assert r1["bias"] == pytest.approx(0.2)
    assert r1["decay_s"] == 20.0
    assert "size" in r1
    assert "intensity" in r1
    assert "episode_s" in r1

    r2 = records[1]
    assert r2["tier"] == 2
    assert "emotion_before" in r2
    assert "emotion_after" in r2

    r3 = records[2]
    assert r3["tier"] == 3
    assert r3["action"] == "request_maintenance"


@pytest.mark.asyncio
async def test_emotion_real_producer(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        regulation=ThreeTierRegulation(RegulationConfig()),
        publish_interval_s=1000.0,
    )
    affect._last_emotion = CategoricalEmotion.FEAR
    await _drive(affect, t, 95, valence=-0.8, negative=True)

    events = [
        e for e in await _read_affect_events(bus) if e.type == "affect.emotion"
    ]
    assert len(events) >= 1

    obs = ResearchEventObserver(FakeBus(), FakeSink())
    for ev in events:
        record = obs._build_record(ev)
        payload = ev.payload
        assert record["coping_available"] == payload["coping_available"]
        assert record["obstruction"] == payload["obstruction"]
        assert record["goal_significance_method"] == payload["goal_significance_method"]
        assert record["state"] == payload["state"]

    reappraised = Event(
        source="affect",
        type="affect.emotion",
        payload={
            "emotion": "fear",
            "scores": (0.1, 0.2, 0.3),
            "norm_compatibility_available": False,
            "alert": True,
            "state": {"valence": -0.5},
            "coping_available": True,
            "obstruction": 0.0,
            "goal_significance_method": "max",
            "reappraised": True,
        },
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    record = obs._build_record(reappraised)
    assert record["reappraised"] is True


def test_normalised_change_allowlisted():
    obs = ResearchEventObserver(FakeBus(), FakeSink())

    vision = Event(
        source="vision",
        type="vision.report",
        payload={
            "prediction_error": 0.2,
            "normalised_error": 1.1,
            "normalised_change": 1.4,
            "alert": False,
        },
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    record = obs._build_record(vision)
    assert record["normalised_change"] == pytest.approx(1.4)

    audition = Event(
        source="audition",
        type="audition.perception",
        payload={
            "prediction_error": 0.2,
            "normalised_error": 1.1,
            "normalised_change": 0.7,
            "alert": False,
        },
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    record = obs._build_record(audition)
    assert record["normalised_change"] == pytest.approx(0.7)


def test_affective_reset_state_record():
    obs = ResearchEventObserver(FakeBus(), FakeSink())
    ev = Event(
        source="affect",
        type="affect.state",
        payload={
            "state": {"valence": 0.0, "arousal": 0.5, "dominance": 0.0},
            "drives": {},
            "emotion": "neutral",
            "reset": True,
            "alert": True,
        },
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    record = obs._build_record(ev)
    assert record["reset"] is True
    assert record["alert"] is True


def test_goal_description_never_leaks():
    obs = ResearchEventObserver(FakeBus(), FakeSink())
    ev = Event(
        source="affect",
        type="affect.goal",
        payload={
            "action": "added",
            "id": "g1",
            "description": "SECRET goal text",
            "priority": 0.5,
        },
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    record = obs._build_record(ev)
    assert "description" not in record
    assert "SECRET" not in json.dumps(record)


def test_workspace_metadata_bias_and_feedback():
    snapshot = {
        "tick_index": 7,
        "metadata": {
            "regulation_bias": {"source": "vision", "factor": 0.83, "extra": 1},
            "workspace_feedback": {
                "arm": "full",
                "gains": {"vision": 0.9, "audition": 1.1, "interoception": 1.0},
                "sequence_prediction": [0.1] * 24,
                "episodes": [
                    {
                        "kind": "conflict",
                        "conflicting": "vision",
                        "toward": "audition",
                        "away": "vision",
                        "delta": 0.1,
                        "extra": "x",
                    }
                ],
                "other": 5,
            },
        },
    }
    record = _workspace_metadata_record(snapshot)
    assert record["regulation_bias"] == {"source": "vision", "factor": 0.83}
    assert record["workspace_feedback"] == {
        "arm": "full",
        "gains": {"vision": 0.9, "audition": 1.1, "interoception": 1.0},
        "episodes": [
            {
                "kind": "conflict",
                "conflicting": "vision",
                "toward": "audition",
                "away": "vision",
                "delta": 0.1,
            }
        ],
    }
    assert "sequence_prediction" not in record

    empty = _workspace_metadata_record({"tick_index": 2})
    assert "regulation_bias" not in empty
    assert "workspace_feedback" not in empty


def test_sleep_completed_link_counts():
    obs = ResearchEventObserver(FakeBus(), FakeSink())
    ev = Event(
        source="sleep",
        type="sleep.sleep.completed",
        payload={
            "phases_completed": ["merge"],
            "memory_links_pruned": 3,
            "memory_nodes_pruned": 1,
        },
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    record = obs._build_record(ev)
    assert record["memory_links_pruned"] == 3
    assert record["memory_nodes_pruned"] == 1


def test_log_schema_ranges():
    assert _bound_for("affect.goal", "likelihood") == UNIT
    assert _bound_for("affect.goal", "priority") == UNIT
    assert _bound_for("affect.regulation", "tier") == (1.0, 3.0)
    assert _bound_for("affect.regulation", "intensity") == UNIT
    assert _bound_for("affect.emotion", "obstruction") == NONNEG
    assert _bound_for("sleep.sleep.completed", "memory_links_pruned") == NONNEG
    assert _bound_for("sleep.sleep.completed", "memory_nodes_pruned") == NONNEG
