# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import contextlib
import importlib.util
import math
from pathlib import Path
from typing import Any

import pytest
import torch
import torch.nn.functional as F

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "sleep_external_train", REPO / "scripts" / "sleep_external_train.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _tiny_tokenizer() -> Any:
    class TinyTokenizer:
        def apply_chat_template(
            self, messages, tokenize=False, add_generation_prompt=False
        ):
            text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
            if add_generation_prompt:
                text += "\nassistant: "
            return text

        def __call__(self, text, add_special_tokens=False, **kwargs):
            return {"input_ids": [2 + (ord(c) % 60) for c in text]}

        eos_token_id = 1

    return TinyTokenizer()


def _tiny_model():
    pytest.importorskip("transformers")
    from transformers import Qwen2Config, Qwen2ForCausalLM

    torch.manual_seed(0)
    config = Qwen2Config(
        vocab_size=64,
        hidden_size=16,
        intermediate_size=32,
        num_hidden_layers=1,
        num_attention_heads=2,
        num_key_value_heads=1,
        max_position_embeddings=64,
    )
    return Qwen2ForCausalLM(config)


def _row(tokenizer):
    pair = {
        "prompt": "hi",
        "chosen": "hello",
        "rejected": "go away",
        "system": "persona",
    }
    rows = MODULE.build_dataset_rows([pair])
    return rows[0]


def test_logits_to_keep_reaches_the_base_model_through_peft():
    pytest.importorskip("peft")
    from peft import LoraConfig, get_peft_model

    model = _tiny_model()
    wrapped = get_peft_model(
        model,
        LoraConfig(r=4, lora_alpha=4, lora_dropout=0.0, target_modules="all-linear"),
    )

    recorded: dict[str, Any] = {}

    def hook(module, args, kwargs):
        recorded["logits_to_keep"] = kwargs.get("logits_to_keep")

    handle = wrapped.base_model.model.register_forward_pre_hook(hook, with_kwargs=True)
    try:
        MODULE.completion_logprob(wrapped, [5, 6, 7, 8, 9], [-100, -100, -100, 8, 9], "cpu")
    finally:
        handle.remove()

    assert recorded["logits_to_keep"] == 3


def test_completion_logprob_matches_direct_computation():
    model = _tiny_model()
    model.eval()
    tokenizer = _tiny_tokenizer()
    row = _row(tokenizer)
    enc = MODULE.encode_dpo_row(tokenizer, row, max_length=768)
    input_ids = enc["chosen_input_ids"]
    labels = enc["chosen_labels"]
    n = sum(1 for label in labels if label != -100)

    got = MODULE.completion_logprob(model, input_ids, labels, "cpu")

    with torch.no_grad():
        out = model(input_ids=torch.tensor([input_ids]))
        logits = out.logits
    shifted = logits[0, :-1, :]
    token_logp = torch.log_softmax(shifted.float(), dim=-1)
    target_ids = torch.tensor(input_ids[1:])
    gathered = token_logp.gather(1, target_ids.unsqueeze(1)).squeeze(1)
    completion_indices = [i for i, label in enumerate(labels) if label != -100]
    direct = sum(gathered[i - 1] for i in completion_indices if i > 0)
    if n == len(input_ids):
        direct = direct
    torch.testing.assert_close(got, direct)


def test_dpo_loss_matches_hand_computation():
    for beta in (0.1, 0.5):
        pc = torch.tensor(0.3)
        pr = torch.tensor(-0.1)
        rc = torch.tensor(0.2)
        rr = torch.tensor(0.05)
        expected = -F.logsigmoid(beta * ((pc - pr) - (rc - rr)))
        actual = MODULE.dpo_loss(pc, pr, rc, rr, beta)
        torch.testing.assert_close(actual, expected)


