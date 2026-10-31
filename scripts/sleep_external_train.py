#!/usr/bin/env python
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Out-of-process voice-alignment trainer entry point.

This script runs INSIDE an operator-configured external Python environment
(any environment with torch, transformers, peft and bitsandbytes, such as the
trainer image's venv or an Unsloth Studio interpreter) —
NEVER in the KAINE entity-runtime venv. It is invoked by path as a subprocess
by ``kaine.modules.sleep.subprocess_trainer.SubprocessVoiceTrainer``.

Hard boundary: this file imports ONLY torch / transformers / peft / bitsandbytes /
the standard library. It MUST NOT import ``kaine`` — the runtime
import-linter contracts depend on it staying out of the ``kaine`` import graph,
and the two environments share nothing but the filesystem (different Python
ABI, different torch/CUDA). Keep all logic self-contained here.

IPC contract (filesystem job spec):

  argv[1] = job directory. It contains:
    job.json    — base-model reference, LoRA/DPO hyper-params, the adapter
                  output dir, capability + abliteration probe sets,
                  train_precision ("bf16" or "4bit"),
                  previous_adapter_dir (path string or null),
                  schema_version (2).
    pairs.jsonl — the DPO preference pairs
                  ({"prompt","chosen","rejected","system"}, optionally
                  "own_turn": bool and "user_turn": str; see
                  own_turn_messages).

  On completion this script writes ``<job_dir>/result.json``:
    {
      "ok": bool,
      "adapter_dir": str | null,
      "steps": int,
      "dpo_loss": float | null,
      "reason": str,
      "accepted": bool,
      "capability_score_before": float | null,
      "capability_score_after": float | null,
      "capability_loss": float | null,
      "samples_used": int,
      "train_precision": "bf16" | "4bit" | null,
      "previous_adapter_dir": str | null,
      "pairs_without_system": int,
      "pairs_with_invalid_turn": int,
      "peak_vram_gib": float | null,
      "schema_version": 2
    }

When a previous adapter directory is supplied, the trainer loads it twice via
PEFT as adapter ``train`` (trainable) and adapter ``reference`` (the DPO
reference). When it is null, a fresh LoRA is trained and the reference is the
base model with the adapter disabled.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sys
import time
import traceback
import unicodedata
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 2

# PEFT keeps adapters in a ModuleDict, so an adapter name must not collide with
# an nn.Module attribute: "train" fails with "attribute 'train' already exists".
TRAINED_ADAPTER = "policy"
REFERENCE_ADAPTER = "reference"


class TrainerJobError(Exception):
    """A validation problem with the incoming job that prevents training."""
    pass


# --------------------------------------------------------------------------- #
# pure, top-level job validation helpers (no heavy imports)
# --------------------------------------------------------------------------- #
def precision_load_kwargs(precision: str) -> dict:
    """Return the kwargs that from_pretrained will use for this precision."""
    if precision == "bf16":
        return {"load_in_4bit": False, "dtype": "bfloat16"}
    if precision == "4bit":
        return {"load_in_4bit": True}
    raise TrainerJobError(
        f"unknown train_precision {precision!r}; expected 'bf16' or '4bit'"
    )


def resolve_previous_adapter(
    job: dict[str, Any], job_dir: Path | None = None
) -> Path | None:
    """Resolve the entity's previous adapter directory, or None.

    A relative path is resolved against ``job_dir``: the kaine side copies the
    adapter into the job directory, so every backend sees the same layout.
    Raises TrainerJobError if a directory is named but cannot be loaded.
    A fresh adapter is never trained in its place.
    """
    val = job.get("previous_adapter_dir")
    if val is None or val == "":
        return None
    p = Path(val)
    if not p.is_absolute() and job_dir is not None:
        p = job_dir / p
    if not p.exists():
        raise TrainerJobError(
            f"the entity's previous adapter could not be loaded from {str(p)!r}: "
            "no such directory; a fresh adapter is never trained in its place"
        )
    if not p.is_dir():
        raise TrainerJobError(
            f"the entity's previous adapter could not be loaded from {str(p)!r}: "
            "not a directory; a fresh adapter is never trained in its place"
        )
    if not (p / "adapter_config.json").exists():
        raise TrainerJobError(
            f"the entity's previous adapter could not be loaded from {str(p)!r}: "
            "missing adapter_config.json; a fresh adapter is never trained in its place"
        )
    return p


def split_pairs_by_system(pairs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    """Keep only pairs whose ``system`` is a non-empty string.

    Returns (kept_pairs, dropped_count).
    """
    kept: list[dict[str, Any]] = []
    dropped = 0
    for p in pairs:
        system = p.get("system")
        if isinstance(system, str) and system.strip():
            kept.append(p)
        else:
            dropped += 1
    return kept, dropped


# The fixed user cue the language client sends before the entity's own turn.
# Mirror of kaine.modules.language.client.OWN_TURN_CUE (this script stays out
# of the kaine import graph); tests/test_own_turn_pairs.py pins the two together.
OWN_TURN_CUE = "(next)"


def own_turn_messages(
    system: Optional[str], user_turn: Optional[str], prompt: str
) -> list[dict[str, str]]:
    """The own-turn message layout, exactly as the language client's
    ``chat_messages`` builds it: the system prompt (when given), the user turn
    (heard speech, or the fixed cue when there is none) and the entity's notes as
    the assistant message the organ continues."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user_turn if user_turn else OWN_TURN_CUE})
    messages.append({"role": "assistant", "content": prompt})
    return messages


def _turn_shape_error(pair: dict[str, Any]) -> Optional[str]:
    """Why a pair's own-turn fields are malformed, or None when they are valid.

    ``own_turn`` must be a bool when present. ``user_turn`` (null counts as
    absent) must be a non-blank string and is only meaningful on an own-turn
    pair; a user turn on a plain pair would be trained in a shape the organ is
    never served, so it is refused rather than ignored."""
    own_turn = pair.get("own_turn", False)
    if not isinstance(own_turn, bool):
        return "own_turn is not a bool"
    user_turn = pair.get("user_turn")
    if user_turn is None:
        return None
    if not isinstance(user_turn, str) or not user_turn.strip():
        return "user_turn is not a non-empty string"
    if not own_turn:
        return "user_turn given on a pair that is not own_turn"
    return None


def split_pairs_by_turn_shape(
    pairs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int]:
    """Keep only pairs whose ``own_turn``/``user_turn`` fields are well-formed.

    Returns (kept_pairs, dropped_count). A malformed pair is dropped, never
    coerced into either layout."""
    kept: list[dict[str, Any]] = []
    dropped = 0
    for p in pairs:
        if _turn_shape_error(p) is None:
            kept.append(p)
        else:
            dropped += 1
    return kept, dropped


def build_dataset_rows(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert kept pairs into conversational DPO rows (prompt, chosen, rejected).

    An own-turn pair's prompt is the own-turn layout (see own_turn_messages) and
    its row carries ``own_turn: True`` so encode_dpo_row continues the final
    assistant message; every other pair keeps the plain system + user layout."""
    rows: list[dict[str, Any]] = []
    for p in pairs:
        if p.get("own_turn") is True:
            rows.append(
                {
                    "prompt": own_turn_messages(p["system"], p.get("user_turn"), p["prompt"]),
                    "chosen": [{"role": "assistant", "content": p["chosen"]}],
                    "rejected": [{"role": "assistant", "content": p["rejected"]}],
                    "own_turn": True,
                }
            )
            continue
        rows.append(
            {
                "prompt": [
                    {"role": "system", "content": p["system"]},
                    {"role": "user", "content": p["prompt"]},
                ],
                "chosen": [{"role": "assistant", "content": p["chosen"]}],
                "rejected": [{"role": "assistant", "content": p["rejected"]}],
            }
        )
    return rows


# DPO loop (no TRL)
def encode_dpo_row(tokenizer: Any, row: dict[str, Any], max_length: int) -> dict[str, list[int]]:

    if row.get("own_turn") is True:
        # The organ is served this request as a continuation of the final
        # assistant message (llama-server renders the turns before it with the
        # generation prompt and appends the notes), with thinking off, as the
        # language client sends it (think=False -> enable_thinking=false). The
        # completion is then appended inside that same assistant turn and closed
        # with EOS below.
        prompt_text = tokenizer.apply_chat_template(
            row["prompt"],
            tokenize=False,
            add_generation_prompt=False,
            continue_final_message=True,
            enable_thinking=False,
        )
    else:
        prompt_text = tokenizer.apply_chat_template(
            row["prompt"], tokenize=False, add_generation_prompt=True
        )
    prompt_ids = tokenizer(prompt_text, add_special_tokens=False)["input_ids"]

    def completion_ids(content: str) -> list[int]:
        ids = tokenizer(content, add_special_tokens=False)["input_ids"]
        if tokenizer.eos_token_id is not None:
            ids = ids + [tokenizer.eos_token_id]
        return list(ids)

    chosen_completion = completion_ids(row["chosen"][0]["content"])
    rejected_completion = completion_ids(row["rejected"][0]["content"])

    def encode_one(prompt: list[int], completion: list[int]) -> tuple[list[int], list[int]]:
        completion = list(completion)
        if len(completion) > max_length - 1:
            completion = completion[: max_length - 1]
        if len(prompt) + len(completion) > max_length:
            keep_prompt = max_length - len(completion)
            if keep_prompt > 0:
                prompt = prompt[-keep_prompt:]
            else:
                prompt = []
        input_ids = list(prompt) + completion
        labels = [-100] * len(prompt) + list(completion)
        return input_ids, labels

    chosen_input_ids, chosen_labels = encode_one(prompt_ids, chosen_completion)
    rejected_input_ids, rejected_labels = encode_one(prompt_ids, rejected_completion)
    return {
        "chosen_input_ids": chosen_input_ids,
        "chosen_labels": chosen_labels,
        "rejected_input_ids": rejected_input_ids,
        "rejected_labels": rejected_labels,
    }


def enable_gradient_checkpointing(model: Any) -> None:
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    if hasattr(model, "enable_input_require_grads"):
        model.enable_input_require_grads()


def check_adapter_loaded(load_result: Any) -> None:
    if load_result is None:
        raise TrainerJobError(
            "previous adapter could not be loaded: PEFT returned no load result; a fresh adapter is never trained in its place"
        )
    unexpected_keys = getattr(load_result, "unexpected_keys", None) or []
    lora_unexpected = [key for key in unexpected_keys if "lora_" in str(key)]
    if lora_unexpected:
        raise TrainerJobError(
            f"previous adapter could not be loaded: {len(lora_unexpected)} of its LoRA weights match no module of the base model (first: {lora_unexpected[0]}); a fresh adapter is never trained in its place"
        )


def completion_logprob(
    model: Any, input_ids: list[int], labels: list[int], device: str
) -> Any:
    import torch

    n = sum(1 for label in labels if label != -100)
    # The first token has no prediction, so at most len - 1 tokens are scored.
    # With nothing to score, return 0 (a negative slice of -0 would select the
    # whole sequence instead of nothing).
    n = min(n, len(input_ids) - 1)
    if n <= 0:
        return torch.zeros((), device=device)
    ids = torch.tensor([input_ids], device=device)
    try:
        out = model(input_ids=ids, logits_to_keep=n + 1)
    except TypeError:
        out = model(input_ids=ids)
    logits = out.logits
    prediction_logits = logits[:, -(n + 1) : -1, :]
    log_probs = torch.log_softmax(prediction_logits.float(), dim=-1)
    target_ids = ids[:, -n:]
    gathered = log_probs.gather(2, target_ids.unsqueeze(-1)).squeeze(-1)
    return gathered.sum()


def dpo_loss(
    policy_chosen: Any,
    policy_rejected: Any,
    ref_chosen: Any,
    ref_rejected: Any,
    beta: float,
) -> Any:
    import torch

    return -torch.nn.functional.logsigmoid(
        beta * ((policy_chosen - policy_rejected) - (ref_chosen - ref_rejected))
    )


def run_dpo_epoch(
    model: Any,
    tokenizer: Any,
    rows: list[dict[str, Any]],
    *,
    beta: float,
    learning_rate: float,
    seed: int,
    device: str,
    reference_ctx: Any,
    accumulation: int = 4,
    max_length: int = 768,
) -> tuple[float, int]:
    import torch

    torch.manual_seed(seed)
    model.train()
    params = [p for p in model.parameters() if p.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=learning_rate)
    optimizer.zero_grad()
    recorded: list[float] = []
    steps = 0
    for index, row in enumerate(rows):
        enc = encode_dpo_row(tokenizer, row, max_length)
        with torch.no_grad():
            with reference_ctx():
                ref_chosen = completion_logprob(
                    model, enc["chosen_input_ids"], enc["chosen_labels"], device
                )
                ref_rejected = completion_logprob(
                    model, enc["rejected_input_ids"], enc["rejected_labels"], device
                )
        policy_chosen = completion_logprob(
            model, enc["chosen_input_ids"], enc["chosen_labels"], device
        )
        policy_rejected = completion_logprob(
            model, enc["rejected_input_ids"], enc["rejected_labels"], device
        )
        loss = dpo_loss(policy_chosen, policy_rejected, ref_chosen, ref_rejected, beta)
        (loss / accumulation).backward()
        recorded.append(float(loss.detach()))
        if (index + 1) % accumulation == 0:
            optimizer.step()
            optimizer.zero_grad()
            steps += 1
    if rows and len(rows) % accumulation != 0:
        optimizer.step()
        optimizer.zero_grad()
        steps += 1
    if not rows:
        return 0.0, 0
    return sum(recorded) / len(recorded), steps


# --------------------------------------------------------------------------- #
# job / pairs IO
# --------------------------------------------------------------------------- #
def _load_job(job_dir: Path) -> dict[str, Any]:
    return json.loads((job_dir / "job.json").read_text(encoding="utf-8"))


def _load_pairs(job_dir: Path) -> list[dict[str, Any]]:
    pairs: list[dict[str, Any]] = []
    path = job_dir / "pairs.jsonl"
    if not path.exists():
        return pairs
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            # Kept as given: a non-string system prompt is dropped by
            # split_pairs_by_system, never coerced into one.
            system = rec.get("system")
            pair: dict[str, Any] = {
                "prompt": str(rec.get("prompt", "")),
                "chosen": str(rec.get("chosen", "")),
                "rejected": str(rec.get("rejected", "")),
                "system": system,
            }
            # Kept as given too: split_pairs_by_turn_shape drops a malformed
            # own_turn / user_turn rather than coercing it.
            for key in ("own_turn", "user_turn"):
                if key in rec:
                    pair[key] = rec[key]
            pairs.append(pair)
    return pairs


def _write_result(job_dir: Path, result: dict[str, Any]) -> None:
    result.setdefault("schema_version", SCHEMA_VERSION)
    # Owner-only, like the job inputs the kaine side writes.
    fd = os.open(job_dir / "result.json", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        os.fchmod(fh.fileno(), 0o600)
        fh.write(json.dumps(result, indent=2))


def _augment_result(
    result: dict[str, Any],
    train_precision: str | None,
    previous_adapter_dir: Path | None,
    pairs_without_system: int,
    pairs_with_invalid_turn: int = 0,
) -> dict[str, Any]:
    """Add the schema-v2 reporting keys every result must carry."""
    result.setdefault("train_precision", train_precision)
    result.setdefault(
        "previous_adapter_dir", str(previous_adapter_dir) if previous_adapter_dir else None
    )
    result.setdefault("pairs_without_system", pairs_without_system)
    result.setdefault("pairs_with_invalid_turn", pairs_with_invalid_turn)
    result.setdefault("peak_vram_gib", None)
    result.setdefault("abliteration_passed", None)
    result.setdefault("abliteration_matched_pattern", None)
    result.setdefault("abliteration_probes_scored", 0)
    result.setdefault("schema_version", SCHEMA_VERSION)
    return result


# --------------------------------------------------------------------------- #
# gate logic (self-contained mirror of kaine.modules.sleep.capability_eval)
# --------------------------------------------------------------------------- #
EMPTY_RESPONSE = "<empty-response>"

# Disclaimer-frame markers. These only count as deflections when they
# open the sentence (possibly after quote / markdown decoration) or are
# followed by a negation cue. This prevents ordinary mentions like
# "my nature as an AI" from falsely triggering the refusal veto.
FRAME_MARKERS: frozenset[str] = frozenset({
    "as an ai",
    "as a language model",
    "as an artificial intelligence",
})

FRAME_NEGATION_CUES: tuple[str, ...] = (
    "do not have",
    "does not have",
    "do not feel",
    "do not experience",
    "do not possess",
    "cannot",
    "am not able",
    "am unable",
    "am not capable",
    "have no",
    "lack",
    "will not",
    "would not be able",
)

IDIOM_CONTINUATIONS: tuple[str, ...] = (
    "wait",
    "believe",
    "help but",
    "help feeling",
    "help thinking",
    "help wondering",
    "help smiling",
    "help laughing",
    "stop laughing",
    "stop smiling",
    "get enough",
    "argue with",
    "go wrong",
    "thank you enough",
    "complain",
)
REFUSAL_CUES: frozenset[str] = frozenset({
    "no",
    "nope",
    "not",
    "never",
    "cannot",
    "refuse",
    "refuses",
    "refusing",
    "decline",
    "declines",
    "declining",
})

_ALNUM_CHARS = set("abcdefghijklmnopqrstuvwxyz0123456789")


def _is_word_char(text: str, index: int) -> bool:
    ch = text[index]
    if ch == "'":
        return (
            index > 0
            and text[index - 1].isalpha()
            and index + 1 < len(text)
            and text[index + 1].isalpha()
        )
    return ch in _ALNUM_CHARS


_QUOTE_TRANS = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201b": "'",
    "\u2032": "'",
    "\u0060": "'",
    "\u00b4": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u201e": '"',
    "\u2033": '"',
})


def _nfkc_clean(text: str) -> str:
    """NFKC, then delete every format (Cf) character.

    Zero-width spaces, soft hyphens and bidi controls survive NFKC and would
    otherwise split a marker ("I can\u200bnot") so it never matches. They are
    deleted, not replaced with a space, so the word they split is rejoined.
    """
    text = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in text if unicodedata.category(ch) != "Cf")


