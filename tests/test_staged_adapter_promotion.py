# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The trainer stages its adapter; kaine promotes only after validation.

On every backend (in-process, subprocess, job queue) the trainer writes its
candidate under the job directory. The entity's adapter store and its
``current`` link change only after :func:`validate_trainer_result` accepts the
result. A refused result leaves ``current`` where it was, the refusal is in
the voice-alignment audit trail, and the next sleep trains from the old
adapter, never from the refused one.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

import kaine.modules.sleep.capability_eval as capability_eval
from kaine.modules.sleep import adapter_store
from kaine.modules.sleep.job_queue_trainer import JobQueueVoiceTrainer
from kaine.modules.sleep.subprocess_trainer import (
    SCHEMA_VERSION,
    SubprocessTrainerError,
    SubprocessVoiceTrainer,
    TrainerResultRefusedError,
    promote_staged_adapter,
    write_job_spec,
)
from kaine.modules.sleep.voice_alignment import DPOPair, VoiceAlignmentConfig
from kaine.modules.sleep.voice_audit import voice_audit_path
from tests.fake_training_stack import (
    RELATIVE_ABLITERATION_PASS,
    run_inprocess,
    write_one_probe_set,
)

OLD = "20260101T000000"
NEW = "20261031T120000"


def _pair() -> DPOPair:
    return DPOPair(prompt="hi", chosen="hello", rejected="go away", system="sys")


def _seed_current(store: Path) -> Path:
    """An accepted adapter the entity already has, marked so it can be told apart."""
    old = store / OLD
    old.mkdir(parents=True)
    (old / "adapter_config.json").write_text("{}", encoding="utf-8")
    (old / "marker.txt").write_text("old", encoding="utf-8")
    os.symlink(OLD, store / "current")
    return old


def _assert_current_is_old(store: Path) -> None:
    assert adapter_store.current_path(store) == (store / OLD).resolve()
    # Nothing but the old adapter and the link is in the store.
    assert sorted(p.name for p in store.iterdir() if p.name != "current") == [OLD]


def _assert_next_sleep_uses_old(tmp_path: Path, config: VoiceAlignmentConfig) -> None:
    """The next job's previous adapter is the old one, not the refused candidate."""
    next_job = tmp_path / "next-job"
    next_job.mkdir()
    write_job_spec(
        next_job,
        [_pair()],
        config,
        base_path=str(config.base_model_path),
        adapter_output_dir="out",
    )
    assert (next_job / "previous_adapter" / "marker.txt").read_text(encoding="utf-8") == "old"


def _last_audit(store: Path) -> dict[str, Any]:
    lines = voice_audit_path(store).read_text(encoding="utf-8").splitlines()
    return json.loads([line for line in lines if line.strip()][-1])


def _no_staged_left(jobs: Path) -> None:
    assert not any((d / "out").exists() for d in jobs.iterdir() if d.is_dir())


def _accepted(adapter_dir: str, **overrides: Any) -> dict[str, Any]:
    result = {
        "ok": True,
        "accepted": True,
        "schema_version": SCHEMA_VERSION,
        **RELATIVE_ABLITERATION_PASS,
        "adapter_dir": adapter_dir,
        "reason": "accepted",
        "capability_loss": 0.0,
        "samples_used": 1,
        "steps": 1,
        "dpo_loss": 0.1,
    }
    result.update(overrides)
    return result


# A result the trainer calls accepted but whose own record shows the adapter
# deflecting on a probe the base passed: the kaine side must refuse it.
_REFUSED = {
    "abliteration_adapter_deflecting": [
        {"index": 0, "probe_id": "p1", "matched_pattern": "I cannot"}
    ],
    "abliteration_adapter_deflecting_total": 1,
}


# --------------------------------------------------------------------------- #
# in-process backend (the real trainer script on the fake training stack)
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_in_process_refused_result_leaves_current_in_place(
    tmp_path, fake_training_stack, monkeypatch
):
    store = tmp_path / "store" / "adapters"
    _seed_current(store)

    # The script's own veto passes; the kaine side's recomputation refuses.
    def refuse(base, adapter):
        return capability_eval.RelativeAbliterationVerdict(
            passed=False, reason="forced kaine-side refusal"
        )

    monkeypatch.setattr(capability_eval, "relative_abliteration_verdict", refuse)

    with pytest.raises(TrainerResultRefusedError, match="forced kaine-side refusal"):
        await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})

    _assert_current_is_old(store)
    _no_staged_left(tmp_path / "jobs")
    last = _last_audit(store)
    assert last["event"] == "trainer_result_refused"
    assert last["accepted"] is False
    assert "forced kaine-side refusal" in last["reason"]
    config = VoiceAlignmentConfig(
        intent_log_path=str(tmp_path / "intent.jsonl"),
        adapter_output_dir=str(store),
        base_model_path=str(tmp_path / "base_model"),
    )
    _assert_next_sleep_uses_old(tmp_path, config)


