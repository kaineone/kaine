# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Familiarity cache persistence tests — task 5.3.

Covers:
- Familiarity cache round-trips through serialize/deserialize.
- Coupling uses cached values on the next event after deserialize.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.thymos import Thymos
from kaine.modules.thymos.coupling import CouplingConfig
from kaine.modules.thymos.state import DimensionalState


def _empty_snapshot() -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=0, selected_events=[], inhibited=False)


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _emotion_event(category: str, source_label: str = "agent_a") -> Event:
    categories = ["neutral", "happy", "sad", "angry", "surprised", "fearful", "disgusted"]
    return Event(
        source="audition",
        type="audition.emotion",
        payload={
            "category": category,
            "confidence": 0.9,
            "scores": {c: (0.9 if c == category else 0.0) for c in categories},
            "model": "test",
            "source_label": source_label,
            "latency_ms": 1.0,
        },
        salience=0.8,
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Scenario: Cache survives a serialize/deserialize round-trip
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_familiarity_cache_survives_round_trip(bus: AsyncBus):
    """Non-empty familiarity cache is present after serialize + deserialize."""
    cfg = CouplingConfig(enabled=True)
    thymos = Thymos(bus, coupling=cfg, publish_interval_s=999.0)

    # Seed cache with two agents.
    thymos._familiarity_cache["agent_a"] = 0.75
    thymos._familiarity_cache["agent_b"] = 0.30

    snapshot = thymos.serialize()

    # Verify the key is in the snapshot and holds the right values.
    assert "familiarity_cache" in snapshot
    assert snapshot["familiarity_cache"]["agent_a"] == pytest.approx(0.75)
    assert snapshot["familiarity_cache"]["agent_b"] == pytest.approx(0.30)

    # Restore into a fresh instance.
    thymos2 = Thymos(bus, coupling=cfg, publish_interval_s=999.0)
    assert thymos2._familiarity_cache == {}  # cold start

    thymos2.deserialize(snapshot)

    assert thymos2._familiarity_cache.get("agent_a") == pytest.approx(0.75)
    assert thymos2._familiarity_cache.get("agent_b") == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_coupling_uses_restored_familiarity_on_next_event(bus: AsyncBus):
    """After deserialize, the restored familiarity yields a larger appraisal contribution."""
    coupling_base = 0.05
    familiarity_gain = 0.20
    ceiling = 1.0
    high_familiarity = 0.9

    cfg = CouplingConfig(
        enabled=True,
        coupling_base=coupling_base,
        coupling_familiarity_gain=familiarity_gain,
        coupling_ceiling=ceiling,
        decay_s=10.0,
    )

    # Build and serialize with high familiarity.
    original = Thymos(bus, coupling=cfg, publish_interval_s=999.0)
    original._familiarity_cache["mic"] = high_familiarity
    snapshot = original.serialize()

    # Restore.
    restored = Thymos(bus, coupling=cfg, publish_interval_s=999.0)
    restored.deserialize(snapshot)

    # Also build a cold instance (no familiarity) for comparison.
    cold = Thymos(bus, coupling=cfg, publish_interval_s=999.0)

    snap = _empty_snapshot()
    event = _emotion_event("happy", source_label="mic")

    restored_base = restored._score_snapshot(snap).intrinsic_pleasantness
    restored._record_perceived_emotion(event)
    restored_contrib = restored._score_snapshot(snap).intrinsic_pleasantness - restored_base

    cold_base = cold._score_snapshot(snap).intrinsic_pleasantness
    cold._record_perceived_emotion(event)
    cold_contrib = cold._score_snapshot(snap).intrinsic_pleasantness - cold_base

    # Restored should use high familiarity → larger appraisal contribution.
    assert restored_contrib > cold_contrib, (
        f"Restored familiarity should give a larger appraisal contribution: "
        f"restored={restored_contrib:.4f}, cold={cold_contrib:.4f}"
    )


@pytest.mark.asyncio
async def test_empty_familiarity_cache_survives_round_trip(bus: AsyncBus):
    """An empty familiarity cache also round-trips cleanly."""
    cfg = CouplingConfig(enabled=True)
    thymos = Thymos(bus, coupling=cfg, publish_interval_s=999.0)
    assert thymos._familiarity_cache == {}

    snapshot = thymos.serialize()
    assert snapshot["familiarity_cache"] == {}

    fresh = Thymos(bus, coupling=cfg, publish_interval_s=999.0)
    fresh.deserialize(snapshot)
    assert fresh._familiarity_cache == {}


@pytest.mark.asyncio
async def test_deserialize_ignores_non_numeric_familiarity_values(bus: AsyncBus):
    """Malformed familiarity values in a snapshot are silently dropped."""
    cfg = CouplingConfig(enabled=True)
    thymos = Thymos(bus, coupling=cfg, publish_interval_s=999.0)
    thymos.deserialize({
        "familiarity_cache": {
            "good_agent": 0.5,
            "bad_agent": "not_a_number",
            "none_agent": None,
        }
    })
    assert "good_agent" in thymos._familiarity_cache
    assert thymos._familiarity_cache["good_agent"] == pytest.approx(0.5)
    assert "bad_agent" not in thymos._familiarity_cache
    assert "none_agent" not in thymos._familiarity_cache


@pytest.mark.asyncio
async def test_full_serialize_still_includes_pre_existing_keys(bus: AsyncBus):
    """serialize() still includes state/baseline/drives/last_emotion keys."""
    cfg = CouplingConfig(enabled=True)
    thymos = Thymos(bus, coupling=cfg, publish_interval_s=999.0)
    thymos._state = DimensionalState(valence=0.4, arousal=0.5, dominance=-0.2)
    thymos._familiarity_cache["x"] = 0.1

    snap = thymos.serialize()

    assert "state" in snap
    assert "baseline" in snap
    assert "drives" in snap
    assert "last_emotion" in snap
    assert "familiarity_cache" in snap
    assert snap["state"]["valence"] == pytest.approx(0.4)
