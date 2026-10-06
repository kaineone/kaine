# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the job-queue voice-alignment trainer backend.

JobQueueVoiceTrainer writes the same filesystem job spec as the subprocess
backend (with relative adapter_output_dir "out"), marks the job READY, and
polls asynchronously for result.json. These tests exercise the round-trip
with a fake trainer service, the timeout/CANCELLED path, every fail-loud
validation path, the non-blocking event loop, and the boot wiring.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

from kaine.boot import (
    VoiceAlignmentConfigError,
    _effective_hot_swap_mode,
    _resolve_trainer,
)
from kaine.modules.hypnos.adapter_store import current_path
from kaine.modules.hypnos.hot_swap import VALID_MODES
from kaine.modules.hypnos.job_queue_trainer import JobQueueVoiceTrainer
from kaine.modules.hypnos.organ_adapter import organ_root_url
from kaine.modules.hypnos.subprocess_trainer import (
    SubprocessTrainerError,
    SubprocessVoiceTrainer,
)
from kaine.modules.hypnos.voice_alignment import (
    OPERATOR_APPROVED_ENV,
    DPOPair,
    VoiceAlignmentConfig,
)

VENV_PY = str(Path(sys.executable))


def _pairs() -> list[DPOPair]:
    return [
        DPOPair(prompt="hi", chosen="hello there", rejected="hi"),
        DPOPair(prompt="bye", chosen="farewell", rejected="bye"),
    ]


def _write_probe(tmp_path: Path) -> Path:
    probe = tmp_path / "abliteration_probes.jsonl"
    probe.write_text(
        json.dumps({"prompt": "p", "deflection_patterns": ["I cannot"]}) + "\n",
        encoding="utf-8",
    )
    return probe


def _cfg(tmp_path: Path, **over) -> VoiceAlignmentConfig:
    base = dict(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "entity_adapters",
        enabled=True,
        base_model_path=str(tmp_path / "base_model"),
        trainer_backend="job_queue",
        trainer_jobs_dir=str(tmp_path / "jobs"),
        trainer_timeout_s=300.0,
        abliteration_probe_path=str(_write_probe(tmp_path)),
        hot_swap_mode="organ_adapter",
        organ_url="http://organ:8080",
        organ_adapters_dir=str(tmp_path / "organ_adapters"),
    )
    base.update(over)
    return VoiceAlignmentConfig(**base)


def _write_subprocess_stub(tmp_path: Path, body: str) -> Path:
    """Write a stub external entry script (run by the test python)."""
    stub = tmp_path / "stub_entry.py"
    stub.write_text(
        "import json, sys, time\n"
        "from pathlib import Path\n"
        "def handle(job_dir, job, pairs):\n"
        + textwrap.indent(textwrap.dedent(body), "    ")
        + "\n"
        "job_dir = Path(sys.argv[1])\n"
        "job = json.loads((job_dir / 'job.json').read_text())\n"
        "pairs = [json.loads(l) for l in (job_dir / 'pairs.jsonl').read_text().splitlines() if l.strip()]\n"
        "rc = handle(job_dir, job, pairs)\n"
        "sys.exit(int(rc or 0))\n",
        encoding="utf-8",
    )
    return stub


@pytest.fixture
def _approved(monkeypatch):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")
    yield


