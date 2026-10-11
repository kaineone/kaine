# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Coherence between voice-alignment trainer backends and hot-swap modes.

- Boot refuses ``organ_adapter`` unless the backend is ``job_queue``.
- The subprocess backend dispatches the configured hot swap after an accepted
  adapter, matching the in-process trainer.
- ``run_with_organ_window`` does not bracket ``job_queue`` training.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path
from typing import Any, Optional

import pytest

from kaine.boot import VoiceAlignmentConfigError, _validate_backend_pairing
from kaine.modules.hypnos.organ_window import (
    OrganServerController,
    run_with_organ_window,
)
from kaine.modules.hypnos.subprocess_trainer import SubprocessVoiceTrainer
from kaine.modules.hypnos.voice_alignment import (
    DPOPair,
    TrainingResult,
    VoiceAlignmentConfig,
)

VENV_PY = str(Path(sys.executable))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _voice_cfg(tmp_path, **over) -> VoiceAlignmentConfig:
    base = dict(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
        base_model_path=str(tmp_path / "base_model"),
        trainer_backend="in_process",
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        hot_swap_mode="manual",
    )
    base.update(over)
    return VoiceAlignmentConfig(**base)


def _pairs() -> list[DPOPair]:
    return [
        DPOPair(prompt="hi", chosen="hello there", rejected="hi"),
        DPOPair(prompt="bye", chosen="farewell", rejected="bye"),
    ]


def _write_stub(tmp_path: Path, body: str) -> Path:
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


def _accepted_stub(tmp_path: Path) -> Path:
    return _write_stub(
        tmp_path,
        """
        # The real script promotes inside the adapter output dir.
        adapter = Path(job['adapter_output_dir']) / 'adapter_out'
        adapter.mkdir(parents=True, exist_ok=True)
        (adapter / 'adapter_config.json').write_text('{}')
        (adapter / 'adapter_model.safetensors').write_text('fake-weights')
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
            'capability_loss': 0.01,
            'samples_used': len(pairs),
        }
        (job_dir / 'result.json').write_text(json.dumps(result))
        """,
    )


def _rejected_stub(tmp_path: Path) -> Path:
    return _write_stub(
        tmp_path,
        """
        (job_dir / 'result.json').write_text(json.dumps({
            'ok': True,
            'accepted': False,
            'schema_version': 2,
            'reason': 'rejected by gate',
            'capability_loss': None,
            'adapter_dir': None,
            'samples_used': len(pairs),
        }))
        """,
    )


class RecordingController(OrganServerController):
    """Controller whose stop/start are recorded."""

    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []
        super().__init__(config={})

    def unload(self) -> bool:
        self.events.append(("unload", None))
        return True

    def reload(self, *, adapter_path: Optional[Path]) -> bool:
        self.events.append(("reload", str(adapter_path) if adapter_path else None))
        return True


def _single_gpu_host():
    return {"cuda_devices": [{"device": "cuda:0", "free_vram_gb": 11.6}]}


# --------------------------------------------------------------------------- #
# Boot: backend / hot-swap pairing
# --------------------------------------------------------------------------- #
def test_organ_adapter_refused_with_in_process_backend(tmp_path):
    with pytest.raises(VoiceAlignmentConfigError) as exc:
        _validate_backend_pairing(
            _voice_cfg(tmp_path, trainer_backend="in_process", hot_swap_mode="organ_adapter")
        )
    assert "organ_adapter" in str(exc.value)
    assert "job_queue" in str(exc.value)


def test_organ_adapter_refused_with_subprocess_backend(tmp_path):
    with pytest.raises(VoiceAlignmentConfigError) as exc:
        _validate_backend_pairing(
            _voice_cfg(tmp_path, trainer_backend="subprocess", hot_swap_mode="organ_adapter")
        )
    assert "organ_adapter" in str(exc.value)


def test_organ_adapter_allowed_with_job_queue_backend(tmp_path):
    _validate_backend_pairing(
        _voice_cfg(tmp_path, trainer_backend="job_queue", hot_swap_mode="organ_adapter")
    )


@pytest.mark.parametrize("backend", ["in_process", "subprocess", "job_queue"])
def test_manual_allowed_for_all_backends(tmp_path, backend):
    _validate_backend_pairing(
        _voice_cfg(tmp_path, trainer_backend=backend, hot_swap_mode="manual")
    )


@pytest.mark.parametrize("backend", ["in_process", "subprocess", "job_queue"])
def test_reload_endpoint_allowed_for_all_backends(tmp_path, backend):
    _validate_backend_pairing(
        _voice_cfg(tmp_path, trainer_backend=backend, hot_swap_mode="reload_endpoint")
    )


@pytest.mark.parametrize("backend", ["in_process", "subprocess", "job_queue"])
def test_restart_service_allowed_for_all_backends(tmp_path, backend):
    _validate_backend_pairing(
        _voice_cfg(tmp_path, trainer_backend=backend, hot_swap_mode="restart_service")
    )


def test_disabled_voice_alignment_skips_backend_pairing_validation(tmp_path):
    _validate_backend_pairing(
        _voice_cfg(
            tmp_path,
            enabled=False,
            trainer_backend="in_process",
            hot_swap_mode="organ_adapter",
        )
    )


