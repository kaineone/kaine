# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from kaine.research.ignition_study.__main__ import main
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
            "db": {"gestation": 10, "branch": 11, "repeat": 12, "accumulate": 13},
        },
        "collections": {"gestation": "t_g_", "branch": "t_b_", "repeat": "t_r_", "accumulate": "t_a_"},
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

    step_dirs = [study_dir / "gestation", study_dir / "repeat", study_dir / "accumulate"]
    step_dirs += [study_dir / "branch" / str(k) for k in range(len(plan["order"]) + 1)]
    assert set(LINES) == {"gestation", "branch", "repeat", "accumulate"}
    assert not (study_dir / "branch" / "config").exists()
    for ld in step_dirs:
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
    base_plan["redis"]["db"]["repeat"] = 11
    with pytest.raises(ValueError, match="distinct"):
        validate_plan(base_plan)


def test_validate_db_zero_refused(base_plan):
    base_plan["redis"]["db"]["gestation"] = 0
    with pytest.raises(ValueError, match="1..15"):
        validate_plan(base_plan)


def test_validate_db_out_of_range_refused(base_plan):
    base_plan["redis"]["db"]["gestation"] = 16
    with pytest.raises(ValueError, match="1..15"):
        validate_plan(base_plan)


def test_validate_sha_mismatch(base_plan):
    base_plan["programme"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="sha256 mismatch"):
        validate_plan(base_plan)


def test_validate_ignores_legacy_viewings_per_line(base_plan):
    base_plan["viewings_per_line"] = 2
    plan = validate_plan(base_plan)
    assert "viewings_per_line" in plan


def test_validate_db_bool_refused(base_plan):
    base_plan["redis"]["db"]["gestation"] = True
    with pytest.raises(ValueError, match="1..15"):
        validate_plan(base_plan)


def test_validate_db_operator_refused():
    from kaine.research.ignition_study.plan import validate_redis_dbs

    dbs = {"gestation": 10, "branch": 11, "repeat": 12, "accumulate": 13}
    validate_redis_dbs(dbs, {0, 3})
    with pytest.raises(ValueError, match="operator"):
        validate_redis_dbs(dbs, {0, 12})


def test_validate_collection_prefix_starting_another_refused(base_plan):
    # Branch k's prefix is "t_b_<k>_": a line prefix "t_b_1_" would share it.
    base_plan["collections"]["accumulate"] = "t_b_1_"
    with pytest.raises(ValueError, match="start with one another"):
        validate_plan(base_plan)


def test_ensure_line_dir_never_replaces_a_real_file(base_plan, tmp_path):
    from kaine.research.ignition_study.plan import ensure_line_dir

    repo_root = Path(base_plan["repo_root"])
    _repo_config(repo_root)
    study_dir = tmp_path / "study"
    ld = study_dir / "branch" / "3"
    (ld / "config").mkdir(parents=True)
    (ld / "config" / "kaine.toml").write_text("kept")
    with pytest.raises(ValueError, match="not a symlink"):
        ensure_line_dir(study_dir, "branch", 3, repo_root)
    assert (ld / "config" / "kaine.toml").read_text() == "kept"

    made = ensure_line_dir(study_dir, "branch", 4, repo_root)
    assert made == study_dir.resolve() / "branch" / "4"
    assert os.readlink(made / "config" / "kaine.toml") == str(
        repo_root.resolve() / "config" / "kaine.toml"
    )


@pytest.fixture
def nine_module_plan(base_plan):
    plan = dict(base_plan)
    plan["order"] = [
        "mnemos",
        "phantasia",
        "nous",
        "eidolon",
        "empatheia",
        "vox",
        "praxis",
        "perception",
        "mundus",
    ]
    return plan


def test_voice_alignment_default_is_final_accumulate(nine_module_plan):
    plan = validate_plan(nine_module_plan)
    assert plan["voice_alignment_steps"] == [{"line": "accumulate", "k": 9}]