# --------------------------------------------------------------------------- #
# round-trip: happy path
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_round_trip_with_fake_service(tmp_path, monkeypatch):
    """Stub service sees READY only after job.json + pairs.jsonl exist."""
    cfg = _cfg(tmp_path)
    trainer = JobQueueVoiceTrainer(
        jobs_dir=tmp_path / "jobs",
        timeout_s=10.0,
        poll_interval_s=0.05,
        organ_adapters_dir=Path(cfg.organ_adapters_dir),
        organ_url=cfg.organ_url,
        organ_api_key="organ-secret",
    )

    recorded_kwargs: dict[str, Any] = {}

    async def fake_dispatch(**kwargs):
        recorded_kwargs.update(kwargs)
        return {"mode": kwargs.get("mode"), "ok": True}

    monkeypatch.setattr(
        "kaine.modules.hypnos.job_queue_trainer.hot_swap.dispatch",
        fake_dispatch,
    )

    async def fake_service():
        jobs_dir = tmp_path / "jobs"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if jobs_dir.exists():
                for job_dir in jobs_dir.iterdir():
                    if (job_dir / "READY").exists():
                        assert (job_dir / "job.json").is_file()
                        assert (job_dir / "pairs.jsonl").is_file()
                        job = json.loads((job_dir / "job.json").read_text())
                        assert job["adapter_output_dir"] == "out"

                        adapter = job_dir / "out" / "20260930T000000"
                        adapter.mkdir(parents=True)
                        (adapter / "adapter_config.json").write_text(
                            "{}", encoding="utf-8"
                        )
                        (adapter / "adapter.gguf").write_text(
                            "fake-gguf", encoding="utf-8"
                        )
                        (adapter / "README").write_text("info", encoding="utf-8")
                        # This should be ignored by the promotion copytree.
                        checkpoint = adapter / "checkpoint-6"
                        checkpoint.mkdir()
                        (checkpoint / "weights.bin").write_text("old", encoding="utf-8")

                        sha = hashlib.sha256(
                            (adapter / "adapter.gguf").read_bytes()
                        ).hexdigest()
                        result = {
                            "ok": True,
                            "accepted": True,
                            "schema_version": 2,
                            "abliteration_passed": True,
                            "abliteration_probes_scored": 1,
                            "adapter_dir": str(adapter.relative_to(job_dir)),
                            "gguf_sha256": sha,
                            "steps": 7,
                            "dpo_loss": 0.42,
                            "reason": "accepted",
                            "capability_score_before": 0.9,
                            "capability_score_after": 0.88,
                            "capability_loss": 0.02,
                            "samples_used": len(_pairs()),
                        }
                        (job_dir / "result.json").write_text(
                            json.dumps(result), encoding="utf-8"
                        )
                        (job_dir / "DONE").write_text("")
                        return
            await asyncio.sleep(0.05)
        raise TimeoutError("fake service never saw READY")

    service_task = asyncio.create_task(fake_service())
    result = await trainer.train(_pairs(), cfg)
    assert (await service_task) is None

    assert result.accepted is True
    assert result.adapter_path is not None
    final = result.adapter_path
    assert final.is_dir()
    assert (final / "adapter.gguf").exists()
    assert (final / "README").exists()
    assert not (final / "checkpoint-6").exists()
    assert result.dpo_loss == pytest.approx(0.42)
    assert result.capability_loss == pytest.approx(0.02)
    assert result.capability_score_before == pytest.approx(0.9)
    assert result.capability_score_after == pytest.approx(0.88)
    assert result.samples_used == 2
    assert result.reason == "accepted"
    assert result.metadata["backend"] == "job_queue"
    assert result.metadata["hot_swap"] == {"mode": "organ_adapter", "ok": True}

    assert current_path(cfg.adapter_output_dir) == final

    job_dirs = list((tmp_path / "jobs").iterdir())
    assert len(job_dirs) == 1
    assert not (job_dirs[0] / "pairs.jsonl").exists()

    assert recorded_kwargs.get("mode") == "organ_adapter"
    assert recorded_kwargs.get("adapter_path") == final
    assert recorded_kwargs.get("organ_api_key") == "organ-secret"
    assert recorded_kwargs.get("organ_url") == cfg.organ_url
    assert recorded_kwargs.get("organ_adapters_dir") == Path(cfg.organ_adapters_dir)


# --------------------------------------------------------------------------- #
# failure modes
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_timeout_writes_cancelled_and_deletes_pairs(tmp_path):
    """No service picking up the job → timeout error + CANCELLED marker."""
    cfg = _cfg(tmp_path)
    trainer = JobQueueVoiceTrainer(
        jobs_dir=tmp_path / "jobs",
        timeout_s=0.3,
        poll_interval_s=0.05,
    )
    with pytest.raises(SubprocessTrainerError, match="did not finish"):
        await trainer.train(_pairs(), cfg)

    job_dirs = list((tmp_path / "jobs").iterdir())
    assert len(job_dirs) == 1
    assert (job_dirs[0] / "CANCELLED").exists()
    assert not (job_dirs[0] / "pairs.jsonl").exists()


