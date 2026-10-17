# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The workspace-feedback ablation arms are selectable by study (paper §6.4)."""

import tomllib
from pathlib import Path

import pytest

from kaine.boot.feedback import make_workspace_feedback
from kaine.config import load_kaine_config

REPO = Path(__file__).resolve().parents[1]
_MISSING = "/nonexistent-operator-for-tests.toml"

ARMS = ["off", "head_only", "head_gain", "full", "matched_random"]


def _load_feedback_study(arm):
    return load_kaine_config(
        REPO / "config" / "kaine.toml",
        _MISSING,
        profile="first_configuration",
        profiles_dir=REPO / "config" / "profiles",
        study=f"workspace_feedback_{arm}",
        studies_dir=REPO / "config" / "studies",
    )


@pytest.mark.parametrize("arm", ARMS)
def test_feedback_study_config(arm):
    cfg = _load_feedback_study(arm)
    assert cfg["workspace"]["feedback"]["enabled"] is True
    assert cfg["workspace"]["feedback"]["arm"] == arm
    assert cfg["workspace"]["arm"] == "competitive"
    assert cfg["language"]["temperature"] == 0.0


@pytest.mark.parametrize("arm", ARMS)
def test_feedback_study_builder(arm):
    cfg = _load_feedback_study(arm)
    refusal = bool(
        cfg.get("oscillator", {}).get("enabled")
        or cfg.get("positive_control", {}).get("enabled")
    )

    # The first configuration runs with the coherence layer and the positive control off.
    assert not refusal

    if arm == "off":
        assert make_workspace_feedback(cfg, seed=1) is None
        return

    fb = make_workspace_feedback(cfg, seed=1)
    assert fb is not None
    assert fb.arm == arm


def test_shipped_feedback_is_disabled():
    cfg = load_kaine_config(
        REPO / "config" / "kaine.toml",
        _MISSING,
        profile="first_configuration",
        profiles_dir=REPO / "config" / "profiles",
    )
    assert cfg["workspace"]["feedback"]["enabled"] is False
    assert make_workspace_feedback(cfg, seed=1) is None


def test_workspace_mediation_studies_unchanged():
    for path in sorted((REPO / "config" / "studies").glob("workspace_mediation_*.toml")):
        with path.open("rb") as fh:
            data = tomllib.load(fh)
        workspace = data.get("workspace", {})
        assert "feedback" not in workspace
