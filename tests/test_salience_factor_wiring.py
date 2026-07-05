# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Live four-factor salience wiring (wire-salience-goal-thymos).

Covers the real Thymos factor (StateModulator, live by default) and the real
goal factor (DriveRelevanceGoalScorer, built but staged), the AffectStateProvider
DI seam that feeds them without a workspace->modules import, the static negative
control's bit-for-bit reproduction of the two-factor selection, and determinism.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.boot import ConfigurationError, make_salience_factors
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle import CognitiveCycle
from kaine.cycle.affect_state import AffectStateProvider
from kaine.modules.thymos.modulator import StateModulator
from kaine.modules.thymos.state import DimensionalState
from kaine.workspace.novelty import NoveltyTracker
from kaine.workspace.salience import RuleBasedSalience
from kaine.workspace.strategies import (
    DriveRelevanceGoalScorer,
    StaticGoalScorer,
    StaticThymosModulator,
)
from kaine.workspace.syneidesis import Syneidesis
from tests._fakes import FakeClock, FakeRegistry, FakeSyneidesis


def _event(source: str, intensity: float, payload=None, type_: str = "percept") -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload or {"k": source},
        salience=intensity,
        timestamp=datetime.now(timezone.utc),
    )


def _thymos_state(*, valence=0.0, arousal=0.3, dominance=0.0, drives=None) -> Event:
    return Event(
        source="thymos",
        type="thymos.state",
        payload={
            "state": {"valence": valence, "arousal": arousal, "dominance": dominance},
            "drives": drives or {},
        },
        salience=0.1,
        timestamp=datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# AffectStateProvider: the DI seam
# ---------------------------------------------------------------------------


def test_provider_defaults_to_baseline_before_any_state():
    provider = AffectStateProvider()
    assert provider.dimensional_state() == DimensionalState()
    assert provider.drive_values() == {}


def test_provider_folds_latest_thymos_state():
    provider = AffectStateProvider()
    provider.observe(
        [
            ("1-0", _thymos_state(arousal=0.2, drives={"curiosity": 0.1})),
            ("2-0", _event("perception", 0.5)),  # ignored (not thymos.state)
            ("3-0", _thymos_state(arousal=0.9, drives={"curiosity": 0.8})),
        ]
    )
    # The LAST thymos.state in the batch wins.
    assert provider.dimensional_state().arousal == pytest.approx(0.9)
    assert provider.drive_values() == {"curiosity": 0.8}


def test_provider_keeps_last_known_when_no_state_this_tick():
    provider = AffectStateProvider()
    provider.observe([("1-0", _thymos_state(arousal=0.7))])
    provider.observe([("2-0", _event("perception", 0.5))])
    assert provider.dimensional_state().arousal == pytest.approx(0.7)


def test_provider_drive_values_is_a_copy():
    provider = AffectStateProvider()
    provider.observe([("1-0", _thymos_state(drives={"curiosity": 0.5}))])
    snapshot = provider.drive_values()
    snapshot["curiosity"] = 99.0
    assert provider.drive_values() == {"curiosity": 0.5}


# ---------------------------------------------------------------------------
# Real Thymos factor changes selection vs the static placeholder
# ---------------------------------------------------------------------------


async def _select_one(strategy, event) -> tuple:
    syn = Syneidesis(strategy, top_k=1, publication_threshold=0.35)
    snap = await syn.select([("1-0", event)], {"tick_index": 1})
    return snap


@pytest.mark.asyncio
async def test_real_thymos_factor_changes_selection_outcome():
    """The arousal-weighted Thymos factor alters selection vs the constant stub.

    intensity=0.5, novelty=1.0, goal=1.0. Under the real modulator the score is
    0.5 * arousal-derived multiplier (floor 0.2, ceiling 1.0): zero arousal
    collapses the score below threshold (inhibited), a raised-but-sub-ceiling
    arousal both publishes the event AND yields a score distinct from the
    constant-1.0 placeholder.
    """
    ev = _event("perception", 0.5)

    low = AffectStateProvider()
    low.observe([("0-0", _thymos_state(arousal=0.0))])
    snap_low = await _select_one(
        RuleBasedSalience(NoveltyTracker(), StaticGoalScorer(), StateModulator(low.dimensional_state)),
        ev,
    )

    high = AffectStateProvider()
    high.observe([("0-0", _thymos_state(arousal=0.9))])
    snap_high = await _select_one(
        RuleBasedSalience(NoveltyTracker(), StaticGoalScorer(), StateModulator(high.dimensional_state)),
        ev,
    )

    snap_static = await _select_one(
        RuleBasedSalience(NoveltyTracker(), StaticGoalScorer(), StaticThymosModulator()),
        ev,
    )

    assert snap_low.inhibited is True      # arousal collapses salience below threshold
    assert snap_high.inhibited is False    # arousal lifts salience above threshold
    assert snap_static.inhibited is False
    # The real factor produced a genuinely different score than the constant stub.
    assert snap_low.salience_scores["1-0"] != snap_static.salience_scores["1-0"]
    assert snap_high.salience_scores["1-0"] != snap_static.salience_scores["1-0"]


def test_real_factors_emit_no_degraded_warning(caplog):
    import logging

    provider = AffectStateProvider()
    with caplog.at_level(logging.WARNING, logger="kaine.workspace.salience"):
        RuleBasedSalience(
            NoveltyTracker(),
            DriveRelevanceGoalScorer(provider.drive_values),
            StateModulator(provider.dimensional_state),
        )
    assert caplog.records == [], f"unexpected warnings: {[r.message for r in caplog.records]}"


def test_deliberate_downgrade_emits_degraded_warning(caplog):
    import logging

    # A factor named as downgraded (as make_salience_factors does for a real-by-
    # default factor set to static) triggers the degraded-mode warning.
    with caplog.at_level(logging.WARNING, logger="kaine.workspace.salience"):
        RuleBasedSalience(
            NoveltyTracker(),
            StaticGoalScorer(),
            StaticThymosModulator(),
            downgraded_factors=["thymos_modulation (set to static)"],
        )
    combined = " ".join(r.message for r in caplog.records)
    assert "negative control" in combined
    assert "degraded" in combined


def test_static_defaults_do_not_warn(caplog):
    import logging

    # Static scorers with no downgrade flag (the strategy-level equivalent of the
    # shipped goal-static baseline) must be silent — no nag on a normal boot.
    with caplog.at_level(logging.WARNING, logger="kaine.workspace.salience"):
        RuleBasedSalience(NoveltyTracker(), StaticGoalScorer(), StaticThymosModulator())
    assert caplog.records == []


# ---------------------------------------------------------------------------
# Static fallback reproduces the two-factor selection BIT-FOR-BIT
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_static_fallback_reproduces_two_factor_selection_bit_for_bit():
    """With both factors on the static default, selection is byte-identical to a
    pure intensity x novelty computation — the guard that flipping the live
    default to the real factors did not change scoring where static is chosen.
    """
    events = [
        ("1-0", _event("perception", 0.9, payload={"a": 1})),
        ("2-0", _event("soma", 0.4, payload={"b": 2})),
        ("3-0", _event("perception", 0.9, payload={"a": 1})),  # repeat -> novelty decays
        ("4-0", _event("topos", 0.7, payload={"c": 3})),
    ]

    strategy = RuleBasedSalience(NoveltyTracker(window=4), StaticGoalScorer(), StaticThymosModulator())
    syn = Syneidesis(strategy, top_k=3, publication_threshold=0.35)
    snap = await syn.select(list(events), {"tick_index": 1})

    # Independent two-factor reference: intensity * novelty, same order/algorithm.
    ref_novelty = NoveltyTracker(window=4)
    ref_scores = {}
    for entry_id, ev in events:
        ref_scores[entry_id] = ev.salience * ref_novelty.observe(ev)

    assert snap.salience_scores == ref_scores  # exact float equality (bit-for-bit)


@pytest.mark.asyncio
async def test_real_four_factor_selection_is_deterministic():
    """Same events + same scripted affect/drives ⇒ identical selection, repeated
    (salience is a pure function of event + affect + drive state; no RNG/clock)."""
    events = [
        ("1-0", _event("perception", 0.8, payload={"a": 1})),
        ("2-0", _event("praxis", 0.8, payload={"b": 2})),
        ("3-0", _event("audition", 0.6, payload={"c": 3})),
    ]
    thymos = _thymos_state(arousal=0.7, drives={"curiosity": 0.9, "boredom": 0.2})

    def run():
        provider = AffectStateProvider()
        provider.observe([("0-0", thymos)])
        strategy = RuleBasedSalience(
            NoveltyTracker(window=8),
            DriveRelevanceGoalScorer(provider.drive_values),
            StateModulator(provider.dimensional_state),
        )
        return Syneidesis(strategy, top_k=3, publication_threshold=0.05)

    async def select():
        syn = run()
        return await syn.select(list(events), {"tick_index": 1})

    a = await select()
    b = await select()
    assert a.salience_scores == b.salience_scores
    assert [e for _, e in a.selected_events] == [e for _, e in b.selected_events]


# ---------------------------------------------------------------------------
# DriveRelevanceGoalScorer (new)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drive_relevance_prefers_source_serving_dominant_drive():
    drives = {"curiosity": 0.9, "boredom": 0.1, "social_drive": 0.0, "restlessness": 0.0}
    scorer = DriveRelevanceGoalScorer(lambda: drives)

    serving = await scorer.relevance(_event("perception", 0.5))  # serves curiosity
    non_serving = await scorer.relevance(_event("praxis", 0.5))  # does not

    assert serving > non_serving
    # Bounded "around 1.0": serving source unattenuated at 1.0; floor = 1 - 0.5.
    assert serving == pytest.approx(1.0)
    assert non_serving == pytest.approx(1.0 - 0.9 * 0.5)  # 0.55
    assert 0.0 <= non_serving <= 1.0
    assert 0.0 <= serving <= 1.0


@pytest.mark.asyncio
async def test_drive_relevance_neutral_without_drives():
    scorer = DriveRelevanceGoalScorer(lambda: {})
    assert await scorer.relevance(_event("praxis", 0.5)) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_drive_relevance_neutral_when_all_drives_zero():
    scorer = DriveRelevanceGoalScorer(
        lambda: {"curiosity": 0.0, "boredom": 0.0, "social_drive": 0.0, "restlessness": 0.0}
    )
    assert await scorer.relevance(_event("praxis", 0.5)) == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_drive_relevance_dominant_pick_is_deterministic():
    # Tie on value -> broken by name, independent of insertion order.
    a = DriveRelevanceGoalScorer(lambda: {"curiosity": 0.6, "restlessness": 0.6})
    b = DriveRelevanceGoalScorer(lambda: {"restlessness": 0.6, "curiosity": 0.6})
    ev = _event("praxis", 0.5)  # serves restlessness, not curiosity
    assert await a.relevance(ev) == await b.relevance(ev)


def test_invalid_attenuation_rejected():
    with pytest.raises(ValueError):
        DriveRelevanceGoalScorer(lambda: {}, attenuation=1.5)


# ---------------------------------------------------------------------------
# make_salience_factors: config-driven factor selection + downgrade signal
# ---------------------------------------------------------------------------


def _cfg(**syn) -> dict:
    return {"syneidesis": syn}


def test_make_salience_factors_shipped_defaults():
    """Shipped defaults: Thymos real, goal on the staged static baseline, and NO
    downgrade (goal-static is the intended shipped state, not a downgrade)."""
    thymos, goal, downgraded = make_salience_factors({}, AffectStateProvider())
    assert isinstance(thymos, StateModulator)
    assert isinstance(goal, StaticGoalScorer)
    assert downgraded == []


def test_make_salience_factors_thymos_static_is_a_downgrade():
    thymos, goal, downgraded = make_salience_factors(
        _cfg(salience_thymos_factor="static"), AffectStateProvider()
    )
    assert isinstance(thymos, StaticThymosModulator)
    assert any("thymos" in d for d in downgraded), downgraded


def test_make_salience_factors_goal_drive_relevance_activates_real_scorer():
    thymos, goal, downgraded = make_salience_factors(
        _cfg(salience_goal_factor="drive_relevance"), AffectStateProvider()
    )
    assert isinstance(goal, DriveRelevanceGoalScorer)
    assert downgraded == []


def test_make_salience_factors_unknown_thymos_value_raises():
    with pytest.raises(ConfigurationError):
        make_salience_factors(
            _cfg(salience_thymos_factor="bogus"), AffectStateProvider()
        )


def test_make_salience_factors_unknown_goal_value_raises():
    with pytest.raises(ConfigurationError):
        make_salience_factors(
            _cfg(salience_goal_factor="bogus"), AffectStateProvider()
        )


def test_make_salience_factors_unknown_key_raises():
    # A typo'd key (salience_goal_factorS) must fail loudly, not silently leave
    # the goal factor on its default.
    with pytest.raises(ValueError):
        make_salience_factors(
            _cfg(salience_goal_factors="drive_relevance"), AffectStateProvider()
        )


# ---------------------------------------------------------------------------
# Engine integration seam: the affect observer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_calls_observer_before_select_with_sorted_batch():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    order: list[str] = []
    seen: list[list] = []

    class RecordingSyneidesis(FakeSyneidesis):
        async def select(self, events, context):
            order.append("select")
            return await super().select(events, context)

    def observer(events):
        order.append("observe")
        seen.append(list(events))

    try:
        # Publish in reverse-canonical order; the engine sorts by (source, ...).
        await bus.publish(_event("soma", 0.5))
        await bus.publish(_event("audition", 0.5))
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=RecordingSyneidesis(),
            registry=FakeRegistry(["soma.out", "audition.out"]),
            clock=FakeClock(),
            sleep=FakeClock().sleep,
            affect_observer=observer,
        )
        await cycle.tick()
    finally:
        await bus.close()

    # Observer fires each tick, BEFORE selection.
    assert order == ["observe", "select"]
    # It receives the canonically-sorted batch (audition < soma by source).
    sources = [ev.source for _, ev in seen[0]]
    assert sources == sorted(sources) == ["audition", "soma"]


@pytest.mark.asyncio
async def test_engine_swallows_observer_exception_and_tick_continues():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    def boom(events):
        raise RuntimeError("observer blew up")

    try:
        await bus.publish(_event("soma", 0.5))
        syn = FakeSyneidesis()
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=syn,
            registry=FakeRegistry(["soma.out"]),
            clock=FakeClock(),
            sleep=FakeClock().sleep,
            affect_observer=boom,
        )
        result = await cycle.tick()
    finally:
        await bus.close()

    # A raising observer must not crash or error the tick; selection still ran.
    assert result.error is False
    assert len(syn.calls) == 1
