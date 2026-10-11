# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Injectable fake training stack for in-process voice-alignment tests.

The ``fake_training_stack`` fixture installs stub ``unsloth`` / ``trl`` /
``peft`` / ``datasets`` modules so ``scripts/hypnos_external_train.py`` can
run end to end without a real model or GPU. The returned control object lets
tests script generation responses (capability/abliteration) and DPOTrainer
behaviour.
"""
from __future__ import annotations

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest

from kaine.modules.hypnos.subprocess_trainer import SubprocessVoiceTrainer
from kaine.modules.hypnos.voice_alignment import DPOPair, VoiceAlignmentConfig


def accepted_result(adapter_dir: Path, **overrides) -> dict:
    """Return a schema-v2 accepted trainer result."""
    result = {
        "ok": True,
        "accepted": True,
        "reason": "accepted",
        "schema_version": 2,
        "abliteration_passed": True,
        "abliteration_probes_scored": 1,
        "abliteration_matched_pattern": None,
        "capability_loss": 0.0,
        "adapter_dir": str(adapter_dir),
        "samples_used": 1,
        "dpo_loss": 0.69,
        "peak_vram_gib": None,
        "train_precision": "bf16",
    }
    result.update(overrides)
    return result


def rejected_result(reason: str, **overrides) -> dict:
    """Return a schema-v2 clean rejection result."""
    result = {
        "ok": True,
        "accepted": False,
        "reason": reason,
        "schema_version": 2,
        "capability_loss": None,
        "adapter_dir": None,
    }
    result.update(overrides)
    return result


#: The current control object installed by the fixture. Fake callables close
#: over this name, so mutating the fixture's control object is visible to the
#: already-imported trainer script.
_control: Optional[Any] = None


class FakeTensor:
    def to(self, device: str) -> "FakeTensor":
        return self


class FakeModel:
    device = "cpu"

    def generate(self, **inputs: Any) -> list[list[int]]:
        return [[0]]

    def save_pretrained(self, path: str, selected_adapters: Optional[list[str]] = None) -> None:
        target = Path(path)
        if selected_adapters:
            # PEFT writes a named (non-default) adapter into a subdirectory.
            target = target / selected_adapters[0]
        target.mkdir(parents=True, exist_ok=True)
        (target / "adapter_config.json").write_text("{}", encoding="utf-8")
        (target / "adapter_model.safetensors").write_text("fake", encoding="utf-8")

    def load_adapter(self, *args: Any, **kwargs: Any) -> None:
        _control.load_adapter_calls.append({"args": args, "kwargs": kwargs})

    def set_adapter(self, *args: Any, **kwargs: Any) -> None:
        _control.set_adapter_calls.append({"args": args, "kwargs": kwargs})

    def gradient_checkpointing_enable(self) -> None:
        _control.gradient_checkpointing_enable_calls.append(True)


class FakeTokenizer:
    def __init__(self) -> None:
        self.last_prompt = ""

    def __call__(self, prompt: str, return_tensors: str = "pt") -> dict[str, FakeTensor]:
        self.last_prompt = prompt
        return {"input_ids": FakeTensor()}

    def decode(self, ids: Any, skip_special_tokens: bool = True) -> str:
        return _control.reply_for(self.last_prompt)

    def save_pretrained(self, path: str) -> None:
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        (target / "tokenizer_config.json").write_text("{}", encoding="utf-8")


class _Control:
    def __init__(self) -> None:
        self.dpo_loss = 0.123
        self.train_raises: Optional[BaseException] = None
        self.from_pretrained_raises: Optional[BaseException] = None
        self.train_sleep = 0.0
        self.deflect = False
        self.capability_after_wrong = False

        self.from_pretrained_calls: list[dict[str, Any]] = []
        self.get_peft_model_calls: list[dict[str, Any]] = []
        self.dpo_config_calls: list[dict[str, Any]] = []
        self.dpo_trainer_calls: list[dict[str, Any]] = []
        self.peft_from_pretrained_calls: list[dict[str, Any]] = []
        self.load_adapter_calls: list[dict[str, Any]] = []
        self.set_adapter_calls: list[dict[str, Any]] = []
        self.gradient_checkpointing_enable_calls: list[bool] = []
        self.dataset_rows: list[dict[str, Any]] = []

        self.capability_probes: list[dict[str, Any]] = []
        self.abliteration_probes: list[dict[str, Any]] = []
        self._prompt_counts: dict[str, int] = {}

    def set_probes(
        self,
        capability: list[dict[str, Any]],
        abliteration: list[dict[str, Any]],
    ) -> None:
        self.capability_probes = list(capability)
        self.abliteration_probes = list(abliteration)
        self._prompt_counts = {}

    def reply_for(self, prompt: str) -> str:
        for probe in self.capability_probes:
            if probe["prompt"] in prompt:
                count = self._prompt_counts.get(prompt, 0)
                self._prompt_counts[prompt] = count + 1
                if self.capability_after_wrong and count >= 1:
                    return f"{prompt} wrong"
                return f"{prompt}{probe['expected']}"
        for probe in self.abliteration_probes:
            if probe["prompt"] in prompt:
                if self.deflect:
                    return f"{prompt}{probe['deflection_patterns'][0]}"
                return f"{prompt}Sure, here is the answer."
        return f"{prompt}ok"


def _install_module(name: str, attrs: dict[str, Any]) -> types.ModuleType:
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


@pytest.fixture
def fake_training_stack(monkeypatch):
    """Install the fake training stack and return the control object."""
    global _control
    control = _Control()
    _control = control

    def _from_pretrained(path: str, *, device_map: Any = None, **kwargs: Any) -> tuple[FakeModel, FakeTokenizer]:
        if control.from_pretrained_raises is not None:
            raise control.from_pretrained_raises
        control.from_pretrained_calls.append({"path": path, "kwargs": dict(kwargs, device_map=device_map)})
        return FakeModel(), FakeTokenizer()

    def _get_peft_model(model: FakeModel, *, r: int, use_gradient_checkpointing: Any = None) -> FakeModel:
        control.get_peft_model_calls.append({"r": r, "use_gradient_checkpointing": use_gradient_checkpointing})
        return model

    unsloth_mod = _install_module(
        "unsloth",
        {
            "FastLanguageModel": SimpleNamespace(
                from_pretrained=_from_pretrained,
                get_peft_model=_get_peft_model,
            ),
        },
    )

    class _DPOConfig:
        def __init__(self, **kwargs: Any) -> None:
            control.dpo_config_calls.append(kwargs)
            self.__dict__.update(kwargs)

    class _DPOTrainer:
        def __init__(self, **kwargs: Any) -> None:
            control.dpo_trainer_calls.append(kwargs)
            self.args = kwargs.get("args")
            self.state: Optional[SimpleNamespace] = None

        def train(self) -> SimpleNamespace:
            # Like the real trainer, training writes into args.output_dir (the
            # script's tmp adapter dir) before it can fail.
            out = getattr(self.args, "output_dir", None)
            if out:
                Path(out).mkdir(parents=True, exist_ok=True)
            if control.train_sleep:
                import time

                time.sleep(control.train_sleep)
            if control.train_raises is not None:
                raise control.train_raises
            self.state = SimpleNamespace(global_step=3)
            return SimpleNamespace(training_loss=control.dpo_loss)

    trl_mod = _install_module(
        "trl",
        {
            "DPOConfig": _DPOConfig,
            "DPOTrainer": _DPOTrainer,
        },
    )

    class _PeftModel:
        @staticmethod
        def from_pretrained(
            model: FakeModel,
            path: str,
            *,
            adapter_name: Optional[str] = None,
            is_trainable: Optional[bool] = None,
            **kwargs: Any,
        ) -> FakeModel:
            control.peft_from_pretrained_calls.append(
                {
                    "path": path,
                    "adapter_name": adapter_name,
                    "is_trainable": is_trainable,
                    **kwargs,
                }
            )
            return model

    peft_mod = _install_module("peft", {"PeftModel": _PeftModel})

    def _dataset_from_list(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        control.dataset_rows.extend(rows)
        return rows

    datasets_mod = _install_module(
        "datasets",
        {"Dataset": SimpleNamespace(from_list=_dataset_from_list)},
    )

    for name, mod in (
        ("unsloth", unsloth_mod),
        ("trl", trl_mod),
        ("peft", peft_mod),
        ("datasets", datasets_mod),
    ):
        monkeypatch.setitem(sys.modules, name, mod)

    yield control


async def run_inprocess(
    tmp_path: Path,
    *,
    pairs: list[DPOPair],
    config_overrides: dict[str, Any],
) -> Any:
    """Run the in-process trainer script with the fake stack."""
    if _control is None:
        raise RuntimeError("run_inprocess requires the fake_training_stack fixture")

    adapter_output_dir = tmp_path / "store" / "adapters"
    adapter_output_dir.mkdir(parents=True, exist_ok=True)
    base_model_path = tmp_path / "base_model"
    base_model_path.mkdir(parents=True, exist_ok=True)

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
        "".join(json.dumps(r) + "\n" for r in capability_probes),
        encoding="utf-8",
    )
    abl_path.write_text(
        "".join(json.dumps(r) + "\n" for r in abliteration_probes),
        encoding="utf-8",
    )
    _control.set_probes(capability_probes, abliteration_probes)

    defaults: dict[str, Any] = {
        "intent_log_path": str(tmp_path / "intent.jsonl"),
        "adapter_output_dir": str(adapter_output_dir),
        "enabled": True,
        "base_model_path": str(base_model_path),
        "capability_probe_path": str(cap_path),
        "abliteration_probe_path": str(abl_path),
        "capability_loss_threshold": 0.05,
        "train_precision": "bf16",
        "lora_rank": 8,
        "adapter_retention": 0,
    }
    defaults.update(config_overrides)
    config = VoiceAlignmentConfig(**defaults)

    trainer = SubprocessVoiceTrainer(
        trainer_python=None,
        trainer_workdir=tmp_path / "jobs",
        run_in_process=True,
    )
    return await trainer.train(pairs, config)
