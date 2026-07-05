# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for Empatheia(BaseModule) — event-driven behavior with fakeredis."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.modules.empatheia.agent import AgentModel, EMOTION_CATEGORIES
from kaine.modules.empatheia.module import Empatheia
from kaine.modules.empatheia.store import InMemoryAgentStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _emotion_event(
    category: str = "happy",
    confidence: float = 0.8,
    prediction_error: float = 0.0,
    source_label: str = "operator",
) -> Event:
    return Event(
        source="audition",
        type="audition.emotion",
        payload={
            "category": category,
            "confidence": confidence,
            "scores": {c: (1.0 if c == category else 0.0) for c in EMOTION_CATEGORIES},
            "model": "emotion2vec/emotion2vec_plus_base",
            "source_label": source_label,
            "latency_ms": 50.0,
            "prediction_error": prediction_error,
        },
        salience=0.4,
        timestamp=datetime.now(timezone.utc),
    )


def _transcription_event(source_label: str = "operator") -> Event:
    return Event(
        source="audition",
        type="audition.transcription",
        payload={
            "text": "hello world",
            "source_label": source_label,
            "model": "whisper",
            "sample_rate": 16000,
            "audio_bytes_length": 1024,
            "latency_ms": 100.0,
            "prediction_error": 0.0,
        },
        salience=0.4,
        timestamp=datetime.now(timezone.utc),
    )


async def _new_empatheia(bus: AsyncBus, **kwargs) -> Empatheia:
    store = InMemoryAgentStore()
    emp = Empatheia(
        bus,
        store=store,
        deviation_threshold=kwargs.pop("deviation_threshold", 0.5),
        **kwargs,
    )
    return emp


async def _drain_events(bus: AsyncBus, stream: str) -> list[Event]:
    entries = await bus.read(stream, last_id="0")
    return [e for _, e in entries]


# ---------------------------------------------------------------------------
# Emotion events update agent model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emotion_event_updates_agent_model(bus: AsyncBus):
    emp = await _new_empatheia(bus)
    await emp.initialize()
    try:
        event = _emotion_event("happy", confidence=0.9)
        await emp._handle_audition_event(event)
        model = await emp.store.get("operator")
        assert model is not None
        assert model.interaction_count == 1
        assert model.emotion_histogram.get("happy", 0.0) > 0.0
    finally:
        await emp.shutdown()


@pytest.mark.asyncio
async def test_multiple_emotion_events_accumulate(bus: AsyncBus):
    emp = await _new_empatheia(bus)
    await emp.initialize()
    try:
        for cat in ["happy", "sad", "neutral"]:
            await emp._handle_audition_event(_emotion_event(cat, confidence=0.7))
        model = await emp.store.get("operator")
        assert model is not None
        assert model.interaction_count == 3
    finally:
        await emp.shutdown()


# ---------------------------------------------------------------------------
# empatheia.agent_model published with familiarity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emotion_event_publishes_agent_model(bus: AsyncBus):
    emp = await _new_empatheia(bus)
    await emp.initialize()
    try:
        await emp._handle_audition_event(_emotion_event("happy", confidence=0.8))
        events = await _drain_events(bus, "empatheia.out")
        agent_model_events = [e for e in events if e.type == "empatheia.agent_model"]
        assert len(agent_model_events) >= 1
        payload = agent_model_events[-1].payload
        assert "familiarity" in payload
        assert isinstance(payload["familiarity"], float)
        assert 0.0 <= payload["familiarity"] <= 1.0
        assert "interaction_count" in payload
        assert "reliability" in payload
        assert "agent_id" in payload
    finally:
        await emp.shutdown()


@pytest.mark.asyncio
async def test_agent_model_familiarity_increases_with_observations(bus: AsyncBus):
    emp = await _new_empatheia(bus)
    await emp.initialize()
    try:
        await emp._handle_audition_event(_emotion_event("happy", confidence=0.8))
        events_1 = await _drain_events(bus, "empatheia.out")
        fam_1 = next(
            e.payload["familiarity"]
            for e in events_1
            if e.type == "empatheia.agent_model"
        )
        for _ in range(50):
            await emp._handle_audition_event(_emotion_event("happy", confidence=0.8))
        events_many = await _drain_events(bus, "empatheia.out")
        fam_many = max(
            e.payload["familiarity"]
            for e in events_many
            if e.type == "empatheia.agent_model"
        )
        assert fam_many > fam_1
    finally:
        await emp.shutdown()


# ---------------------------------------------------------------------------
# Transcription events update model
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_transcription_event_updates_interaction_count(bus: AsyncBus):
    emp = await _new_empatheia(bus)
    await emp.initialize()
    try:
        await emp._handle_audition_event(_transcription_event())
        model = await emp.store.get("operator")
        assert model is not None
        assert model.interaction_count == 1
    finally:
        await emp.shutdown()


