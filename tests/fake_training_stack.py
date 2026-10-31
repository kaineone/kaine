# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Injectable fake training stack for in-process voice-alignment tests.

The ``fake_training_stack`` fixture installs stub ``transformers`` / ``peft`` /
``bitsandbytes`` modules so ``scripts/sleep_external_train.py`` can run end to
end without a real model or GPU. The returned control object lets tests script
generation responses (capability/abliteration) and model behaviour.
"""
from __future__ import annotations

import json
import sys
import time
import types
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Optional

import pytest
import torch

from kaine.modules.sleep.subprocess_trainer import SubprocessVoiceTrainer
from kaine.modules.sleep.voice_alignment import DPOPair, VoiceAlignmentConfig


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


class FakeModel(torch.nn.Module):
    device = "cpu"

    def __init__(self) -> None:
        super().__init__()
        torch.manual_seed(0)
        self.embedding = torch.nn.Embedding(64, 8)
        self.linear = torch.nn.Linear(8, 64, bias=False)
        with torch.no_grad():
            self.linear.weight.zero_()

    def forward(self, input_ids: Any, logits_to_keep: Optional[int] = None, **kwargs: Any) -> SimpleNamespace:
        if _control is not None:
            if _control.train_raises is not None:
                raise _control.train_raises
            if _control.train_sleep and not getattr(_control, "train_sleep_done", False):
                _control.train_sleep_done = True
                time.sleep(_control.train_sleep)
        logits = self.linear(self.embedding(input_ids))
        if logits_to_keep is not None:
            logits = logits[:, -logits_to_keep:, :]
        return SimpleNamespace(logits=logits)

    def generate(self, **inputs: Any) -> list[list[int]]:
        return [[0]]

    def save_pretrained(self, path: str, selected_adapters: Optional[list[str]] = None) -> None:
        _control.save_paths.append(path)
        target = Path(path)
        if selected_adapters:
            target = target / selected_adapters[0]
        target.mkdir(parents=True, exist_ok=True)
        (target / "adapter_config.json").write_text("{}", encoding="utf-8")
        (target / "adapter_model.safetensors").write_text("fake", encoding="utf-8")
        if _control.save_raises is not None:
            raise _control.save_raises

    def load_adapter(self, *args: Any, **kwargs: Any) -> Any:
        _control.load_adapter_calls.append({"args": args, "kwargs": kwargs})
        return SimpleNamespace(
            missing_keys=[], unexpected_keys=list(_control.load_adapter_unexpected_keys)
        )

    def set_adapter(self, *args: Any, **kwargs: Any) -> None:
        _control.set_adapter_calls.append({"args": args, "kwargs": kwargs})

    def gradient_checkpointing_enable(self, gradient_checkpointing_kwargs=None) -> None:
        _control.gradient_checkpointing_enable_calls.append(
            gradient_checkpointing_kwargs if gradient_checkpointing_kwargs is not None else {}
        )

    def enable_input_require_grads(self) -> None:
        _control.enable_input_require_grads_calls.append(True)

    def disable_adapter(self) -> Any:
        class _Context:
            def __enter__(self) -> None:
                _control.disable_adapter_calls.append(True)

            def __exit__(self, *exc: Any) -> bool:
                return False

        return _Context()


class FakeTokenizer:
    def __init__(self) -> None:
        self.last_prompt = ""

    def __call__(self, text: str, return_tensors: Optional[str] = None, **kwargs: Any) -> Any:
        self.last_prompt = text
        if return_tensors == "pt":
            return {"input_ids": FakeTensor()}
        ids = [2 + (ord(c) % 60) for c in text]
        # A real tokenizer called on one string returns a flat list of ids.
        return {"input_ids": ids}

    def apply_chat_template(
        self, messages: Any, tokenize: bool = False, add_generation_prompt: bool = False
    ) -> str:
        _control.chat_template_calls.append(messages)
        text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
        if add_generation_prompt:
            text += "\nassistant: "
        return text

    def decode(self, ids: Any, skip_special_tokens: bool = True) -> str:
        return _control.reply_for(self.last_prompt)

    def save_pretrained(self, path: str) -> None:
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        (target / "tokenizer_config.json").write_text("{}", encoding="utf-8")

    eos_token_id = 1


class _Control:
    def __init__(self) -> None:
        self.train_raises: Optional[BaseException] = None
        self.from_pretrained_raises: Optional[BaseException] = None
        self.train_sleep = 0.0
        self.train_sleep_done = False
        self.deflect = False
        self.capability_after_wrong = False

        self.from_pretrained_calls: list[dict[str, Any]] = []
        self.tokenizer_from_pretrained_calls: list[dict[str, Any]] = []
        self.bnb_config_calls: list[dict[str, Any]] = []
        self.get_peft_model_calls: list[dict[str, Any]] = []
        self.peft_from_pretrained_calls: list[dict[str, Any]] = []
        self.load_adapter_calls: list[dict[str, Any]] = []
        self.load_adapter_unexpected_keys: list[str] = []
        self.set_adapter_calls: list[dict[str, Any]] = []
        self.gradient_checkpointing_enable_calls: list[dict[str, Any]] = []
        self.enable_input_require_grads_calls: list[bool] = []
        self.save_raises: Optional[BaseException] = None
        self.save_paths: list[str] = []
        self.events: list[str] = []
        self.disable_adapter_calls: list[Any] = []
        self.chat_template_calls: list[Any] = []

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

    def _from_pretrained(path: str, **kwargs: Any) -> FakeModel:
        if control.from_pretrained_raises is not None:
            raise control.from_pretrained_raises
        control.from_pretrained_calls.append({"path": path, "kwargs": dict(kwargs)})
        return FakeModel()

    def _tokenizer_from_pretrained(path: str, **kwargs: Any) -> FakeTokenizer:
        control.tokenizer_from_pretrained_calls.append({"path": path, "kwargs": dict(kwargs)})
        return FakeTokenizer()

    def _bitsandbytes_config(**kwargs: Any) -> SimpleNamespace:
        obj = SimpleNamespace(**kwargs)
        control.bnb_config_calls.append(dict(kwargs))
        return obj

    transformers_mod = _install_module(
        "transformers",
        {
            "AutoModelForCausalLM": SimpleNamespace(from_pretrained=_from_pretrained),
            "AutoTokenizer": SimpleNamespace(from_pretrained=_tokenizer_from_pretrained),
            "BitsAndBytesConfig": _bitsandbytes_config,
        },
    )

    class _LoraConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.__dict__.update(kwargs)

    def _get_peft_model(model: FakeModel, config: Any) -> FakeModel:
        control.get_peft_model_calls.append({"r": config.r, "config": config})
        control.events.append("get_peft_model")
        return model


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

    peft_mod = _install_module(
        "peft",
        {
            "LoraConfig": _LoraConfig,
            "PeftModel": _PeftModel,
            "get_peft_model": _get_peft_model,
        },
    )

    bitsandbytes_mod = _install_module("bitsandbytes", {})

    for name, mod in (
        ("transformers", transformers_mod),
        ("peft", peft_mod),
        ("bitsandbytes", bitsandbytes_mod),
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
