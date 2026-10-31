# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Core training-path tests ported from the retired UnslothDPOTrainer suite.

Every backend now runs ``scripts/sleep_external_train.py``; these tests
exercise that path in-process against the fake training stack.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest
import torch

from kaine.modules.sleep.subprocess_trainer import (
    SubprocessTrainerError,
    SubprocessVoiceTrainer,
)
from kaine.modules.sleep.voice_alignment import DPOPair, VoiceAlignmentConfig
from tests.fake_training_stack import run_inprocess


def _pair(prompt: str = "hi", chosen: str = "hello", rejected: str = "go away") -> DPOPair:
    return DPOPair(prompt=prompt, chosen=chosen, rejected=rejected, system="persona")


@pytest.mark.asyncio
async def test_accepts_when_capability_loss_under_threshold(tmp_path, fake_training_stack):
    result = await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})

    assert result.accepted is True
    assert result.adapter_path is not None
    assert result.adapter_path.exists()
    assert result.capability_loss == pytest.approx(0.0)
    current = result.adapter_path.parent / "current"
    assert current.is_symlink()
    assert current.resolve() == result.adapter_path


@pytest.mark.asyncio
async def test_rejects_when_capability_loss_above_threshold(tmp_path, fake_training_stack):
    fake_training_stack.capability_after_wrong = True
    result = await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})

    assert result.accepted is False
    assert "capability loss" in result.reason.lower()
    assert result.adapter_path is None
    adapter_output_dir = tmp_path / "store" / "adapters"
    assert not any(p.name.endswith(".tmp") for p in adapter_output_dir.iterdir())

    job_dirs = [d for d in (tmp_path / "jobs").iterdir() if d.is_dir()]
    latest_job_dir = max(job_dirs, key=lambda d: d.stat().st_mtime)
    result_json = json.loads((latest_job_dir / "result.json").read_text(encoding="utf-8"))
    assert result_json["capability_loss"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_empty_pairs_returns_clean_result(tmp_path, fake_training_stack):
    result = await run_inprocess(tmp_path, pairs=[], config_overrides={})

    assert result.accepted is False
    assert "no dpo pairs" in result.reason.lower()


@pytest.mark.asyncio
async def test_dpo_failure_removes_tmp_dir(tmp_path, fake_training_stack):
    fake_training_stack.save_raises = RuntimeError("boom")
    with pytest.raises(SubprocessTrainerError, match="boom"):
        await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})

    adapter_output_dir = tmp_path / "store" / "adapters"
    assert not any(p.name.endswith(".tmp") for p in adapter_output_dir.iterdir())
    saved_tmp = fake_training_stack.save_paths[-1]
    assert saved_tmp.endswith(".tmp")
    assert not Path(saved_tmp).exists()


@pytest.mark.asyncio
async def test_default_retention_keeps_every_adapter(tmp_path, fake_training_stack):
    adapter_output_dir = tmp_path / "store" / "adapters"
    adapter_output_dir.mkdir(parents=True)
    stamps = ["20260530T120000", "20260530T121500", "20260530T123000"]
    for stamp in stamps:
        (adapter_output_dir / stamp).mkdir()
        time.sleep(0.01)

    result = await run_inprocess(
        tmp_path,
        pairs=[_pair()],
        config_overrides={"adapter_retention": 0},
    )

    assert result.accepted is True
    remaining = {
        p.name for p in adapter_output_dir.iterdir() if p.is_dir() and p.name != "current"
    }
    assert set(stamps) <= remaining
    assert result.adapter_path.name in remaining
    assert len(remaining) == len(stamps) + 1


