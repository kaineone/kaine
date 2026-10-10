# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.modules.thymos.modulator import StateModulator
from kaine.modules.thymos.state import DimensionalState
from kaine.workspace.novelty import NoveltyTracker
from kaine.workspace.salience import RuleBasedSalience, arousal_contrast
from kaine.workspace.strategies import StaticGoalScorer, StaticThymosModulator


def _ev(intensity: float = 0.8, source: str = "soma", payload=None) -> Event:
    return Event(
        source=source,
        type="t",
        payload=payload or {"k": "v"},
        salience=intensity,
        timestamp=datetime.now(timezone.utc),
    )


def test_arousal_contrast_identity_and_values():
    grid = [i / 100.0 for i in range(101)]
    assert all(arousal_contrast(p, 0.0) == p for p in grid)
    assert arousal_contrast(0.8, 8.0) == pytest.approx(0.9324, abs=1e-3)
    assert arousal_contrast(0.2, 8.0) == pytest.approx(0.0676, abs=1e-3)

    contrasted = [arousal_contrast(p, 8.0) for p in grid]
    assert all(
        contrasted[i] <= contrasted[i + 1] + 1e-12
        for i in range(len(contrasted) - 1)
    )
    assert arousal_contrast(0.0, 8.0) == 0.0
    assert arousal_contrast(1.0, 8.0) == 1.0


@pytest.mark.asyncio
async def test_rule_based_salience_is_original_product_at_zero_gain():
    s = RuleBasedSalience(
        novelty=NoveltyTracker(window=32),
        goal_scorer=StaticGoalScorer(1.0),
        thymos_modulator=StaticThymosModulator(1.0),
    )
    score = await s.score(_ev(0.8), context={})
    assert score == pytest.approx(0.8, abs=1e-9)


def test_state_modulator_contrast_gain():
    baseline = 0.3
    max_gain = 8.0
    assert (
        StateModulator(
            lambda: DimensionalState(arousal=0.3),
            contrast_gain_max=max_gain,
            baseline_arousal=baseline,
        ).contrast_gain()
        == 0.0
    )
    assert (
        StateModulator(
            lambda: DimensionalState(arousal=0.1),
            contrast_gain_max=max_gain,
            baseline_arousal=baseline,
        ).contrast_gain()
        == 0.0
    )
    assert (
        StateModulator(
            lambda: DimensionalState(arousal=1.0),
            contrast_gain_max=max_gain,
            baseline_arousal=baseline,
        ).contrast_gain()
        == max_gain
    )


@pytest.mark.asyncio
async def test_arousal_contrast_preserves_order_and_sharpens():
    s = RuleBasedSalience(
        novelty=NoveltyTracker(window=1000),
        goal_scorer=StaticGoalScorer(1.0),
        thymos_modulator=StateModulator(
            lambda: DimensionalState(arousal=1.0),
            contrast_gain_max=8.0,
            baseline_arousal=0.3,
        ),
    )
    high = await s.score(_ev(0.8, source="h"), context={})
    low = await s.score(_ev(0.2, source="l"), context={})
    assert 0.0 < low < high <= 1.0
    assert high / low > 4.0


@pytest.mark.asyncio
async def test_steady_source_does_not_suppress_alerts():
    strategy = RuleBasedSalience(
        novelty=NoveltyTracker(window=32),
        goal_scorer=StaticGoalScorer(1.0),
        thymos_modulator=StaticThymosModulator(1.0),
    )
    fresh = RuleBasedSalience(
        novelty=NoveltyTracker(window=32),
        goal_scorer=StaticGoalScorer(1.0),
        thymos_modulator=StaticThymosModulator(1.0),
    )
    expected = await fresh.score(
        _ev(0.8, source="audition", payload={"p": "fresh"}), context={}
    )

    for i in range(600):
        await strategy.score(
            _ev(0.1, source="thymos", payload={"i": i}), context={}
        )
        if i % 10 == 9:
            score = await strategy.score(
                _ev(0.8, source="audition", payload={"a": i}), context={}
            )
            assert score == pytest.approx(expected, abs=1e-9)
