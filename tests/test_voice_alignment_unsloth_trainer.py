# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine.modules.hypnos.unsloth_trainer.UnslothDPOTrainer.

Uses a FakeUnslothBackend so no real CUDA model is loaded. Verifies
the trainer's contract: tmp-dir staging, capability-loss veto,
atomic promotion via adapter_store.promote(), retention sweep,
hot-swap dispatch, and TrainingResult field population.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from kaine.modules.hypnos.capability_eval import (
    NoopAbliterationScorer,
    NoopCapabilityEval,
)
from kaine.modules.hypnos.voice_alignment import (
    DPOPair,
    TrainingResult,
    VoiceAlignmentConfig,
)


# Make the extras-check think they're installed for these tests. We're
# using a fake backend, so real DPOTrainer is never called.
@pytest.fixture(autouse=True)
def _fake_training_extras(monkeypatch):
    for name in ("unsloth", "trl", "peft", "datasets"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    yield


class FakeBackend:
    def __init__(
        self,
        *,
        dpo_loss: float = 0.123,
        load_raises: BaseException | None = None,
        dpo_raises: BaseException | None = None,
        save_raises: BaseException | None = None,
    ) -> None:
        self.calls: list[tuple[str, dict]] = []
        self._dpo_loss = dpo_loss
        self._load_raises = load_raises
        self._dpo_raises = dpo_raises
        self._save_raises = save_raises

    def load_model(self, *, base_model_path, training_device, lora_rank):
        self.calls.append(
            (
                "load_model",
                {
                    "base_model_path": base_model_path,
                    "training_device": training_device,
                    "lora_rank": lora_rank,
                },
            )
        )
        if self._load_raises:
            raise self._load_raises
        return ("fake-model", "fake-tokenizer")

    def run_dpo(self, *, model, tokenizer, pairs, config, output_dir):
        self.calls.append(
            (
                "run_dpo",
                {
                    "pairs": len(pairs),
                    "output_dir": str(output_dir),
                    "lr": config.learning_rate,
                    "beta": config.dpo_beta,
                    "max_samples": config.max_samples,
                },
            )
        )
        if self._dpo_raises:
            raise self._dpo_raises
        return self._dpo_loss

    def save_adapter(self, *, model, tokenizer, output_dir):
        self.calls.append(("save_adapter", {"output_dir": str(output_dir)}))
        if self._save_raises:
            raise self._save_raises
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "adapter_model.safetensors").write_text(
            "fake", encoding="utf-8"
        )
        (Path(output_dir) / "adapter_config.json").write_text(
            "{}", encoding="utf-8"
        )


def _config(tmp_path: Path, **overrides) -> VoiceAlignmentConfig:
    return VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=True,
        base_model_path=str(tmp_path / "fake-base-model"),
        capability_loss_threshold=overrides.pop("threshold", 0.05),
        adapter_retention=overrides.pop("retention", 5),
        **overrides,
    )


def _pairs(n: int = 3) -> list[DPOPair]:
    return [DPOPair(prompt=f"p{i}", chosen=f"c{i}", rejected=f"r{i}") for i in range(n)]


@pytest.mark.asyncio
async def test_accepts_when_capability_loss_under_threshold(tmp_path: Path):
    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    backend = FakeBackend(dpo_loss=0.42)
    capability = NoopCapabilityEval(score=0.60)  # before & after both 0.60
    trainer = UnslothDPOTrainer(
        capability_eval=capability,
        abliteration_scorer=NoopAbliterationScorer(),
        backend=backend,
    )
    result = await trainer.train(_pairs(), _config(tmp_path))
    assert result.accepted is True
    assert result.dpo_loss == pytest.approx(0.42)
    assert result.capability_score_before == pytest.approx(0.60)
    assert result.capability_score_after == pytest.approx(0.60)
    assert result.capability_loss == pytest.approx(0.0)
    assert result.adapter_path is not None
    assert result.adapter_path.exists()
    # `current` symlink swung to the new adapter.
    current = result.adapter_path.parent / "current"
    assert current.is_symlink()
    assert current.resolve() == result.adapter_path


@pytest.mark.asyncio
async def test_rejects_when_capability_loss_above_threshold(tmp_path: Path):
    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    # Custom eval: 0.80 before training, 0.40 after. Loss = 0.40 > 0.05.
    class DroppingEval:
        def __init__(self) -> None:
            self.calls = 0

        async def eval(self, model, tokenizer):
            self.calls += 1
            return 0.80 if self.calls == 1 else 0.40

    backend = FakeBackend()
    trainer = UnslothDPOTrainer(
        capability_eval=DroppingEval(),
        abliteration_scorer=NoopAbliterationScorer(),
        backend=backend,
    )
    result = await trainer.train(_pairs(), _config(tmp_path))
    assert result.accepted is False
    assert result.capability_loss == pytest.approx(0.40)
    assert result.adapter_path is None
    # No surviving tmp or final dirs.
    adapter_dir = tmp_path / "adapters"
    survivors = list(adapter_dir.iterdir()) if adapter_dir.exists() else []
    # Only the directory itself; no actual adapter dirs.
    assert all(p.name == "current" for p in survivors) or survivors == []
    # `reason` mentions both numbers.
    assert "0.40" in result.reason or "0.4000" in result.reason