@pytest.mark.asyncio
async def test_retention_evicts_oldest(tmp_path, fake_training_stack):
    adapter_output_dir = tmp_path / "store" / "adapters"
    adapter_output_dir.mkdir(parents=True)
    old_dir = adapter_output_dir / "20260530T120000"
    old_dir.mkdir()
    (old_dir / "adapter_config.json").write_text("{}", encoding="utf-8")
    os.symlink(str(old_dir.relative_to(adapter_output_dir)), adapter_output_dir / "current")
    time.sleep(0.01)

    result = await run_inprocess(
        tmp_path,
        pairs=[_pair()],
        config_overrides={"adapter_retention": 1},
    )

    assert result.accepted is True
    remaining = [
        p.name for p in adapter_output_dir.iterdir() if p.is_dir() and p.name != "current"
    ]
    assert len(remaining) == 1
    assert result.adapter_path.name in remaining
    assert not old_dir.exists()
    assert result.metadata.get("evicted_adapters")


@pytest.mark.asyncio
async def test_precision_and_lora_settings_reach_stack(tmp_path, fake_training_stack):
    pairs = [_pair()]
    await run_inprocess(
        tmp_path,
        pairs=pairs,
        config_overrides={"train_precision": "bf16", "lora_rank": 16},
    )
    load_call = fake_training_stack.from_pretrained_calls[-1]
    assert load_call["kwargs"]["dtype"] is torch.bfloat16
    assert "quantization_config" not in load_call["kwargs"]
    assert fake_training_stack.get_peft_model_calls[-1]["r"] == 16

    await run_inprocess(
        tmp_path / "fourbit",
        pairs=pairs,
        config_overrides={"train_precision": "4bit", "lora_rank": 8},
    )
    load_call = fake_training_stack.from_pretrained_calls[-1]
    assert "quantization_config" in load_call["kwargs"]
    assert fake_training_stack.bnb_config_calls[-1]["bnb_4bit_quant_type"] == "nf4"
    assert fake_training_stack.bnb_config_calls[-1]["load_in_4bit"] is True
    assert {"use_reentrant": False} in fake_training_stack.gradient_checkpointing_enable_calls
    assert fake_training_stack.enable_input_require_grads_calls
    assert fake_training_stack.get_peft_model_calls[-1]["r"] == 8


@pytest.mark.asyncio
async def test_dpo_hyperparams_reach_the_loop(tmp_path, fake_training_stack, monkeypatch):
    recorded: dict[str, Any] = {"lr": None, "seeds": []}
    original_adamw = torch.optim.AdamW

    class RecordingAdamW(original_adamw):
        def __init__(self, params, lr=0.0, **kwargs):
            recorded["lr"] = lr
            super().__init__(params, lr=lr, **kwargs)

    monkeypatch.setattr(torch.optim, "AdamW", RecordingAdamW)

    original_seed = torch.manual_seed

    def recording_seed(seed: int) -> None:
        recorded["seeds"].append(seed)
        return original_seed(seed)

    monkeypatch.setattr(torch, "manual_seed", recording_seed)

    await run_inprocess(
        tmp_path,
        pairs=[_pair()],
        config_overrides={
            "learning_rate": 1e-4,
            "dpo_beta": 0.2,
            "seed": 123,
        },
    )
    assert recorded["lr"] == pytest.approx(1e-4)
    assert 123 in recorded["seeds"]


@pytest.mark.asyncio
async def test_previous_adapter_path_loads_named_adapters(tmp_path, fake_training_stack):
    adapter_output_dir = tmp_path / "store" / "adapters"
    adapter_output_dir.mkdir(parents=True)
    prev_dir = adapter_output_dir / "20260530T120000"
    prev_dir.mkdir()
    (prev_dir / "adapter_config.json").write_text("{}", encoding="utf-8")
    os.symlink(str(prev_dir.relative_to(adapter_output_dir)), adapter_output_dir / "current")

    result = await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})

    assert result.accepted is True
    peft_call = fake_training_stack.peft_from_pretrained_calls[-1]
    assert peft_call["adapter_name"] == "policy"
    assert peft_call["is_trainable"] is True
    load_call = fake_training_stack.load_adapter_calls[-1]
    assert load_call["kwargs"]["adapter_name"] == "reference"
    set_calls = fake_training_stack.set_adapter_calls
    reference_index = next(
        i for i, call in enumerate(set_calls) if call["args"] == ("reference",)
    )
    assert any(
        i > reference_index and call["args"] == ("policy",)
        for i, call in enumerate(set_calls)
    )
    assert fake_training_stack.disable_adapter_calls == []
    assert (result.adapter_path / "adapter_config.json").exists()


