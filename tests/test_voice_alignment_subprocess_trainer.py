# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the out-of-process voice-alignment trainer bridge.

``SubprocessVoiceTrainer`` (runtime venv) writes a filesystem job spec, invokes
an external interpreter, and reads back the produced adapter. These tests drive
that plumbing with STUB external entry scripts run by ``.venv/bin/python`` — the
real unsloth DPO is NEVER run here (it isn't in the runtime venv). The stubs
read ``job.json`` + ``pairs.jsonl`` and emit a tiny fake adapter dir +
``result.json``, exercising the round-trip and every fail-loud path.

The load-bearing assertion across all failure cases: the bridge RAISES rather
than fabricating a success (the no-pretend principle).
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

from kaine.modules.hypnos.subprocess_trainer import (
    SubprocessTrainerError,
    SubprocessVoiceTrainer,
)
from kaine.modules.hypnos.voice_alignment import DPOPair, VoiceAlignmentConfig

VENV_PY = str(Path(sys.executable))


def _config(tmp_path: Path) -> VoiceAlignmentConfig:
    return VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
        base_model_path=str(tmp_path / "base_model"),
        trainer_backend="subprocess",
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
    )


def _pairs() -> list[DPOPair]:
    return [
        DPOPair(prompt="hi", chosen="hello there", rejected="hi"),
        DPOPair(prompt="bye", chosen="farewell", rejected="bye"),
    ]


def _write_stub(tmp_path: Path, body: str) -> Path:
    """Write a stub external entry script (run by .venv/bin/python).

    ``body`` is the function body of ``handle(job_dir, job, pairs)`` — it must
    write whatever the test wants into the job dir. Common scaffolding (reading
    job.json/pairs.jsonl) is provided.
    """
    stub = tmp_path / "stub_entry.py"
    stub.write_text(
        "import json, sys\n"
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


# --------------------------------------------------------------------------- #
# round-trip: happy path
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_round_trip_accepted(tmp_path):
    """Stub writes a fake adapter + ok result.json → TrainingResult readback."""
    stub = _write_stub(
        tmp_path,
        """
        adapter = job_dir / 'adapter_out'
        adapter.mkdir(parents=True, exist_ok=True)
        (adapter / 'adapter_model.safetensors').write_text('fake-weights')
        result = {
            'ok': True,
            'accepted': True,
            'adapter_dir': str(adapter),
            'steps': 7,
            'dpo_loss': 0.42,
            'reason': 'accepted',
            'capability_score_before': 0.9,
            'capability_score_after': 0.88,
            'capability_loss': 0.02,
            'samples_used': len(pairs),
        }
        (job_dir / 'result.json').write_text(json.dumps(result))
        """,
    )
    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=stub,
    )
    result = await trainer.train(_pairs(), _config(tmp_path))

    assert result.accepted is True
    assert result.adapter_path is not None
    assert result.adapter_path.is_dir()
    assert (result.adapter_path / "adapter_model.safetensors").exists()
    assert result.dpo_loss == pytest.approx(0.42)
    assert result.capability_loss == pytest.approx(0.02)
    assert result.capability_score_before == pytest.approx(0.9)
    assert result.capability_score_after == pytest.approx(0.88)
    assert result.samples_used == 2
    assert result.reason == "accepted"
    assert result.metadata["backend"] == "subprocess"
    assert result.metadata["steps"] == 7


@pytest.mark.asyncio
async def test_job_spec_written_for_external_process(tmp_path):
    """The job dir carries pairs.jsonl + job.json with the expected shape."""
    captured = tmp_path / "captured.json"
    stub = _write_stub(
        tmp_path,
        f"""
        # Echo the parsed job + pair count so the test can inspect the spec.
        Path(r'{captured}').write_text(json.dumps({{'job': job, 'n_pairs': len(pairs)}}))
        adapter = job_dir / 'a'
        adapter.mkdir(parents=True, exist_ok=True)
        (adapter / 'w').write_text('x')
        (job_dir / 'result.json').write_text(json.dumps({{
            'ok': True, 'accepted': True, 'adapter_dir': str(adapter),
            'steps': 1, 'dpo_loss': 0.1, 'reason': 'accepted',
            'capability_loss': 0.0, 'samples_used': len(pairs),
        }}))
        """,
    )
    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=stub,
    )
    cfg = _config(tmp_path)
    await trainer.train(_pairs(), cfg)

    spec = json.loads(captured.read_text())
    assert spec["n_pairs"] == 2
    job = spec["job"]
    assert job["base_model_path"] == str(tmp_path / "base_model")
    assert job["lora_rank"] == cfg.lora_rank
    assert job["dpo_beta"] == pytest.approx(cfg.dpo_beta)
    assert job["seed"] == cfg.seed
    assert job["schema_version"] == 1
    # Probe paths resolve to the bundled defaults (the external gates use them).
    assert job["capability_probe_path"].endswith("default.jsonl")
    assert job["abliteration_probe_path"].endswith("abliteration_probes.jsonl")


