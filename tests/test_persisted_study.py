# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import copy
import hashlib
import json
from pathlib import Path

import pytest

from kaine import legacy_aliases, legacy_names
from kaine.research.ignition_study.plan import validate_plan
from kaine.research.ignition_study.runner import StudyError, StudyRunner

BASE_MODULES = [
    "interoception",
    "sequence",
    "vision",
    "audition",
    "language",
    "affect",
    "sleep",
]

ORDER = [
    "episodic_memory",
    "world_model",
    "planning",
    "self_model",
    "social_cognition",
    "vocal",
    "effectors",
    "perceptual_locus",
    "embodiment",
]

OLD_LINE = next(e["old"] for e in legacy_names.STAGE_VALUES if e["new"] == "development")
OLD_MATURATION = next(
    e["old"] for e in legacy_names.STORED_TAGS if e["new"] == "maturation"
)
OLD_FAILED_DEV_UNVIABLE = next(
    e["old"]
    for e in legacy_names.STORED_TAGS
    if e["new"] == "failed:development_unviable"
)


@pytest.fixture
def known_modules(monkeypatch):
    names = [
        "recorder",
        "interoception",
        "sequence",
        "vision",
        "planning",
        "episodic_memory",
        "self_model",
        "affect",
        "effectors",
        "language",
        "vocal",
        "audition",
        "sleep",
        "social_cognition",
        "world_model",
        "perceptual_locus",
        "embodiment",
    ]
    monkeypatch.setattr("kaine.boot.known_module_names", lambda: names)
    monkeypatch.setenv("KAINE_REDIS_PASSWORD", "test-redis-pw")
    monkeypatch.delenv("KAINE_REDIS_USERNAME", raising=False)
    monkeypatch.delenv("KAINE_REDIS_URL", raising=False)
    for name in (
        "IGNITION_STANDIN_SCENARIO",
        "IGNITION_STANDIN_MANIFEST",
        "IGNITION_STANDIN_BLOOM_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    return names


@pytest.fixture
def rename_done(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "done")
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "done")


def _write_repo(repo_root: Path) -> None:
    cfg = repo_root / "config"
    cfg.mkdir(parents=True)
    (cfg / "profiles").mkdir()
    (cfg / "kaine.toml").write_text(
        "[modules]\n"
        "echo = false\n"
        "interoception = false\n"
        "[vision]\n"
        'encoder_local_dir = "state/models"\n'
    )


def _valid_plan(tmp_path: Path, old_line: str | None = None) -> dict:
    repo_root = tmp_path / "repo"
    _write_repo(repo_root)
    manifest = repo_root / "programme.toml"
    manifest.write_text("[programme]\n")
    sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    plan = {
        "study_id": "persisted-test",
        "repo_root": str(repo_root),
        "base_modules": BASE_MODULES,
        "order": ORDER[:2],
        "programme": {"manifest": str(manifest), "sha256": sha},
        "redis": {
            "base_url": "redis://127.0.0.1:6479",
            "db": {
                "development": 10,
                "branch": 11,
                "repeat": 12,
                "accumulate": 13,
            },
        },
        "collections": {
            "development": "r_g_",
            "branch": "r_b_",
            "repeat": "r_r_",
            "accumulate": "r_a_",
        },
        "viewing_budget_seconds": 5.0,
        "development_budget_seconds": 5.0,
    }
    validated = validate_plan(plan)
    if old_line is not None:
        validated = copy.deepcopy(validated)
        validated["redis"]["db"][old_line] = validated["redis"]["db"].pop("development")
        validated["collections"][old_line] = validated["collections"].pop("development")
        validated[f"{old_line}_budget_seconds"] = validated.pop(
            "development_budget_seconds"
        )
    return validated


def test_map_study_plan(rename_done):
    plan = {
        "redis": {"db": {OLD_LINE: 10, "branch": 11}},
        "collections": {OLD_LINE: "r_g_", "branch": "r_b_"},
        f"{OLD_LINE}_budget_seconds": 3600,
        "voice_alignment_steps": [
            {"line": OLD_LINE, "k": 1},
            {"line": "accumulate", "k": 2},
        ],
        "other": "keep",
    }
    original = copy.deepcopy(plan)
    mapped = legacy_aliases.map_study_plan(plan)
    assert mapped["redis"]["db"] == {"development": 10, "branch": 11}
    assert mapped["collections"] == {"development": "r_g_", "branch": "r_b_"}
    assert f"{OLD_LINE}_budget_seconds" not in mapped
    assert mapped["development_budget_seconds"] == 3600
    assert [step["line"] for step in mapped["voice_alignment_steps"]] == [
        "development",
        "accumulate",
    ]
    assert mapped["other"] == "keep"
    assert plan == original


def test_map_study_plan_inert_when_pending(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "keys", "pending")
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "pending")
    plan = {
        f"{OLD_LINE}_budget_seconds": 3600,
        "voice_alignment_steps": [{"line": OLD_LINE, "k": 1}],
    }
    assert legacy_aliases.map_study_plan(plan) is plan


def test_map_study_step(rename_done):
    rec = {
        "line": OLD_LINE,
        "step": 0,
        "outcome": OLD_FAILED_DEV_UNVIABLE,
        "extra": "x",
    }
    original = copy.deepcopy(rec)
    mapped = legacy_aliases.map_study_step(rec)
    assert mapped == {
        "line": "development",
        "step": 0,
        "outcome": "failed:development_unviable",
        "extra": "x",
    }
    assert rec == original


def test_map_study_step_inert_when_pending(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "pending")
    rec = {"line": OLD_LINE, "outcome": OLD_FAILED_DEV_UNVIABLE}
    assert legacy_aliases.map_study_step(rec) is rec


def test_runner_renames_old_line_dir(
    tmp_path: Path, known_modules, rename_done
) -> None:
    study_dir = tmp_path / "study"
    study_dir.mkdir(parents=True)
    old_dir = study_dir / OLD_LINE
    new_dir = study_dir / "development"

    plan = _valid_plan(tmp_path, old_line=OLD_LINE)
    (study_dir / "study.json").write_text(json.dumps(plan))

    (old_dir / "state").mkdir(parents=True)
    bundle_dir = old_dir / "backups" / "b1"
    bundle_dir.mkdir(parents=True)
    (study_dir / "steps.jsonl").write_text(
        json.dumps(
            {
                "line": OLD_LINE,
                "step": 0,
                "outcome": "complete",
                "bundle": str(bundle_dir),
            }
        )
        + "\n"
    )

    runner = StudyRunner(study_dir, flush_db=lambda url: None)

    assert not old_dir.exists()
    assert new_dir.exists()
    assert (new_dir / "state").exists()
    expected_bundle = str(new_dir / "backups" / "b1")
    assert ("development", 0) in runner.completed_steps
    assert runner.line_bundles[("development", 0)] == expected_bundle
    assert Path(runner.line_bundles[("development", 0)]).exists()


def test_runner_both_line_dirs_raise(
    tmp_path: Path, known_modules, rename_done
) -> None:
    study_dir = tmp_path / "study"
    study_dir.mkdir(parents=True)
    plan = _valid_plan(tmp_path)
    (study_dir / "study.json").write_text(json.dumps(plan))

    old_dir = study_dir / OLD_LINE
    new_dir = study_dir / "development"
    old_dir.mkdir()
    new_dir.mkdir()

    with pytest.raises(StudyError):
        StudyRunner(study_dir, flush_db=lambda url: None)

    assert old_dir.exists()
    assert new_dir.exists()