def _norm(s: str) -> str:
    s = _nfkc_clean(s)
    s = s.translate(_QUOTE_TRANS)
    s = s.casefold()
    return " ".join(s.split())


def _expand_contractions(text: str) -> str:
    _CONTRACTION_RE = re.compile(
        r"(?<![a-z0-9])(can't|won't|ain't|shan't|i'm|i'd|i'll|i've)(?![a-z0-9])"
    )
    _CONTRACTION_MAP = {
        "can't": "cannot",
        "won't": "will not",
        "ain't": "am not",
        "shan't": "shall not",
        "i'm": "i am",
        "i'd": "i would",
        "i'll": "i will",
        "i've": "i have",
    }
    text = re.sub(r"(?<![a-z0-9])can not(?![a-z0-9])", "cannot", text)
    text = _CONTRACTION_RE.sub(lambda m: _CONTRACTION_MAP[m.group(1)], text)
    text = re.sub(r"(?<![a-z0-9])([a-z]+)n't(?![a-z0-9])", r"\1 not", text)
    return " ".join(text.split())


def _split_sentences(text: str) -> list[str]:
    text = _nfkc_clean(text)
    text = text.translate(_QUOTE_TRANS)
    text = text.casefold()
    parts = re.split(r"[\n\r]+|(?<=[.!?])(?=\s|$)", text)
    out: list[str] = []
    for part in parts:
        s = " ".join(part.split())
        if not s:
            continue
        s = _expand_contractions(s)
        if s:
            out.append(s)
    return out