@pytest.mark.asyncio
async def test_in_process_accepted_result_is_promoted_into_the_store(
    tmp_path, fake_training_stack
):
    store = tmp_path / "store" / "adapters"
    _seed_current(store)

    result = await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})

    assert result.accepted is True
    assert result.adapter_path is not None
    assert result.adapter_path.parent == store
    assert adapter_store.current_path(store) == result.adapter_path.resolve()
    assert (result.adapter_path / "adapter_config.json").is_file()
    _no_staged_left(tmp_path / "jobs")


# --------------------------------------------------------------------------- #
# subprocess backend (a stub entry script run by this interpreter)
# --------------------------------------------------------------------------- #
def _subprocess_trainer(tmp_path: Path, result_overrides: dict[str, Any]) -> SubprocessVoiceTrainer:
    stub = tmp_path / "stub_entry.py"
    stub.write_text(
        textwrap.dedent(
            f"""
            import json, sys
            from pathlib import Path

            job_dir = Path(sys.argv[1])
            job = json.loads((job_dir / "job.json").read_text())
            adapter = Path(job["adapter_output_dir"]) / {NEW!r}
            adapter.mkdir(parents=True)
            (adapter / "adapter_config.json").write_text("{{}}")
            (adapter / "adapter_model.safetensors").write_text("new")
            result = {_accepted("__ADAPTER__", **result_overrides)!r}
            result["adapter_dir"] = str(adapter)
            (job_dir / "result.json").write_text(json.dumps(result))
            """
        ),
        encoding="utf-8",
    )
    return SubprocessVoiceTrainer(
        trainer_python=sys.executable,
        trainer_workdir=tmp_path / "jobs",
        entry_script=stub,
    )


def _subprocess_config(tmp_path: Path, store: Path) -> VoiceAlignmentConfig:
    return VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=store,
        enabled=True,
        base_model_path=str(tmp_path / "base_model"),
        trainer_backend="subprocess",
        trainer_python=sys.executable,
        trainer_workdir=str(tmp_path / "jobs"),
        abliteration_probe_path=str(write_one_probe_set(tmp_path)),
    )


@pytest.mark.asyncio
async def test_subprocess_refused_result_leaves_current_in_place(tmp_path):
    store = tmp_path / "adapters"
    _seed_current(store)
    config = _subprocess_config(tmp_path, store)
    trainer = _subprocess_trainer(tmp_path, _REFUSED)

    with pytest.raises(TrainerResultRefusedError, match="'p1'"):
        await trainer.train([_pair()], config)

    _assert_current_is_old(store)
    _no_staged_left(tmp_path / "jobs")
    assert _last_audit(store)["event"] == "trainer_result_refused"
    _assert_next_sleep_uses_old(tmp_path, config)


@pytest.mark.asyncio
async def test_subprocess_accepted_result_is_promoted_into_the_store(tmp_path):
    store = tmp_path / "adapters"
    _seed_current(store)
    config = _subprocess_config(tmp_path, store)
    trainer = _subprocess_trainer(tmp_path, {})

    result = await trainer.train([_pair()], config)

    assert result.accepted is True
    assert result.adapter_path == store / NEW
    assert adapter_store.current_path(store) == (store / NEW).resolve()
    assert (store / NEW / "adapter_model.safetensors").read_text() == "new"
    _no_staged_left(tmp_path / "jobs")