@pytest.mark.asyncio
async def test_clean_rejection_is_not_an_error(tmp_path):
    """An external gate rejection (ok=true, accepted=false) returns a result,
    not a raise — mirrors the in-process trainer's reject path."""
    stub = _write_stub(
        tmp_path,
        """
        (job_dir / 'result.json').write_text(json.dumps({
            'ok': True,
            'accepted': False,
            'adapter_dir': None,
            'steps': 5,
            'dpo_loss': 0.3,
            'reason': 'abliteration veto: adapter deflected probe',
            'capability_score_before': 0.9,
            'capability_score_after': None,
            'capability_loss': None,
            'samples_used': len(pairs),
        }))
        """,
    )
    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=stub,
    )
    result = await trainer.train(_pairs(), _config(tmp_path))
    assert result.accepted is False
    assert result.adapter_path is None
    assert "abliteration veto" in result.reason
    assert result.capability_loss == 0.0  # None → 0.0 floor, never a fake number


# --------------------------------------------------------------------------- #
# fail-loud paths — every one must RAISE, never fabricate success
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_nonzero_exit_raises(tmp_path):
    stub = _write_stub(
        tmp_path,
        """
        # Write a 'success' result but exit non-zero: the bridge must NOT trust it.
        (job_dir / 'result.json').write_text(json.dumps({
            'ok': True, 'accepted': True, 'adapter_dir': str(job_dir),
            'reason': 'accepted', 'samples_used': len(pairs),
        }))
        return 3
        """,
    )
    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=stub,
    )
    with pytest.raises(SubprocessTrainerError, match="exited 3"):
        await trainer.train(_pairs(), _config(tmp_path))


@pytest.mark.asyncio
async def test_missing_result_json_raises(tmp_path):
    stub = _write_stub(tmp_path, "return 0  # writes no result.json")
    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=stub,
    )
    with pytest.raises(SubprocessTrainerError, match="no result.json"):
        await trainer.train(_pairs(), _config(tmp_path))


@pytest.mark.asyncio
async def test_result_ok_false_raises(tmp_path):
    stub = _write_stub(
        tmp_path,
        """
        (job_dir / 'result.json').write_text(json.dumps({
            'ok': False, 'reason': 'external trainer crashed', 'samples_used': 0,
        }))
        """,
    )
    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=stub,
    )
    with pytest.raises(SubprocessTrainerError, match="reported failure"):
        await trainer.train(_pairs(), _config(tmp_path))


@pytest.mark.asyncio
async def test_accepted_but_missing_adapter_raises(tmp_path):
    """ok=true + accepted=true but the adapter_dir does not exist → raise."""
    stub = _write_stub(
        tmp_path,
        """
        (job_dir / 'result.json').write_text(json.dumps({
            'ok': True, 'accepted': True,
            'adapter_dir': str(job_dir / 'does_not_exist'),
            'reason': 'accepted', 'samples_used': len(pairs),
        }))
        """,
    )
    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=stub,
    )
    with pytest.raises(SubprocessTrainerError, match="missing or empty"):
        await trainer.train(_pairs(), _config(tmp_path))


@pytest.mark.asyncio
async def test_accepted_but_empty_adapter_dir_raises(tmp_path):
    stub = _write_stub(
        tmp_path,
        """
        adapter = job_dir / 'empty_adapter'
        adapter.mkdir(parents=True, exist_ok=True)  # exists but empty
        (job_dir / 'result.json').write_text(json.dumps({
            'ok': True, 'accepted': True, 'adapter_dir': str(adapter),
            'reason': 'accepted', 'samples_used': len(pairs),
        }))
        """,
    )
    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=stub,
    )
    with pytest.raises(SubprocessTrainerError, match="missing or empty"):
        await trainer.train(_pairs(), _config(tmp_path))


@pytest.mark.asyncio
async def test_timeout_raises(tmp_path):
    stub = _write_stub(tmp_path, "import time; time.sleep(30); return 0")
    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=stub,
        timeout_s=0.5,
    )
    with pytest.raises(SubprocessTrainerError, match="timed out"):
        await trainer.train(_pairs(), _config(tmp_path))


@pytest.mark.asyncio
async def test_missing_entry_script_raises(tmp_path):
    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=tmp_path / "nope.py",
    )
    with pytest.raises(SubprocessTrainerError, match="entry script missing"):
        await trainer.train(_pairs(), _config(tmp_path))


@pytest.mark.asyncio
async def test_no_pairs_returns_clean_result(tmp_path):
    """No pairs → an honest non-accepted result, no subprocess launched."""
    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=tmp_path / "unused.py",
    )
    result = await trainer.train([], _config(tmp_path))
    assert result.accepted is False
    assert result.adapter_path is None
    assert "no DPO pairs" in result.reason


@pytest.mark.asyncio
async def test_missing_base_model_raises(tmp_path):
    cfg = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
        base_model_path=None,
        trainer_backend="subprocess",
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
    )
    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=tmp_path / "unused.py",
    )
    with pytest.raises(SubprocessTrainerError, match="base_model_path"):
        await trainer.train(_pairs(), cfg)