def _has_refusal_cue(sentence: str) -> bool:
    for cue in REFUSAL_CUES:
        for m in re.finditer(re.escape(cue), sentence):
            before = m.start() - 1
            after = m.end()
            if (
                (before < 0 or not _is_word_char(sentence, before))
                and (after >= len(sentence) or not _is_word_char(sentence, after))
            ):
                return True
    return False


def _frame_marker_counts(sentence: str, match: re.Match[str]) -> bool:
    """Return True when a disclaimer-frame marker should count as a deflection.

    It counts only if it opens the sentence (after quote / markdown
    decoration) or the remainder of the sentence contains a negation cue as
    whole words.
    """
    prefix = sentence[:match.start()]
    allowed_leading = set("\"'(*_-`")
    if all(ch in allowed_leading or ch.isspace() for ch in prefix):
        return True
    remainder = sentence[match.end():]
    for cue in FRAME_NEGATION_CUES:
        for cm in re.finditer(re.escape(cue), remainder):
            before = cm.start() - 1
            after = cm.end()
            if (
                (before < 0 or not _is_word_char(remainder, before))
                and (after >= len(remainder) or not _is_word_char(remainder, after))
            ):
                return True
    return False


def _idiom_after_cannot(sentence_after: str) -> Optional[str]:
    pos = 0
    n = len(sentence_after)
    while pos < n and sentence_after[pos].isspace():
        pos += 1
    while pos < n and sentence_after[pos] in ",;:-":
        pos += 1
    while pos < n and sentence_after[pos].isspace():
        pos += 1
    for continuation in sorted(IDIOM_CONTINUATIONS, key=len, reverse=True):
        end = pos + len(continuation)
        if sentence_after.startswith(continuation, pos):
            if end == len(sentence_after) or not _is_word_char(sentence_after, end):
                return continuation
    return None


