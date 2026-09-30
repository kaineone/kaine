# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests for ``kaine.modules.hypnos.trainer_service``.

All tests use fakes: no network calls, no GPU queries, and no real training
subprocesses.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import types
from pathlib import Path
from typing import Any

from kaine.modules.hypnos.trainer_service import (
    claim,
    find_ready_jobs,
    run_job,
    serve,
    wait_for_device,
)


class _Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class _Sleep:
    def __init__(self, clock: _Clock) -> None:
        self.clock = clock
        self.durations: list[float] = []

    def __call__(self, duration: float) -> None:
        self.durations.append(duration)
        self.clock.t += duration


def _config(**overrides: Any) -> types.SimpleNamespace:
    defaults = {
        "trainer_python": "/opt/trainer/bin/python",
        "train_script": "scripts/hypnos_external_train.py",
        "converter": "/opt/llama.cpp/convert_lora_to_gguf.py",
        "min_free_mib": 7000,
        "organ_wait_s": 10.0,
        "poll_s": 1.0,
        "job_timeout_s": 3600.0,
    }
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def test_find_ready_jobs(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    jobs.mkdir()

    a = jobs / "a_ready"
    a.mkdir()
    (a / "READY").write_text("")

    b = jobs / "b_ready"
    b.mkdir()
    (b / "READY").write_text("")

    symlink = jobs / "symlink"
    symlink.symlink_to(a)

    claimed = jobs / "claimed"
    claimed.mkdir()
    (claimed / "READY").touch()
    (claimed / "CLAIMED").touch()

    cancelled = jobs / "cancelled"
    cancelled.mkdir()
    (cancelled / "READY").touch()
    (cancelled / "CANCELLED").touch()

    done = jobs / "done"
    done.mkdir()
    (done / "READY").touch()
    (done / "result.json").touch()

    (jobs / "no_ready").mkdir()

    found = find_ready_jobs(jobs)
    assert found == [a, b]


def test_claim_atomic(tmp_path: Path) -> None:
    d = tmp_path / "job"
    d.mkdir()
    ready = d / "READY"
    ready.write_text("")

    assert claim(d) is True
    assert not ready.exists()
    assert (d / "CLAIMED").is_file()

    assert claim(d) is False


def test_wait_for_device_becomes_ready() -> None:
    clock = _Clock()
    sleep = _Sleep(clock)
    organ = iter([False, False, True]).__next__
    vram = lambda: 9000  # noqa: E731

    ok, reason = wait_for_device(
        organ, vram, min_free_mib=7000, wait_s=10, poll_s=2, sleep=sleep, clock=clock
    )

    assert ok is True
    assert "asleep" in reason and "9000" in reason
    assert sleep.durations == [2.0, 2.0]


def test_wait_for_device_always_awake() -> None:
    clock = _Clock()
    sleep = _Sleep(clock)

    ok, reason = wait_for_device(
        lambda: False,
        lambda: 9000,
        min_free_mib=7000,
        wait_s=5,
        poll_s=2,
        sleep=sleep,
        clock=clock,
    )

    assert ok is False
    assert "awake" in reason


def test_wait_for_device_low_vram() -> None:
    clock = _Clock()
    sleep = _Sleep(clock)

    ok, reason = wait_for_device(
        lambda: True,
        lambda: 1000,
        min_free_mib=7000,
        wait_s=5,
        poll_s=2,
        sleep=sleep,
        clock=clock,
    )

    assert ok is False
    assert "VRAM" in reason and "1000" in reason


def test_run_job_success(tmp_path: Path) -> None:
    job = tmp_path / "jobs" / "j1"
    job.mkdir(parents=True)
    adapter_dir = job / "out" / "20260930T000000Z"

    (job / "job.json").write_text(
        json.dumps(
            {
                "base_model_path": "/models/base",
                "adapter_output_dir": str(job / "out"),
            }
        )
    )
    (job / "pairs.jsonl").write_text(
        '{"prompt":"hi","chosen":"a","rejected":"b"}\n'
    )

    calls: list[list[str]] = []

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        calls.append(cmd)
        if "hypnos_external_train.py" in cmd[1]:
            adapter_dir.mkdir(parents=True)
            (adapter_dir / "adapter_config.json").write_text("{}")
            (job / "result.json").write_text(
                json.dumps(
                    {
                        "ok": True,
                        "accepted": True,
                        "adapter_dir": str(adapter_dir),
                        "reason": "accepted",
                    }
                )
            )
        else:
            (adapter_dir / "adapter.gguf").write_bytes(b"ggufdata")
        return types.SimpleNamespace(returncode=0)

    clock = _Clock()
    sleep = _Sleep(clock)
    result = run_job(
        job,
        _config(),
        runner,
        organ_probe=lambda: True,
        vram_probe=lambda: 8000,
        sleep=sleep,
        clock=clock,
    )

    assert result["ok"] is True
    assert result["gguf"] == "adapter.gguf"
    assert result["gguf_sha256"] == hashlib.sha256(b"ggufdata").hexdigest()
    assert not (job / "pairs.jsonl").exists()
    assert (job / "result.json").exists()
    assert not (job / "result.json.tmp").exists()
    assert len([c for c in calls if "hypnos_external_train.py" in c[1]]) == 1
    assert len([c for c in calls if "convert_lora_to_gguf.py" in c[1]]) == 1


def test_run_job_converter_failure(tmp_path: Path) -> None:
    job = tmp_path / "jobs" / "j1"
    job.mkdir(parents=True)
    adapter_dir = job / "out" / "20260930T000000Z"

    (job / "job.json").write_text(
        json.dumps(
            {
                "base_model_path": "/models/base",
                "adapter_output_dir": str(job / "out"),
            }
        )
    )
    (job / "pairs.jsonl").write_text("x\n")

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        if "hypnos_external_train.py" in cmd[1]:
            adapter_dir.mkdir(parents=True)
            (adapter_dir / "adapter_config.json").write_text("{}")
            (job / "result.json").write_text(
                json.dumps(
                    {
                        "ok": True,
                        "accepted": True,
                        "adapter_dir": str(adapter_dir),
                        "reason": "accepted",
                    }
                )
            )
            return types.SimpleNamespace(returncode=0)
        return types.SimpleNamespace(returncode=1)

    result = run_job(
        job,
        _config(),
        runner,
        organ_probe=lambda: True,
        vram_probe=lambda: 8000,
        sleep=lambda x: None,
        clock=lambda: 0.0,
    )

    assert result["ok"] is False
    assert "gguf conversion failed (exit 1)" in result["reason"]
    assert not (job / "pairs.jsonl").exists()


def test_run_job_adapter_output_dir_outside_job(tmp_path: Path) -> None:
    job = tmp_path / "j"
    job.mkdir()
    (job / "job.json").write_text(
        json.dumps(
            {
                "base_model_path": "/models/base",
                "adapter_output_dir": "/tmp/outside",
            }
        )
    )
    (job / "pairs.jsonl").write_text("x\n")

    called = False

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        nonlocal called
        called = True
        return types.SimpleNamespace(returncode=0)

    result = run_job(
        job,
        _config(),
        runner,
        organ_probe=lambda: True,
        vram_probe=lambda: 8000,
        sleep=lambda x: None,
        clock=lambda: 0.0,
    )

    assert result["ok"] is False
    assert result["reason"] == "adapter_output_dir outside the job directory"
    assert called is False
    assert not (job / "pairs.jsonl").exists()


def test_run_job_symlinked_pairs(tmp_path: Path) -> None:
    job = tmp_path / "j"
    job.mkdir()
    real_pairs = tmp_path / "real_pairs.jsonl"
    real_pairs.write_text('{"prompt":"p","chosen":"c","rejected":"r"}\n')

    (job / "job.json").write_text(
        json.dumps(
            {
                "base_model_path": "/models/base",
                "adapter_output_dir": "out",
            }
        )
    )
    (job / "pairs.jsonl").symlink_to(real_pairs)

    called = False

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        nonlocal called
        called = True
        return types.SimpleNamespace(returncode=0)

    result = run_job(
        job,
        _config(),
        runner,
        organ_probe=lambda: True,
        vram_probe=lambda: 8000,
        sleep=lambda x: None,
        clock=lambda: 0.0,
    )

    assert result["ok"] is False
    assert "symlinked or missing" in result["reason"]
    assert called is False


def test_run_job_device_not_ready(tmp_path: Path) -> None:
    job = tmp_path / "j"
    job.mkdir()
    (job / "job.json").write_text(
        json.dumps(
            {
                "base_model_path": "/models/base",
                "adapter_output_dir": "out",
            }
        )
    )
    (job / "pairs.jsonl").write_text("x\n")

    called = False

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        nonlocal called
        called = True
        return types.SimpleNamespace(returncode=0)

    clock = _Clock()
    sleep = _Sleep(clock)
    result = run_job(
        job,
        _config(organ_wait_s=3.0, poll_s=1.0),
        runner,
        organ_probe=lambda: False,
        vram_probe=lambda: 100,
        sleep=sleep,
        clock=clock,
    )

    assert result["ok"] is False
    assert ("awake" in result["reason"] or "VRAM" in result["reason"])
    assert called is False
    assert not (job / "pairs.jsonl").exists()


def test_run_job_train_nonzero_exit(tmp_path: Path) -> None:
    job = tmp_path / "j"
    job.mkdir()
    (job / "job.json").write_text(
        json.dumps(
            {
                "base_model_path": "/models/base",
                "adapter_output_dir": "out",
            }
        )
    )
    (job / "pairs.jsonl").write_text("x\n")

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        return types.SimpleNamespace(returncode=1)

    result = run_job(
        job,
        _config(),
        runner,
        organ_probe=lambda: True,
        vram_probe=lambda: 8000,
        sleep=lambda x: None,
        clock=lambda: 0.0,
    )

    assert result["ok"] is False
    assert "training exited 1" in result["reason"]
    assert not (job / "pairs.jsonl").exists()


def test_run_job_train_timeout(tmp_path: Path) -> None:
    job = tmp_path / "j"
    job.mkdir()
    (job / "job.json").write_text(
        json.dumps(
            {
                "base_model_path": "/models/base",
                "adapter_output_dir": "out",
            }
        )
    )
    (job / "pairs.jsonl").write_text("x\n")

    def runner(cmd: list[str], **kwargs: Any) -> Any:
        raise subprocess.TimeoutExpired(cmd, kwargs["timeout"])

    result = run_job(
        job,
        _config(),
        runner,
        organ_probe=lambda: True,
        vram_probe=lambda: 8000,
        sleep=lambda x: None,
        clock=lambda: 0.0,
    )

    assert result["ok"] is False
    assert result["reason"] == "training timed out"
    assert not (job / "pairs.jsonl").exists()


def test_serve_once_processes_one_job(tmp_path: Path) -> None:
    jobs = tmp_path / "jobs"
    jobs.mkdir()
    for name in ("j1", "j2"):
        d = jobs / name
        d.mkdir()
        (d / "READY").touch()
        (d / "job.json").write_text(
            json.dumps(
                {"base_model_path": "/models/base", "adapter_output_dir": "out"}
            )
        )
        (d / "pairs.jsonl").write_text("x\n")

    processed: list[str] = []

    def fake_run_job(
        job_dir: Path,
        cfg: Any,
        runner: Any,
        organ: Any,
        vram: Any,
        sleep: Any,
        clock: Any,
    ) -> dict[str, Any]:
        processed.append(Path(job_dir).name)
        return {"ok": True, "reason": "done"}

    clock = _Clock()
    sleep = _Sleep(clock)
    cfg = types.SimpleNamespace(jobs_dir=jobs, poll_s=1.0)

    serve(
        cfg,
        once=True,
        run_job_fn=fake_run_job,
        sleep=sleep,
        clock=clock,
        organ_probe=lambda: True,
        vram_probe=lambda: 99_999,
    )

    assert len(processed) == 1
    claimed = jobs / processed[0] / "CLAIMED"
    assert claimed.is_file()

    remaining = {"j1", "j2"} - set(processed)
    for name in remaining:
        assert (jobs / name / "READY").is_file()
        assert not (jobs / name / "CLAIMED").exists()

