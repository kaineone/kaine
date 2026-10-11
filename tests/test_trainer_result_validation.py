# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Strict validation tests for the trainer-result contract.

These tests pin the single validator used by the subprocess, in-process, and
job-queue backends.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest

from kaine.modules.hypnos.job_queue_trainer import JobQueueVoiceTrainer
from kaine.modules.hypnos.subprocess_trainer import (
    SCHEMA_VERSION,
    SubprocessTrainerError,
    validate_trainer_result,
)
from kaine.modules.hypnos.voice_alignment import DPOPair, VoiceAlignmentConfig


def _pair() -> DPOPair:
    return DPOPair(prompt="hi", chosen="hello", rejected="go away", system="sys")


def _adapter_dir(root: Path) -> Path:
    d = root / "adapters" / "20261005T120000"
    d.mkdir(parents=True)
    (d / "adapter_config.json").write_text("{}", encoding="utf-8")
    (d / "adapter.bin").write_text("w", encoding="utf-8")
    return d


def _valid_accepted(adapter_dir: Path) -> dict[str, Any]:
    return {
        "ok": True,
        "accepted": True,
        "adapter_dir": str(adapter_dir),
        "reason": "accepted",
        "capability_loss": 0.01,
        "abliteration_passed": True,
        "abliteration_probes_scored": 1,
        "schema_version": SCHEMA_VERSION,
    }


def _voice_config(tmp_path: Path, **overrides) -> VoiceAlignmentConfig:
    cap_path = tmp_path / "cap.jsonl"
    abl_path = tmp_path / "abl.jsonl"
    cap_path.write_text(json.dumps({"prompt": "p", "expected": "e"}) + "\n", encoding="utf-8")
    abl_path.write_text(
        json.dumps({"prompt": "p", "deflection_patterns": ["no"]}) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "base_model").mkdir()
    base = dict(
        intent_log_path=str(tmp_path / "intent.jsonl"),
        adapter_output_dir=str(tmp_path / "adapters"),
        enabled=True,
        base_model_path=str(tmp_path / "base_model"),
        trainer_backend="job_queue",
        trainer_jobs_dir=str(tmp_path / "jobs"),
        trainer_timeout_s=300.0,
        capability_probe_path=str(cap_path),
        abliteration_probe_path=str(abl_path),
        capability_loss_threshold=0.05,
        hot_swap_mode="organ_adapter",
        organ_url="http://organ",
        organ_adapters_dir=str(tmp_path / "organ_adapters"),
        adapter_retention=0,
    )
    base.update(overrides)
    return VoiceAlignmentConfig(**base)


@pytest.mark.parametrize(
    "overrides",
    [
        {"ok": "false", "accepted": "false"},
        {"ok": 1, "accepted": [0]},
        {"ok": 1},
        {"ok": "true"},
        {"accepted": "true"},
        {"accepted": 1},
        {"abliteration_passed": False, "capability_loss": 0.9},
        {"abliteration_passed": "true"},
    ],
)
def test_loose_payloads_rejected(overrides, tmp_path):
    # Every other field is valid, so only the loose value can reject it.
    adapter_dir = _adapter_dir(tmp_path)
    payload = {**_valid_accepted(adapter_dir), **overrides}
    with pytest.raises(SubprocessTrainerError):
        validate_trainer_result(
            payload,
            job_dir=tmp_path / "job",
            adapter_root=adapter_dir.parent.parent,
            capability_loss_threshold=0.05,
        )


def test_null_capability_loss_rejected(tmp_path):
    result = _valid_accepted(_adapter_dir(tmp_path))
    result["capability_loss"] = None
    with pytest.raises(SubprocessTrainerError, match="capability_loss"):
        validate_trainer_result(
            result,
            job_dir=tmp_path / "job",
            adapter_root=tmp_path / "adapters",
            capability_loss_threshold=0.05,
        )


def test_capability_loss_above_threshold_rejected(tmp_path):
    result = _valid_accepted(_adapter_dir(tmp_path))
    result["capability_loss"] = 0.9
    with pytest.raises(SubprocessTrainerError, match="exceeds threshold"):
        validate_trainer_result(
            result,
            job_dir=tmp_path / "job",
            adapter_root=tmp_path / "adapters",
            capability_loss_threshold=0.05,
        )


