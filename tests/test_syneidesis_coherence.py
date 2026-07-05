# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Syneidesis coherence-multiplier tests (oscillatory-layer).

The load-bearing safety test: with the layer DISABLED (no CoherenceScorer)
selection is bit-for-bit identical to the baseline — same selected events, same
scores, same inhibition, AND no `metadata['coherence']` key. Also verifies that
when enabled a phase-locked coalition out-ranks an equally-salient
desynchronized one.

No snnTorch needed — coherence operates on phase sequences fed via context.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticGoalScorer,
    StaticThymosModulator,
    Syneidesis,
)
from kaine.workspace.coherence import CoherenceScorer


def _ev(intensity: float, eid: str, source: str = "soma") -> tuple[str, Event]:
    return eid, Event(
        source=source,
        type=f"t.{eid}",
        payload={"id": eid},
        salience=intensity,
        timestamp=datetime.now(timezone.utc),
    )


def _strategy() -> RuleBasedSalience:
    return RuleBasedSalience(
        novelty=NoveltyTracker(window=64),
        goal_scorer=StaticGoalScorer(),
        thymos_modulator=StaticThymosModulator(),
    )


# --------------------------------------------------------------------------
# Bit-for-bit identical when disabled
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_selection_bit_for_bit_identical_when_disabled():
    """coherence=None ⇒ identical scores, selection, inhibition, no metadata."""
    events = [
        _ev(0.9, "a", "soma"),
        _ev(0.7, "b", "chronos"),
        _ev(0.5, "c", "topos"),
        _ev(0.3, "d", "thymos"),
    ]

    baseline = Syneidesis(strategy=_strategy(), top_k=3, publication_threshold=0.35)
    # Identical strategy/params; the only difference would be a coherence
    # scorer, which we deliberately leave as the default (None).
    flagged_off = Syneidesis(
        strategy=_strategy(), top_k=3, publication_threshold=0.35, coherence=None
    )

    # Even when phases are provided in context, a disabled layer ignores them.
    ctx = {
        "tick_index": 0,
        "phases": {"soma": 0.1, "chronos": 0.1, "topos": 2.0, "thymos": 2.0},
    }
    snap_base = await baseline.select(list(events), context=dict(ctx))
    snap_off = await flagged_off.select(list(events), context=dict(ctx))

    assert snap_off.salience_scores == snap_base.salience_scores
    assert [e for _, e in snap_off.selected_events] == [
        e for _, e in snap_base.selected_events
    ]
    assert [eid for eid, _ in snap_off.selected_events] == [
        eid for eid, _ in snap_base.selected_events
    ]
    assert snap_off.inhibited == snap_base.inhibited
    # No coherence metadata key when disabled.
    assert snap_base.metadata.get("coherence") is None
    assert snap_off.metadata.get("coherence") is None


# --------------------------------------------------------------------------
# Multi-cycle bit-for-bit identity (depth: disabled == absent over N cycles)
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disabled_layer_bit_for_bit_identical_across_many_cycles():
    """Disabled-layer selection == layer-absent baseline on EVERY cycle.

    Extends the single-tick negative control to MANY cycles with the same seed
    and the same per-cycle events/phases: a coherence side effect that only
    manifests after several ticks (e.g. a leaking phase buffer) would diverge
    here even though a single-tick check passes.
    """
    n_cycles = 25
    baseline = Syneidesis(strategy=_strategy(), top_k=3, publication_threshold=0.35)
    # Identical params; the only possible difference would be a coherence scorer,
    # which is deliberately left as the default (None) on the disabled arm.
    disabled = Syneidesis(
        strategy=_strategy(), top_k=3, publication_threshold=0.35, coherence=None
    )

    # Deterministic per-cycle inputs from a fixed seed.
    rng = random.Random(2027)
    sources = ["soma", "chronos", "topos", "thymos"]
    for cycle in range(n_cycles):
        events = [
            _ev(round(rng.uniform(0.1, 0.95), 4), f"e{cycle}_{i}", sources[i])
            for i in range(4)
        ]
        ctx = {
            "tick_index": cycle,
            "phases": {s: rng.uniform(0.0, 2 * math.pi) for s in sources},
        }
        snap_base = await baseline.select(list(events), context=dict(ctx))
        snap_off = await disabled.select(list(events), context=dict(ctx))

        assert snap_off.salience_scores == snap_base.salience_scores, cycle
        assert [eid for eid, _ in snap_off.selected_events] == [
            eid for eid, _ in snap_base.selected_events
        ], cycle
        assert [e for _, e in snap_off.selected_events] == [
            e for _, e in snap_base.selected_events
        ], cycle
        assert snap_off.inhibited == snap_base.inhibited, cycle
        # No coherence metadata on EITHER arm on EVERY cycle.
        assert snap_base.metadata.get("coherence") is None, cycle
        assert snap_off.metadata.get("coherence") is None, cycle


# --------------------------------------------------------------------------
# Explicit unit-multiplier / literal no-op when disabled
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_disabled_multiplier_is_literal_no_op():
    """Disabled path: scores equal raw strategy scores (×1.0), no coherence key."""
    strategy = _strategy()
    events = [_ev(0.6, "a", "soma"), _ev(0.4, "b", "chronos")]
    ctx = {"tick_index": 0, "phases": {"soma": 0.3, "chronos": 1.7}}

    # Compute the raw strategy scores directly (effective multiplier 1.0 target).
    raw = {}
    for eid, ev in events:
        raw[eid] = await strategy.score(ev, dict(ctx))

    # Fresh strategy with identical novelty trajectory for the runner.
    syn = Syneidesis(
        strategy=_strategy(), top_k=5, publication_threshold=0.0, coherence=None
    )
    snap = await syn.select(list(events), context=dict(ctx))

    # No coherence metadata key written on the disabled path.
    assert snap.metadata.get("coherence") is None
    # Salience scores equal the raw strategy scores — multiplier is exactly 1.0.
    assert snap.salience_scores == raw


