# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for affect & memory honesty fixes (audit batch affect-memory-honesty).

Covers findings:
  H2 — thymos.emotion carries norm_compatibility_available=False
  H3 — audition.emotion carries degraded=True when model absent
  L2 — empatheia skips fold on degraded emotion events
  M3 — thymos PassiveDecay no-op is visible (first-use debug log)
  M4 — thymos.emotion carries goal_significance_method; no-goals guard
  M7 — mnemos recall surfaces StorageError instead of fake empty result
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.audition import (
    CATEGORIES,
    Audition,
    EmotionResult,
    FakeEmotionClassifier,
    FakeSTTClient,
)
from kaine.modules.empatheia.module import Empatheia
from kaine.modules.empatheia.store import InMemoryAgentStore
from kaine.modules.mnemos import (
    FakeEmbedder,
    InMemoryStorage,
    Mnemos,
    MnemosCore,
    StorageError,
)
from kaine.modules.thymos import Thymos
from kaine.modules.thymos.goals import GoalLedger
from kaine.modules.thymos.regulation import PassiveDecay
from kaine.modules.thymos.state import DimensionalState


# ---------------------------------------------------------------------------
# Shared fixtures
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


# ---------------------------------------------------------------------------
# H2 — thymos.emotion event carries norm_compatibility_available=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thymos_emotion_carries_norm_unavailable_flag(bus: AsyncBus):
    """thymos.emotion event must signal that norm_compatibility is not a real reading."""
    fake_now = [0.0]
    thymos = Thymos(bus, publish_interval_s=5.0, clock=lambda: fake_now[0])
    await thymos.initialize()
    try:
        # Add a goal so goal_significance can become non-zero → emotion change fires.
        thymos.goals.add("explore", priority=1.0)
        await thymos.on_workspace(
            _snapshot([_ev(salience=0.9, type_="explore_event")])
        )
        entries = await bus.read("thymos.out", last_id="0", count=20)
        emotion_events = [e for _, e in entries if e.type == "thymos.emotion"]
        assert emotion_events, "expected at least one thymos.emotion event"
        ev = emotion_events[0]
        assert ev.payload.get("norm_compatibility_available") is False, (
            "thymos.emotion must carry norm_compatibility_available=False "
            "until Eidolon norm signals are wired"
        )
    finally:
        await thymos.shutdown()


# ---------------------------------------------------------------------------
# M4 — thymos.emotion event carries goal_significance_method tag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thymos_emotion_carries_goal_significance_method(bus: AsyncBus):
    """thymos.emotion must carry goal_significance_method to disclose proxy."""
    fake_now = [0.0]
    thymos = Thymos(bus, publish_interval_s=5.0, clock=lambda: fake_now[0])
    await thymos.initialize()
    try:
        thymos.goals.add("navigate", priority=1.0)
        await thymos.on_workspace(
            _snapshot([_ev(salience=0.9, type_="navigate_event")])
        )
        entries = await bus.read("thymos.out", last_id="0", count=20)
        emotion_events = [e for _, e in entries if e.type == "thymos.emotion"]
        assert emotion_events, "expected at least one thymos.emotion event"
        ev = emotion_events[0]
        assert ev.payload.get("goal_significance_method") == "token_overlap_v1", (
            "thymos.emotion must disclose goal_significance is a token-overlap proxy"
        )
    finally:
        await thymos.shutdown()


# ---------------------------------------------------------------------------
# M4 — goals.relevance returns 0.0 when no goals registered
# ---------------------------------------------------------------------------


def test_goal_relevance_returns_zero_when_no_goals():
    """GoalLedger.relevance must return 0.0 (not a spurious positive) with no goals."""
    ledger = GoalLedger()
    assert ledger.relevance("some interesting event text") == 0.0


def test_goal_relevance_returns_zero_after_all_goals_completed():
    """After all goals complete, relevance must return 0.0 (no spurious noise)."""
    ledger = GoalLedger()
    g = ledger.add("explore the corridor", priority=1.0)
    ledger.complete(g.id)
    assert ledger.relevance("explore the corridor") == 0.0