def test_voice_alignment_explicit_list_kept(nine_module_plan):
    steps = [{"line": "accumulate", "k": 9}, {"line": "branch", "k": 3}]
    nine_module_plan["voice_alignment_steps"] = steps
    plan = validate_plan(nine_module_plan)
    assert plan["voice_alignment_steps"] == steps


def test_voice_alignment_gestation_refused(nine_module_plan):
    entry = {"line": "gestation", "k": 0}
    nine_module_plan["voice_alignment_steps"] = [entry]
    with pytest.raises(ValueError) as exc_info:
        validate_plan(nine_module_plan)
    assert str(entry) in str(exc_info.value)


def test_voice_alignment_out_of_range_refused(nine_module_plan):
    bad_entries = [
        {"line": "accumulate", "k": 0},
        {"line": "branch", "k": 10},
        {"line": "repeat", "k": 1},
    ]
    for entry in bad_entries:
        plan = dict(nine_module_plan)
        plan["voice_alignment_steps"] = [entry]
        with pytest.raises(ValueError) as exc_info:
            validate_plan(plan)
        assert str(entry) in str(exc_info.value)


def test_voice_alignment_duplicate_refused(nine_module_plan):
    entry = {"line": "accumulate", "k": 9}
    nine_module_plan["voice_alignment_steps"] = [entry, entry]
    with pytest.raises(ValueError) as exc_info:
        validate_plan(nine_module_plan)
    assert str(entry) in str(exc_info.value)


def test_voice_alignment_bool_k_refused(nine_module_plan):
    entry = {"line": "accumulate", "k": True}
    nine_module_plan["voice_alignment_steps"] = [entry]
    with pytest.raises(ValueError) as exc_info:
        validate_plan(nine_module_plan)
    assert str(entry) in str(exc_info.value)


def test_voice_alignment_unknown_key_refused(nine_module_plan):
    entry = {"line": "accumulate", "k": 9, "extra": 1}
    nine_module_plan["voice_alignment_steps"] = [entry]
    with pytest.raises(ValueError) as exc_info:
        validate_plan(nine_module_plan)
    assert str(entry) in str(exc_info.value)


def _nine_module_argv(nine_module_plan, study_dir):
    repo_root = Path(nine_module_plan["repo_root"])
    return [
        "init",
        "--study-id",
        nine_module_plan["study_id"],
        "--study-dir",
        str(study_dir),
        "--repo-root",
        str(repo_root),
        "--base-modules",
        *nine_module_plan["base_modules"],
        "--order",
        *nine_module_plan["order"],
        "--programme-manifest",
        nine_module_plan["programme"]["manifest"],
        "--redis-base-url",
        nine_module_plan["redis"]["base_url"],
        "--db-gestation",
        str(nine_module_plan["redis"]["db"]["gestation"]),
        "--db-branch",
        str(nine_module_plan["redis"]["db"]["branch"]),
        "--db-repeat",
        str(nine_module_plan["redis"]["db"]["repeat"]),
        "--db-accumulate",
        str(nine_module_plan["redis"]["db"]["accumulate"]),
    ]


def test_init_cli_records_voice_alignment_steps(nine_module_plan, tmp_path):
    repo_root = Path(nine_module_plan["repo_root"])
    _repo_config(repo_root)
    study_dir = tmp_path / "study"
    argv = _nine_module_argv(nine_module_plan, study_dir) + [
        "--voice-alignment-step",
        "accumulate:9",
        "--voice-alignment-step",
        "branch:9",
    ]
    assert main(argv) == 0
    plan = load_plan(study_dir)
    assert plan["voice_alignment_steps"] == [
        {"line": "accumulate", "k": 9},
        {"line": "branch", "k": 9},
    ]


def test_init_cli_malformed_voice_alignment_step_errors(nine_module_plan, tmp_path):
    repo_root = Path(nine_module_plan["repo_root"])
    _repo_config(repo_root)
    study_dir = tmp_path / "study"
    argv = _nine_module_argv(nine_module_plan, study_dir) + [
        "--voice-alignment-step",
        "accumulate",
    ]
    with pytest.raises(SystemExit) as exc_info:
        main(argv)
    assert exc_info.value.code == 2