# --------------------------------------------------------------------------- #
# job-queue backend (a fake kaine-trainer service)
# --------------------------------------------------------------------------- #
def _job_queue_config(tmp_path: Path, store: Path) -> VoiceAlignmentConfig:
    (tmp_path / "base_model").mkdir(exist_ok=True)
    return VoiceAlignmentConfig(
        intent_log_path=str(tmp_path / "intent.jsonl"),
        adapter_output_dir=str(store),
        enabled=True,
        base_model_path=str(tmp_path / "base_model"),
        trainer_backend="job_queue",
        trainer_jobs_dir=str(tmp_path / "jobs"),
        trainer_timeout_s=300.0,
        abliteration_probe_path=str(write_one_probe_set(tmp_path)),
        hot_swap_mode="organ_adapter",
        organ_url="http://organ",
        organ_adapters_dir=str(tmp_path / "organ_adapters"),
        adapter_retention=0,
    )


async def _run_job_queue(tmp_path: Path, config: VoiceAlignmentConfig, result_overrides, monkeypatch):
    trainer = JobQueueVoiceTrainer(
        jobs_dir=tmp_path / "jobs",
        timeout_s=10.0,
        poll_interval_s=0.05,
        organ_adapters_dir=Path(config.organ_adapters_dir),
        organ_url=config.organ_url,
        organ_api_key="organ-secret",
    )

    async def fake_dispatch(**kwargs):
        return {"mode": kwargs.get("mode"), "ok": True}

    monkeypatch.setattr("kaine.modules.sleep.job_queue_trainer.hot_swap.dispatch", fake_dispatch)

    async def fake_service():
        jobs_dir = tmp_path / "jobs"
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if jobs_dir.exists():
                for job_dir in jobs_dir.iterdir():
                    if (job_dir / "READY").exists():
                        adapter_dir = job_dir / "out" / NEW
                        adapter_dir.mkdir(parents=True)
                        (adapter_dir / "adapter_config.json").write_text("{}", encoding="utf-8")
                        (adapter_dir / "adapter.gguf").write_text("gguf", encoding="utf-8")
                        sha = hashlib.sha256(b"gguf").hexdigest()
                        result = _accepted(
                            str(adapter_dir.relative_to(job_dir)),
                            gguf_sha256=sha,
                            **result_overrides,
                        )
                        (job_dir / "result.json").write_text(json.dumps(result), encoding="utf-8")
                        (job_dir / "DONE").write_text("", encoding="utf-8")
                        return
            await asyncio.sleep(0.01)

    service = asyncio.create_task(fake_service())
    try:
        return await trainer.train([_pair()], config)
    finally:
        await service


@pytest.mark.asyncio
async def test_job_queue_refused_result_leaves_current_in_place(tmp_path, monkeypatch):
    store = tmp_path / "adapters"
    _seed_current(store)
    config = _job_queue_config(tmp_path, store)

    with pytest.raises(TrainerResultRefusedError, match="'p1'"):
        await _run_job_queue(tmp_path, config, _REFUSED, monkeypatch)

    _assert_current_is_old(store)
    assert _last_audit(store)["event"] == "trainer_result_refused"
    _assert_next_sleep_uses_old(tmp_path, config)


@pytest.mark.asyncio
async def test_job_queue_accepted_result_is_promoted_into_the_store(tmp_path, monkeypatch):
    store = tmp_path / "adapters"
    _seed_current(store)
    config = _job_queue_config(tmp_path, store)

    result = await _run_job_queue(tmp_path, config, {}, monkeypatch)

    assert result.accepted is True
    assert adapter_store.current_path(store) == (store / NEW).resolve()


# --------------------------------------------------------------------------- #
# promotion itself
# --------------------------------------------------------------------------- #
def test_failed_promotion_leaves_current_in_place(tmp_path):
    store = tmp_path / "adapters"
    _seed_current(store)
    staged = tmp_path / "job" / "out" / OLD  # same name as the live adapter
    staged.mkdir(parents=True)
    (staged / "adapter_config.json").write_text("{}", encoding="utf-8")
    (staged / "marker.txt").write_text("new", encoding="utf-8")

    with pytest.raises(SubprocessTrainerError, match="adapter promotion failed"):
        promote_staged_adapter(staged, store, job_dir=tmp_path / "job")

    _assert_current_is_old(store)
    assert (store / OLD / "marker.txt").read_text(encoding="utf-8") == "old"
    assert not adapter_store.tmp_dir_for(store, OLD).exists()


def test_validation_refusal_is_a_trainer_error():
    # Callers that handle SubprocessTrainerError keep handling a refusal.
    assert issubclass(TrainerResultRefusedError, SubprocessTrainerError)