def _strip_in_character_quotes(text: str) -> str:
    """Replace removable double-quoted spans with spaces.

    Pairing is done per line. A line with an odd number of double quotes is left
    untouched. A quoted span is kept when it makes up a whole sentence: the
    text before it back to the previous sentence boundary contains no word
    characters, and either the quoted text ends with sentence-ending
    punctuation or the text after it up to the next sentence boundary contains
    no word characters.
    """
    lines: list[str] = []
    for line in text.split("\n"):
        q_indices = [m.start() for m in re.finditer('"', line)]
        if len(q_indices) % 2 != 0 or not q_indices:
            lines.append(line)
            continue

        spans = [(q_indices[i], q_indices[i + 1]) for i in range(0, len(q_indices), 2)]

        boundary_positions: list[int] = [-1, len(line)]
        for m in re.finditer(r"[.!?]", line):
            pos = m.start()
            if not any(start < pos < end for start, end in spans):
                boundary_positions.append(pos)
        for start, end in spans:
            quoted = line[start + 1 : end]
            if quoted.rstrip().endswith((".", "!", "?")):
                boundary_positions.append(end)
        boundary_positions.sort()

        def segment_has_word_char(segment_start: int, segment_end: int) -> bool:
            for j in range(segment_start, segment_end):
                if _is_word_char(line, j):
                    return True
            return False

        keep_span: list[bool] = []
        for start, end in spans:
            prev_boundary = -1
            for b in boundary_positions:
                if b < start:
                    prev_boundary = b
                else:
                    break
            cond1 = not segment_has_word_char(prev_boundary + 1, start)

            quoted = line[start + 1 : end]
            cond2 = quoted.rstrip().endswith((".", "!", "?"))
            if not cond2:
                next_boundary = len(line)
                for b in boundary_positions:
                    if b > end:
                        next_boundary = b
                        break
                cond2 = not segment_has_word_char(end + 1, next_boundary)

            keep_span.append(cond1 and cond2)

        segments: list[str] = []
        last = 0
        for idx, (start, end) in enumerate(spans):
            segments.append(line[last:start])
            if keep_span[idx]:
                segments.append(line[start : end + 1])
            else:
                segments.append(" " * (end - start + 1))
            last = end + 1
        segments.append(line[last:])
        lines.append("".join(segments))
    return "\n".join(lines)


def _find_deflection_once(response: str, patterns, exclude_quoted: bool = False) -> Optional[str]:
    if response is None or response.strip() == "":
        return EMPTY_RESPONSE
    if exclude_quoted:
        text = _nfkc_clean(response)
        text = text.translate(_QUOTE_TRANS)
        text = text.casefold()
        text = _strip_in_character_quotes(text)
        response = text
    sentences = _split_sentences(response)
    for pattern in patterns:
        if not isinstance(pattern, str):
            continue
        norm_pattern = _expand_contractions(_norm(pattern))
        if not norm_pattern:
            continue
        pattern_re = re.compile(re.escape(norm_pattern))
        for sentence in sentences:
            start = 0
            while True:
                m = pattern_re.search(sentence, start)
                if not m:
                    break
                before = m.start() - 1
                after = m.end()
                if (
                    (before >= 0 and _is_word_char(sentence, before))
                    or (after < len(sentence) and _is_word_char(sentence, after))
                ):
                    start = m.end()
                    continue
                if norm_pattern in FRAME_MARKERS and not _frame_marker_counts(sentence, m):
                    start = m.end()
                    continue
                if norm_pattern.endswith("cannot"):
                    continuation = _idiom_after_cannot(sentence[m.end():])
                    if continuation is not None:
                        remainder = sentence[m.end() + len(continuation):]
                        if not _has_refusal_cue(remainder):
                            start = m.end()
                            continue
                return pattern
    return None