# ---------------------------------------------------------------------------
# M3 — PassiveDecay logs once on first call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_passive_decay_logs_on_first_use(caplog):
    """PassiveDecay must emit a debug/info log on first suggest() call."""
    import logging
    policy = PassiveDecay()
    state = DimensionalState()
    with caplog.at_level(logging.DEBUG, logger="kaine.modules.thymos.regulation"):
        await policy.suggest(state)
    assert any(
        "PassiveDecay" in r.message or "passive" in r.message.lower()
        for r in caplog.records
    ), "PassiveDecay must log something on first use to make the no-op visible"


@pytest.mark.asyncio
async def test_passive_decay_logs_only_once(caplog):
    """PassiveDecay must not spam the log — one message, then silence."""
    import logging
    policy = PassiveDecay()
    state = DimensionalState()
    with caplog.at_level(logging.DEBUG, logger="kaine.modules.thymos.regulation"):
        await policy.suggest(state)
        await policy.suggest(state)
        await policy.suggest(state)
    regulation_records = [
        r for r in caplog.records
        if r.name.startswith("kaine.modules.thymos.regulation")
    ]
    assert len(regulation_records) == 1, (
        "PassiveDecay must log exactly once, not on every tick"
    )


# ---------------------------------------------------------------------------
# H3 — audition.emotion carries degraded=True when model absent
# ---------------------------------------------------------------------------


class DegradedEmotionClassifier(FakeEmotionClassifier):
    """Simulates the funasr-unavailable path: returns a degraded EmotionResult."""

    async def classify(self, audio_bytes: bytes, *, sample_rate: int) -> EmotionResult:
        return EmotionResult(
            category="neutral",
            confidence=0.0,
            scores={c: (1.0 if c == "neutral" else 0.0) for c in CATEGORIES},
            model=self.model_id,
            latency_ms=0.0,
            raw={"degraded": True},
        )


@pytest.mark.asyncio
async def test_audition_emotion_carries_degraded_flag(bus: AsyncBus):
    """When emotion model is absent/degraded, audition.emotion must carry degraded=True."""
    audition = Audition(
        bus,
        stt_client=FakeSTTClient(responses=["hello"]),
        emotion_classifier=DegradedEmotionClassifier(),
        stt_model="fake-stt",
    )
    await audition.initialize()
    try:
        await audition.process_audio(b"\x00" * 512, sample_rate=16000)
        entries = await bus.read("audition.out", last_id="0", count=10)
        emo = next(e for _, e in entries if e.type == "audition.emotion")
        assert emo.payload.get("degraded") is True, (
            "audition.emotion must carry degraded=True when emotion model did not run"
        )
    finally:
        await audition.shutdown()


@pytest.mark.asyncio
async def test_audition_emotion_no_degraded_flag_when_model_runs(bus: AsyncBus):
    """Normal (non-degraded) emotion result must NOT carry the degraded flag."""
    audition = Audition(
        bus,
        stt_client=FakeSTTClient(responses=["hello"]),
        emotion_classifier=FakeEmotionClassifier(),
        stt_model="fake-stt",
    )
    await audition.initialize()
    try:
        await audition.process_audio(b"\x00" * 512, sample_rate=16000)
        entries = await bus.read("audition.out", last_id="0", count=10)
        emo = next(e for _, e in entries if e.type == "audition.emotion")
        assert not emo.payload.get("degraded"), (
            "non-degraded emotion event must not carry degraded flag"
        )
    finally:
        await audition.shutdown()


# ---------------------------------------------------------------------------
# L2 — empatheia skips fold on degraded emotion events
# ---------------------------------------------------------------------------