def test_factor_from_unit_plv_is_ceiling_and_map_is_monotone():
    """factor_from_plv(1.0) == ceiling; the bounded map is monotone in PLV."""
    scorer = CoherenceScorer(
        plv_window=12, coherence_floor=0.5, coherence_ceiling=1.5
    )
    assert scorer.factor_from_plv(1.0) == scorer.coherence_ceiling
    assert scorer.factor_from_plv(0.0) == scorer.coherence_floor
    # Monotone non-decreasing across PLV in [0, 1].
    prev = scorer.factor_from_plv(0.0)
    for i in range(1, 21):
        cur = scorer.factor_from_plv(i / 20.0)
        assert cur >= prev
        prev = cur


# --------------------------------------------------------------------------
# Extreme-gain positive control: selection demonstrably FLIPS
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_extreme_gain_flips_top_selection():
    """An EXTREME precision gain overturns the salience-only ranking.

    A desynchronized source carries HIGHER raw salience (0.6) than a phase-locked
    source (0.4). With the layer absent the desync event ranks first. With the
    layer enabled at an extreme ceiling and low floor, the phase-locked event's
    coherence factor (→ ceiling) overwhelms the desync event's (→ floor) and the
    phase-locked event overtakes it — a strong proof the toggle is wired to
    selection.
    """
    # Build a scorer where lockA/lockB are perfectly phase-locked and
    # desyncA/desyncB are far apart.
    scorer = CoherenceScorer(
        plv_window=12, coherence_floor=0.01, coherence_ceiling=100.0
    )
    rng = random.Random(7)
    for k in range(12):
        ph = k * 0.5
        scorer.observe(
            {
                "lockA": ph,
                "lockB": ph,
                "desyncA": rng.uniform(0, 2 * math.pi),
                "desyncB": rng.uniform(0, 2 * math.pi),
            }
        )

    # Phase-locked event has LOWER raw salience than the desync event.
    events = [
        _ev(0.4, "locked", "lockA"),
        _ev(0.6, "loose", "desyncA"),
        _ev(0.4, "lockedB", "lockB"),
        _ev(0.6, "looseB", "desyncB"),
    ]
    ctx = {
        "tick_index": 1,
        "phases": {"lockA": 0.0, "lockB": 0.0, "desyncA": 1.0, "desyncB": 2.5},
    }

    # Layer ABSENT: the higher-raw-salience desync event ranks first.
    baseline = Syneidesis(strategy=_strategy(), top_k=4, publication_threshold=0.0)
    base_snap = await baseline.select(list(events), context=dict(ctx))
    base_top_id = base_snap.selected_events[0][0]
    assert base_top_id == "loose"  # raw 0.6 > 0.4 wins without coherence

    # Layer ENABLED at extreme gain: the phase-locked event overtakes it.
    syn = Syneidesis(
        strategy=_strategy(),
        top_k=4,
        publication_threshold=0.0,
        coherence=scorer,
    )
    snap = await syn.select(list(events), context=dict(ctx))
    top_id = snap.selected_events[0][0]
    assert top_id == "locked"  # selection FLIPPED under extreme coherence gain
    assert snap.salience_scores["locked"] > snap.salience_scores["loose"]
    assert snap.metadata.get("coherence") is not None


@pytest.mark.asyncio
async def test_disabled_layer_does_not_write_coherence_metadata():
    syn = Syneidesis(strategy=_strategy(), top_k=5, publication_threshold=0.0)
    snap = await syn.select([_ev(0.6, "a")], context={"tick_index": 1})
    assert "coherence" not in snap.metadata or snap.metadata["coherence"] is None


# --------------------------------------------------------------------------
# Enabled: phase-locked coalition out-ranks desynchronized
# --------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_phase_locked_coalition_outranks_desync_when_enabled():
    scorer = CoherenceScorer(
        plv_window=12, coherence_floor=0.5, coherence_ceiling=1.5
    )
    # Two sources locked (lockA/lockB), two desynchronized random sources.
    rng = random.Random(11)
    for k in range(12):
        ph = k * 0.4
        scorer.observe(
            {
                "lockA": ph,
                "lockB": ph,
                "desyncA": rng.uniform(0, 2 * math.pi),
                "desyncB": rng.uniform(0, 2 * math.pi),
            }
        )

    syn = Syneidesis(
        strategy=_strategy(),
        top_k=4,
        publication_threshold=0.0,
        coherence=scorer,
    )
    # Equal raw salience for a locked-source event and a desync-source event.
    events = [
        _ev(0.6, "locked", "lockA"),
        _ev(0.6, "loose", "desyncA"),
        # padding so the cohort contains the partner sources
        _ev(0.6, "lockedB", "lockB"),
        _ev(0.6, "looseB", "desyncB"),
    ]
    # observe() in select consumes context phases too; keep them aligned.
    ctx = {
        "tick_index": 99,
        "phases": {"lockA": 0.0, "lockB": 0.0, "desyncA": 1.0, "desyncB": 2.5},
    }
    snap = await syn.select(events, context=ctx)
    assert snap.salience_scores["locked"] > snap.salience_scores["loose"]
    # Coherence metadata populated when enabled.
    assert snap.metadata.get("coherence") is not None
    assert 0.0 <= snap.metadata["coherence"] <= 1.0