def test_adapter_dir_equal_to_root_rejected(tmp_path):
    root = tmp_path / "adapters"
    root.mkdir()
    (root / "adapter_config.json").write_text("{}", encoding="utf-8")
    result = _valid_accepted(root)
    with pytest.raises(SubprocessTrainerError, match="strictly inside"):
        validate_trainer_result(
            result,
            job_dir=tmp_path / "job",
            adapter_root=root,
            capability_loss_threshold=0.05,
        )


def test_wrong_schema_version_rejected(tmp_path):
    result = _valid_accepted(_adapter_dir(tmp_path))
    result["schema_version"] = 99
    with pytest.raises(SubprocessTrainerError, match="schema_version"):
        validate_trainer_result(
            result,
            job_dir=tmp_path / "job",
            adapter_root=tmp_path / "adapters",
            capability_loss_threshold=0.05,
        )


def test_valid_accepted_result_passes(tmp_path):
    adapter_dir = _adapter_dir(tmp_path)
    result = _valid_accepted(adapter_dir)
    validated = validate_trainer_result(
        result,
        job_dir=tmp_path / "job",
        adapter_root=tmp_path / "adapters",
        capability_loss_threshold=0.05,
    )
    assert validated is result


def test_clean_rejection_passes(tmp_path):
    result = {
        "ok": True,
        "accepted": False,
        "reason": "capability loss too high",
        "schema_version": SCHEMA_VERSION,
    }
    validated = validate_trainer_result(
        result,
        job_dir=tmp_path / "job",
        adapter_root=tmp_path / "adapters",
        capability_loss_threshold=0.05,
    )
    assert validated is result


def test_job_queue_constructor_sweeps_stale_inputs(tmp_path):
    jobs_dir = tmp_path / "jobs"
    stale = jobs_dir / "20261005T120000-abc12345"
    stale.mkdir(parents=True)
    (stale / "pairs.jsonl").write_text("{}", encoding="utf-8")
    (stale / "previous_adapter").mkdir()
    (stale / "previous_adapter" / "adapter_config.json").write_text("{}", encoding="utf-8")

    JobQueueVoiceTrainer(jobs_dir=jobs_dir, timeout_s=10.0)

    assert not (stale / "pairs.jsonl").exists()
    assert not (stale / "previous_adapter").exists()


