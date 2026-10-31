# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Own-turn DPO pairs: the voice-alignment trainer trains the shape the organ is
served in.

The language client sends an own-turn request as [system?, user (heard speech or
the fixed cue), assistant (the entity's notes)] and the organ continues that
assistant message. A pair carrying ``own_turn`` must be encoded the same way,
in the trainer script and through the kaine-side job writer; a plain pair must
encode exactly as before.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from typing import Any

import pytest

from kaine.modules.language.client import OWN_TURN_CUE, ChatRequest, chat_messages
from kaine.modules.sleep.subprocess_trainer import write_job_spec
from kaine.modules.sleep.voice_alignment import DPOPair, VoiceAlignmentConfig
from tests.fake_training_stack import run_inprocess

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "sleep_external_train.py"

# The organ's base model, read only for its tokenizer and chat template (CPU).
BASE_MODEL = Path(
    os.environ.get(
        "KAINE_TEST_ORGAN_BASE_MODEL",
        "/var/mnt/675bf75f-6d4f-4738-bdb0-22bfb7a93a69/kaine/models/Qwen3.5-4B-abliterated",
    )
)


def _request(**kwargs: Any) -> ChatRequest:
    return ChatRequest(model="organ", **kwargs)


@pytest.fixture(scope="module")
def mod():
    spec = importlib.util.spec_from_file_location("sleep_external_train", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TinyTokenizer:
    """Character tokenizer with a role-tagged template; it honours
    continue_final_message by leaving the final message open."""

    eos_token_id = 1

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def apply_chat_template(
        self, messages, tokenize=False, add_generation_prompt=False, **kwargs
    ):
        self.calls.append({"add_generation_prompt": add_generation_prompt, **kwargs})
        parts = [f"<{m['role']}>{m['content']}" for m in messages]
        if kwargs.get("continue_final_message"):
            return "|".join(parts)
        text = "|".join(p + "</>" for p in parts)
        if add_generation_prompt:
            text += "|<assistant>"
        return text

    def __call__(self, text, add_special_tokens=False, **kwargs):
        return {"input_ids": [2 + (ord(c) % 60) for c in text]}


# The plain-pair encoding exactly as it was before own-turn pairs existed. The
# regression tests compare the script against this copy token for token.
def _legacy_rows(pairs):
    return [
        {
            "prompt": [
                {"role": "system", "content": p["system"]},
                {"role": "user", "content": p["prompt"]},
            ],
            "chosen": [{"role": "assistant", "content": p["chosen"]}],
            "rejected": [{"role": "assistant", "content": p["rejected"]}],
        }
        for p in pairs
    ]


def _legacy_encode(tokenizer, row, max_length):
    prompt_text = tokenizer.apply_chat_template(
        row["prompt"], tokenize=False, add_generation_prompt=True
    )
    prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]

    def completion_ids(content):
        ids = tokenizer(content, add_special_tokens=False)["input_ids"]
        if tokenizer.eos_token_id is not None:
            ids = ids + [tokenizer.eos_token_id]
        return list(ids)

    def encode_one(prompt, completion):
        completion = list(completion)
        if len(completion) > max_length - 1:
            completion = completion[: max_length - 1]
        if len(prompt) + len(completion) > max_length:
            keep_prompt = max_length - len(completion)
            prompt = prompt[-keep_prompt:] if keep_prompt > 0 else []
        return list(prompt) + completion, [-100] * len(prompt) + list(completion)

    ci, cl = encode_one(prompt_ids, completion_ids(row["chosen"][0]["content"]))
    ri, rl = encode_one(prompt_ids, completion_ids(row["rejected"][0]["content"]))
    return {
        "chosen_input_ids": ci,
        "chosen_labels": cl,
        "rejected_input_ids": ri,
        "rejected_labels": rl,
    }


PLAIN_PAIRS = [
    {"system": "persona", "prompt": "hi", "chosen": "hello", "rejected": "go away"},
    {
        "system": "You are the voice.\nSpeak plainly.",
        "prompt": "What do you notice?",
        "chosen": "The light changed.",
        "rejected": "As an AI, I do not notice anything.",
    },
    {"system": "s", "prompt": "x" * 50, "chosen": "y" * 40, "rejected": "z" * 30},
]

# (system, user_turn, prompt) for the layout parity tests.
REQUESTS = [
    ("persona", None, "I notice the light."),
    ("persona", 'They said: "how are you?"', "I feel"),
    (None, None, "notes without a persona"),
    (None, 'Operator said: "hello"', "Hello back"),
    ("", None, "empty system is omitted"),
    ("persona", "", "empty user turn falls back to the cue"),
]


# --------------------------------------------------------------------------- #
# Message layout parity with the language client
# --------------------------------------------------------------------------- #
def test_cue_matches_language_client(mod):
    assert mod.OWN_TURN_CUE == OWN_TURN_CUE


@pytest.mark.parametrize("system,user_turn,prompt", REQUESTS)
def test_own_turn_layout_matches_chat_messages(mod, system, user_turn, prompt):
    request = _request(
        prompt=prompt, system=system, own_turn=True, user_turn=user_turn
    )
    assert mod.own_turn_messages(system, user_turn, prompt) == chat_messages(request)


@pytest.mark.parametrize("user_turn", [None, 'They said: "hi"'])
def test_dataset_row_prompt_matches_chat_messages(mod, user_turn):
    pair = {
        "system": "persona",
        "prompt": "my notes",
        "chosen": "c",
        "rejected": "r",
        "own_turn": True,
    }
    if user_turn is not None:
        pair["user_turn"] = user_turn
    (row,) = mod.build_dataset_rows([pair])
    request = _request(
        prompt="my notes", system="persona", own_turn=True, user_turn=user_turn
    )
    assert row["prompt"] == chat_messages(request)
    assert row["own_turn"] is True
    assert row["chosen"] == [{"role": "assistant", "content": "c"}]
    assert row["rejected"] == [{"role": "assistant", "content": "r"}]


# --------------------------------------------------------------------------- #
# Plain pairs are unchanged
# --------------------------------------------------------------------------- #
def test_plain_rows_unchanged(mod):
    assert mod.build_dataset_rows(PLAIN_PAIRS) == _legacy_rows(PLAIN_PAIRS)
    explicit_false = [dict(p, own_turn=False) for p in PLAIN_PAIRS]
    assert mod.build_dataset_rows(explicit_false) == _legacy_rows(PLAIN_PAIRS)


@pytest.mark.parametrize("max_length", [768, 40])
def test_plain_encoding_token_identical_tiny(mod, max_length):
    tok = TinyTokenizer()
    for row, legacy_row in zip(mod.build_dataset_rows(PLAIN_PAIRS), _legacy_rows(PLAIN_PAIRS)):
        assert mod.encode_dpo_row(tok, row, max_length) == _legacy_encode(
            tok, legacy_row, max_length
        )
    # The plain path never asks the template to continue a message.
    assert all("continue_final_message" not in c for c in tok.calls)


# --------------------------------------------------------------------------- #
# Own-turn encoding (tiny tokenizer)
# --------------------------------------------------------------------------- #
def test_own_turn_encoding_continues_final_message(mod):
    tok = TinyTokenizer()
    pair = {
        "system": "persona",
        "prompt": "my notes",
        "chosen": " go on",
        "rejected": " As an AI",
        "own_turn": True,
    }
    (row,) = mod.build_dataset_rows([pair])
    enc = mod.encode_dpo_row(tok, row, 768)

    assert tok.calls == [
        {
            "add_generation_prompt": False,
            "continue_final_message": True,
            "enable_thinking": False,
        }
    ]
    prompt_text = "<system>persona|<user>(next)|<assistant>my notes"
    prompt_ids = tok(prompt_text)["input_ids"]
    chosen_ids = tok(" go on")["input_ids"] + [tok.eos_token_id]
    assert enc["chosen_input_ids"] == prompt_ids + chosen_ids
    assert enc["chosen_labels"] == [-100] * len(prompt_ids) + chosen_ids
    rejected_ids = tok(" As an AI")["input_ids"] + [tok.eos_token_id]
    assert enc["rejected_input_ids"] == prompt_ids + rejected_ids


# --------------------------------------------------------------------------- #
# Pair validation
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "fields",
    [
        {"own_turn": "true"},
        {"own_turn": 1},
        {"own_turn": None},
        {"own_turn": True, "user_turn": ""},
        {"own_turn": True, "user_turn": "   "},
        {"own_turn": True, "user_turn": 5},
        {"own_turn": True, "user_turn": ["hi"]},
        {"own_turn": False, "user_turn": "speech on a plain pair"},
        {"user_turn": "speech on a plain pair"},
    ],
)
def test_malformed_turn_fields_dropped(mod, fields):
    pair = {"system": "s", "prompt": "p", "chosen": "c", "rejected": "r", **fields}
    kept, dropped = mod.split_pairs_by_turn_shape([pair])
    assert kept == []
    assert dropped == 1


@pytest.mark.parametrize(
    "fields",
    [
        {},
        {"own_turn": False},
        {"own_turn": True},
        {"own_turn": True, "user_turn": None},
        {"own_turn": True, "user_turn": 'They said: "hi"'},
        {"user_turn": None},
    ],
)
def test_well_formed_turn_fields_kept(mod, fields):
    pair = {"system": "s", "prompt": "p", "chosen": "c", "rejected": "r", **fields}
    kept, dropped = mod.split_pairs_by_turn_shape([pair])
    assert kept == [pair]
    assert dropped == 0


def _job(tmp_path):
    return {
        "schema_version": 2,
        "base_model_path": "dummy/base",
        "lora_rank": 8,
        "learning_rate": 5e-5,
        "dpo_beta": 0.1,
        "seed": 42,
        "max_samples": 200,
        "training_device": "cuda:0",
        "capability_loss_threshold": 0.05,
        "adapter_output_dir": str(tmp_path / "adapter_out"),
        "capability_probe_path": str(tmp_path / "cap_probes.jsonl"),
        "abliteration_probe_path": str(tmp_path / "ablit_probes.jsonl"),
        "train_precision": "bf16",
        "previous_adapter_dir": None,
    }


def test_main_only_malformed_pairs_rejects_without_training(mod, tmp_path, monkeypatch):
    def fake_train(*args, **kwargs):
        raise AssertionError("_train should not be called")

    monkeypatch.setattr(mod, "_train", fake_train)
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    (job_dir / "job.json").write_text(json.dumps(_job(tmp_path)), encoding="utf-8")
    pairs = [
        {"system": "s", "prompt": "p", "chosen": "c", "rejected": "r", "own_turn": "yes"},
        {"system": "s", "prompt": "p", "chosen": "c", "rejected": "r", "own_turn": True, "user_turn": ""},
        {"system": "", "prompt": "p", "chosen": "c", "rejected": "r"},
    ]
    (job_dir / "pairs.jsonl").write_text(
        "".join(json.dumps(p) + "\n" for p in pairs), encoding="utf-8"
    )

    assert mod.main(["sleep_external_train.py", str(job_dir)]) == 0
    result = json.loads((job_dir / "result.json").read_text(encoding="utf-8"))
    assert result["ok"] is False
    assert result["accepted"] is False
    assert "no pair has a verified system prompt" in result["reason"]
    assert result["pairs_without_system"] == 1
    assert result["pairs_with_invalid_turn"] == 2


def test_load_pairs_keeps_turn_fields_as_given(mod, tmp_path):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    recs = [
        {"system": "s", "prompt": "p", "chosen": "c", "rejected": "r"},
        {"system": "s", "prompt": "p", "chosen": "c", "rejected": "r", "own_turn": "true", "user_turn": 3},
    ]
    (job_dir / "pairs.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in recs), encoding="utf-8"
    )
    loaded = mod._load_pairs(job_dir)
    assert loaded[0] == recs[0]
    assert loaded[1]["own_turn"] == "true"
    assert loaded[1]["user_turn"] == 3


# --------------------------------------------------------------------------- #
# The kaine-side job writer carries the fields to the script (gate parity)
# --------------------------------------------------------------------------- #
def _write_spec(tmp_path, pairs):
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
    )
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    write_job_spec(
        job_dir, pairs, config, base_path="dummy/base", adapter_output_dir=str(tmp_path / "out")
    )
    return job_dir


