# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.workspace.novelty import NoveltyTracker
from kaine.workspace.salience import RuleBasedSalience
from kaine.workspace.strategies import StaticGoalScorer, StaticThymosModulator


def _ev(intensity: float = 0.8, payload=None) -> Event:
    return Event(
        source="soma",
        type="t",
        payload=payload or {"k": "v"},
        salience=intensity,
        timestamp=datetime.now(timezone.utc),
    )


def _strategy(
    *,
    novelty_window: int = 32,
    goal: float = 1.0,
    thymos: float = 1.0,
) -> RuleBasedSalience:
    return RuleBasedSalience(
        novelty=NoveltyTracker(window=novelty_window),
        goal_scorer=StaticGoalScorer(goal),
        thymos_modulator=StaticThymosModulator(thymos),
    )


@pytest.mark.asyncio
async def test_product_form_score():
    s = _strategy(goal=1.0, thymos=1.0)
    # intensity=0.8, novelty=1.0 (first obs), goal=1.0, thymos=1.0
    score = await s.score(_ev(0.8), context={})
    assert score == pytest.approx(0.8, abs=1e-9)


@pytest.mark.asyncio
async def test_zero_goal_zeroes_score():
    s = _strategy(goal=0.0)
    score = await s.score(_ev(0.9), context={})
    assert score == 0.0


@pytest.mark.asyncio
async def test_zero_thymos_zeroes_score():
    s = _strategy(thymos=0.0)
    score = await s.score(_ev(0.9), context={})
    assert score == 0.0


@pytest.mark.asyncio
async def test_clamp_handles_overshoot():
    # Intensity at the boundary; verify final clamp behaves.
    s = _strategy(goal=1.0, thymos=1.0)
    score = await s.score(_ev(1.0), context={})
    assert 0.0 <= score <= 1.0


@pytest.mark.asyncio
async def test_default_static_scorers_yield_intensity_times_novelty():
    s = RuleBasedSalience(
        novelty=NoveltyTracker(window=4),
        goal_scorer=StaticGoalScorer(),
        thymos_modulator=StaticThymosModulator(),
    )
    score = await s.score(_ev(0.6), context={})
    assert score == pytest.approx(0.6, abs=1e-9)


@pytest.mark.asyncio
async def test_repeated_event_drops_score():
    s = _strategy(novelty_window=4)
    e = _ev(0.9, payload={"same": "x"})
    first = await s.score(e, context={})
    for _ in range(3):
        await s.score(_ev(0.9, payload={"same": "x"}), context={})
    later = await s.score(_ev(0.9, payload={"same": "x"}), context={})
    assert later < first


@pytest.mark.asyncio
async def test_invalid_default_static_scorer_rejected():
    with pytest.raises(ValueError):
        StaticGoalScorer(default=1.5)
    with pytest.raises(ValueError):
        StaticThymosModulator(default=-0.1)


# ---------------------------------------------------------------------------
# Degraded-mode warning: fires ONLY for factors explicitly named as downgraded
# from their shipped default (computed by the cycle assembly). A factor sitting
# on its shipped default — including a Static* scorer passed with no
# downgraded_factors, e.g. the STAGED goal factor — is silent.
# ---------------------------------------------------------------------------


def test_downgraded_factors_emit_warning(caplog):
    """A named downgraded factor triggers a degraded-mode warning."""
    import logging
    with caplog.at_level(logging.WARNING, logger="kaine.workspace.salience"):
        RuleBasedSalience(
            novelty=NoveltyTracker(window=4),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
            downgraded_factors=["thymos_modulation (set to static)"],
        )
    combined = " ".join(r.message for r in caplog.records)
    assert "downgraded" in combined.lower()
    assert "thymos_modulation" in combined


def test_static_scorers_without_downgrade_flag_are_silent(caplog):
    """Static scorers on their shipped default (no downgraded_factors) do NOT
    warn — the staged goal-static baseline must not nag on a normal boot."""
    import logging
    with caplog.at_level(logging.WARNING, logger="kaine.workspace.salience"):
        RuleBasedSalience(
            novelty=NoveltyTracker(window=4),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        )
    assert caplog.records == [], f"unexpected warnings: {[r.message for r in caplog.records]}"


def test_no_warning_for_real_scorers(caplog):
    """No warning is emitted when real scorers are injected (no downgrade)."""
    import logging

    class RealGoalScorer:
        async def relevance(self, event):
            return 0.8

    class RealThymosModulator:
        async def modulate(self, event):
            return 0.9

    with caplog.at_level(logging.WARNING, logger="kaine.workspace.salience"):
        RuleBasedSalience(
            novelty=NoveltyTracker(window=4),
            goal_scorer=RealGoalScorer(),
            thymos_modulator=RealThymosModulator(),
        )
    assert caplog.records == [], f"unexpected warnings: {[r.message for r in caplog.records]}"
