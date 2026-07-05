# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Perceived-emotion decay + boundedness (thymos-emergent-affect-coupling).

WELFARE-LOAD-BEARING.

The perceived-emotion signal is appraisal-routed, transient, and decaying:
- Its appraisal contribution decays to zero over ``decay_s``; once the signal
  is stale it contributes nothing and the existing drift returns the state
  toward baseline.
- Because it flows through appraisal (a small, bounded contribution) and the
  existing appraisal→state nudge + drift/hysteresis apply, sustained extreme
  perceived emotion cannot pin the dimensional state at a boundary.

This replaces the removed DriftSafeguard rolling-rate-cap tests: there is no
longer any direct write to cap; boundedness comes from the appraisal-weight
clamp and the decay window.
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


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _emotion_event(category: str) -> Event:
    categories = ["neutral", "happy", "sad", "angry", "surprised", "fearful", "disgusted"]
    return Event(
        source="audition",
        type="audition.emotion",
        payload={
            "category": category,
            "confidence": 1.0,
            "scores": {c: (1.0 if c == category else 0.0) for c in categories},
            "model": "test",
            "source_label": "mic",
            "latency_ms": 1.0,
        },
        salience=1.0,
        timestamp=datetime.now(timezone.utc),
    )


def _empty_snapshot() -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=0, selected_events=[], inhibited=False)


@pytest.mark.asyncio
async def test_perceived_contribution_decays_to_zero(bus: AsyncBus):
    """The perceived-emotion appraisal contribution decays to zero after decay_s."""
    fake_now = [0.0]
    cfg = CouplingConfig(
        enabled=True,
        coupling_base=0.20,
        coupling_familiarity_gain=0.0,
        coupling_ceiling=0.30,
        decay_s=10.0,
    )
    thymos = Thymos(bus, coupling=cfg, clock=lambda: fake_now[0], publish_interval_s=999.0)
    snap = _empty_snapshot()
    baseline_pleas = thymos._score_snapshot(snap).intrinsic_pleasantness

    # Record at t=0.
    fake_now[0] = 0.0
    thymos._record_perceived_emotion(_emotion_event("happy"))

    # Fresh: contributes.
    fresh_pleas = thymos._score_snapshot(snap).intrinsic_pleasantness
    assert fresh_pleas > baseline_pleas

    # Halfway through decay window: smaller but still positive contribution.
    fake_now[0] = 5.0
    half_pleas = thymos._score_snapshot(snap).intrinsic_pleasantness
    assert baseline_pleas < half_pleas < fresh_pleas

    # At/after decay_s: contribution is exactly zero.
    fake_now[0] = 10.0
    stale_pleas = thymos._score_snapshot(snap).intrinsic_pleasantness
    assert stale_pleas == pytest.approx(baseline_pleas)

    fake_now[0] = 20.0
    older_pleas = thymos._score_snapshot(snap).intrinsic_pleasantness
    assert older_pleas == pytest.approx(baseline_pleas)


@pytest.mark.asyncio
async def test_state_returns_toward_baseline_after_decay(bus: AsyncBus):
    """Once the signal decays, drift returns the dimensional state toward baseline."""
    fake_now = [0.0]
    cfg = CouplingConfig(
        enabled=True,
        coupling_base=0.30,
        coupling_familiarity_gain=0.0,
        coupling_ceiling=0.30,
        decay_s=10.0,
    )
    baseline = DimensionalState(valence=0.0, arousal=0.3, dominance=0.0)
    thymos = Thymos(
        bus,
        baseline=baseline,
        coupling=cfg,
        clock=lambda: fake_now[0],
        drift_rate_per_s=0.10,
        publish_interval_s=999.0,
    )

    # Sustained joy for 10 s of ticks (1 Hz) — appraisal-routed.
    for i in range(10):
        fake_now[0] = float(i)
        thymos._record_perceived_emotion(_emotion_event("happy"))
        await thymos.on_workspace(_empty_snapshot())

    valence_under_input = thymos.state.valence
    # WELFARE: appraisal-routed input must not pin the state at the boundary.
    assert valence_under_input < 1.0, (
        f"State pinned at boundary under sustained perceived joy: "
        f"valence={valence_under_input:.4f}"
    )
    assert valence_under_input > baseline.valence  # it did move up some

    # Input stops; signal goes stale (past decay_s) and drift recovers.
    for tick in range(60):
        fake_now[0] = 10.0 + float(tick + 1)
        await thymos.on_workspace(_empty_snapshot())

    valence_after = thymos.state.valence
    assert valence_after < valence_under_input, (
        f"Drift did not recover after the perceived signal decayed: "
        f"under_input={valence_under_input:.4f}, after={valence_after:.4f}"
    )
    # Recovered close to baseline.
    assert valence_after <= baseline.valence + 0.1


@pytest.mark.asyncio
async def test_sustained_input_does_not_pin_state(bus: AsyncBus):
    """WELFARE: sustained high-frequency extreme perceived emotion cannot pin state.

    With a synthetic clock the signal is always "fresh" but the contribution is
    bounded by the appraisal-weight clamp and the appraisal→state nudge is small;
    drift/hysteresis keep the state off the boundary.
    """
    fake_now = [0.0]
    cfg = CouplingConfig(
        enabled=True,
        coupling_base=0.30,
        coupling_familiarity_gain=0.0,
        coupling_ceiling=0.30,
        decay_s=10.0,
    )
    thymos = Thymos(
        bus,
        coupling=cfg,
        clock=lambda: fake_now[0],
        drift_rate_per_s=0.05,
        publish_interval_s=999.0,
    )
    thymos._state = DimensionalState(valence=0.0, arousal=0.3, dominance=0.0)

    dt = 1.0 / 3.33
    for i in range(33):
        fake_now[0] = i * dt
        thymos._record_perceived_emotion(_emotion_event("happy"))
        await thymos.on_workspace(_empty_snapshot())

    assert thymos.state.valence < 1.0, (
        f"State pinned at boundary under 33 perceived-joy events: "
        f"valence={thymos.state.valence:.4f}"
    )
