# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.boot.errors import ConfigurationError
from kaine.boot.wiring import make_source_precision
from kaine.bus.schema import Event
from kaine.modules.thymos.modulator import StateModulator
from kaine.modules.thymos.state import DimensionalState
from kaine.workspace.novelty import NoveltyTracker
from kaine.workspace.precision import SourcePrecision
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


def test_precision_weights_after_warmup():
    sp = SourcePrecision()
    for i in range(200):
        a_int = 0.2 if i % 2 == 0 else 0.7
        b_int = 0.8 if i % 25 == 24 else 0.4
        sp.observe("a", a_int)
        sp.observe("b", b_int)
        sp.observe("c", 0.1)

    assert sp._count["a"] == 200
    # Precision orders the sources by how steady their surprise is: the
    # alternating source is least reliable, the constant one most.
    assert sp.weight("a") < sp.weight("b") < sp.weight("c")
    assert sp.weight("a") < 1.0 < sp.weight("c")
    for src in ("a", "b", "c"):
        assert 0.5 <= sp.weight(src) <= 1.5


def test_precision_weight_neutral_until_warmed_and_for_unknown():
    sp = SourcePrecision()
    for _ in range(19):
        sp.observe("a", 0.5)
        sp.observe("b", 0.5)
    assert sp.weight("a") == 1.0
    assert sp.weight("b") == 1.0
    assert sp.weight("c") == 1.0
    assert sp.weight("unknown") == 1.0


@pytest.mark.parametrize(
    "override",
    [
        {"sample_weight": 0.0},
        {"sample_weight": 1.1},
        {"warmup_samples": 0},
        {"bounds": (0.0, 1.5)},
        {"bounds": (0.5, 0.9)},
        {"bounds": (1.5, 2.0)},
        {"variance_floor": 0.0},
        {"min_sources": 0},
    ],
)
def test_source_precision_rejects_invalid_arguments(override):
    defaults = {
        "sample_weight": 0.02,
        "warmup_samples": 20,
        "bounds": (0.5, 1.5),
        "variance_floor": 1e-4,
        "min_sources": 3,
    }
    defaults.update(override)
    with pytest.raises(ValueError):
        SourcePrecision(**defaults)


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
async def test_rule_based_salience_without_precision_is_original_product():
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


def test_make_source_precision_switch_and_bounds():
    assert make_source_precision({"syneidesis": {"precision_weighting": False}}) is None
    sp = make_source_precision({})
    assert isinstance(sp, SourcePrecision)

    with pytest.raises(ConfigurationError):
        make_source_precision(
            {"syneidesis": {"precision_weighting": True, "precision_bounds": [0.5]}}
        )
    with pytest.raises(ConfigurationError):
        make_source_precision(
            {"syneidesis": {"precision_weighting": True, "precision_bounds": (0.0, 1.5)}}
        )
