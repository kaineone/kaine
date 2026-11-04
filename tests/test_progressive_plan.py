# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from kaine.research.ignition_study.plan import (
    collection_prefix_for_step,
    generate_progressive_plan,
    init_study,
    step_dir_name,
    validate_plan,
)

BASE = [
    "interoception", "sequence", "vision", "audition",
    "language", "affect", "sleep",
]
ORDER = [
    "episodic_memory", "world_model", "planning",
    "self_model", "social_cognition", "vocal",
]


def test_progressive_plan_step_count():
    steps = generate_progressive_plan(ORDER, BASE)
    assert len(steps) == len(ORDER) + 1


def test_progressive_plan_step_zero_is_seed():
    steps = generate_progressive_plan(ORDER, BASE)
    s0 = steps[0]
    assert s0["kind"] == "seed"
    assert s0["step_index"] == 0
    assert s0["modules"] == BASE
    assert s0["modules_added"] == []
    assert s0["start_bundle"] is None


def test_progressive_plan_each_step_adds_one_module():
    steps = generate_progressive_plan(ORDER, BASE)
    for i, step in enumerate(steps[1:], start=1):
        assert step["kind"] == "progressive"
        assert step["step_index"] == i
        assert step["modules_added"] == [ORDER[i - 1]]
        assert set(step["modules"]) == set(BASE + ORDER[:i])


def test_progressive_plan_modules_are_progressive():
    steps = generate_progressive_plan(ORDER, BASE)
    prev = set(BASE)
    for step in steps[1:]:
        current = set(step["modules"])
        added = current - prev
        assert len(added) == 1
        assert list(added) == step["modules_added"]
        prev = current


def test_progressive_plan_broadcast_capacity():
    steps = generate_progressive_plan(ORDER, BASE, broadcast_capacity=3)
    for step in steps:
        assert step["broadcast_capacity"] == 3


def test_progressive_plan_broadcast_capacity_none():
    steps = generate_progressive_plan(ORDER, BASE)
    for step in steps:
        assert step["broadcast_capacity"] is None


def test_progressive_plan_unknown_module_rejected():
    with pytest.raises(ValueError, match="Unknown module"):
        generate_progressive_plan(["nonexistent_module"], BASE)


def test_progressive_plan_overlap_rejected():
    with pytest.raises(ValueError, match="disjoint"):
        generate_progressive_plan(["vision"], BASE)


def _make_progressive_plan(tmp_path: Path) -> dict:
    manifest = tmp_path / "manifest.toml"
    manifest.write_text("[[films]]\npath = 'test.mp4'\n")
    sha = hashlib.sha256(manifest.read_bytes()).hexdigest()
    return {
        "protocol": "progressive",
        "study_id": "dev-run-test",
        "repo_root": str(tmp_path),
        "base_modules": BASE,
        "order": ORDER,
        "programme": {"manifest": str(manifest), "sha256": sha},
        "redis": {"base_url": "redis://127.0.0.1:6479", "db": 1},
    }


def test_validate_progressive_plan(tmp_path):
    (tmp_path / "config").mkdir()
    plan = _make_progressive_plan(tmp_path)
    validated = validate_plan(plan)
    assert validated["protocol"] == "progressive"
    assert validated["collection_prefix"] == "devrun"
    assert validated["voice_alignment_steps"] == [{"step_index": len(ORDER)}]


def test_validate_progressive_bad_db(tmp_path):
    (tmp_path / "config").mkdir()
    plan = _make_progressive_plan(tmp_path)
    plan["redis"]["db"] = 0
    with pytest.raises(ValueError, match="1..15"):
        validate_plan(plan)


def test_validate_progressive_broadcast_capacity(tmp_path):
    (tmp_path / "config").mkdir()
    plan = _make_progressive_plan(tmp_path)
    plan["broadcast_capacity"] = 3
    validated = validate_plan(plan)
    assert validated["broadcast_capacity"] == 3


def test_validate_progressive_bad_broadcast_capacity(tmp_path):
    (tmp_path / "config").mkdir()
    plan = _make_progressive_plan(tmp_path)
    plan["broadcast_capacity"] = 0
    with pytest.raises(ValueError, match="positive integer"):
        validate_plan(plan)


def test_progressive_voice_alignment_out_of_range(tmp_path):
    (tmp_path / "config").mkdir()
    plan = _make_progressive_plan(tmp_path)
    plan["voice_alignment_steps"] = [{"step_index": 0}]
    with pytest.raises(ValueError, match="out of range"):
        validate_plan(plan)


def test_progressive_voice_alignment_duplicate(tmp_path):
    (tmp_path / "config").mkdir()
    plan = _make_progressive_plan(tmp_path)
    plan["voice_alignment_steps"] = [{"step_index": 3}, {"step_index": 3}]
    with pytest.raises(ValueError, match="Duplicate"):
        validate_plan(plan)


def test_init_progressive_creates_step_dirs(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "kaine.toml").write_text("[core]\n")
    plan = _make_progressive_plan(tmp_path)
    validated = validate_plan(plan)
    study = tmp_path / "study"
    init_study(study, validated)

    assert (study / "seed").is_dir()
    for i in range(1, len(ORDER) + 1):
        assert (study / f"step_{i}").is_dir()
        assert (study / f"step_{i}" / "config" / "kaine.toml").is_symlink()

    assert not (study / "branch").exists()
    assert not (study / "repeat").exists()
    assert not (study / "accumulate").exists()


def test_step_dir_name_seed():
    assert step_dir_name({}, 0) == "seed"


def test_step_dir_name_progressive():
    assert step_dir_name({}, 3) == "step_3"


def test_collection_prefix_for_step_default():
    plan = {"collection_prefix": "devrun"}
    assert collection_prefix_for_step(plan, 0) == "devrun_step0_"
    assert collection_prefix_for_step(plan, 3) == "devrun_step3_"


def test_collection_prefix_for_step_custom():
    plan = {"collection_prefix": "myrun"}
    assert collection_prefix_for_step(plan, 1) == "myrun_step1_"