@pytest.mark.asyncio
async def test_missing_base_model_path_returns_clean_result(tmp_path: Path):
    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    cfg = _config(tmp_path, **{})
    # Override base_model_path via dataclasses.replace
    from dataclasses import replace

    cfg = replace(cfg, base_model_path=None)
    trainer = UnslothDPOTrainer(capability_eval=NoopCapabilityEval(), backend=FakeBackend())
    result = await trainer.train(_pairs(), cfg)
    assert result.accepted is False
    assert "base_model_path" in result.reason


@pytest.mark.asyncio
async def test_empty_pairs_returns_clean_result(tmp_path: Path):
    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    trainer = UnslothDPOTrainer(capability_eval=NoopCapabilityEval(), backend=FakeBackend())
    result = await trainer.train([], _config(tmp_path))
    assert result.accepted is False
    assert "no DPO pairs" in result.reason


@pytest.mark.asyncio
async def test_load_failure_cleans_up_and_reports(tmp_path: Path):
    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    backend = FakeBackend(load_raises=RuntimeError("oom"))
    trainer = UnslothDPOTrainer(capability_eval=NoopCapabilityEval(), backend=backend)
    result = await trainer.train(_pairs(), _config(tmp_path))
    assert result.accepted is False
    assert "model load failed" in result.reason
    assert "oom" in result.reason


@pytest.mark.asyncio
async def test_dpo_failure_removes_tmp_dir(tmp_path: Path):
    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    backend = FakeBackend(dpo_raises=RuntimeError("nan in loss"))
    trainer = UnslothDPOTrainer(capability_eval=NoopCapabilityEval(), backend=backend)
    result = await trainer.train(_pairs(), _config(tmp_path))
    assert result.accepted is False
    # No leftover .tmp dirs.
    adapter_dir = tmp_path / "adapters"
    if adapter_dir.exists():
        for p in adapter_dir.iterdir():
            assert not p.name.endswith(".tmp"), f"leftover tmp: {p}"


@pytest.mark.asyncio
async def test_retention_evicts_oldest(tmp_path: Path):
    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    cfg = _config(tmp_path, retention=2)
    trainer = UnslothDPOTrainer(
        capability_eval=NoopCapabilityEval(),
        abliteration_scorer=NoopAbliterationScorer(),
        backend=FakeBackend(),
    )
    # Pre-populate three accepted adapters older than the new one.
    out = tmp_path / "adapters"
    out.mkdir(parents=True)
    import time as _time

    for stamp in ("20260530T120000", "20260530T121500", "20260530T123000"):
        (out / stamp).mkdir()
        _time.sleep(0.01)

    result = await trainer.train(_pairs(), cfg)
    assert result.accepted is True
    # With retention=2 and 4 dirs (3 pre + 1 new), 2 oldest evicted.
    remaining = sorted(p.name for p in out.iterdir() if p.is_dir() and p.name != "current")
    assert len(remaining) == 2  # retention cap honored
    # Newest (the one just promoted) is among them.
    assert result.adapter_path.name in remaining


@pytest.mark.asyncio
async def test_hot_swap_runs_for_manual_default(tmp_path: Path):
    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    trainer = UnslothDPOTrainer(
        capability_eval=NoopCapabilityEval(),
        abliteration_scorer=NoopAbliterationScorer(),
        backend=FakeBackend(),
    )
    result = await trainer.train(_pairs(), _config(tmp_path))
    assert result.accepted is True
    marker = result.adapter_path.parent / "PENDING_OPERATOR_RELOAD"
    assert marker.exists()
    assert str(result.adapter_path) in marker.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_missing_extras_returns_remediation(tmp_path: Path, monkeypatch):
    # Force unsloth import to fail at the check.
    monkeypatch.setitem(sys.modules, "unsloth", None)
    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    trainer = UnslothDPOTrainer(capability_eval=NoopCapabilityEval(), backend=FakeBackend())
    result = await trainer.train(_pairs(), _config(tmp_path))
    assert result.accepted is False
    assert "[training]" in result.reason


@pytest.mark.asyncio
async def test_backend_load_receives_config_values(tmp_path: Path):
    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    backend = FakeBackend()
    trainer = UnslothDPOTrainer(capability_eval=NoopCapabilityEval(), backend=backend)
    cfg = _config(tmp_path, lora_rank=16, training_device="cpu")
    await trainer.train(_pairs(), cfg)
    load_calls = [c for c in backend.calls if c[0] == "load_model"]
    assert len(load_calls) == 1
    args = load_calls[0][1]
    assert args["lora_rank"] == 16
    assert args["training_device"] == "cpu"
    assert args["base_model_path"] == str(tmp_path / "fake-base-model")


@pytest.mark.asyncio
async def test_run_dpo_receives_config_args(tmp_path: Path):
    from kaine.modules.hypnos.unsloth_trainer import UnslothDPOTrainer

    backend = FakeBackend()
    trainer = UnslothDPOTrainer(capability_eval=NoopCapabilityEval(), backend=backend)
    cfg = _config(tmp_path, learning_rate=1e-4, dpo_beta=0.2, max_samples=2)
    await trainer.train(_pairs(n=5), cfg)
    run_calls = [c for c in backend.calls if c[0] == "run_dpo"]
    assert len(run_calls) == 1
    args = run_calls[0][1]
    assert args["lr"] == pytest.approx(1e-4)
    assert args["beta"] == pytest.approx(0.2)
    assert args["max_samples"] == 2
