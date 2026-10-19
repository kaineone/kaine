# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Regression tests for the affect-related research log allowlist.

These tests verify that the new valence-target terms in affect.state payloads
are preserved in privacy-filtered research records, that unknown keys are still
dropped, and that the corresponding log_schema ranges exist.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.evaluation.observers.research_event_observer import ResearchEventObserver
from kaine.experiment.log_schema import NONNEG, SIGNED_UNIT, UNIT, _bound_for
from kaine.modules.affect import Affect
from tests.test_research_event_log import FakeBus, FakeSink

fakeredis_aioredis = pytest.importorskip("fakeredis.aioredis")


TERM_KEYS = (
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
)


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


async def _read_affect_events(bus):
    entries = await bus.read("affect.out", last_id="0", count=500)
    return [event for _, event in entries]


async def test_periodic_state_record_keeps_every_key(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    now = datetime.now(timezone.utc)

    await affect._handle_peer_event(
        "vision.out",
        Event(
            source="vision",
            type="vision.report",
            payload={"alert": False, "prediction_error": 1.0},
            salience=0.5,
            timestamp=now,
        ),
    )

    t[0] = 5.0
    await affect._handle_peer_event(
        "vision.out",
        Event(
            source="vision",
            type="vision.report",
            payload={"alert": False, "prediction_error": 0.5},
            salience=0.5,
            timestamp=now,
        ),
    )
    await affect._handle_peer_event(
        "interoception.out",
        Event(
            source="interoception",
            type="interoception.report",
            payload={"wellness": 0.8, "alerts": []},
            salience=0.5,
            timestamp=now,
        ),
    )
    await affect._maybe_publish_state()

    observer = ResearchEventObserver(FakeBus(), FakeSink())
    events = await _read_affect_events(bus)
    state_events = [
        ev for ev in events if ev.type == "affect.state" and not ev.payload.get("reset")
    ]
    assert state_events, "expected at least one periodic affect.state event"

    for ev in state_events:
        if "valence_target" not in ev.payload:
            pytest.fail("affect.state payload lacks the valence terms")
        record = observer._build_record(ev)
        assert record is not None
        for key, value in ev.payload.items():
            assert key in record, key
            assert record[key] == value


async def test_reset_state_record_keeps_terms(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0], publish_interval_s=1.0)
    now = datetime.now(timezone.utc)

    await affect._handle_peer_event(
        "vision.out",
        Event(
            source="vision",
            type="vision.report",
            payload={"alert": False, "prediction_error": 1.0},
            salience=0.5,
            timestamp=now,
        ),
    )

    t[0] = 5.0
    await affect._handle_peer_event(
        "vision.out",
        Event(
            source="vision",
            type="vision.report",
            payload={"alert": False, "prediction_error": 0.5},
            salience=0.5,
            timestamp=now,
        ),
    )
    await affect._handle_peer_event(
        "interoception.out",
        Event(
            source="interoception",
            type="interoception.report",
            payload={"wellness": 0.8, "alerts": []},
            salience=0.5,
            timestamp=now,
        ),
    )
    await affect.affective_reset()

    observer = ResearchEventObserver(FakeBus(), FakeSink())
    events = await _read_affect_events(bus)
    reset_events = [
        ev for ev in events if ev.type == "affect.state" and ev.payload.get("reset")
    ]
    assert reset_events, "expected an affect.state reset event"

    for ev in reset_events:
        if "valence_target" not in ev.payload:
            pytest.fail("affect.state payload lacks the valence terms")
        record = observer._build_record(ev)
        assert record is not None
        for key in TERM_KEYS:
            assert key in record, key
            assert record[key] == ev.payload[key]


async def test_null_values_kept():
    payload = {
        "state": {"valence": 0.0, "arousal": 0.5, "dominance": 0.0},
        "drives": {},
        "emotion": "neutral",
    }
    for key in TERM_KEYS:
        payload[key] = None if key.startswith("audition_") else 0.1

    ev = Event(
        source="affect",
        type="affect.state",
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    record = ResearchEventObserver(FakeBus(), FakeSink())._build_record(ev)
    assert record is not None
    for key in TERM_KEYS:
        assert key in record, key
        assert record[key] == payload[key]


async def test_unknown_key_still_dropped():
    payload = {
        "state": {"valence": 0.0, "arousal": 0.5, "dominance": 0.0},
        "drives": {},
        "emotion": "neutral",
        "audition_text": "hello",
    }
    ev = Event(
        source="affect",
        type="affect.state",
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    record = ResearchEventObserver(FakeBus(), FakeSink())._build_record(ev)
    assert record is not None
    assert "audition_text" not in record


def test_log_schema_bounds():
    nonneg = {
        "vision_error_fast",
        "vision_error_slow",
        "audition_error_fast",
        "audition_error_slow",
    }
    unit = {"learning_progress", "wellness", "wellness_fast", "wellness_slow"}
    signed = {
        "vision_progress",
        "vision_learning_progress",
        "audition_progress",
        "audition_learning_progress",
        "signed_progress",
        "signed_learning_progress",
        "wellness_change",
        "pleasantness",
        "valence_target",
    }
    for key in TERM_KEYS:
        bound = _bound_for("affect.state", key)
        if key in nonneg:
            assert bound == NONNEG, key
        elif key in unit:
            assert bound == UNIT, key
        elif key in signed:
            assert bound == SIGNED_UNIT, key
        else:
            raise AssertionError(f"unexpected term key {key}")
