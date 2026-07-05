# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for Thymos emergent affect coupling (thymos-emergent-affect-coupling).

A perceived speaker emotion (audition.emotion) is an INPUT to the entity's own
Scherer appraisal, weighted by familiarity and decayed by recency — never a
direct write to the dimensional (VAD) state. The existing appraisal→state nudge
produces the entity's response.

Covers:
- Perceived positive-valence emotion raises appraised intrinsic_pleasantness
  (and, downstream, valence) — only when enabled.
- Higher familiarity → strictly larger appraisal contribution.
- Disabled coupling → appraisal scores identical to no-signal AND no state change.
- No-Empatheia → base weight used.
- No code path writes the dimensional state toward EMOTION_VAD directly.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.thymos import Thymos
from kaine.modules.thymos.coupling import (
    EMOTION_VAD,
    CouplingConfig,
    compute_coupling,
)
from kaine.modules.thymos.state import DimensionalState


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _emotion_event(category: str, source_label: str = "mic") -> Event:
    return Event(
        source="audition",
        type="audition.emotion",
        payload={
            "category": category,
            "confidence": 0.9,
            "scores": {c: (0.9 if c == category else 0.0) for c in
                       ["neutral", "happy", "sad", "angry", "surprised", "fearful", "disgusted"]},
            "model": "test",
            "source_label": source_label,
            "latency_ms": 1.0,
        },
        salience=0.8,
        timestamp=datetime.now(timezone.utc),
    )


def _empty_snapshot() -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=0, selected_events=[], inhibited=False)


def _make_thymos_with_coupling(bus: AsyncBus, fake_now, **coupling_kwargs) -> Thymos:
    """Build a Thymos with coupling enabled at given settings + a synthetic clock."""
    cfg = CouplingConfig(enabled=True, **coupling_kwargs)
    return Thymos(
        bus,
        coupling=cfg,
        clock=lambda: fake_now[0],
        publish_interval_s=999.0,  # suppress automatic publish
    )


# ---------------------------------------------------------------------------
# Scenario: Perceived emotion is appraised, not imposed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_positive_emotion_raises_appraised_pleasantness(bus: AsyncBus):
    """audition.emotion(happy) raises appraised intrinsic_pleasantness vs. baseline."""
    fake_now = [0.0]
    thymos = _make_thymos_with_coupling(
        bus, fake_now,
        coupling_base=0.10,
        coupling_familiarity_gain=0.0,
        coupling_ceiling=0.20,
    )
    snap = _empty_snapshot()

    baseline_scores = thymos._score_snapshot(snap)

    thymos._record_perceived_emotion(_emotion_event("happy"))
    after_scores = thymos._score_snapshot(snap)

    assert after_scores.intrinsic_pleasantness > baseline_scores.intrinsic_pleasantness, (
        "Perceiving a positive-valence speaker must raise appraised pleasantness."
    )
    # happy carries positive arousal → novelty contribution non-negative too.
    assert after_scores.novelty >= baseline_scores.novelty


@pytest.mark.asyncio
async def test_positive_emotion_moves_valence_up_via_appraisal(bus: AsyncBus):
    """The entity's own appraisal→state path moves valence up after perceiving joy."""
    fake_now = [0.0]
    thymos = _make_thymos_with_coupling(
        bus, fake_now,
        coupling_base=0.15,
        coupling_familiarity_gain=0.0,
        coupling_ceiling=0.30,
    )
    # Disable drift so the appraisal nudge is the only mover for a clean assert.
    thymos._drift_rate = 0.0
    thymos._state = DimensionalState(valence=0.0, arousal=0.3, dominance=0.0)
    before_v = thymos.state.valence

    thymos._record_perceived_emotion(_emotion_event("happy"))
    await thymos.on_workspace(_empty_snapshot())

    assert thymos.state.valence > before_v, (
        f"Appraisal of a joyful other should move valence up via the appraisal "
        f"path; before={before_v:.4f}, after={thymos.state.valence:.4f}"
    )


@pytest.mark.asyncio
async def test_negative_emotion_lowers_appraised_pleasantness(bus: AsyncBus):
    """Perceiving a sad speaker lowers appraised intrinsic_pleasantness."""
    fake_now = [0.0]
    thymos = _make_thymos_with_coupling(
        bus, fake_now,
        coupling_base=0.15,
        coupling_familiarity_gain=0.0,
        coupling_ceiling=0.30,
    )
    snap = _empty_snapshot()
    baseline = thymos._score_snapshot(snap)

    thymos._record_perceived_emotion(_emotion_event("sad"))
    after = thymos._score_snapshot(snap)

    assert after.intrinsic_pleasantness < baseline.intrinsic_pleasantness