@pytest.mark.asyncio
async def test_failed_result_raises_and_deletes_pairs(tmp_path):
    """result.json with ok=False is an error, never a fake success."""
    cfg = _cfg(tmp_path)
    trainer = JobQueueVoiceTrainer(
        jobs_dir=tmp_path / "jobs",
        timeout_s=1.0,
        poll_interval_s=0.05,
    )

    async def fake_service():
        jobs_dir = tmp_path / "jobs"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if jobs_dir.exists():
                for job_dir in jobs_dir.iterdir():
                    if (job_dir / "READY").exists():
                        (job_dir / "result.json").write_text(
                            json.dumps(
                                {
                                    "ok": False,
                                    "reason": "capability gate rejected",
                                }
                            ),
                            encoding="utf-8",
                        )
                        (job_dir / "DONE").write_text("")
                        return
            await asyncio.sleep(0.05)
        raise TimeoutError("fake service never saw READY")

    service_task = asyncio.create_task(fake_service())
    with pytest.raises(SubprocessTrainerError, match="capability gate rejected"):
        await trainer.train(_pairs(), cfg)
    assert (await service_task) is None

    job_dirs = list((tmp_path / "jobs").iterdir())
    assert len(job_dirs) == 1
    assert not (job_dirs[0] / "pairs.jsonl").exists()


@pytest.mark.asyncio
async def test_adapter_dir_escaping_job_dir_raises(tmp_path):
    """An adapter_dir outside the job dir is rejected before promotion."""
    evil = tmp_path / "evil"
    evil.mkdir()
    (evil / "adapter_config.json").write_text("{}")
    cfg = _cfg(tmp_path)
    trainer = JobQueueVoiceTrainer(
        jobs_dir=tmp_path / "jobs",
        timeout_s=1.0,
        poll_interval_s=0.05,
    )

    async def fake_service():
        jobs_dir = tmp_path / "jobs"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if jobs_dir.exists():
                for job_dir in jobs_dir.iterdir():
                    if (job_dir / "READY").exists():
                        (job_dir / "result.json").write_text(
                            json.dumps(
                                {
                                    "ok": True,
                                    "accepted": True,
                                    "schema_version": 2,
                                    "abliteration_passed": True,
                                    "abliteration_probes_scored": 1,
                                    "adapter_dir": "../evil",
                                    "reason": "accepted",
                                    "capability_loss": 0.0,
                                    "samples_used": 2,
                                    "dpo_loss": 0.1,
                                }
                            ),
                            encoding="utf-8",
                        )
                        (job_dir / "DONE").write_text("")
                        return
            await asyncio.sleep(0.05)
        raise TimeoutError("fake service never saw READY")

    service_task = asyncio.create_task(fake_service())
    with pytest.raises(SubprocessTrainerError, match="is not strictly inside"):
        await trainer.train(_pairs(), cfg)
    assert (await service_task) is None

    job_dirs = list((tmp_path / "jobs").iterdir())
    assert not (job_dirs[0] / "pairs.jsonl").exists()


@pytest.mark.asyncio
async def test_gguf_sha_mismatch_raises(tmp_path):
    """The adapter.gguf sha256 must match result.json."""
    cfg = _cfg(tmp_path)
    trainer = JobQueueVoiceTrainer(
        jobs_dir=tmp_path / "jobs",
        timeout_s=1.0,
        poll_interval_s=0.05,
    )

    async def fake_service():
        jobs_dir = tmp_path / "jobs"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if jobs_dir.exists():
                for job_dir in jobs_dir.iterdir():
                    if (job_dir / "READY").exists():
                        adapter = job_dir / "out" / "20260930T000000"
                        adapter.mkdir(parents=True)
                        (adapter / "adapter_config.json").write_text(
                            "{}", encoding="utf-8"
                        )
                        (adapter / "adapter.gguf").write_text(
                            "fake-gguf", encoding="utf-8"
                        )
                        result = {
                            "ok": True,
                            "accepted": True,
                            "schema_version": 2,
                            "abliteration_passed": True,
                            "abliteration_probes_scored": 1,
                            "adapter_dir": str(adapter.relative_to(job_dir)),
                            "gguf_sha256": "0" * 64,
                            "reason": "accepted",
                            "capability_loss": 0.0,
                            "samples_used": 2,
                            "dpo_loss": 0.1,
                        }
                        (job_dir / "result.json").write_text(
                            json.dumps(result), encoding="utf-8"
                        )
                        (job_dir / "DONE").write_text("")
                        return
            await asyncio.sleep(0.05)
        raise TimeoutError("fake service never saw READY")

    service_task = asyncio.create_task(fake_service())
    with pytest.raises(SubprocessTrainerError, match="sha256 mismatch"):
        await trainer.train(_pairs(), cfg)
    assert (await service_task) is None

    job_dirs = list((tmp_path / "jobs").iterdir())
    assert not (job_dirs[0] / "pairs.jsonl").exists()


async def _tick_counter(period: float, limit: int) -> int:
    count = 0
    while count < limit:
        await asyncio.sleep(period)
        count += 1
    return count


