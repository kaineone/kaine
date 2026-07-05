# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

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


def _ev(intensity: float, eid: str) -> tuple[str, Event]:
    return eid, Event(
        source="soma",
        type=f"t.{eid}",
        payload={"id": eid},
        salience=intensity,
        timestamp=datetime.now(timezone.utc),
    )


def _real_syn(top_k: int = 5, threshold: float = 0.35) -> Syneidesis:
    return Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=64),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=top_k,
        publication_threshold=threshold,
    )


@pytest.mark.asyncio
async def test_top_k_truncates_to_five():
    syn = _real_syn(top_k=5)
    events = [_ev(0.1 * (i + 1), f"e{i}") for i in range(10)]
    snap = await syn.select(events, context={"tick_index": 0})
    assert len(snap.selected_events) == 5


@pytest.mark.asyncio
async def test_selected_events_in_descending_score_order():
    syn = _real_syn(top_k=5, threshold=0.0)
    events = [_ev(0.1 * (i + 1), f"e{i}") for i in range(10)]
    snap = await syn.select(events, context={})
    scores = [snap.salience_scores[eid] for eid, _ in snap.selected_events]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_fewer_than_k_returned_without_padding():
    syn = _real_syn(top_k=5)
    events = [_ev(0.5, "a"), _ev(0.4, "b")]
    snap = await syn.select(events, context={})
    assert len(snap.selected_events) == 2


@pytest.mark.asyncio
async def test_inhibition_when_top_below_threshold():
    syn = _real_syn(top_k=5, threshold=0.5)
    events = [_ev(0.1, "a"), _ev(0.2, "b")]  # max intensity 0.2
    snap = await syn.select(events, context={})
    assert snap.inhibited is True


@pytest.mark.asyncio
async def test_no_inhibition_when_top_above_threshold():
    syn = _real_syn(top_k=5, threshold=0.35)
    events = [_ev(0.6, "a"), _ev(0.2, "b")]
    snap = await syn.select(events, context={})
    assert snap.inhibited is False


@pytest.mark.asyncio
async def test_empty_event_list_returns_inhibited_snapshot():
    syn = _real_syn()
    snap = await syn.select([], context={"tick_index": 7})
    assert snap.selected_events == []
    assert snap.inhibited is True
    assert snap.tick_index == 7


@pytest.mark.asyncio
async def test_runtime_mutators_validate_inputs():
    syn = _real_syn()
    syn.set_top_k(3)
    assert syn.top_k == 3
    with pytest.raises(ValueError):
        syn.set_top_k(0)
    syn.set_publication_threshold(0.5)
    assert syn.publication_threshold == 0.5
    with pytest.raises(ValueError):
        syn.set_publication_threshold(1.5)


@pytest.mark.asyncio
async def test_invalid_construction_rejected():
    rb = RuleBasedSalience(
        NoveltyTracker(window=4), StaticGoalScorer(), StaticThymosModulator()
    )
    with pytest.raises(ValueError):
        Syneidesis(strategy=rb, top_k=0)
    with pytest.raises(ValueError):
        Syneidesis(strategy=rb, top_k=5, publication_threshold=1.5)


@pytest.mark.asyncio
async def test_strategy_error_isolated_to_one_event():
    class FlakyStrategy:
        async def score(self, event, context):
            if event.payload.get("id") == "bad":
                raise RuntimeError("boom")
            return event.salience

    syn = Syneidesis(strategy=FlakyStrategy(), top_k=5, publication_threshold=0.0)
    events = [_ev(0.7, "a"), _ev(0.3, "bad"), _ev(0.5, "b")]
    snap = await syn.select(events, context={})
    # All three event ids appear in salience_scores; bad scored 0.0
    assert snap.salience_scores["bad"] == 0.0
    # Top-2 should be a and b
    selected_ids = [eid for eid, _ in snap.selected_events]
    assert "a" in selected_ids and "b" in selected_ids


@pytest.mark.asyncio
async def test_custom_strategy_substitutes_cleanly():
    class ConstantStrategy:
        async def score(self, event, context):
            return 0.9

    syn = Syneidesis(strategy=ConstantStrategy(), top_k=3, publication_threshold=0.5)
    events = [_ev(0.1, "a"), _ev(0.2, "b"), _ev(0.3, "c")]
    snap = await syn.select(events, context={})
    assert snap.inhibited is False
    assert all(snap.salience_scores[eid] == 0.9 for eid in snap.salience_scores)
