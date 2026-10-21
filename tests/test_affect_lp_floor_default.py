# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the default learning-progress floor lp_0 = 0.20 (paper A.4, Table A1)."""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from kaine.boot import make_salience_factors
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.affect_state import AffectStateProvider
from kaine.modules.affect import Affect
from kaine.workspace.strategies import InterestGoalScorer
from tests.test_interest_goal_factor import _affect_state, _event


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.mark.asyncio
async def test_affect_default_learning_progress_floor(bus) -> None:
    affect = Affect(bus)
    assert affect._learning_progress_floor == 0.20


def test_shipped_config_learning_progress_floor() -> None:
    root = Path(__file__).resolve().parents[1]
    with (root / "config" / "kaine.toml").open("rb") as handle:
        config = tomllib.load(handle)
    assert config["affect"]["learning_progress_floor"] == 0.20


@pytest.mark.asyncio
async def test_make_salience_factors_interest_default_floor() -> None:
    provider = AffectStateProvider()
    provider.observe([
        ("affect", _affect_state(drives={"curiosity": 1.0}, vision_learning_progress=0.6)),
    ])
    _, goal, _ = make_salience_factors(
        {
            "workspace": {
                "salience_goal_factor": "interest",
                "interest_gain": 0.25,
                "salience_affect_factor": "static",
            },
        },
        provider,
        drive_sources={},
    )
    assert isinstance(goal, InterestGoalScorer)
    # lp_plus = (0.6 - 0.20) / (1 - 0.20) = 0.5 with the default floor
    expected = 1.0 + 0.25 * (0.6 - 0.20) / (1 - 0.20)
    assert await goal.relevance(_event("vision", 0.5)) == pytest.approx(expected)


@pytest.mark.asyncio
async def test_make_salience_factors_interest_below_default_floor() -> None:
    provider = AffectStateProvider()
    provider.observe([
        ("affect", _affect_state(drives={"curiosity": 1.0}, vision_learning_progress=0.15)),
    ])
    _, goal, _ = make_salience_factors(
        {
            "workspace": {
                "salience_goal_factor": "interest",
                "interest_gain": 0.25,
                "salience_affect_factor": "static",
            },
        },
        provider,
        drive_sources={},
    )
    assert isinstance(goal, InterestGoalScorer)
    # 0.15 is below the default 0.20 floor, so lp_plus clamps to 0.0
    assert await goal.relevance(_event("vision", 0.5)) == 1.0
