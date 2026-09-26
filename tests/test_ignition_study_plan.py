# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from kaine.research.ignition_study.plan import (
    DEFAULT_GESTATION_BUDGET_SECONDS,
    DEFAULT_VIEWING_BUDGET_SECONDS,
    LINES,
    init_study,
    load_plan,
    validate_plan,
)


@pytest.fixture
def known_modules(monkeypatch):
    names = [
        "echo",
        "soma",
        "chronos",
        "topos",
        "nous",
        "mnemos",
        "eidolon",
        "thymos",
        "praxis",
        "lingua",
        "vox",
        "audition",
        "hypnos",
        "empatheia",
        "phantasia",
        "perception",
        "mundus",
    ]
    monkeypatch.setattr("kaine.boot.known_module_names", lambda: names)
    return names


@pytest.fixture
def base_plan(tmp_path, known_modules):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    manifest = repo_root / "programme.toml"
    manifest.write_text("# programme manifest")
    sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return {
        "study_id": "ignite-test",
        "repo_root": str(repo_root),
        "base_modules": ["soma", "chronos", "topos", "audition", "lingua"],
        "order": ["thymos", "mnemos"],
        "programme": {"manifest": str(manifest), "sha256": sha},
        "redis": {
            "base_url": "redis://127.0.0.1:6479",
            "db": {"gestation": 10, "main": 11, "control": 12},
        },
        "collections": {"gestation": "t_g_", "main": "t_m_", "control": "t_c_"},
        "viewings_per_line": 2,
    }


def _repo_config(repo_root: Path) -> None:
    cfg = repo_root / "config"
    cfg.mkdir()
    (cfg / "kaine.toml").write_text("[modules]\n")
    (cfg / "profiles").mkdir()


def test_init_creates_layout_and_symlinks(base_plan, tmp_path):
    repo_root = Path(base_plan["repo_root"])
    _repo_config(repo_root)
    study_dir = tmp_path / "study"
    plan = validate_plan(base_plan)
    init_study(study_dir, plan)

    assert (study_dir / "study.json").exists()
    loaded = load_plan(study_dir)
    assert loaded["study_id"] == "ignite-test"
    assert loaded["viewing_budget_seconds"] == DEFAULT_VIEWING_BUDGET_SECONDS
    assert loaded["gestation_budget_seconds"] == DEFAULT_GESTATION_BUDGET_SECONDS

    for line in LINES:
        ld = study_dir / line
        assert ld.is_dir()
        assert (ld / "config" / "kaine.toml").is_symlink()
        assert (ld / "config" / "profiles").is_symlink()
        assert os.readlink(ld / "config" / "kaine.toml") == str(
            repo_root / "config" / "kaine.toml"
        )


def test_double_init_refuses(base_plan, tmp_path):
    _repo_config(Path(base_plan["repo_root"]))
    study_dir = tmp_path / "study"
    init_study(study_dir, validate_plan(base_plan))
    with pytest.raises(FileExistsError):
        init_study(study_dir, validate_plan(base_plan))


def test_validate_unknown_module(base_plan):
    base_plan["order"].append("notamodule")
    with pytest.raises(ValueError, match="Unknown module name"):
        validate_plan(base_plan)


def test_validate_duplicate_base(base_plan):
    base_plan["base_modules"] = ["soma", "soma"]
    with pytest.raises(ValueError, match="Duplicate module in base_modules"):
        validate_plan(base_plan)


def test_validate_duplicate_order(base_plan):
    base_plan["order"] = ["thymos", "thymos"]
    with pytest.raises(ValueError, match="Duplicate module in order"):
        validate_plan(base_plan)


def test_validate_base_order_overlap(base_plan):
    base_plan["order"].append("soma")
    with pytest.raises(ValueError, match="disjoint"):
        validate_plan(base_plan)


def test_validate_duplicate_db(base_plan):
    base_plan["redis"]["db"]["control"] = 11
    with pytest.raises(ValueError, match="distinct"):
        validate_plan(base_plan)


def test_validate_sha_mismatch(base_plan):
    base_plan["programme"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="sha256 mismatch"):
        validate_plan(base_plan)