# --------------------------------------------------------------------------- #
# Subprocess trainer: hot-swap dispatch
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_subprocess_dispatches_hot_swap_after_accepted_adapter(tmp_path, monkeypatch):
    stub = _accepted_stub(tmp_path)
    calls: list[dict[str, Any]] = []

    async def recorder(
        *,
        mode: str,
        adapter_output_dir: Path,
        adapter_path: Path,
        reload_endpoint_url: Optional[str],
        restart_service_unit: Optional[str],
    ):
        calls.append(
            dict(
                mode=mode,
                adapter_output_dir=adapter_output_dir,
                adapter_path=adapter_path,
                reload_endpoint_url=reload_endpoint_url,
                restart_service_unit=restart_service_unit,
            )
        )
        return {"mode": mode, "ok": True, "notified": reload_endpoint_url}

    monkeypatch.setattr(
        "kaine.modules.hypnos.subprocess_trainer.dispatch_hot_swap",
        recorder,
    )

    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=stub,
    )
    cfg = _voice_cfg(
        tmp_path,
        trainer_backend="subprocess",
        hot_swap_mode="reload_endpoint",
        reload_endpoint_url="http://localhost:9999/reload",
    )
    result = await trainer.train(_pairs(), cfg)

    assert result.accepted is True
    assert result.adapter_path is not None
    assert len(calls) == 1
    assert calls[0]["mode"] == "reload_endpoint"
    assert calls[0]["adapter_path"] == result.adapter_path
    assert calls[0]["reload_endpoint_url"] == "http://localhost:9999/reload"
    assert result.metadata["hot_swap"]["ok"] is True
    assert result.metadata["hot_swap"]["notified"] == "http://localhost:9999/reload"


@pytest.mark.asyncio
async def test_subprocess_does_not_dispatch_when_rejected(tmp_path, monkeypatch):
    stub = _rejected_stub(tmp_path)
    calls: list[dict[str, Any]] = []

    async def recorder(
        *,
        mode: str,
        adapter_output_dir: Path,
        adapter_path: Path,
        reload_endpoint_url: Optional[str],
        restart_service_unit: Optional[str],
    ):
        calls.append(dict(mode=mode, adapter_path=adapter_path))
        return {"mode": mode, "ok": True}

    monkeypatch.setattr(
        "kaine.modules.hypnos.subprocess_trainer.dispatch_hot_swap",
        recorder,
    )

    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=stub,
    )
    cfg = _voice_cfg(tmp_path, trainer_backend="subprocess", hot_swap_mode="reload_endpoint")
    result = await trainer.train(_pairs(), cfg)

    assert result.accepted is False
    assert len(calls) == 0


@pytest.mark.asyncio
async def test_subprocess_hot_swap_failure_keeps_result_accepted(tmp_path, monkeypatch):
    stub = _accepted_stub(tmp_path)

    async def raiser(
        *,
        mode: str,
        adapter_output_dir: Path,
        adapter_path: Path,
        reload_endpoint_url: Optional[str],
        restart_service_unit: Optional[str],
    ):
        raise RuntimeError("reload endpoint unreachable")

    monkeypatch.setattr(
        "kaine.modules.hypnos.subprocess_trainer.dispatch_hot_swap",
        raiser,
    )

    trainer = SubprocessVoiceTrainer(
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
        entry_script=stub,
    )
    cfg = _voice_cfg(tmp_path, trainer_backend="subprocess", hot_swap_mode="reload_endpoint")
    result = await trainer.train(_pairs(), cfg)

    assert result.accepted is True
    assert result.adapter_path is not None
    assert result.metadata["hot_swap"]["ok"] is False
    assert result.metadata["hot_swap"]["mode"] == "reload_endpoint"


# --------------------------------------------------------------------------- #
# Organ window: job-queue exemption
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_organ_window_skips_bracket_for_job_queue(tmp_path):
    ctrl = RecordingController()

    async def train():
        return TrainingResult(
            accepted=True,
            adapter_path=None,
            capability_loss=0.0,
            reason="trained",
            samples_used=2,
        )

    result, window = await run_with_organ_window(
        train=train,
        config={},
        serve_device="cuda:0",
        hot_swap_mode="organ_adapter",
        trainer_backend="job_queue",
        controller=ctrl,
        host_describer=_single_gpu_host,
        state_path=tmp_path / "organ_window.json",
    )

    assert result.accepted is True
    assert window.bracketed is False
    assert window.organ_restored is True
    assert "job_queue" in window.skipped_reason
    assert ctrl.events == []


@pytest.mark.asyncio
async def test_organ_window_brackets_subprocess_reload_endpoint(tmp_path):
    ctrl = RecordingController()

    async def train():
        return TrainingResult(
            accepted=True,
            adapter_path=None,
            capability_loss=0.0,
            reason="trained",
            samples_used=2,
        )

    result, window = await run_with_organ_window(
        train=train,
        config={},
        serve_device="cuda:0",
        hot_swap_mode="reload_endpoint",
        trainer_backend="subprocess",
        controller=ctrl,
        host_describer=_single_gpu_host,
        state_path=tmp_path / "organ_window.json",
    )

    assert result.accepted is True
    assert window.bracketed is True
    assert window.organ_restored is True
    assert window.error is None
    assert ctrl.events == [("unload", None), ("reload", None)]
