# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Every shipped study file enables the module supervisor.

A research run selected through ``KAINE_STUDY`` must pass the research gate's
supervisor condition whatever the operator config says, so every file under
``config/studies/`` sets ``[supervisor].enabled = true``. A study may switch
the supervisor on, never off.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from kaine.config import ProfileError, _load_merged_config

REPO_ROOT = Path(__file__).resolve().parents[1]
STUDIES = REPO_ROOT / "config" / "studies"


def _study_files() -> list[Path]:
    return sorted(STUDIES.glob("*.toml"))


def test_there_are_study_files():
    assert _study_files(), "no shipped study files found"


def test_every_shipped_study_file_enables_the_supervisor():
    missing = []
    for path in _study_files():
        data = tomllib.loads(path.read_text())
        if (data.get("supervisor") or {}).get("enabled") is not True:
            missing.append(path.name)
    assert not missing, f"study files without [supervisor].enabled = true: {missing}"


@pytest.mark.parametrize("path", _study_files(), ids=lambda p: p.stem)
def test_every_study_loads_with_the_supervisor_on(path, tmp_path):
    config = _load_merged_config(
        REPO_ROOT / "config" / "kaine.toml",
        tmp_path / "absent.operator.toml",
        study=path.stem,
        studies_dir=STUDIES,
    )
    assert config["supervisor"]["enabled"] is True


def test_a_study_may_not_switch_the_supervisor_off(tmp_path):
    studies = tmp_path / "studies"
    studies.mkdir()
    (studies / "quiet.toml").write_text("[supervisor]\nenabled = false\n")
    with pytest.raises(ProfileError, match="only switch the module supervisor on"):
        _load_merged_config(
            REPO_ROOT / "config" / "kaine.toml",
            tmp_path / "absent.operator.toml",
            study="quiet",
            studies_dir=studies,
        )


def test_a_study_may_not_retune_the_supervisor(tmp_path):
    studies = tmp_path / "studies"
    studies.mkdir()
    (studies / "retune.toml").write_text(
        "[supervisor]\nenabled = true\nmax_restart_attempts = 0\n"
    )
    with pytest.raises(ProfileError, match="may set only enabled in \\[supervisor\\]"):
        _load_merged_config(
            REPO_ROOT / "config" / "kaine.toml",
            tmp_path / "absent.operator.toml",
            study="retune",
            studies_dir=studies,
        )
