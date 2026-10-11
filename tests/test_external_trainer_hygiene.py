# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the external voice-alignment trainer's job hygiene.

These tests run in the kaine venv and must not require a GPU, unsloth or trl.
They import the trainer script by path and exercise its pure top-level helpers.
"""
import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "hypnos_external_train.py"


@pytest.fixture
def mod():
    spec = importlib.util.spec_from_file_location(
        "hypnos_external_train", SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_job_dir(tmp_path, job, pairs):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    with (job_dir / "pairs.jsonl").open("w", encoding="utf-8") as fh:
        for p in pairs:
            fh.write(json.dumps(p) + "\n")
    return job_dir


def _default_job(tmp_path, **overrides):
    base = {
        "schema_version": 2,
        "base_model_path": "dummy/base",
        "lora_rank": 8,
        "learning_rate": 5e-5,
        "dpo_beta": 0.1,
        "seed": 42,
        "max_samples": 200,
        "training_device": "cuda:0",
        "capability_loss_threshold": 0.05,
        "adapter_output_dir": str(tmp_path / "adapter_out"),
        "capability_probe_path": str(tmp_path / "cap_probes.jsonl"),
        "abliteration_probe_path": str(tmp_path / "ablit_probes.jsonl"),
        "train_precision": "bf16",
        "previous_adapter_dir": None,
    }
    base.update(overrides)
    return base


# --------------------------------------------------------------------------- #
# precision_load_kwargs
# --------------------------------------------------------------------------- #
def test_precision_load_kwargs_bf16(mod):
    assert mod.precision_load_kwargs("bf16") == {
        "load_in_4bit": False,
        "dtype": "bfloat16",
    }


def test_precision_load_kwargs_4bit(mod):
    assert mod.precision_load_kwargs("4bit") == {"load_in_4bit": True}


def test_precision_load_kwargs_unknown(mod):
    with pytest.raises(mod.TrainerJobError, match="unknown train_precision"):
        mod.precision_load_kwargs("8bit")


# --------------------------------------------------------------------------- #
# resolve_previous_adapter
# --------------------------------------------------------------------------- #
def test_resolve_previous_adapter_null(mod):
    assert mod.resolve_previous_adapter({}) is None
    assert mod.resolve_previous_adapter({"previous_adapter_dir": None}) is None


def test_resolve_previous_adapter_valid(tmp_path, mod):
    prev = tmp_path / "prev"
    prev.mkdir()
    (prev / "adapter_config.json").write_text("{}", encoding="utf-8")
    assert mod.resolve_previous_adapter(
        {"previous_adapter_dir": str(prev)}
    ) == prev


def test_resolve_previous_adapter_missing(tmp_path, mod):
    missing = tmp_path / "missing"
    with pytest.raises(mod.TrainerJobError, match="previous adapter could not be loaded"):
        mod.resolve_previous_adapter({"previous_adapter_dir": str(missing)})
    try:
        mod.resolve_previous_adapter({"previous_adapter_dir": str(missing)})
    except mod.TrainerJobError as exc:
        assert "fresh adapter is never trained in its place" in str(exc)


def test_resolve_previous_adapter_not_a_directory(tmp_path, mod):
    f = tmp_path / "file"
    f.write_text("not a dir", encoding="utf-8")
    with pytest.raises(mod.TrainerJobError, match="fresh adapter is never trained in its place"):
        mod.resolve_previous_adapter({"previous_adapter_dir": str(f)})


def test_resolve_previous_adapter_missing_config(tmp_path, mod):
    d = tmp_path / "empty_dir"
    d.mkdir()
    with pytest.raises(mod.TrainerJobError, match="fresh adapter is never trained in its place"):
        mod.resolve_previous_adapter({"previous_adapter_dir": str(d)})


# --------------------------------------------------------------------------- #
# split_pairs_by_system and build_dataset_rows
# --------------------------------------------------------------------------- #
def test_split_pairs_by_system(mod):
    pairs = [
        {"system": "valid", "prompt": "p1"},
        {"system": "", "prompt": "p2"},
        {"prompt": "p3"},
        {"system": 123, "prompt": "p4"},
    ]
    kept, dropped = mod.split_pairs_by_system(pairs)
    assert kept == [{"system": "valid", "prompt": "p1"}]
    assert dropped == 3


def test_build_dataset_rows(mod):
    rows = mod.build_dataset_rows(
        [
            {
                "system": "SYS",
                "prompt": "PROMPT",
                "chosen": "CHOSEN",
                "rejected": "REJECTED",
            }
        ]
    )
    assert rows == [
        {
            "prompt": [
                {"role": "system", "content": "SYS"},
                {"role": "user", "content": "PROMPT"},
            ],
            "chosen": [{"role": "assistant", "content": "CHOSEN"}],
            "rejected": [{"role": "assistant", "content": "REJECTED"}],
        }
    ]


# --------------------------------------------------------------------------- #
# main: validation failures before training
# --------------------------------------------------------------------------- #
def test_main_no_system_prompts_rejects_without_training(mod, tmp_path, monkeypatch):
    calls = []

    def fake_train(*args, **kwargs):
        calls.append(True)
        raise AssertionError("_train should not be called")

    monkeypatch.setattr(mod, "_train", fake_train)

    pairs = [
        {"prompt": "p1", "chosen": "c", "rejected": "r", "system": ""},
        {"prompt": "p2", "chosen": "c", "rejected": "r"},
        {"prompt": "p3", "chosen": "c", "rejected": "r", "system": 42},
    ]
    job_dir = _write_job_dir(
        tmp_path,
        _default_job(tmp_path, train_precision="bf16", previous_adapter_dir=None),
        pairs,
    )

    assert mod.main(["hypnos_external_train.py", str(job_dir)]) == 0
    assert not calls

    result = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert "no pair has a verified system prompt" in result["reason"]
    assert result["pairs_without_system"] == 3
    assert result["schema_version"] == 2
    assert result["train_precision"] == "bf16"
    assert result["previous_adapter_dir"] is None
    assert result.get("accepted") is False


def test_main_missing_previous_adapter_rejects_without_training(
    mod, tmp_path, monkeypatch
):
    def fake_train(*args, **kwargs):
        raise AssertionError("_train should not be called")

    monkeypatch.setattr(mod, "_train", fake_train)

    pairs = [
        {"system": "s", "prompt": "p", "chosen": "c", "rejected": "r"},
    ]
    job_dir = _write_job_dir(
        tmp_path,
        _default_job(
            tmp_path,
            previous_adapter_dir=str(tmp_path / "nonexistent_adapter"),
        ),
        pairs,
    )

    assert mod.main(["hypnos_external_train.py", str(job_dir)]) == 0

    result = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert "previous adapter could not be loaded" in result["reason"]
    assert "fresh adapter is never trained in its place" in result["reason"]
    assert result["previous_adapter_dir"] is None
    assert result.get("accepted") is False


def test_main_unknown_precision_rejects_without_training(
    mod, tmp_path, monkeypatch
):
    def fake_train(*args, **kwargs):
        raise AssertionError("_train should not be called")

    monkeypatch.setattr(mod, "_train", fake_train)

    pairs = [
        {"system": "s", "prompt": "p", "chosen": "c", "rejected": "r"},
    ]
    job_dir = _write_job_dir(
        tmp_path,
        _default_job(tmp_path, train_precision="8bit"),
        pairs,
    )

    assert mod.main(["hypnos_external_train.py", str(job_dir)]) == 0

    result = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert "unknown train_precision" in result["reason"]
    assert result["train_precision"] == "8bit"
    assert result.get("accepted") is False


# --------------------------------------------------------------------------- #
# import boundary
# --------------------------------------------------------------------------- #
def test_source_contains_no_kaine_import(mod):
    text = SCRIPT.read_text(encoding="utf-8")
    assert "import kaine" not in text
    assert "from kaine" not in text


def test_relative_previous_adapter_resolves_against_the_job_dir(mod, tmp_path):
    """The kaine side copies the adapter into the job dir and writes a
    relative path, so every backend sees the same layout."""
    job_dir = tmp_path / "job"
    (job_dir / "previous_adapter").mkdir(parents=True)
    (job_dir / "previous_adapter" / "adapter_config.json").write_text("{}")
    resolved = mod.resolve_previous_adapter({"previous_adapter_dir": "previous_adapter"}, job_dir)
    assert resolved == job_dir / "previous_adapter"


def test_main_refuses_an_empty_abliteration_set_before_training(mod, tmp_path, monkeypatch):
    """The welfare veto must be able to run: an empty abliteration probe set is
    refused before any model is loaded, and result.json is owner-only."""
    import stat

    def must_not_train(*args, **kwargs):
        raise AssertionError("_train must not run without an abliteration probe set")

    monkeypatch.setattr(mod, "_train", must_not_train)
    empty = tmp_path / "abliteration.jsonl"
    empty.write_text("")
    cap = tmp_path / "cap_probes.jsonl"
    cap.write_text(json.dumps({"prompt": "2+2", "expected": "4"}) + "\n")
    job = _default_job(tmp_path, train_precision="bf16", previous_adapter_dir=None)
    job["capability_probe_path"] = str(cap)
    job["abliteration_probe_path"] = str(empty)
    job_dir = _write_job_dir(
        tmp_path, job, [{"prompt": "p", "chosen": "c", "rejected": "r", "system": "s"}]
    )
    assert mod.main(["hypnos_external_train.py", str(job_dir)]) == 0
    result_path = job_dir / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    assert result["accepted"] is False
    assert "abliteration probe set is empty" in result["reason"]
    assert stat.S_IMODE(result_path.stat().st_mode) == 0o600


def test_unsloth_is_imported_before_any_other_training_package():
    """Unsloth's import fixes repair trl on transformers 5 only when unsloth is
    imported first; this pins the order in the script source."""
    import ast

    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    heavy = {"unsloth", "trl", "peft", "datasets", "transformers", "torch"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != "_train":
            continue
        order = []
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.ImportFrom) and stmt.module:
                order.append((stmt.lineno, stmt.module.split(".")[0]))
            elif isinstance(stmt, ast.Import):
                order.extend((stmt.lineno, a.name.split(".")[0]) for a in stmt.names)
        first = [m for _, m in sorted(order) if m in heavy]
        assert first and first[0] == "unsloth", first
        break
    else:
        raise AssertionError("_train not found")
    # No heavy package at module level, where it would load before unsloth.
    top_level = {
        (n.module or "").split(".")[0] if isinstance(n, ast.ImportFrom) else a.name.split(".")[0]
        for n in tree.body
        if isinstance(n, (ast.Import, ast.ImportFrom))
        for a in (n.names if isinstance(n, ast.Import) else [n])
    }
    assert not (top_level & (heavy - {"unsloth"})), top_level


def test_adapter_names_do_not_collide_with_module_attributes(mod):
    """PEFT keeps adapters in a ModuleDict; a name equal to an nn.Module
    attribute (e.g. "train") fails at load time with a KeyError."""
    import torch

    module_attrs = set(dir(torch.nn.Module))
    assert mod.TRAINED_ADAPTER not in module_attrs
    assert mod.REFERENCE_ADAPTER not in module_attrs
    assert mod.TRAINED_ADAPTER != mod.REFERENCE_ADAPTER
