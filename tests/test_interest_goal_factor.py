# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the interest goal factor (paper A.1)."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.boot import ConfigurationError, make_salience_factors
from kaine.bus.schema import Event
from kaine.cycle.affect_state import AffectStateProvider
from kaine.workspace.novelty import NoveltyTracker
from kaine.workspace.salience import RuleBasedSalience
from kaine.workspace.strategies import (
    DriveRelevanceGoalScorer,
    InterestGoalScorer,
    StaticAffectModulator,
    StaticGoalScorer,
    build_drive_sources,
)


def _event(source: str, intensity: float, payload=None, type_: str = "percept") -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload or {"k": source},
        salience=intensity,
        timestamp=datetime.now(timezone.utc),
    )


def _affect_state(**kwargs) -> Event:
    payload: dict[str, object] = {}
    if "valence" in kwargs or "arousal" in kwargs or "dominance" in kwargs:
        payload["state"] = {
            "valence": kwargs.get("valence", 0.0),
            "arousal": kwargs.get("arousal", 0.3),
            "dominance": kwargs.get("dominance", 0.0),
        }
    if "drives" in kwargs:
        payload["drives"] = kwargs["drives"]
    for key, value in kwargs.items():
        if key.endswith("_learning_progress"):
            payload[key] = value
    return Event(
        source="affect",
        type="affect.state",
        payload=payload,
        salience=0.1,
        timestamp=datetime.now(timezone.utc),
    )


def _interest_scorer(drives, learning_progress, **kwargs):
    return InterestGoalScorer(lambda: drives, lambda: learning_progress, **kwargs)


class _FixedGoalScorer:
    def __init__(self, value: float) -> None:
        self._value = value

    async def relevance(self, event: Event) -> float:
        return self._value


@pytest.mark.asyncio
async def test_interest_returns_one_when_no_curiosity():
    s = _interest_scorer({"curiosity": 0.0}, {"vision": 0.9})
    assert await s.relevance(_event("vision", 0.5)) == 1.0


@pytest.mark.asyncio
async def test_interest_returns_one_when_curiosity_missing():
    s = _interest_scorer({}, {"vision": 0.9})
    assert await s.relevance(_event("vision", 0.5)) == 1.0


@pytest.mark.asyncio
async def test_interest_returns_one_for_sources_without_learning_progress():
    s = _interest_scorer({"curiosity": 0.96}, {"vision": 0.9})
    for source in ("affect", "sequence", "interoception", "language"):
        assert await s.relevance(_event(source, 0.5)) == 1.0


@pytest.mark.asyncio
async def test_interest_returns_one_when_progress_missing_none_or_below_floor():
    s = _interest_scorer({"curiosity": 0.96}, {"vision": None}, floor=0.05)
    assert await s.relevance(_event("vision", 0.5)) == 1.0

    s2 = _interest_scorer({"curiosity": 0.96}, {}, floor=0.05)
    assert await s2.relevance(_event("vision", 0.5)) == 1.0

    s3 = _interest_scorer({"curiosity": 0.96}, {"vision": 0.04}, floor=0.05)
    assert await s3.relevance(_event("vision", 0.5)) == 1.0


@pytest.mark.asyncio
async def test_interest_formula_and_clamping():
    s = _interest_scorer({"curiosity": 0.96}, {"vision": 0.9}, gain=0.5, floor=0.05)
    expected = 1.0 + 0.5 * 0.96 * ((0.9 - 0.05) / (1.0 - 0.05))
    assert await s.relevance(_event("vision", 0.5)) == pytest.approx(expected)

    # Learning progress above 1 is clamped to 1.
    s2 = _interest_scorer({"curiosity": 0.96}, {"vision": 2.0}, gain=0.5, floor=0.05)
    expected_clamped_lp = 1.0 + 0.5 * 0.96 * ((1.0 - 0.05) / (1.0 - 0.05))
    assert await s2.relevance(_event("vision", 0.5)) == pytest.approx(expected_clamped_lp)

    # Curiosity above 1 is clamped to 1.
    s3 = _interest_scorer({"curiosity": 1.5}, {"vision": 0.9}, gain=0.5, floor=0.05)
    expected_clamped_drive = 1.0 + 0.5 * 1.0 * ((0.9 - 0.05) / (1.0 - 0.05))
    assert await s3.relevance(_event("vision", 0.5)) == pytest.approx(expected_clamped_drive)

    # Zero gain forces exactly 1.0.
    s4 = _interest_scorer({"curiosity": 0.96}, {"vision": 0.9}, gain=0.0, floor=0.05)
    assert await s4.relevance(_event("vision", 0.5)) == 1.0


def test_interest_rejects_invalid_constructor_args():
    with pytest.raises(ValueError):
        _interest_scorer({}, {}, gain=-0.1)
    with pytest.raises(ValueError):
        _interest_scorer({}, {}, gain=float("inf"))
    with pytest.raises(ValueError):
        _interest_scorer({}, {}, gain=float("nan"))
    with pytest.raises(ValueError):
        _interest_scorer({}, {}, floor=1.0)
    with pytest.raises(ValueError):
        _interest_scorer({}, {}, floor=-0.1)


@pytest.mark.asyncio
async def test_rule_based_salience_allows_goal_above_one():
    novelty = NoveltyTracker(window=10)
    goal = _FixedGoalScorer(1.5)
    affect = StaticAffectModulator()
    salience = RuleBasedSalience(novelty, goal, affect)

    high = await salience.score(_event("vision", 0.7), {})
    assert high == 1.0

    medium = await salience.score(_event("audition", 0.4), {})
    assert medium == pytest.approx(0.6)