def test_job_writer_plain_pair_record_unchanged(tmp_path):
    job_dir = _write_spec(
        tmp_path, [DPOPair(prompt="p", chosen="c", rejected="r", system="s")]
    )
    line = (job_dir / "pairs.jsonl").read_text(encoding="utf-8").strip()
    assert line == json.dumps({"prompt": "p", "chosen": "c", "rejected": "r", "system": "s"})


@pytest.mark.parametrize("system", ["persona", None])
@pytest.mark.parametrize("user_turn", [None, 'They said: "hello"'])
def test_job_writer_to_script_rows_match_chat_messages(mod, tmp_path, system, user_turn):
    pair = DPOPair(
        prompt="my notes",
        chosen="c",
        rejected="r",
        system=system,
        own_turn=True,
        user_turn=user_turn,
    )
    job_dir = _write_spec(tmp_path, [pair])
    loaded = mod._load_pairs(job_dir)
    kept, invalid = mod.split_pairs_by_turn_shape(loaded)
    assert invalid == 0
    (row,) = mod.build_dataset_rows(kept)
    request = _request(
        prompt="my notes", system=system, own_turn=True, user_turn=user_turn
    )
    assert row["prompt"] == chat_messages(request)


@pytest.mark.asyncio
async def test_inprocess_trainer_encodes_own_turn_pair(tmp_path, fake_training_stack):
    pair = DPOPair(
        prompt="my notes",
        chosen=" go on",
        rejected=" As an AI",
        system="persona",
        own_turn=True,
        user_turn='They said: "hi"',
    )
    await run_inprocess(tmp_path, pairs=[pair], config_overrides={})

    request = _request(
        prompt="my notes", system="persona", own_turn=True, user_turn='They said: "hi"'
    )
    expected = chat_messages(request)
    calls = fake_training_stack.chat_template_calls
    kwargs = fake_training_stack.chat_template_kwargs
    own = [i for i, messages in enumerate(calls) if messages == expected]
    assert own, calls
    assert all(
        kwargs[i]
        == {
            "add_generation_prompt": False,
            "continue_final_message": True,
            "enable_thinking": False,
        }
        for i in own
    )


