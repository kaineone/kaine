# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""A study step's real merged config must satisfy the research gate's config checks.

Builds the config the way a study child sees it: the shipped config/kaine.toml
with the per-step study overlay on top, and checks every requirement the
research safety-net gate reads from config. The operator supplies the state key
and the Redis password, so those are not part of the config checks.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from kaine.config import _load_merged_config, deep_merge
from kaine.cycle.research_gate import config_requirements
from kaine.research.ignition_study.overlay import build_overlay

REPO_ROOT = Path(__file__).resolve().parents[1]
SHIPPED = REPO_ROOT / "config" / "kaine.toml"

STEPS = [
    ("development", "development", 0),
    ("branch", "viewing", 0),
    ("branch", "viewing", 1),
    ("repeat", "viewing", 0),
    ("accumulate", "viewing", 1),
]


def _plan() -> dict:
    return {
        "study_id": "gate-test",
        "repo_root": str(REPO_ROOT),
        "base_modules": ["interoception", "sequence", "vision", "audition", "language", "affect", "sleep"],
        "order": ["episodic_memory", "self_model"],
        "programme": {"manifest": "programme.toml", "sha256": "a" * 64},
        "redis": {
            "base_url": "redis://127.0.0.1:6479",
            "db": {"development": 10, "branch": 11, "repeat": 12, "accumulate": 13},
        },
        "collections": {"development": "g_", "branch": "b_", "repeat": "r_", "accumulate": "a_"},
    }


def _step_config(tmp_path: Path, line: str, kind: str, k: int, operator_toml: str | None) -> dict:
    operator = tmp_path / "kaine.operator.toml"
    if operator_toml is not None:
        operator.write_text(operator_toml)
    overlay, _, _ = build_overlay(_plan(), line, kind, k, REPO_ROOT, SHIPPED, operator)
    # The child loads shipped config, then the step overlay in the operator layer.
    shipped = _load_merged_config(SHIPPED, tmp_path / "absent.operator.toml")
    return deep_merge(shipped, overlay)


@pytest.mark.parametrize(("line", "kind", "k"), STEPS)
def test_study_step_config_meets_every_config_requirement(tmp_path, line, kind, k):
    config = _step_config(tmp_path, line, kind, k, None)
    assert config_requirements(config) == {
        "preservation_enabled": True,
        "welfare_response_wired": True,
        "logging_active": True,
        "encryption_satisfied": True,
        "individuation_enabled": True,
    }


def test_operator_cannot_switch_individuation_off_for_a_step(tmp_path):
    config = _step_config(
        tmp_path, "development", "development", 0,
        "[individuation]\nenabled = false\n[preservation.welfare_response]\nenabled = false\n",
    )
    assert all(config_requirements(config).values())


def test_shipped_config_alone_fails_individuation_requirement():
    shipped = _load_merged_config(SHIPPED, Path("/nonexistent/kaine.operator.toml"))
    assert config_requirements(shipped)["individuation_enabled"] is False