@pytest.mark.asyncio
async def test_rule_based_salience_rejects_negative_or_nan_goal():
    affect = StaticAffectModulator()

    negative = RuleBasedSalience(NoveltyTracker(window=10), _FixedGoalScorer(-0.2), affect)
    assert await negative.score(_event("vision", 0.7), {}) == 0.0

    nan = RuleBasedSalience(NoveltyTracker(window=10), _FixedGoalScorer(float("nan")), affect)
    assert await nan.score(_event("vision", 0.7), {}) == 0.0


@pytest.mark.asyncio
async def test_rule_based_salience_rejects_infinite_goal():
    affect = StaticAffectModulator()

    infinite = RuleBasedSalience(NoveltyTracker(window=10), _FixedGoalScorer(float("inf")), affect)
    assert await infinite.score(_event("vision", 0.7), {}) == 0.0
    assert await infinite.score(_event("vision", 0.0), {}) == 0.0


@pytest.mark.asyncio
async def test_static_goal_scorer_score_unchanged_after_unclipping():
    novelty = NoveltyTracker(window=10)
    goal = StaticGoalScorer(0.8)
    affect = StaticAffectModulator()
    salience = RuleBasedSalience(novelty, goal, affect)

    score = await salience.score(_event("vision", 0.7), {})
    assert score == pytest.approx(0.8 * 0.7)


@pytest.mark.asyncio
async def test_drive_relevance_score_unchanged_after_unclipping():
    goal = DriveRelevanceGoalScorer(lambda: {}, drive_sources=build_drive_sources({}))
    assert await goal.relevance(_event("vision", 0.5)) == 1.0


def test_affect_state_provider_folds_per_source_learning_progress():
    provider = AffectStateProvider()
    provider.observe([
        ("affect", _affect_state(vision_learning_progress=0.6, audition_learning_progress=-0.2)),
    ])
    assert provider.learning_progress() == {"vision": 0.6, "audition": -0.2}


def test_affect_state_provider_ignores_non_per_source_keys_and_invalid_values():
    provider = AffectStateProvider()
    provider.observe([
        ("affect", _affect_state(
            learning_progress=0.9,
            signed_learning_progress=0.8,
            vision_learning_progress=None,
            audition_learning_progress=True,
            interoception_learning_progress=0.4,
        )),
    ])
    assert provider.learning_progress() == {"interoception": 0.4}


def test_affect_state_provider_keeps_last_mapping_when_no_lp_keys():
    provider = AffectStateProvider()
    provider.observe([("affect", _affect_state(vision_learning_progress=0.6))])
    provider.observe([("affect", _affect_state(drives={"curiosity": 1.0}))])
    assert provider.learning_progress() == {"vision": 0.6}


def test_affect_state_provider_replaces_when_later_has_keys():
    provider = AffectStateProvider()
    provider.observe([("affect", _affect_state(vision_learning_progress=0.6))])
    provider.observe([("affect", _affect_state(audition_learning_progress=0.3))])
    assert provider.learning_progress() == {"audition": 0.3}


def test_affect_state_provider_learning_progress_returns_copy():
    provider = AffectStateProvider()
    provider.observe([("affect", _affect_state(vision_learning_progress=0.6))])
    copy = provider.learning_progress()
    copy["vision"] = 99.0
    assert provider.learning_progress() == {"vision": 0.6}


@pytest.mark.asyncio
async def test_make_salience_factors_interest():
    provider = AffectStateProvider()
    provider.observe([
        ("affect", _affect_state(drives={"curiosity": 1.0}, vision_learning_progress=0.55)),
    ])
    _, goal, _ = make_salience_factors(
        {
            "workspace": {
                "salience_goal_factor": "interest",
                "interest_gain": 0.25,
                "salience_affect_factor": "static",
            },
            "affect": {"learning_progress_floor": 0.1},
        },
        provider,
        drive_sources={},
    )
    assert isinstance(goal, InterestGoalScorer)
    # lp_plus = (0.55 - 0.1) / (1 - 0.1) = 0.5
    assert await goal.relevance(_event("vision", 0.5)) == pytest.approx(1.0 + 0.25 * 0.5)


def test_make_salience_factors_rejects_negative_interest_gain():
    provider = AffectStateProvider()
    with pytest.raises(ConfigurationError):
        make_salience_factors(
            {
                "workspace": {
                    "salience_goal_factor": "interest",
                    "interest_gain": -0.1,
                    "salience_affect_factor": "static",
                },
            },
            provider,
            drive_sources={},
        )


def test_make_salience_factors_rejects_unknown_goal_factor():
    provider = AffectStateProvider()
    with pytest.raises(ConfigurationError) as exc_info:
        make_salience_factors(
            {
                "workspace": {
                    "salience_goal_factor": "mystery",
                    "salience_affect_factor": "static",
                },
            },
            provider,
            drive_sources={},
        )
    msg = str(exc_info.value)
    assert "drive_relevance" in msg
    assert "interest" in msg
    assert "static" in msg


def test_make_salience_factors_drive_relevance_still_works():
    provider = AffectStateProvider()
    _, goal, _ = make_salience_factors(
        {
            "workspace": {
                "salience_goal_factor": "drive_relevance",
                "salience_affect_factor": "static",
            },
        },
        provider,
        drive_sources=build_drive_sources({"vision": {"curiosity"}}),
    )
    assert isinstance(goal, DriveRelevanceGoalScorer)