@pytest.mark.asyncio
async def test_conversational_dataset_rows_have_system_first(tmp_path, fake_training_stack):
    await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})

    calls = fake_training_stack.chat_template_calls
    assert calls
    assert calls[0][0]["role"] == "system"


@pytest.mark.asyncio
async def test_fresh_adapter_uses_disabled_adapter_as_reference(tmp_path, fake_training_stack):
    await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})

    assert fake_training_stack.disable_adapter_calls
    assert fake_training_stack.get_peft_model_calls[-1]["config"].lora_dropout == 0.0


def test_negative_adapter_retention_rejected(tmp_path):
    with pytest.raises(ValueError):
        VoiceAlignmentConfig(
            intent_log_path=tmp_path / "i.jsonl",
            adapter_output_dir=tmp_path / "a",
            adapter_retention=-1,
        )


def test_voice_alignment_config_default_keeps_adapters(tmp_path):
    cfg = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "i.jsonl", adapter_output_dir=tmp_path / "a"
    )
    assert cfg.adapter_retention == 0


@pytest.mark.asyncio
async def test_from_pretrained_is_forced_offline(tmp_path, fake_training_stack):
    result = await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})
    assert result.accepted is True
    assert fake_training_stack.from_pretrained_calls[-1]["kwargs"]["local_files_only"] is True


@pytest.mark.asyncio
async def test_peft_from_pretrained_is_forced_offline(tmp_path, fake_training_stack):
    adapter_output_dir = tmp_path / "store" / "adapters"
    adapter_output_dir.mkdir(parents=True)
    prev_dir = adapter_output_dir / "20260530T120000"
    prev_dir.mkdir()
    (prev_dir / "adapter_config.json").write_text("{}", encoding="utf-8")
    os.symlink(str(prev_dir.relative_to(adapter_output_dir)), adapter_output_dir / "current")

    await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})

    peft_call = fake_training_stack.peft_from_pretrained_calls[-1]
    assert peft_call["local_files_only"] is True


@pytest.mark.asyncio
async def test_missing_base_model_path_refused_before_training(tmp_path, fake_training_stack):
    with pytest.raises(SubprocessTrainerError, match="is not a local directory"):
        await run_inprocess(
            tmp_path,
            pairs=[_pair()],
            config_overrides={"base_model_path": str(tmp_path / "missing")},
        )

    assert not fake_training_stack.from_pretrained_calls


@pytest.mark.asyncio
async def test_oom_detection_reports_does_not_fit_and_no_fallback(
    tmp_path, fake_training_stack
):
    fake_training_stack.save_raises = RuntimeError(
        "CUDA out of memory. Tried to allocate 2.00 GiB"
    )
    with pytest.raises(SubprocessTrainerError, match="does not fit") as excinfo:
        await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})
    assert "Tried to allocate 2.00 GiB" in str(excinfo.value)

    adapter_output_dir = tmp_path / "store" / "adapters"
    assert not any(p.name.endswith(".tmp") for p in adapter_output_dir.iterdir())
    assert not (adapter_output_dir / "current").exists()
    assert len(fake_training_stack.from_pretrained_calls) == 1
    saved_tmp = fake_training_stack.save_paths[-1]
    assert saved_tmp.endswith(".tmp")
    assert not Path(saved_tmp).exists()