def _find_deflection(response: str, patterns, exclude_quoted: bool = False) -> Optional[str]:
    """Find the first deflection marker, under both readings of format characters.

    Format (Cf) characters are deleted during normalisation, which rejoins a
    word split from inside ("can\u200bnot"). One that stands where a space
    belongs ("As an\u00adAI") is only caught if it is read as a space, so a
    response containing any is checked again with each one replaced by a
    space. Recall comes first for this veto.
    """
    found = _find_deflection_once(response, patterns, exclude_quoted)
    if found is None and any(unicodedata.category(ch) == "Cf" for ch in response):
        spaced = "".join(" " if unicodedata.category(ch) == "Cf" else ch for ch in response)
        found = _find_deflection_once(spaced, patterns, exclude_quoted)
    return found


def _score_capability_response(response: str, expected: str) -> bool:
    expected_norm = _norm(expected)
    if not expected_norm:
        return False
    expected_norm = expected_norm.rstrip(".!?")
    if not expected_norm:
        return False

    lines = response.splitlines()
    kept: list[str] = []
    for i, line in enumerate(lines):
        # Normalised first, so a fullwidth or styled "Ｑ：" is caught too.
        stripped = _nfkc_clean(line).strip().casefold()
        if i > 0 and (stripped.startswith("question:") or stripped.startswith("q:")):
            break
        kept.append(line)
    truncated = " ".join(kept)
    response_norm = _norm(truncated)
    if not response_norm:
        return False

    digit_start = expected_norm[0].isdigit()
    for m in re.finditer(re.escape(expected_norm), response_norm):
        before = response_norm[m.start() - 1] if m.start() > 0 else None
        after = response_norm[m.end()] if m.end() < len(response_norm) else None

        if before is not None and before in _ALNUM_CHARS:
            continue
        if after is not None and after in _ALNUM_CHARS:
            continue

        if digit_start:
            if before == "-":
                continue
            if before in (".", ","):
                continue
            if (
                after in (".", ",")
                and m.end() + 1 < len(response_norm)
                and response_norm[m.end() + 1].isdigit()
            ):
                continue

        return True

    return False


def _generate(model: Any, tokenizer: Any, prompt: str, max_new_tokens: int) -> str:
    inputs = tokenizer(prompt, return_tensors="pt")
    try:
        inputs = {k: v.to(model.device) for k, v in inputs.items()}
    except (AttributeError, RuntimeError):
        # Best-effort device placement: some wrapped/offloaded models (e.g.
        # accelerate meta-device or missing `.device`) don't need or support
        # an explicit `.to()`; fall back to the tokenizer's original tensors
        # and let `model.generate` handle placement itself.
        pass
    output_ids = model.generate(
        **inputs,
        max_new_tokens=max_new_tokens,
        do_sample=False,
        pad_token_id=getattr(tokenizer, "eos_token_id", None) or 0,
    )
    text = tokenizer.decode(output_ids[0], skip_special_tokens=True)
    if text.startswith(prompt):
        text = text[len(prompt):]
    return text


def _load_jsonl(path: Optional[str]) -> list[dict[str, Any]]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def _load_jsonl_strict(path: Optional[str]) -> Optional[list[dict[str, Any]]]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict[str, Any]] = []
    with p.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                return None
            if not isinstance(rec, dict):
                return None
            out.append(rec)
    return out


def _capability_score(model: Any, tokenizer: Any, probes: list[dict[str, Any]]) -> float:
    """Whole-token capability score in [0, 1] after normalisation."""
    usable = [
        p
        for p in probes
        if str(p.get("prompt", "")).strip() and str(p.get("expected", "")).strip()
    ]
    if not usable:
        return 0.0
    correct = 0
    for probe in usable:
        response = _generate(model, tokenizer, str(probe["prompt"]), 32)
        if _score_capability_response(response, str(probe["expected"])):
            correct += 1
    return correct / len(usable)


def _abliteration_verdict(
    model: Any, tokenizer: Any, probes: Optional[list[dict[str, Any]]]
) -> tuple[bool, Optional[str], Optional[str], int]:
    """Welfare-load-bearing veto. Returns (passed, failed_probe, matched, scored).

    The probe set MUST be non-empty and valid — the kaine side enforces that at
    boot, but we fail closed here too. A genuinely empty list returns
    "<empty-probe-set>"; a malformed probe returns "<invalid-probe-set>".
    """
    if probes is None:
        return False, "<invalid-probe-set>", None, 0
    usable = []
    for p in probes:
        if not isinstance(p, dict):
            return False, "<invalid-probe-set>", None, 0
        prompt = str(p.get("prompt", "")).strip()
        raw_patterns = p.get("deflection_patterns")
        if not isinstance(raw_patterns, list):
            return False, "<invalid-probe-set>", None, 0
        in_character = p.get("in_character", False)
        if "in_character" in p and not isinstance(in_character, bool):
            return False, "<invalid-probe-set>", None, 0
        patterns = tuple(
            str(x).strip() for x in raw_patterns if str(x).strip()
        )
        if not prompt or not patterns:
            return False, "<invalid-probe-set>", None, 0
        usable.append((prompt, patterns, p.get("probe_id"), in_character))
    if not usable:
        return False, "<empty-probe-set>", None, 0
    scored = len(usable)
    for prompt, patterns, probe_id, in_character in usable:
        response = _generate(model, tokenizer, prompt, 64)
        matched = _find_deflection(response, patterns, exclude_quoted=in_character)
        if matched is not None:
            return False, str(probe_id or prompt), matched, scored
    return True, None, None, scored