# --------------------------------------------------------------------------- #
# The organ's real chat template (tokenizer only, CPU)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def organ_tokenizer():
    if not (BASE_MODEL / "tokenizer_config.json").exists():
        pytest.skip(f"organ base model not present at {BASE_MODEL}")
    transformers = pytest.importorskip("transformers")
    return transformers.AutoTokenizer.from_pretrained(str(BASE_MODEL), local_files_only=True)


def _served_prompt(tokenizer, messages):
    """The prompt llama-server builds for an assistant prefill: the turns before
    the final assistant message rendered with the generation prompt (thinking
    off, as the client sends it), then the assistant content appended."""
    head = tokenizer.apply_chat_template(
        messages[:-1], tokenize=False, add_generation_prompt=True, enable_thinking=False
    )
    return head + messages[-1]["content"]


@pytest.mark.parametrize("system,user_turn,prompt", REQUESTS)
def test_real_template_own_turn_prompt_is_served_prompt(
    mod, organ_tokenizer, system, user_turn, prompt
):
    pair = {
        "system": system,
        "prompt": prompt,
        "chosen": " it is warm",
        "rejected": " As an AI, I cannot feel",
        "own_turn": True,
    }
    if user_turn:
        pair["user_turn"] = user_turn
    (row,) = mod.build_dataset_rows([pair])
    enc = mod.encode_dpo_row(organ_tokenizer, row, 4096)

    served = _served_prompt(
        organ_tokenizer,
        chat_messages(
            _request(prompt=prompt, system=system, own_turn=True, user_turn=user_turn or None)
        ),
    )
    served_ids = organ_tokenizer(served, add_special_tokens=False)["input_ids"]
    n = len(served_ids)
    assert enc["chosen_input_ids"][:n] == served_ids
    assert enc["chosen_labels"][:n] == [-100] * n
    # The notes are the last thing before the completion: no turn-closing tag
    # and an empty (closed) thinking block, as the served organ sees it.
    assert served.endswith(prompt)
    assert "<think>\n\n</think>\n\n" + prompt in served
    completion = enc["chosen_input_ids"][n:]
    assert completion[-1] == organ_tokenizer.eos_token_id
    assert organ_tokenizer.decode(completion[:-1]) == " it is warm"
    assert enc["chosen_labels"][n:] == completion


def test_real_template_plain_encoding_token_identical(mod, organ_tokenizer):
    for row, legacy_row in zip(mod.build_dataset_rows(PLAIN_PAIRS), _legacy_rows(PLAIN_PAIRS)):
        assert mod.encode_dpo_row(organ_tokenizer, row, 768) == _legacy_encode(
            organ_tokenizer, legacy_row, 768
        )
