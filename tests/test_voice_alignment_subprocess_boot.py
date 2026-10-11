# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boot-time backend selection for the out-of-process voice-alignment trainer.

``boot.py::_resolve_trainer`` picks the trainer by ``trainer_backend``. The
subprocess backend must:
  - construct a SubprocessVoiceTrainer when trainer_python is set + exists;
  - fail LOUDLY (VoiceAlignmentConfigError) when trainer_python is empty or
    points at a non-existent path — never silently degrade to FakeTrainer.

The two-layer operator gate (config enabled + the approval env var) is enforced
exactly as for the in-process path.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

from kaine.boot import VoiceAlignmentConfigError, _resolve_trainer
from kaine.modules.hypnos.subprocess_trainer import SubprocessVoiceTrainer
from kaine.modules.hypnos.voice_alignment import (
    OPERATOR_APPROVED_ENV,
    VoiceAlignmentConfig,
)

VENV_PY = str(Path(sys.executable))


def _cfg(tmp_path, **over) -> VoiceAlignmentConfig:
    base = dict(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
        base_model_path=str(tmp_path / "base_model"),
        trainer_backend="subprocess",
        trainer_python=VENV_PY,
        trainer_workdir=str(tmp_path / "jobs"),
    )
    base.update(over)
    return VoiceAlignmentConfig(**base)


@pytest.fixture
def _approved(monkeypatch):
    monkeypatch.setenv(OPERATOR_APPROVED_ENV, "1")
    yield


def test_subprocess_backend_selects_subprocess_trainer(tmp_path, _approved):
    trainer = _resolve_trainer(_cfg(tmp_path))
    assert isinstance(trainer, SubprocessVoiceTrainer)


def test_in_process_backend_runs_the_trainer_script(tmp_path, _approved, monkeypatch):
    import types

    for name in ("unsloth", "trl", "peft", "datasets"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))

    trainer = _resolve_trainer(_cfg(tmp_path, trainer_backend="in_process", trainer_python=""))
    assert isinstance(trainer, SubprocessVoiceTrainer)
    assert trainer.run_in_process is True


def test_in_process_backend_fails_closed_without_training_deps(tmp_path, _approved):
    for name in ("unsloth", "trl", "peft", "datasets"):
        sys.modules.pop(name, None)

    with pytest.raises(VoiceAlignmentConfigError) as excinfo:
        _resolve_trainer(_cfg(tmp_path, trainer_backend="in_process", trainer_python=""))

    msg = str(excinfo.value)
    assert "subprocess" in msg
    assert "job_queue" in msg


def test_empty_trainer_python_raises_config_error(tmp_path, _approved):
    with pytest.raises(VoiceAlignmentConfigError, match="trainer_python is empty"):
        _resolve_trainer(_cfg(tmp_path, trainer_python=""))


def test_nonexistent_trainer_python_raises_config_error(tmp_path, _approved):
    bogus = str(tmp_path / "no" / "such" / "python")
    with pytest.raises(VoiceAlignmentConfigError, match="does not exist"):
        _resolve_trainer(_cfg(tmp_path, trainer_python=bogus))


def test_unknown_backend_raises_config_error(tmp_path, _approved):
    with pytest.raises(VoiceAlignmentConfigError, match="trainer_backend"):
        _resolve_trainer(_cfg(tmp_path, trainer_backend="bogus"))


def test_disabled_returns_none(tmp_path):
    assert _resolve_trainer(_cfg(tmp_path, enabled=False)) is None


def test_not_operator_approved_returns_none(tmp_path, monkeypatch):
    monkeypatch.delenv(OPERATOR_APPROVED_ENV, raising=False)
    assert _resolve_trainer(_cfg(tmp_path)) is None