# ---------------------------------------------------------------------------
# Deviation emits empatheia.social_error with ONLY id/salience/deviation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_deviation_emits_social_error(bus: AsyncBus):
    """An out-of-character emotion triggers empatheia.social_error."""
    emp = await _new_empatheia(bus, deviation_threshold=0.1)
    await emp.initialize()
    try:
        # Build a "neutral" baseline model.
        for _ in range(10):
            await emp._handle_audition_event(_emotion_event("neutral", confidence=1.0))

        # Clear the stream so we can see only new events.
        # (fakeredis keeps all entries; we'll read after this point)
        # Record current position.
        entries_before = await bus.read("empatheia.out", last_id="0")
        last_id = entries_before[-1][0] if entries_before else "0"

        # Trigger a sharp out-of-character event.
        await emp._handle_audition_event(_emotion_event("angry", confidence=1.0))

        new_entries = await bus.read("empatheia.out", last_id=last_id)
        new_events = [e for _, e in new_entries]
        social_errors = [e for e in new_events if e.type == "empatheia.social_error"]
        assert len(social_errors) >= 1
    finally:
        await emp.shutdown()


@pytest.mark.asyncio
async def test_social_error_payload_contains_only_allowed_fields(bus: AsyncBus):
    """empatheia.social_error payload must carry ONLY id/salience/deviation."""
    emp = await _new_empatheia(bus, deviation_threshold=0.1)
    await emp.initialize()
    try:
        # Build baseline then trigger sharp deviation.
        for _ in range(10):
            await emp._handle_audition_event(_emotion_event("neutral", confidence=1.0))
        await emp._handle_audition_event(_emotion_event("angry", confidence=1.0))

        events = await _drain_events(bus, "empatheia.out")
        social_errors = [e for e in events if e.type == "empatheia.social_error"]
        assert len(social_errors) >= 1

        for se in social_errors:
            payload_keys = set(se.payload.keys())
            # Allowed keys only.
            allowed = {"agent_id", "agent_label", "salience", "deviation_magnitude"}
            disallowed = payload_keys - allowed
            assert not disallowed, (
                f"social_error payload contains disallowed keys: {disallowed}"
            )
            # Must contain all three required fields.
            assert "agent_id" in se.payload
            assert "salience" in se.payload
            assert "deviation_magnitude" in se.payload
            # No raw behavioral data.
            for key in payload_keys:
                value = se.payload[key]
                if isinstance(value, str):
                    # agent_label is allowed; ensure it's just the label, not transcript
                    assert key in {"agent_id", "agent_label"}, (
                        f"unexpected string field {key!r} in social_error payload"
                    )
    finally:
        await emp.shutdown()


@pytest.mark.asyncio
async def test_social_error_enters_workspace_with_declared_salience(bus: AsyncBus):
    """empatheia.social_error must be published with a numeric salience."""
    emp = await _new_empatheia(bus, deviation_threshold=0.1)
    await emp.initialize()
    try:
        for _ in range(10):
            await emp._handle_audition_event(_emotion_event("neutral", confidence=1.0))
        await emp._handle_audition_event(_emotion_event("angry", confidence=1.0))

        events = await _drain_events(bus, "empatheia.out")
        social_errors = [e for e in events if e.type == "empatheia.social_error"]
        assert len(social_errors) >= 1
        for se in social_errors:
            assert isinstance(se.salience, float)
            assert 0.0 <= se.salience <= 1.0
            # Salience on the event should match the payload field.
            assert se.salience == pytest.approx(se.payload["salience"])
    finally:
        await emp.shutdown()


@pytest.mark.asyncio
async def test_in_character_behavior_does_not_emit_social_error(bus: AsyncBus):
    """Consistent behavior should NOT produce social_error events once the model
    is established (deviation_threshold=0.99 so only truly shocking events would
    count — completely consistent behavior emits no social_error at all)."""
    # Use a very high deviation_threshold so that consistent observations
    # never trigger social_error regardless of model warm-up state.
    emp = await _new_empatheia(bus, deviation_threshold=0.99)
    await emp.initialize()
    try:
        for _ in range(20):
            await emp._handle_audition_event(_emotion_event("neutral", confidence=0.5))

        events = await _drain_events(bus, "empatheia.out")
        social_errors = [e for e in events if e.type == "empatheia.social_error"]
        assert social_errors == []
    finally:
        await emp.shutdown()


# ---------------------------------------------------------------------------
# Fork/merge (serialize/deserialize)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_serialize_deserialize_preserves_agent_model(bus: AsyncBus):
    emp = await _new_empatheia(bus)
    await emp.initialize()
    try:
        for _ in range(5):
            await emp._handle_audition_event(_emotion_event("happy", confidence=0.8))
        state = emp.serialize()
        assert "profiles" in state
        assert "operator" in state["profiles"]

        emp2 = await _new_empatheia(bus)
        await emp2.initialize()
        emp2.deserialize(state)
        model = await emp2.store.get("operator")
        assert model is not None
        assert model.interaction_count == 5
    finally:
        await emp.shutdown()
