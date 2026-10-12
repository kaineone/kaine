# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the workspace-mediation planned-test studies and boot gate."""

from __future__ import annotations

from pathlib import Path

import pytest

import kaine.cycle.__main__ as cyc
from kaine.config import SHIPPED_CONFIG_PATH, load_kaine_config, load_runtime_config
from kaine.cycle.boot_context import BootContext
from kaine.evaluation.observers.research_event_observer import _workspace_metadata_record
from kaine.experiment.planned_test_settings import planned_test_refusal
from kaine.workspace.core import Workspace

REPO_ROOT = Path(__file__).resolve().parents[1]
STUDIES_DIR = REPO_ROOT / "config" / "studies"


class _StubEvent:
    __slots__ = ("entry_id", "salience")

    def __init__(self, entry_id: str, salience: float) -> None:
        self.entry_id = entry_id
        self.salience = salience


class _StubStrategy:
    async def score(self, event, context):
        return event.salience


@pytest.mark.parametrize(
    "study, role, arm, pc_mode, pc_settings, principal_components_run",
    [
        ("workspace_mediation_competitive", "test", "competitive", None, None, None),
        ("workspace_mediation_matched", "test", "matched", None, None, None),
        ("workspace_mediation_pooled", "test", "pooled", None, None, None),
        (
            "workspace_mediation_preliminary",
            "preliminary",
            "competitive",
            "estimate_pc",
            None,
            None,
        ),
        (
            "workspace_mediation_pilot_competitive",
            "pilot",
            "competitive",
            "ladder",
            None,
            "",
        ),
        ("workspace_mediation_pilot_matched", "pilot", "matched", None, None, None),
        ("workspace_mediation_pilot_pooled", "pilot", "pooled", None, None, None),
        ("workspace_mediation_tone", "test", "competitive", None, None, None),
        ("workspace_mediation_pilot_tone", "pilot", "competitive", None, None, None),
        (
            "workspace_mediation_positive_control",
            "positive_control",
            "competitive",
            "control",
            "config/studies/workspace_mediation_settings.json",
            None,
        ),
    ],
)
def test_study_configuration(
    study, role, arm, pc_mode, pc_settings, principal_components_run
):
    cfg = load_kaine_config(
        operator_path="/nonexistent-operator-for-tests.toml",
        study=study,
        studies_dir=STUDIES_DIR,
    )
    assert cfg["lingua"]["temperature"] == 0.0
    assert cfg["syneidesis"]["arm"] == arm
    assert cfg["planned_test"]["role"] == role
    if role in ("test", "positive_control"):
        assert (
            cfg["planned_test"]["settings_record"]
            == "config/studies/workspace_mediation_settings.json"
        )
    if pc_mode is not None:
        assert cfg["positive_control"]["enabled"] is True
        assert cfg["positive_control"]["mode"] == pc_mode
        if pc_settings is not None:
            assert cfg["positive_control"]["settings_record"] == pc_settings
        if principal_components_run is not None:
            assert cfg["positive_control"]["principal_components_run"] == principal_components_run
    else:
        # The shipped configuration keeps the control off; only some studies enable it.
        assert cfg["positive_control"]["enabled"] is False

    assert cfg["audition"]["tone_rule"] == (
        "error_ratio" if study.endswith("_tone") else "categorical"
    )

@pytest.mark.asyncio
async def test_boot_refuses_live_arm_without_settings_record(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(REPO_ROOT)
    monkeypatch.setenv("KAINE_STUDY", "workspace_mediation_competitive")
    cfg = load_runtime_config(
        SHIPPED_CONFIG_PATH,
        "/nonexistent-operator-for-tests.toml",
        study="workspace_mediation_competitive",
        env={},
    )
    cfg["planned_test"]["settings_record"] = str(tmp_path / "missing.json")
    ctx = BootContext(kaine_config=cfg)
    result = await cyc._phase_run_identity(ctx)
    assert result == cyc.PLANNED_TEST_REFUSED_EXIT
    assert "settings record" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_competitive_snapshot_carries_coalition_capacity():
    syn = Workspace(_StubStrategy(), arm="competitive")
    events = [("e1", _StubEvent("e1", 0.9)), ("e2", _StubEvent("e2", 0.8))]
    snapshot = await syn.select(events, {"tick_index": 1, "is_experiential": True})
    assert snapshot.metadata["coalition_capacity"] == syn._top_k


@pytest.mark.asyncio
async def test_competitive_empty_snapshot_carries_coalition_capacity():
    syn = Workspace(_StubStrategy(), arm="competitive")
    snapshot = await syn.select([], {"tick_index": 1, "is_experiential": True})
    assert snapshot.metadata["coalition_capacity"] == syn._top_k


@pytest.mark.asyncio
async def test_matched_snapshot_carries_coalition_capacity():
    syn = Workspace(_StubStrategy(), arm="matched", arm_seed=123)
    events = [("e1", _StubEvent("e1", 0.9)), ("e2", _StubEvent("e2", 0.8))]
    snapshot = await syn.select(events, {"tick_index": 1, "is_experiential": True})
    assert snapshot.metadata["coalition_capacity"] == syn._top_k


def test_workspace_metadata_record_copies_coalition_capacity():
    record = _workspace_metadata_record(
        {"metadata": {"arm": "competitive", "coalition_capacity": 7}}
    )
    assert record["coalition_capacity"] == 7


def test_gate_refuses_a_study_with_the_wrong_tone_rule():
    refusal = planned_test_refusal(
        "workspace_mediation_pilot_competitive",
        {"planned_test": {"role": "pilot"}, "audition": {"tone_rule": "error_ratio"}},
        0,
    )
    assert isinstance(refusal, str)
    assert "tone rule" in refusal

    refusal = planned_test_refusal(
        "workspace_mediation_pilot_tone",
        {"planned_test": {"role": "pilot"}},
        0,
    )
    assert isinstance(refusal, str)
    assert "error_ratio" in refusal

    assert (
        planned_test_refusal(
            "workspace_mediation_pilot_tone",
            {"planned_test": {"role": "pilot"}, "audition": {"tone_rule": "error_ratio"}},
            0,
        )
        is None
    )