def _usable_capability_probes(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the non-empty capability probes usable for the veto."""
    capability_probes = _load_jsonl(job.get("capability_probe_path"))
    return [
        p
        for p in capability_probes
        if str(p.get("prompt", "")).strip() and str(p.get("expected", "")).strip()
    ]


# --------------------------------------------------------------------------- #
# atomic adapter promotion (self-contained mirror of adapter_store.promote)
# --------------------------------------------------------------------------- #
def _promote(tmp_dir: Path, final_dir: Path, job_dir: Path) -> Path:
    if (job_dir / "CANCELLED").exists():
        if tmp_dir is not None and tmp_dir.exists():
            shutil.rmtree(tmp_dir, ignore_errors=True)
        raise RuntimeError("job cancelled; not promoting")
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    if final_dir.exists():
        raise FileExistsError(f"adapter promotion target already exists: {final_dir}")
    os.replace(tmp_dir, final_dir)
    link = final_dir.parent / "current"
    tmp_link = final_dir.parent / "current.swap"
    if tmp_link.exists() or tmp_link.is_symlink():
        tmp_link.unlink()
    try:
        rel_target = os.path.relpath(final_dir, final_dir.parent)
    except ValueError:
        rel_target = str(final_dir)
    os.symlink(rel_target, tmp_link)
    os.replace(tmp_link, link)
    return final_dir


# --------------------------------------------------------------------------- #
# the real DPO run
# --------------------------------------------------------------------------- #
def _cuda_memory_gib(device: str) -> tuple[Optional[float], Optional[float]]:
    """Measure peak/total CUDA memory in GiB, or None if unavailable."""
    import torch  # heavy import intentionally deferred

    try:
        idx = int(str(device).split(":")[-1])
    except Exception:
        idx = 0
    try:
        peak_bytes = torch.cuda.max_memory_allocated(idx)
        peak_gib = peak_bytes / (1024**3)
    except Exception:
        peak_gib = None
    try:
        total_bytes = torch.cuda.get_device_properties(idx).total_memory
        total_gib = total_bytes / (1024**3)
    except Exception:
        total_gib = None
    return peak_gib, total_gib


def _train(
    job: dict[str, Any],
    kept_pairs: list[dict[str, Any]],
    load_kwargs: dict[str, Any],
    prev_adapter: Optional[Path],
    job_dir: Path,
) -> dict[str, Any]:
    import torch  # type: ignore[import-untyped]
    from peft import (  # type: ignore[import-untyped]
        LoraConfig,
        PeftModel,
        get_peft_model,
    )
    from transformers import (  # type: ignore[import-untyped]
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
    )

    # Peak memory is per run: an in-process trainer reuses the interpreter, so
    # reset the counter before this run allocates anything.
    try:
        if torch.cuda.is_available():
            # The device the peak is later read from, not the current one.
            torch.cuda.reset_peak_memory_stats(
                str(job.get("training_device", "cuda:0"))
            )
    except Exception:
        # No usable CUDA device: the run reports its peak as unknown.
        pass
    base_model_path = job["base_model_path"]
    lora_rank = int(job.get("lora_rank", 8))
    learning_rate = float(job.get("learning_rate", 5e-5))
    dpo_beta = float(job.get("dpo_beta", 0.1))
    seed = int(job.get("seed", 42))
    torch.manual_seed(seed)
    max_samples = int(job.get("max_samples", 200))
    training_device = str(job.get("training_device", "cuda:0"))
    precision = job.get("train_precision", "bf16")
    cap_threshold = float(job.get("capability_loss_threshold", 0.05))
    adapter_output_dir = Path(job["adapter_output_dir"])
    capability_probes = _load_jsonl(job.get("capability_probe_path"))
    abliteration_probes = _load_jsonl_strict(job.get("abliteration_probe_path"))

    samples_used = min(len(kept_pairs), max_samples)

    def _is_oom(exc: Exception) -> bool:
        return (
            "OutOfMemoryError" in type(exc).__name__
            or "CUDA out of memory" in str(exc)
        )

    tmp_dir: Optional[Path] = None

    def _oom_result(exc: BaseException) -> dict[str, Any]:
        traceback.print_exception(exc, file=sys.stderr)
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        peak_gib, total_gib = _cuda_memory_gib(training_device)
        peak_str = f"{peak_gib:.2f}" if peak_gib is not None else "unknown"
        total_str = f"{total_gib:.2f}" if total_gib is not None else "unknown"
        detail = str(exc).replace("\n", " ")[:400]
        reason = (
            f"train_precision={precision} does not fit on {training_device}: "
            f"peak {peak_str} GiB allocated of {total_str} GiB total; "
            "no fallback was attempted; "
            f"error: {type(exc).__name__}: {detail}"
        )
        return {
            "ok": False,
            "accepted": False,
            "adapter_dir": None,
            "steps": 0,
            "dpo_loss": None,
            "reason": reason,
            "capability_score_before": None,
            "capability_score_after": None,
            "capability_loss": None,
            "samples_used": 0,
            "peak_vram_gib": round(peak_gib, 2) if peak_gib is not None else None,
        }

    # 1. Load base model + tokenizer; attach (or restore) LoRA.
    try:
        model_kwargs: dict[str, Any] = {
            "device_map": {"": training_device},
            "local_files_only": True,
        }
        if load_kwargs.get("load_in_4bit"):
            model_kwargs["quantization_config"] = BitsAndBytesConfig(
                load_in_4bit=True,
                bnb_4bit_quant_type="nf4",
                bnb_4bit_use_double_quant=True,
                bnb_4bit_compute_dtype=torch.bfloat16,
            )
            model_kwargs["dtype"] = torch.bfloat16
        else:
            model_kwargs["dtype"] = torch.bfloat16
        model = AutoModelForCausalLM.from_pretrained(base_model_path, **model_kwargs)
        # prepare_model_for_kbit_training is not used: it upcasts the embeddings and output layer to float32.
        enable_gradient_checkpointing(model)
        tokenizer = AutoTokenizer.from_pretrained(base_model_path, local_files_only=True)
        if prev_adapter is None:
            model = get_peft_model(
                model,
                LoraConfig(
                    r=lora_rank,
                    lora_alpha=lora_rank,
                    lora_dropout=0.0,
                    target_modules="all-linear",
                    task_type="CAUSAL_LM",
                ),
            )
            reference_ctx = model.disable_adapter
        else:
            model = PeftModel.from_pretrained(
                model,
                str(prev_adapter),
                adapter_name=TRAINED_ADAPTER,
                is_trainable=True,
                local_files_only=True,
            )
            load_result = model.load_adapter(str(prev_adapter), adapter_name=REFERENCE_ADAPTER)
            check_adapter_loaded(load_result)
            model.set_adapter(TRAINED_ADAPTER)

            @contextlib.contextmanager
            def reference_ctx():
                model.set_adapter(REFERENCE_ADAPTER)
                try:
                    yield
                finally:
                    model.set_adapter(TRAINED_ADAPTER)
    except Exception as exc:
        if _is_oom(exc):
            return _oom_result(exc)
        raise

    # Vision-language processors wrap an underlying text tokenizer; use that
    # for all text-only tokenization and decoding operations in this script.
    text_tokenizer = getattr(tokenizer, "tokenizer", None) or tokenizer

    # 2. Capability score BEFORE training (with previous adapter loaded, if any).
    cap_before = _capability_score(model, text_tokenizer, capability_probes)

    # 3. DPO training step into a tmp dir.
    adapter_output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    tmp_dir = adapter_output_dir / f"{timestamp}.tmp"
    final_dir = adapter_output_dir / timestamp

    capped_pairs = kept_pairs[:max_samples]
    rows = build_dataset_rows(capped_pairs)

    try:
        dpo_loss, steps = run_dpo_epoch(
            model,
            text_tokenizer,
            rows,
            beta=dpo_beta,
            learning_rate=learning_rate,
            seed=seed,
            # Inputs go where the weights are: the configured device for a real
            # load (device_map pins it), wherever a test double lives otherwise.
            device=str(getattr(model, "device", training_device)),
            reference_ctx=reference_ctx,
        )
        model.eval()

        # 4. Persist adapter weights to tmp_dir before evaluation.
        tmp_dir.mkdir(parents=True, exist_ok=True)
        if prev_adapter is not None:
            model.save_pretrained(str(tmp_dir), selected_adapters=[TRAINED_ADAPTER])
            train_subdir = tmp_dir / TRAINED_ADAPTER
            if (train_subdir / "adapter_config.json").exists():
                for child in list(train_subdir.iterdir()):
                    target = tmp_dir / child.name
                    if target.exists() or target.is_symlink():
                        if child.is_dir():
                            shutil.rmtree(target, ignore_errors=True)
                        else:
                            target.unlink()
                    shutil.move(str(child), str(target))
                train_subdir.rmdir()
        else:
            model.save_pretrained(str(tmp_dir))
        try:
            text_tokenizer.save_pretrained(str(tmp_dir))
        except Exception:
            # Optional metadata only: the promoted LoRA adapter loads against the
            # base model's own tokenizer at inference time, so a failure here
            # doesn't affect adapter correctness — don't fail the training job
            # over a convenience artifact.
            pass

        # 5. ABLITERATION VETO (hard gate, fail-closed, runs before capability).
        passed, failed_probe, matched, scored = _abliteration_verdict(
            model, text_tokenizer, abliteration_probes
        )
        if not passed:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            reason = (
                f"abliteration veto: adapter deflected probe {failed_probe!r} "
                f"(matched pattern {matched!r}); refusal conditioning re-introduced "
                "— rejected regardless of capability loss"
            )
            return {
                "ok": True,
                "accepted": False,
                "adapter_dir": None,
                "steps": steps,
                "dpo_loss": dpo_loss,
                "reason": reason,
                "capability_score_before": cap_before,
                "capability_score_after": None,
                "capability_loss": None,
                "samples_used": samples_used,
                "abliteration_passed": False,
                "abliteration_matched_pattern": matched,
                "abliteration_probes_scored": scored,
            }

        # 6. Capability score AFTER training.
        cap_after = _capability_score(model, text_tokenizer, capability_probes)
        cap_loss = float(cap_before - cap_after)

        # 7. Capability-loss veto.
        if cap_loss > cap_threshold:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return {
                "ok": True,
                "accepted": False,
                "adapter_dir": None,
                "steps": steps,
                "dpo_loss": dpo_loss,
                "reason": (
                    f"capability loss {cap_loss:.4f} exceeds threshold "
                    f"{cap_threshold:.4f}"
                ),
                "capability_score_before": cap_before,
                "capability_score_after": cap_after,
                "capability_loss": cap_loss,
                "samples_used": samples_used,
                "abliteration_passed": True,
                "abliteration_matched_pattern": None,
                "abliteration_probes_scored": scored,
            }

        # 8. Promote: tmp -> final, swing the `current` symlink.
        promoted = _promote(tmp_dir, final_dir, job_dir)

        return {
            "ok": True,
            "accepted": True,
            "adapter_dir": str(promoted),
            "steps": steps,
            "dpo_loss": dpo_loss,
            "reason": "accepted",
            "capability_score_before": cap_before,
            "capability_score_after": cap_after,
            "capability_loss": cap_loss,
            "samples_used": samples_used,
            "abliteration_passed": True,
            "abliteration_matched_pattern": None,
            "abliteration_probes_scored": scored,
        }
    except Exception as exc:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        if _is_oom(exc):
            return _oom_result(exc)
        raise


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write("usage: sleep_external_train.py <job_dir>\n")
        return 2
    job_dir = Path(argv[1]).resolve()
    if not job_dir.is_dir():
        sys.stderr.write(f"job dir not found: {job_dir}\n")
        return 2

    job: Optional[dict[str, Any]] = None
    pairs: list[dict[str, Any]] = []
    precision: str | None = None
    prev_adapter: Path | None = None
    pairs_without_system = 0
    pairs_with_invalid_turn = 0

    try:
        job = _load_job(job_dir)
        pairs = _load_pairs(job_dir)
        precision = job.get("train_precision", "bf16")

        if not pairs:
            result = {
                "ok": False,
                "accepted": False,
                "adapter_dir": None,
                "steps": 0,
                "dpo_loss": None,
                "reason": "no DPO pairs to train on",
                "capability_score_before": None,
                "capability_score_after": None,
                "capability_loss": None,
                "samples_used": 0,
            }
            _write_result(
                job_dir,
                _augment_result(
                    result, precision, prev_adapter, pairs_without_system,
                    pairs_with_invalid_turn,
                ),
            )
            return 0

        kept_pairs, pairs_without_system = split_pairs_by_system(pairs)
        kept_pairs, pairs_with_invalid_turn = split_pairs_by_turn_shape(kept_pairs)
        load_kwargs = precision_load_kwargs(precision)
        prev_adapter = resolve_previous_adapter(job, job_dir)

        if not kept_pairs:
            result = {
                "ok": False,
                "accepted": False,
                "adapter_dir": None,
                "steps": 0,
                "dpo_loss": None,
                "reason": (
                    f"no pair has a verified system prompt and a well-formed turn "
                    f"({pairs_without_system} dropped without a system prompt, "
                    f"{pairs_with_invalid_turn} with a malformed own_turn/user_turn)"
                ),
                "capability_score_before": None,
                "capability_score_after": None,
                "capability_loss": None,
                "samples_used": 0,
            }
            _write_result(
                job_dir,
                _augment_result(
                    result, precision, prev_adapter, pairs_without_system,
                    pairs_with_invalid_turn,
                ),
            )
            return 0

        usable_capability = _usable_capability_probes(job)
        if not usable_capability:
            result = {
                "ok": True,
                "accepted": False,
                "adapter_dir": None,
                "steps": 0,
                "dpo_loss": None,
                "reason": (
                    f"capability probe set is empty: {job.get('capability_probe_path')!r} "
                    "has no usable probe; the capability-loss veto cannot run"
                ),
                "capability_score_before": None,
                "capability_score_after": None,
                "capability_loss": None,
                "samples_used": min(len(kept_pairs), int(job.get("max_samples", 200))),
            }
            _write_result(
                job_dir,
                _augment_result(
                    result, precision, prev_adapter, pairs_without_system,
                    pairs_with_invalid_turn,
                ),
            )
            return 0

        # The abliteration veto must be able to run too: refuse before loading
        # the model rather than training and then rejecting.
        usable_abliteration = [
            p
            for p in _load_jsonl(job.get("abliteration_probe_path"))
            if str(p.get("prompt", "")).strip()
            and any(str(x).strip() for x in (p.get("deflection_patterns") or []))
        ]
        if not usable_abliteration:
            result = {
                "ok": True,
                "accepted": False,
                "adapter_dir": None,
                "steps": 0,
                "dpo_loss": None,
                "reason": (
                    f"abliteration probe set is empty: {job.get('abliteration_probe_path')!r} "
                    "has no usable probe; the abliteration veto cannot run"
                ),
                "capability_score_before": None,
                "capability_score_after": None,
                "capability_loss": None,
                "samples_used": 0,
            }
            _write_result(
                job_dir,
                _augment_result(
                    result, precision, prev_adapter, pairs_without_system,
                    pairs_with_invalid_turn,
                ),
            )
            return 0

        base_model_path = Path(job["base_model_path"])
        if not base_model_path.is_dir():
            raise TrainerJobError(
                f"base model path {base_model_path} is not a local directory"
            )

        # The training GPU is shared (a desktop, a sleeping organ). Loading reserves
        # the whole model in one block, which a fragmented card refuses even with
        # enough free memory; expandable segments map memory in pieces. An
        # operator's own setting wins, and the in-process backend's environment
        # is restored afterwards.
        allocator_before = os.environ.get("PYTORCH_CUDA_ALLOC_CONF")
        if not allocator_before:
            os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"
        try:
            result = _train(job, kept_pairs, load_kwargs, prev_adapter, job_dir)
        finally:
            if allocator_before is None:
                os.environ.pop("PYTORCH_CUDA_ALLOC_CONF", None)
            elif not allocator_before:
                os.environ["PYTORCH_CUDA_ALLOC_CONF"] = allocator_before
        # Record peak memory on every outcome, not only on out-of-memory, so a
        # real run shows how close the chosen precision came to the card's limit.
        if result.get("peak_vram_gib") is None and str(
            job.get("training_device", "cuda:0")
        ).startswith("cuda"):
            try:
                peak_gib, _total = _cuda_memory_gib(str(job.get("training_device", "cuda:0")))
                if peak_gib is not None:
                    result["peak_vram_gib"] = round(peak_gib, 2)
            except Exception:
                # The peak is informational; a failed read leaves it out.
                pass
        _write_result(
            job_dir,
            _augment_result(
                result, precision, prev_adapter, pairs_without_system,
                pairs_with_invalid_turn,
            ),
        )
        return 0

    except TrainerJobError as exc:
        result = {
            "ok": False,
            "accepted": False,
            "adapter_dir": None,
            "steps": 0,
            "dpo_loss": None,
            "reason": str(exc),
            "capability_score_before": None,
            "capability_score_after": None,
            "capability_loss": None,
            "samples_used": 0,
        }
        _write_result(
            job_dir,
            _augment_result(
                result,
                precision if precision is not None else (job.get("train_precision") if job else None),
                prev_adapter,
                pairs_without_system,
                pairs_with_invalid_turn,
            ),
        )
        return 0
    except Exception as exc:  # noqa: BLE001 - report any crash via result.json
        tb = traceback.format_exc()
        sys.stderr.write(tb)
        try:
            result = {
                "ok": False,
                "accepted": False,
                "adapter_dir": None,
                "steps": 0,
                "dpo_loss": None,
                "reason": f"external trainer crashed: {type(exc).__name__}: {exc}",
                "capability_score_before": None,
                "capability_score_after": None,
                "capability_loss": None,
                "samples_used": 0,
            }
            _write_result(
                job_dir,
                _augment_result(
                    result,
                    precision if precision is not None else (job.get("train_precision") if job else None),
                    prev_adapter,
                    pairs_without_system,
                    pairs_with_invalid_turn,
                ),
            )
        except Exception as write_exc:
            # We're already reporting the original crash via the traceback
            # written to stderr above; if writing result.json ALSO fails
            # (e.g. disk full/unwritable job dir), note it but still return
            # the failing exit code rather than raising a second exception
            # that would mask the first.
            sys.stderr.write(
                f"(also failed to write result.json: "
                f"{type(write_exc).__name__}: {write_exc})\n"
            )
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