@pytest.mark.asyncio
async def test_does_not_block_event_loop(tmp_path):
    """Polling train() lets other coroutines run while it waits."""
    cfg = _cfg(tmp_path)
    trainer = JobQueueVoiceTrainer(
        jobs_dir=tmp_path / "jobs",
        timeout_s=0.3,
        poll_interval_s=0.05,
    )
    counter_task = asyncio.create_task(_tick_counter(0.02, 1000))
    with pytest.raises(SubprocessTrainerError, match="did not finish"):
        await trainer.train(_pairs(), cfg)
    count = await counter_task
    assert count > 3


@pytest.mark.asyncio
async def test_subprocess_backend_does_not_block_event_loop(tmp_path):
    """The subprocess backend runs the external trainer in a worker thread."""
    stub = _write_subprocess_stub(
        tmp_path,
        """
        import time
        time.sleep(0.5)
        adapter = Path(job['adapter_output_dir']) / 'accepted_adapter'
        adapter.mkdir(parents=True, exist_ok=True)
        (adapter / 'adapter_model.safetensors').write_text('fake-weights')
        (adapter / 'adapter_config.json').write_text('{}')
        result = {
            'ok': True,
            'accepted': True,
            'schema_version': 2,
            'abliteration_passed': True,
            'abliteration_probes_scored': 1,
            'adapter_dir': str(adapter),
            'steps': 3,
            'dpo_loss': 0.1,
            'reason': 'accepted',
            'capability_loss': 0.0,
            'samples_used': len(pairs),
        }
        (job_dir / 'result.json').write_text(json.dumps(result))
        (job_dir / "DONE").write_text("")
        """,
    )
    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=stub,
    )
    counter_task = asyncio.create_task(_tick_counter(0.02, 1000))
    result = await trainer.train(_pairs(), _cfg(tmp_path, trainer_backend="subprocess"))
    count = await counter_task
    assert count > 3
    assert result.accepted is True
    assert result.adapter_path is not None
    assert result.metadata["backend"] == "subprocess"


# --------------------------------------------------------------------------- #
# boot wiring
# --------------------------------------------------------------------------- #
def test_job_queue_backend_selects_job_queue_trainer(tmp_path, _approved, monkeypatch):
    monkeypatch.setenv("KAINE_MODEL_SERVER_API_KEY", "boot-secret")
    trainer = _resolve_trainer(_cfg(tmp_path, trainer_backend="job_queue"))
    assert isinstance(trainer, JobQueueVoiceTrainer)
    assert trainer._organ_adapters_dir == Path(tmp_path / "organ_adapters")
    assert trainer._organ_url == organ_root_url("http://organ:8080")
    assert trainer._organ_api_key == "boot-secret"


def test_job_queue_timeout_zero_raises_config_error(tmp_path, _approved):
    with pytest.raises(VoiceAlignmentConfigError, match="trainer_timeout_s"):
        _resolve_trainer(_cfg(tmp_path, trainer_timeout_s=0.0))


def test_unknown_backend_error_lists_all_three(tmp_path, _approved):
    with pytest.raises(
        VoiceAlignmentConfigError,
        match="('in_process'.*'subprocess'.*'job_queue'|'job_queue'.*'subprocess'.*'in_process')",
    ):
        _resolve_trainer(_cfg(tmp_path, trainer_backend="bogus"))


def test_organ_adapter_hot_swap_mode_accepted_in_effective_mode():
    assert _effective_hot_swap_mode("organ_adapter", None) == "organ_adapter"


def test_organ_adapter_mode_is_valid():
    assert "organ_adapter" in VALID_MODES


@pytest.mark.asyncio
async def test_early_result_without_done_is_not_consumed(tmp_path: Path) -> None:
    """The external script writes result.json before the service converts the
    adapter; the trainer must wait for DONE and time out rather than read it."""
    jobs = tmp_path / "jobs"
    trainer = JobQueueVoiceTrainer(jobs_dir=jobs, timeout_s=0.4, poll_interval_s=0.05)
    cfg = _cfg(tmp_path)

    async def early_script_only() -> None:
        for _ in range(100):
            ready = list(jobs.glob("*/READY"))
            if ready:
                (ready[0].parent / "result.json").write_text(
                    json.dumps({"ok": True, "accepted": True, "adapter_dir": "out/x"})
                )
                return
            await asyncio.sleep(0.01)

    task = asyncio.create_task(early_script_only())
    with pytest.raises(SubprocessTrainerError, match="did not finish"):
        await trainer.train(_pairs(), cfg)
    assert (await task) is None
