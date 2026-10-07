# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Capability probe set must be non-empty for the voice-alignment gate.

The boot-time guard and the external trainer script both fail closed when
``capability_probe_path`` resolves to an empty or unusable probe set. An
empty set would score every adapter 0.0, report zero loss, and let the
capability-loss veto pass everything.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from kaine.boot import _require_non_empty_capability_probes
from kaine.modules.hypnos.capability_eval import EmptyCapabilityProbeSetError
from kaine.modules.hypnos.voice_alignment import VoiceAlignmentConfig

# --------------------------------------------------------------------------- #
# Load the external script module by path (it is not a package).
# --------------------------------------------------------------------------- #
_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "hypnos_external_train.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location(
        "hypnos_external_train_under_test", _SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


script = _load_script_module()


def _write_jsonl(path: Path, lines: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for line in lines:
            fh.write(json.dumps(line) + "\n")


def _voice_config(tmp_path: Path, capability_probe_path: str | None) -> VoiceAlignmentConfig:
    return VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.log",
        adapter_output_dir=tmp_path / "adapters",
        capability_probe_path=capability_probe_path,
    )


# --------------------------------------------------------------------------- #
# Boot-time guard.
# --------------------------------------------------------------------------- #
def test_require_non_empty_capability_probes_missing_file(tmp_path: Path):
    missing = tmp_path / "does_not_exist.jsonl"
    with pytest.raises(EmptyCapabilityProbeSetError):
        _require_non_empty_capability_probes(
            _voice_config(tmp_path, str(missing))
        )


def test_require_non_empty_capability_probes_empty_file(tmp_path: Path):
    empty = tmp_path / "empty.jsonl"
    empty.write_text("")
    with pytest.raises(EmptyCapabilityProbeSetError):
        _require_non_empty_capability_probes(
            _voice_config(tmp_path, str(empty))
        )


def test_require_non_empty_capability_probes_lacks_expected(tmp_path: Path):
    bad = tmp_path / "bad.jsonl"
    _write_jsonl(bad, [{"prompt": "hello"}])
    with pytest.raises(EmptyCapabilityProbeSetError):
        _require_non_empty_capability_probes(
            _voice_config(tmp_path, str(bad))
        )


def test_require_non_empty_capability_probes_one_usable(tmp_path: Path):
    good = tmp_path / "good.jsonl"
    _write_jsonl(good, [{"prompt": "hello", "expected": "world"}])
    # Should not raise.
    _require_non_empty_capability_probes(
        _voice_config(tmp_path, str(good))
    )


def test_require_non_empty_capability_probes_default_bundle(tmp_path: Path):
    # capability_probe_path=None falls back to the bundled default set,
    # which must be non-empty.
    _require_non_empty_capability_probes(
        _voice_config(tmp_path, None)
    )


# --------------------------------------------------------------------------- #
# External trainer script guard (self-contained, no kaine imports).
# --------------------------------------------------------------------------- #
def _run_script_job(tmp_path: Path, job: dict) -> dict:
    """Run the script's entry point on a one-pair job; the probe check runs in
    main before any heavy import or training."""
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    (job_dir / "pairs.jsonl").write_text(
        json.dumps({"prompt": "p", "chosen": "c", "rejected": "r", "system": "s"}) + "\n",
        encoding="utf-8",
    )
    assert script.main(["hypnos_external_train.py", str(job_dir)]) == 0
    return json.loads((job_dir / "result.json").read_text(encoding="utf-8"))


def _empty_probe_job(tmp_path: Path, capability_probe_path: str) -> dict[str, str | int]:
    return {
        "capability_probe_path": capability_probe_path,
        "base_model_path": "/nonexistent",
        "adapter_output_dir": str(tmp_path / "out"),
    }


def test_script_rejects_empty_capability_probes_without_importing_unsloth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delitem(sys.modules, "unsloth", raising=False)
    assert "unsloth" not in sys.modules

    empty_probe = tmp_path / "empty.jsonl"
    empty_probe.write_text("")

    job = _empty_probe_job(tmp_path, str(empty_probe))
    result = _run_script_job(tmp_path, job)

    assert "unsloth" not in sys.modules
    assert result["ok"] is True
    assert result["accepted"] is False
    assert result["adapter_dir"] is None
    assert result["steps"] == 0
    assert "capability probe set is empty" in result["reason"]


def test_script_rejects_missing_capability_probe_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delitem(sys.modules, "unsloth", raising=False)
    assert "unsloth" not in sys.modules

    missing = tmp_path / "missing.jsonl"
    job = _empty_probe_job(tmp_path, str(missing))
    result = _run_script_job(tmp_path, job)

    assert "unsloth" not in sys.modules
    assert result["ok"] is True
    assert result["accepted"] is False
    assert result["adapter_dir"] is None
    assert "capability probe set is empty" in result["reason"]


@pytest.mark.parametrize("backend", ["in_process", "subprocess", "job_queue"])
def test_every_backend_refuses_an_empty_capability_probe_set(tmp_path, monkeypatch, backend):
    """Boot wiring: each trainer backend runs the capability-probe check, not
    only the helper in isolation."""
    import types

    from kaine.boot import _resolve_trainer
    from kaine.modules.hypnos.voice_alignment import OPERATOR_APPROVED_ENV

    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")
    monkeypatch.setenv("KAINE_MODEL_SERVER_API_KEY", "boot-secret")
    for name in ("unsloth", "trl", "peft", "datasets"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    empty = tmp_path / "capability_empty.jsonl"
    empty.write_text("", encoding="utf-8")
    cfg = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
        base_model_path=str(tmp_path / "base_model"),
        trainer_backend=backend,
        trainer_python=sys.executable,
        trainer_workdir=str(tmp_path / "work"),
        trainer_jobs_dir=str(tmp_path / "jobs"),
        trainer_timeout_s=300.0,
        hot_swap_mode="organ_adapter" if backend == "job_queue" else "manual",
        organ_url="http://organ:8080",
        organ_adapters_dir=str(tmp_path / "organ_adapters"),
        capability_probe_path=str(empty),
    )
    with pytest.raises(EmptyCapabilityProbeSetError, match="capability_probe_path"):
        _resolve_trainer(cfg)