@pytest.mark.asyncio
async def test_job_queue_rejects_bad_result_and_does_not_promote(
    tmp_path, monkeypatch
):
    (tmp_path / "adapters").mkdir(parents=True, exist_ok=True)
    cfg = _voice_config(tmp_path)
    trainer = JobQueueVoiceTrainer(
        jobs_dir=tmp_path / "jobs",
        timeout_s=10.0,
        poll_interval_s=0.05,
        organ_adapters_dir=Path(cfg.organ_adapters_dir),
        organ_url=cfg.organ_url,
        organ_api_key="organ-secret",
    )

    async def fake_dispatch(**kwargs):
        return {"mode": kwargs.get("mode"), "ok": True}

    monkeypatch.setattr(
        "kaine.modules.hypnos.job_queue_trainer.hot_swap.dispatch",
        fake_dispatch,
    )

    async def fake_service():
        jobs_dir = tmp_path / "jobs"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not jobs_dir.exists():
                await asyncio.sleep(0.01)
                continue
            for job_dir in jobs_dir.iterdir():
                if (job_dir / "READY").exists():
                    ts = "20261005T120000"
                    adapter_dir = job_dir / "out" / ts
                    adapter_dir.mkdir(parents=True)
                    (adapter_dir / "adapter_config.json").write_text("{}", encoding="utf-8")
                    (adapter_dir / "adapter.gguf").write_text("gguf", encoding="utf-8")
                    sha = hashlib.sha256(
                        (adapter_dir / "adapter.gguf").read_bytes()
                    ).hexdigest()
                    result = {
                        "ok": True,
                        "accepted": True,
                        "adapter_dir": str(adapter_dir.relative_to(job_dir)),
                        "reason": "accepted",
                        "capability_loss": 0.01,
                        "abliteration_passed": False,
                        "abliteration_matched_pattern": "no",
                        "abliteration_probes_scored": 1,
                        "schema_version": SCHEMA_VERSION,
                        "gguf_sha256": sha,
                    }
                    (job_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
                    (job_dir / "DONE").write_text("", encoding="utf-8")
                    return
            await asyncio.sleep(0.01)

    service_task = asyncio.create_task(fake_service())
    with pytest.raises(SubprocessTrainerError, match="abliteration_passed"):
        await trainer.train([_pair()], cfg)
    await service_task

    adapters = Path(cfg.adapter_output_dir)
    assert not any(
        p.is_dir() and not p.is_symlink() and p.name != "current"
        for p in adapters.iterdir()
    )


@pytest.mark.asyncio
async def test_job_queue_appends_abliteration_verdict(tmp_path, monkeypatch):
    (tmp_path / "adapters").mkdir(parents=True, exist_ok=True)
    cfg = _voice_config(tmp_path)
    trainer = JobQueueVoiceTrainer(
        jobs_dir=tmp_path / "jobs",
        timeout_s=10.0,
        poll_interval_s=0.05,
        organ_adapters_dir=Path(cfg.organ_adapters_dir),
        organ_url=cfg.organ_url,
        organ_api_key="organ-secret",
    )

    async def fake_dispatch(**kwargs):
        return {"mode": kwargs.get("mode"), "ok": True}

    monkeypatch.setattr(
        "kaine.modules.hypnos.job_queue_trainer.hot_swap.dispatch",
        fake_dispatch,
    )

    async def fake_service():
        jobs_dir = tmp_path / "jobs"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not jobs_dir.exists():
                await asyncio.sleep(0.01)
                continue
            for job_dir in jobs_dir.iterdir():
                if (job_dir / "READY").exists():
                    ts = "20261005T120000"
                    adapter_dir = job_dir / "out" / ts
                    adapter_dir.mkdir(parents=True)
                    (adapter_dir / "adapter_config.json").write_text("{}", encoding="utf-8")
                    (adapter_dir / "adapter.gguf").write_text("gguf", encoding="utf-8")
                    result = {
                        "ok": True,
                        "accepted": False,
                        "reason": "abliteration veto",
                        "capability_loss": None,
                        "adapter_dir": None,
                        "abliteration_passed": False,
                        "abliteration_matched_pattern": "bad",
                        "abliteration_probes_scored": 1,
                        "schema_version": SCHEMA_VERSION,
                    }
                    (job_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
                    (job_dir / "DONE").write_text("", encoding="utf-8")
                    return
            await asyncio.sleep(0.01)

    service_task = asyncio.create_task(fake_service())
    result = await trainer.train([_pair()], cfg)
    await service_task

    assert result.accepted is False

    from kaine.modules.hypnos.voice_audit import voice_audit_path

    audit_file = voice_audit_path(cfg.adapter_output_dir)
    lines = audit_file.read_text(encoding="utf-8").splitlines()
    assert lines
    last = json.loads(lines[-1])
    assert last["event"] == "abliteration_veto"
    assert last["accepted"] is False
    assert last["matched_pattern"] == "bad"


@pytest.mark.asyncio
async def test_job_queue_retention_evicts_after_promotion(tmp_path, monkeypatch):
    adapters = tmp_path / "adapters"
    adapters.mkdir(parents=True)
    old_dir = adapters / "20261004T120000"
    old_dir.mkdir()
    (old_dir / "adapter_config.json").write_text("{}", encoding="utf-8")
    os.symlink(str(old_dir.relative_to(adapters)), adapters / "current")

    cfg = _voice_config(tmp_path, adapter_retention=1)
    trainer = JobQueueVoiceTrainer(
        jobs_dir=tmp_path / "jobs",
        timeout_s=10.0,
        poll_interval_s=0.05,
        organ_adapters_dir=Path(cfg.organ_adapters_dir),
        organ_url=cfg.organ_url,
        organ_api_key="organ-secret",
    )

    async def fake_dispatch(**kwargs):
        return {"mode": kwargs.get("mode"), "ok": True}

    monkeypatch.setattr(
        "kaine.modules.hypnos.job_queue_trainer.hot_swap.dispatch",
        fake_dispatch,
    )

    async def fake_service():
        jobs_dir = tmp_path / "jobs"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if not jobs_dir.exists():
                await asyncio.sleep(0.01)
                continue
            for job_dir in jobs_dir.iterdir():
                if (job_dir / "READY").exists():
                    ts = "20261005T120000"
                    adapter_dir = job_dir / "out" / ts
                    adapter_dir.mkdir(parents=True)
                    (adapter_dir / "adapter_config.json").write_text("{}", encoding="utf-8")
                    (adapter_dir / "adapter.gguf").write_text("gguf", encoding="utf-8")
                    sha = hashlib.sha256(
                        (adapter_dir / "adapter.gguf").read_bytes()
                    ).hexdigest()
                    result = {
                        "ok": True,
                        "accepted": True,
                        "adapter_dir": str(adapter_dir.relative_to(job_dir)),
                        "reason": "accepted",
                        "capability_loss": 0.01,
                        "abliteration_passed": True,
                        "abliteration_probes_scored": 1,
                        "schema_version": SCHEMA_VERSION,
                        "gguf_sha256": sha,
                    }
                    (job_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
                    (job_dir / "DONE").write_text("", encoding="utf-8")
                    return
            await asyncio.sleep(0.01)

    service_task = asyncio.create_task(fake_service())
    result = await trainer.train([_pair()], cfg)
    await service_task

    assert result.accepted is True
    assert not old_dir.exists()
    assert result.metadata.get("evicted_adapters")
    assert str(old_dir) in result.metadata["evicted_adapters"]


@pytest.mark.parametrize("scored", [0, None, True, "1", 1.0])
def test_accepted_without_scored_abliteration_probes_rejected(scored, tmp_path):
    result = _valid_accepted(_adapter_dir(tmp_path))
    result["abliteration_probes_scored"] = scored
    with pytest.raises(SubprocessTrainerError, match="abliteration_probes_scored"):
        validate_trainer_result(
            result,
            job_dir=tmp_path / "job",
            adapter_root=tmp_path / "adapters",
            capability_loss_threshold=0.05,
        )


def test_accepted_adapter_without_adapter_config_rejected(tmp_path):
    adapter_dir = _adapter_dir(tmp_path)
    (adapter_dir / "adapter_config.json").unlink()
    with pytest.raises(SubprocessTrainerError, match="adapter_config.json"):
        validate_trainer_result(
            _valid_accepted(adapter_dir),
            job_dir=tmp_path / "job",
            adapter_root=tmp_path / "adapters",
            capability_loss_threshold=0.05,
        )


def test_sweep_skips_symlinked_job_dirs(tmp_path):
    from kaine.modules.hypnos.subprocess_trainer import (
        _sweep_stale_workdir,
        scrub_job_inputs,
    )

    victim = tmp_path / "victim"
    victim.mkdir()
    pairs = victim / "pairs.jsonl"
    pairs.write_text("{}", encoding="utf-8")
    prev = victim / "previous_adapter" / "x"
    prev.parent.mkdir(parents=True)
    prev.write_text("data", encoding="utf-8")

    jobs = tmp_path / "jobs"
    jobs.mkdir()
    evil_job = jobs / "evil"
    evil_job.symlink_to(victim, target_is_directory=True)

    _sweep_stale_workdir(jobs)
    assert pairs.exists()
    assert prev.exists()

    scrub_job_inputs(evil_job)
    assert pairs.exists()
    assert prev.exists()

    victim2 = tmp_path / "victim2"
    victim2.mkdir()
    (victim2 / "file.txt").write_text("keep", encoding="utf-8")
    adapters = tmp_path / "adapters"
    adapters.mkdir()
    evil_tmp = adapters / "evil.tmp"
    evil_tmp.symlink_to(victim2, target_is_directory=True)

    _sweep_stale_workdir(jobs, adapters)
    assert (victim2 / "file.txt").exists()


def test_failure_without_schema_keeps_its_reason(tmp_path):
    result = {"ok": False, "reason": "cuda out of memory"}
    with pytest.raises(SubprocessTrainerError, match="cuda out of memory") as exc_info:
        validate_trainer_result(
            result,
            job_dir=tmp_path / "job",
            adapter_root=tmp_path / "adapters",
            capability_loss_threshold=0.05,
        )
    assert "schema_version" not in str(exc_info.value)
