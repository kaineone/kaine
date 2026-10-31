# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The abliteration baseline really is the bare base model (real PEFT, CPU).

The trainer scores the base for the relative abliteration veto inside
``model.disable_adapter()``, with the entity's previous adapter loaded twice
(``policy``, trainable, and ``reference``). The fake training stack only
records that the context was entered; this test pins the library semantics
the veto depends on, on a tiny randomly initialised Qwen2 built here (no
download): under ``disable_adapter()`` the logits and greedy generation equal
the raw base exactly, whichever adapter is active, and ``requires_grad`` is
the same after the block as before it.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

torch = pytest.importorskip("torch")
transformers = pytest.importorskip("transformers")
peft = pytest.importorskip("peft")

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "sleep_external_train.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("sleep_external_train_peft_test", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


script = _load_script()

_IDS = [[1, 5, 9, 2, 7, 3]]


def _tiny_base(tmp_path: Path) -> Path:
    config = transformers.Qwen2Config(
        vocab_size=64,
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=2,
        num_attention_heads=4,
        num_key_value_heads=2,
        max_position_embeddings=64,
        tie_word_embeddings=False,
    )
    torch.manual_seed(0)
    path = tmp_path / "base"
    transformers.Qwen2ForCausalLM(config).save_pretrained(str(path))
    return path


def _load_base(path: Path):
    model = transformers.AutoModelForCausalLM.from_pretrained(
        str(path), local_files_only=True, dtype=torch.float32
    )
    model.eval()
    return model


def _lora_config():
    return peft.LoraConfig(
        r=4, lora_alpha=4, lora_dropout=0.0, target_modules="all-linear", task_type="CAUSAL_LM"
    )


def _perturb_lora_b(model, seed: int) -> None:
    """Fresh LoRA has B = 0 (a no-op); give it weight so it changes the output."""
    generator = torch.Generator().manual_seed(seed)
    with torch.no_grad():
        for name, param in model.named_parameters():
            if "lora_B" in name:
                param.copy_(torch.randn(param.shape, generator=generator) * 0.5)


def _saved_adapter(base_path: Path, out: Path, seed: int) -> Path:
    model = peft.get_peft_model(_load_base(base_path), _lora_config())
    _perturb_lora_b(model, seed)
    model.save_pretrained(str(out))
    return out


def _logits(model):
    with torch.no_grad():
        return model(torch.tensor(_IDS)).logits


def _greedy(model):
    with torch.no_grad():
        return model.generate(
            torch.tensor(_IDS), max_new_tokens=6, do_sample=False, pad_token_id=0
        )


def _grad_flags(model) -> dict[str, bool]:
    return {name: param.requires_grad for name, param in model.named_parameters()}


def test_disable_adapter_gives_the_raw_base_with_policy_and_reference_loaded(tmp_path):
    base_path = _tiny_base(tmp_path)
    previous = _saved_adapter(base_path, tmp_path / "previous", seed=1)
    reference = _saved_adapter(base_path, tmp_path / "reference", seed=2)
    raw = _load_base(base_path)

    # The script's previous-adapter path.
    model = _load_base(base_path)
    script.enable_gradient_checkpointing(model)
    model = peft.PeftModel.from_pretrained(
        model,
        str(previous),
        adapter_name=script.TRAINED_ADAPTER,
        is_trainable=True,
        local_files_only=True,
    )
    script.check_adapter_loaded(
        model.load_adapter(str(reference), adapter_name=script.REFERENCE_ADAPTER)
    )
    model.set_adapter(script.TRAINED_ADAPTER)

    # Base scoring happens in eval mode, before any training.
    assert model.training is False
    flags_before = _grad_flags(model)
    trainable = {name for name, flag in flags_before.items() if flag}
    assert trainable and all(f".{script.TRAINED_ADAPTER}." in name for name in trainable)

    raw_logits = _logits(raw)
    assert not torch.equal(_logits(model), raw_logits), "the adapter must change the output"

    with model.disable_adapter():
        assert torch.equal(_logits(model), raw_logits)
        assert torch.equal(_greedy(model), _greedy(raw))
    assert _grad_flags(model) == flags_before

    # Whichever adapter is active, disabling gives the bare base.
    model.set_adapter(script.REFERENCE_ADAPTER)
    with model.disable_adapter():
        assert torch.equal(_logits(model), raw_logits)
    model.set_adapter(script.TRAINED_ADAPTER)
    assert _grad_flags(model) == flags_before


def test_disable_adapter_gives_the_raw_base_for_a_fresh_adapter(tmp_path):
    base_path = _tiny_base(tmp_path)
    raw = _load_base(base_path)

    # The script's fresh-adapter path, with weight in B so the LoRA is live.
    model = _load_base(base_path)
    script.enable_gradient_checkpointing(model)
    model = peft.get_peft_model(model, _lora_config())
    _perturb_lora_b(model, seed=3)
    flags_before = _grad_flags(model)

    raw_logits = _logits(raw)
    assert not torch.equal(_logits(model), raw_logits)
    with model.disable_adapter():
        assert torch.equal(_logits(model), raw_logits)
        assert torch.equal(_greedy(model), _greedy(raw))
    assert _grad_flags(model) == flags_before
