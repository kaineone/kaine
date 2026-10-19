# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boot-path tests for the interest goal factor."""
from __future__ import annotations

import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

import kaine.cycle.__main__ as cyc
from kaine.bus.schema import Event
from kaine.config import deep_merge, load_kaine_config
from kaine.cycle.boot_context import BootContext
from kaine.modules.registry import ModuleRegistry
from kaine.workspace import InterestGoalScorer, StaticGoalScorer

_MISSING = "/nonexistent-operator-for-tests.toml"
_REPO = Path(__file__).resolve().parents[1]

_STUDY_NAMES = (
    "workspace_mediation_competitive",
    "workspace_mediation_matched",
    "workspace_mediation_pilot_competitive",
    "workspace_mediation_pilot_matched",
    "workspace_mediation_pilot_pooled",
    "workspace_mediation_pilot_tone",
    "workspace_mediation_pooled",
    "workspace_mediation_positive_control",
    "workspace_mediation_preliminary",
    "workspace_mediation_tone",
)


def test_first_configuration_selects_interest_goal_factor():
    cfg = load_kaine_config(profile="first_configuration", operator_path=_MISSING)
    assert cfg["workspace"]["salience_goal_factor"] == "interest"
    assert cfg["workspace"]["interest_gain"] == 0.5


def test_shipped_config_keeps_static_goal_factor():
    cfg = load_kaine_config(operator_path=_MISSING)
    assert cfg["workspace"]["salience_goal_factor"] == "static"
    assert cfg["workspace"]["interest_gain"] == 0.5


def test_study_goal_factor_coverage():
    studies_dir = _REPO / "config" / "studies"
    found = {p.stem for p in studies_dir.glob("workspace_mediation_*.toml")}
    assert found == set(_STUDY_NAMES)


@pytest.mark.parametrize("study_name", _STUDY_NAMES)
def test_study_overrides_goal_factor_to_static(study_name):
    cfg = load_kaine_config(
        profile="first_configuration",
        operator_path=_MISSING,
        study=study_name,
        studies_dir=_REPO / "config" / "studies",
    )
    assert cfg["workspace"]["salience_goal_factor"] == "static"


@pytest.mark.asyncio
async def test_boot_path_uses_interest_goal_scorer(monkeypatch):
    monkeypatch.chdir(_REPO)
    cfg = load_kaine_config(profile="first_configuration", operator_path=_MISSING)
    ctx = BootContext(
        kaine_config=cfg,
        registry=ModuleRegistry(),
        run_ctx=types.SimpleNamespace(seed=3),
    )
    assert await cyc._phase_workspace(ctx) is None

    goal = ctx.workspace._strategy._goal
    assert isinstance(goal, InterestGoalScorer)
    assert ctx.affect_observer is not None

    affect_event = Event(
        source="affect",
        type="affect.state",
        payload={
            "state": {"valence": 0.0, "arousal": 0.3, "dominance": 0.0},
            "drives": {"curiosity": 1.0},
            "vision_learning_progress": 0.55,
        },
        salience=0.0,
        timestamp=datetime.now(timezone.utc),
    )
    ctx.affect_observer([("affect.out:1-0", affect_event)])

    vision_event = Event(
        source="vision",
        type="perception",
        payload={},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    sequence_event = Event(
        source="sequence",
        type="narrative",
        payload={},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )

    assert await goal.relevance(vision_event) == pytest.approx(1 + 0.5 * (0.55 - 0.05) / 0.95)
    assert await goal.relevance(sequence_event) == 1.0


@pytest.mark.asyncio
async def test_study_override_restores_static_goal_scorer(monkeypatch):
    monkeypatch.chdir(_REPO)
    cfg = load_kaine_config(
        profile="first_configuration",
        operator_path=_MISSING,
        study="workspace_mediation_competitive",
        studies_dir=_REPO / "config" / "studies",
    )
    ctx = BootContext(
        kaine_config=cfg,
        registry=ModuleRegistry(),
        run_ctx=types.SimpleNamespace(seed=3),
    )
    assert await cyc._phase_workspace(ctx) is None
    assert isinstance(ctx.workspace._strategy._goal, StaticGoalScorer)


@pytest.mark.asyncio
async def test_interest_factor_alone_keeps_the_affect_snapshot_live(monkeypatch):
    monkeypatch.chdir(_REPO)
    for goal_factor in ("static", "interest"):
        cfg = deep_merge(
            load_kaine_config(profile="first_configuration", operator_path=_MISSING),
            {
                "workspace": {
                    "salience_affect_factor": "static",
                    "salience_goal_factor": goal_factor,
                    "regulation_bias": False,
                },
                "cycle": {
                    "access_rate": {
                        "enabled": False,
                    },
                },
            },
        )
        ctx = BootContext(
            kaine_config=cfg,
            registry=ModuleRegistry(),
            run_ctx=types.SimpleNamespace(seed=3),
        )
        assert await cyc._phase_workspace(ctx) is None

        if goal_factor == "static":
            assert ctx.affect_observer is None
        else:
            assert ctx.affect_observer is not None