def test_first_pair_loss_is_log_two():
    model = _tiny_model()
    model.eval()
    tokenizer = _tiny_tokenizer()
    row = _row(tokenizer)
    enc = MODULE.encode_dpo_row(tokenizer, row, max_length=768)
    with torch.no_grad():
        with contextlib.nullcontext():
            rc = MODULE.completion_logprob(
                model, enc["chosen_input_ids"], enc["chosen_labels"], "cpu"
            )
            rr = MODULE.completion_logprob(
                model, enc["rejected_input_ids"], enc["rejected_labels"], "cpu"
            )
    pc = MODULE.completion_logprob(
        model, enc["chosen_input_ids"], enc["chosen_labels"], "cpu"
    )
    pr = MODULE.completion_logprob(
        model, enc["rejected_input_ids"], enc["rejected_labels"], "cpu"
    )
    loss = MODULE.dpo_loss(pc, pr, rc, rr, 0.1)
    assert abs(float(loss) - math.log(2)) < 1e-5


def test_run_dpo_epoch_returns_two_steps_for_five_rows():
    model = _tiny_model()
    tokenizer = _tiny_tokenizer()
    pairs = [
        {
            "prompt": f"prompt{i}",
            "chosen": f"chosen{i}",
            "rejected": f"rejected{i}",
            "system": "persona",
        }
        for i in range(5)
    ]
    rows = MODULE.build_dataset_rows(pairs)
    mean_loss, steps = MODULE.run_dpo_epoch(
        model,
        tokenizer,
        rows,
        beta=0.1,
        learning_rate=1e-3,
        seed=0,
        device="cpu",
        reference_ctx=contextlib.nullcontext,
        accumulation=4,
        max_length=64,
    )
    assert steps == 2
    assert math.isfinite(mean_loss)


def test_only_trainable_parameters_change():
    model = _tiny_model()
    tokenizer = _tiny_tokenizer()
    for name, param in model.named_parameters():
        param.requires_grad = name.startswith("lm_head.")
    before = {name: param.detach().clone() for name, param in model.named_parameters()}
    rows = MODULE.build_dataset_rows(
        [
            {
                "prompt": "prompt",
                "chosen": "chosen",
                "rejected": "rejected",
                "system": "persona",
            }
        ]
    )
    MODULE.run_dpo_epoch(
        model,
        tokenizer,
        rows,
        beta=0.1,
        learning_rate=1e-2,
        seed=0,
        device="cpu",
        reference_ctx=contextlib.nullcontext,
        accumulation=4,
        max_length=64,
    )
    for name, param in model.named_parameters():
        if name.startswith("lm_head."):
            assert not torch.equal(before[name], param.detach())
        else:
            assert torch.equal(before[name], param.detach())


def test_lora_only_parameters_change():
    pytest.importorskip("peft")
    from peft import LoraConfig, get_peft_model

    model = _tiny_model()
    tokenizer = _tiny_tokenizer()
    model = get_peft_model(
        model,
        LoraConfig(r=4, lora_alpha=4, lora_dropout=0.0, target_modules="all-linear"),
    )
    before = {name: param.detach().clone() for name, param in model.named_parameters()}
    rows = MODULE.build_dataset_rows(
        [
            {
                "prompt": "prompt",
                "chosen": "chosen",
                "rejected": "rejected",
                "system": "persona",
            }
        ]
    )
    MODULE.run_dpo_epoch(
        model,
        tokenizer,
        rows,
        beta=0.1,
        learning_rate=1e-2,
        seed=0,
        device="cpu",
        reference_ctx=model.disable_adapter,
        accumulation=4,
        max_length=64,
    )
    changed_lora = False
    for name, param in model.named_parameters():
        if "lora_" in name:
            if not torch.equal(before[name], param.detach()):
                changed_lora = True
        else:
            assert torch.equal(before[name], param.detach())
    assert changed_lora


def test_empty_completion_scores_zero_without_touching_the_model():
    """A completion with no tokens scores 0; it never selects the prompt."""

    class NoForward:
        def forward(self, **kwargs):
            raise AssertionError("an empty completion must not run the model")

        __call__ = forward

    out = MODULE.completion_logprob(NoForward(), [5, 6, 7], [-100, -100, -100], "cpu")
    assert float(out) == 0.0
    out = MODULE.completion_logprob(NoForward(), [5], [5], "cpu")
    assert float(out) == 0.0