# ---------------------------------------------------------------------------
# Scenario: Higher familiarity appraises others' emotion as more significant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_higher_familiarity_gives_larger_contribution(bus: AsyncBus):
    """At familiarity 0.9 the appraisal contribution is strictly larger than at 0.2."""
    coupling_base = 0.05
    familiarity_gain = 0.20
    ceiling = 1.0  # no clamp so the comparison is clean

    # compute_coupling math: higher familiarity → larger weight.
    coeff_lo = compute_coupling(
        coupling_base=coupling_base,
        coupling_familiarity_gain=familiarity_gain,
        familiarity=0.2,
        coupling_ceiling=ceiling,
    )
    coeff_hi = compute_coupling(
        coupling_base=coupling_base,
        coupling_familiarity_gain=familiarity_gain,
        familiarity=0.9,
        coupling_ceiling=ceiling,
    )
    assert coeff_hi > coeff_lo

    def _pleasantness_contribution(familiarity: float) -> float:
        fake_now = [0.0]
        t = _make_thymos_with_coupling(
            bus, fake_now,
            coupling_base=coupling_base,
            coupling_familiarity_gain=familiarity_gain,
            coupling_ceiling=ceiling,
        )
        snap = _empty_snapshot()
        base = t._score_snapshot(snap).intrinsic_pleasantness
        t._familiarity_cache["mic"] = familiarity
        t._record_perceived_emotion(_emotion_event("happy", source_label="mic"))
        return t._score_snapshot(snap).intrinsic_pleasantness - base

    contrib_lo = _pleasantness_contribution(0.2)
    contrib_hi = _pleasantness_contribution(0.9)

    assert contrib_hi > contrib_lo, (
        f"Higher familiarity must yield a strictly larger appraisal contribution: "
        f"fam=0.9 ({contrib_hi:.4f}) should > fam=0.2 ({contrib_lo:.4f})"
    )


# ---------------------------------------------------------------------------
# Scenario: Disabled coupling does nothing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disabled_coupling_identical_appraisal_and_no_state_change(bus: AsyncBus):
    """Disabled coupling → appraisal identical to no-signal AND no state change."""
    fake_now = [0.0]
    cfg = CouplingConfig(enabled=False)
    thymos = Thymos(bus, coupling=cfg, clock=lambda: fake_now[0], publish_interval_s=999.0)
    snap = _empty_snapshot()

    baseline_scores = thymos._score_snapshot(snap)
    initial_state = thymos.state

    # Recording does nothing when disabled.
    thymos._record_perceived_emotion(_emotion_event("happy"))
    assert thymos._perceived_emotion is None

    after_scores = thymos._score_snapshot(snap)
    assert after_scores.as_tuple() == baseline_scores.as_tuple(), (
        "Disabled coupling must leave appraisal scores identical to no-signal."
    )
    assert thymos.state == initial_state, (
        "Disabled coupling must not change the dimensional state."
    )


# ---------------------------------------------------------------------------
# Scenario: No Empatheia → base weight
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_empatheia_uses_base_weight(bus: AsyncBus):
    """With no cached familiarity, the contribution uses coupling_base."""
    fake_now = [0.0]
    coupling_base = 0.08
    familiarity_gain = 0.20  # non-zero but unused without a cache entry
    thymos = _make_thymos_with_coupling(
        bus, fake_now,
        coupling_base=coupling_base,
        coupling_familiarity_gain=familiarity_gain,
        coupling_ceiling=1.0,
    )
    assert len(thymos._familiarity_cache) == 0

    thymos._record_perceived_emotion(_emotion_event("happy", source_label="unknown"))

    expected_weight = compute_coupling(
        coupling_base=coupling_base,
        coupling_familiarity_gain=familiarity_gain,
        familiarity=0.0,  # no cache → 0.0
        coupling_ceiling=1.0,
    )
    assert thymos._perceived_emotion is not None
    assert thymos._perceived_emotion["weight"] == pytest.approx(expected_weight)
    assert expected_weight == pytest.approx(coupling_base)


# ---------------------------------------------------------------------------
# Scenario: No direct VAD write path exists
# ---------------------------------------------------------------------------


def test_no_direct_vad_write_path_exists():
    """The appraisal-bypassing direct-write path is gone; appraisal is the only route."""
    # The old direct-write method must no longer exist.
    assert not hasattr(Thymos, "_apply_coupling_nudge")
    # The DriftSafeguard that only existed to cap that write must be gone too.
    import kaine.modules.thymos.coupling as coupling_mod
    assert not hasattr(coupling_mod, "DriftSafeguard")
    # CouplingConfig no longer carries the rate cap.
    import dataclasses
    fields = {f.name for f in dataclasses.fields(CouplingConfig)}
    assert "coupling_max_rate_per_s" not in fields
    assert "decay_s" in fields


@pytest.mark.asyncio
async def test_recording_perceived_emotion_does_not_touch_state(bus: AsyncBus):
    """Recording the perceived signal must not move the dimensional state."""
    fake_now = [0.0]
    thymos = _make_thymos_with_coupling(
        bus, fake_now,
        coupling_base=0.15,
        coupling_familiarity_gain=0.20,
        coupling_ceiling=0.30,
    )
    thymos._familiarity_cache["mic"] = 0.9
    before = thymos.state

    thymos._record_perceived_emotion(_emotion_event("happy", source_label="mic"))

    assert thymos.state == before, (
        "Recording a perceived emotion must not write the dimensional state; "
        "the only route to state is the entity's own appraisal."
    )