def _emotion_event(
    category: str = "happy",
    confidence: float = 0.8,
    degraded: bool = False,
    source_label: str = "operator",
) -> Event:
    payload: dict[str, Any] = {
        "category": category,
        "confidence": confidence,
        "scores": {c: (1.0 if c == category else 0.0) for c in CATEGORIES},
        "model": "emotion2vec/emotion2vec_plus_base",
        "source_label": source_label,
        "latency_ms": 50.0,
        "prediction_error": 0.0,
    }
    if degraded:
        payload["degraded"] = True
    return Event(
        source="audition",
        type="audition.emotion",
        payload=payload,
        salience=0.4,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_empatheia_skips_degraded_emotion_fold(bus: AsyncBus):
    """Empatheia must not fold interaction when emotion event is degraded."""
    store = InMemoryAgentStore()
    emp = Empatheia(bus, store=store)
    await emp.initialize()
    try:
        # Send a degraded event — interaction_count must stay 0.
        degraded_ev = _emotion_event(degraded=True)
        await emp._handle_emotion(degraded_ev)

        model = await store.get(emp._speaker_label)
        assert model is None or model.interaction_count == 0, (
            "Empatheia must not count a degraded emotion fold as an interaction"
        )
    finally:
        await emp.shutdown()


@pytest.mark.asyncio
async def test_empatheia_folds_real_emotion_event(bus: AsyncBus):
    """Empatheia must still fold a non-degraded emotion event."""
    store = InMemoryAgentStore()
    emp = Empatheia(bus, store=store)
    await emp.initialize()
    try:
        real_ev = _emotion_event(category="happy", confidence=0.8, degraded=False)
        await emp._handle_emotion(real_ev)

        model = await store.get(emp._speaker_label)
        assert model is not None and model.interaction_count >= 1, (
            "Empatheia must fold a real (non-degraded) emotion event"
        )
    finally:
        await emp.shutdown()


# ---------------------------------------------------------------------------
# M7 — mnemos recall surfaces StorageError (not fake empty result)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mnemos_recall_publishes_error_on_storage_failure(bus: AsyncBus):
    """mnemos.recall event must carry error=True on StorageError, not fake count=0."""
    class FailingStorage(InMemoryStorage):
        async def search(self, collection, *, query_vector, limit):
            raise StorageError("simulated qdrant failure")

    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = FailingStorage(latent_dim=8)
    core = MnemosCore(embedder=emb, storage=storage, short_term_capacity=4)
    mnemos = Mnemos(bus, core=core)
    await mnemos.initialize()
    try:
        results = await mnemos.recall("test query")
        # Should return [] (graceful return) but publish error=True
        assert results == []
        entries = await bus.read("mnemos.out", last_id="0", count=10)
        recall_events = [e for _, e in entries if e.type == "mnemos.recall"]
        assert recall_events, "mnemos.recall event must still be published on error"
        ev = recall_events[0]
        assert ev.payload.get("error") is True, (
            "mnemos.recall must carry error=True when storage fails, "
            "not silently publish count=0 as if the search succeeded"
        )
    finally:
        await mnemos.shutdown()


@pytest.mark.asyncio
async def test_mnemos_recall_no_error_flag_on_success(bus: AsyncBus):
    """Successful mnemos.recall must not carry error flag."""
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = InMemoryStorage(latent_dim=8)
    core = MnemosCore(embedder=emb, storage=storage, short_term_capacity=4)
    mnemos = Mnemos(bus, core=core)
    await mnemos.initialize()
    try:
        await mnemos.recall("test query")
        entries = await bus.read("mnemos.out", last_id="0", count=10)
        recall_events = [e for _, e in entries if e.type == "mnemos.recall"]
        assert recall_events
        ev = recall_events[0]
        assert not ev.payload.get("error"), (
            "successful mnemos.recall must not carry error flag"
        )
    finally:
        await mnemos.shutdown()


@pytest.mark.asyncio
async def test_storage_error_is_raised_by_qdrant_search():
    """QdrantStorage.search must raise StorageError (not return []) on backend failure."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from kaine.modules.mnemos.storage import QdrantStorage

    storage = QdrantStorage.__new__(QdrantStorage)
    storage._latent_dim = 8
    # Simulate the qdrant client raising on query_points.
    mock_client = AsyncMock()
    mock_client.query_points.side_effect = RuntimeError("connection refused")
    storage._client = mock_client

    with pytest.raises(StorageError, match="qdrant search failed"):
        await storage.search("col", query_vector=[0.0] * 8, limit=5)
