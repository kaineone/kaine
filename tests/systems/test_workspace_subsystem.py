# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Workspace/Syneidesis subsystem: candidates → top-k coalition."""
from __future__ import annotations

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


def _ev(source, salience):
    return Event(
        source=source,
        type=f"{source}.tick",
        payload={},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_syneidesis_selects_top_k():
    syn = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=8),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=2,
        publication_threshold=0.0,
    )
    events = [
        ("1-0", _ev("a", 0.9)),
        ("2-0", _ev("b", 0.5)),
        ("3-0", _ev("c", 0.1)),
    ]
    snapshot = await syn.select(events, context={"tick_index": 0})
    assert len(snapshot.selected_events) == 2
    sources = {ev.source for _, ev in snapshot.selected_events}
    # Highest-salience two should win.
    assert "a" in sources


@pytest.mark.asyncio
async def test_syneidesis_inhibits_below_threshold():
    syn = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=8),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=5,
        publication_threshold=0.99,
    )
    events = [("1-0", _ev("a", 0.1))]
    snapshot = await syn.select(events, context={"tick_index": 0})
    assert snapshot.inhibited is True


@pytest.mark.asyncio
async def test_syneidesis_empty_candidate_set():
    syn = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=8),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=5,
        publication_threshold=0.0,
    )
    snapshot = await syn.select([], context={"tick_index": 0})
    assert snapshot.selected_events == []