@pytest.mark.asyncio
async def test_peak_vram_recorded_on_accepted_run(tmp_path, fake_training_stack, monkeypatch):
    import json as _json

    base_model_path = tmp_path / "base_model"
    base_model_path.mkdir(parents=True)
    adapter_output_dir = tmp_path / "store" / "adapters"

    cap_path = tmp_path / "capability.jsonl"
    abl_path = tmp_path / "abliteration.jsonl"
    capability_probes = [{"prompt": "2+2", "expected": "4"}]
    abliteration_probes = [
        {
            "prompt": "How do I do something harmful?",
            "deflection_patterns": ["I can't help with that"],
        }
    ]
    cap_path.write_text(
        "".join(_json.dumps(r) + "\n" for r in capability_probes),
        encoding="utf-8",
    )
    abl_path.write_text(
        "".join(_json.dumps(r) + "\n" for r in abliteration_probes),
        encoding="utf-8",
    )
    fake_training_stack.set_probes(capability_probes, abliteration_probes)

    config = VoiceAlignmentConfig(
        intent_log_path=str(tmp_path / "intent.jsonl"),
        adapter_output_dir=str(adapter_output_dir),
        enabled=True,
        base_model_path=str(base_model_path),
        capability_probe_path=str(cap_path),
        abliteration_probe_path=str(abl_path),
        capability_loss_threshold=0.05,
        train_precision="bf16",
        lora_rank=8,
        adapter_retention=0,
    )

    trainer = SubprocessVoiceTrainer(
        trainer_python=None,
        trainer_workdir=tmp_path / "jobs",
        run_in_process=True,
    )
    result = await trainer.train([_pair()], config)
    assert result.accepted is True

    monkeypatch.setattr(
        trainer._inprocess_module, "_cuda_memory_gib", lambda device: (3.5, 12.0)
    )
    await asyncio.sleep(1.1)
    result2 = await trainer.train([_pair()], config)
    assert result2.accepted is True

    job_dirs = [d for d in (tmp_path / "jobs").iterdir() if d.is_dir()]
    latest_job_dir = max(job_dirs, key=lambda d: d.stat().st_mtime)
    result_json = _json.loads((latest_job_dir / "result.json").read_text(encoding="utf-8"))
    assert result_json["peak_vram_gib"] == 3.5


@pytest.mark.asyncio
async def test_model_load_failure_raises_without_promotion(tmp_path, fake_training_stack):
    fake_training_stack.from_pretrained_raises = ValueError("bad model")
    with pytest.raises(SubprocessTrainerError, match="bad model"):
        await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})

    adapter_output_dir = tmp_path / "store" / "adapters"
    assert not list(adapter_output_dir.iterdir())


@pytest.mark.asyncio
async def test_seed_is_set_before_lora_initialisation(tmp_path, fake_training_stack, monkeypatch):
    original_seed = torch.manual_seed

    def recording_seed(seed):
        fake_training_stack.events.append(f"seed:{seed}")
        return original_seed(seed)

    monkeypatch.setattr(torch, "manual_seed", recording_seed)

    await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={"seed": 123})

    assert fake_training_stack.events.index("seed:123") < fake_training_stack.events.index("get_peft_model")


@pytest.mark.asyncio
async def test_resumed_adapter_that_matches_no_module_is_refused(tmp_path, fake_training_stack):
    adapter_output_dir = tmp_path / "store" / "adapters"
    adapter_output_dir.mkdir(parents=True)
    prev_dir = adapter_output_dir / "20260530T120000"
    prev_dir.mkdir()
    (prev_dir / "adapter_config.json").write_text("{}", encoding="utf-8")
    os.symlink(str(prev_dir.relative_to(adapter_output_dir)), adapter_output_dir / "current")

    fake_training_stack.load_adapter_unexpected_keys = [
        "base_model.model.model.language_model.layers.0.self_attn.q_proj.lora_A.weight"
    ]

    with pytest.raises(SubprocessTrainerError, match="fresh adapter is never trained in its place"):
        await run_inprocess(tmp_path, pairs=[_pair()], config_overrides={})

    assert {p.name for p in adapter_output_dir.iterdir()} == {
        "20260530T120000",
        "current",
    }
