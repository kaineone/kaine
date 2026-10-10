#!/usr/bin/env python
# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Out-of-process SFT trainer for K1-Jev.

Runs in an external trainer interpreter (Unsloth Studio, torch 2.x,
transformers v5, peft, unsloth).  It imports NO kaine modules and keeps all
heavy dependencies inside functions so the file can be imported in a plain
Python environment for testing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import time
import traceback
from pathlib import Path
from typing import Any

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
LETTER_TO_INDEX = {ch: i for i, ch in enumerate(LETTERS)}
TARGETS = [
    "q_proj",
    "k_proj",
    "v_proj",
    "o_proj",
    "gate_proj",
    "up_proj",
    "down_proj",
    # Gated DeltaNet (linear-attention) projections in transformers v5's
    # Qwen3.5 implementation; the vision tower uses qkv/proj/linear_fc*.
    "in_proj_qkv",
    "in_proj_z",
    "in_proj_b",
    "in_proj_a",
    "out_proj",
]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="K1-Jev supervised fine-tuning trainer")
    p.add_argument("--base", required=True, help="Local path or HF id of the base model")
    p.add_argument("--train", required=True, help="Training JSONL")
    p.add_argument("--dev", required=True, help="Development JSONL")
    p.add_argument("--out", required=True, help="Output directory")
    p.add_argument("--rank", type=int, default=8)
    p.add_argument("--alpha", type=int, default=16)
    p.add_argument("--lr", type=float, default=5e-5)
    p.add_argument("--batch", type=int, default=8)
    p.add_argument("--epochs", type=int, default=1)
    p.add_argument("--max-len", type=int, default=2048)
    p.add_argument("--warmup", type=float, default=0.03)
    p.add_argument("--seed", type=int, default=20261005)
    p.add_argument("--checkpoint-every-min", type=int, default=30)
    p.add_argument("--resume", action="store_true")
    p.add_argument("--max-minutes", type=int, default=0, help="0 = no limit")
    p.add_argument("--device", default="cuda:0")
    return p.parse_args(argv)


def entity_running(
    *,
    docker_argv_runner: Any = None,
    proc_root: Path = Path("/proc"),
    self_pid: int | None = None,
) -> str | None:
    """Return a reason string if an entity run looks active, else None.

    Arguments are injected so tests can fake docker and /proc.
    """
    if self_pid is None:
        self_pid = os.getpid()

    # (a) docker container named kaine-cycle
    if docker_argv_runner is None:
        def _default_docker(argv: list[str]) -> str:
            proc = subprocess.run(
                argv,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                # A daemon that is down or refuses us says nothing about
                # whether an entity runs: treat it as unknown (fail closed).
                raise RuntimeError(f"docker ps exited {proc.returncode}")
            return proc.stdout

        docker_argv_runner = _default_docker

    docker_out: str | None = None
    try:
        docker_out = docker_argv_runner(
            [
                "docker",
                "ps",
                "--filter",
                "name=^kaine-cycle$",
                "--format",
                "{{.Names}}",
            ]
        )
    except FileNotFoundError:
        pass  # no docker on this host: only the /proc check applies
    except Exception as exc:  # cannot tell, so do not train
        return f"cannot check for a running entity container: {type(exc).__name__}: {exc}"

    if docker_out is not None and docker_out.strip():
        return f"entity running: docker container {docker_out.strip()!r}"

    # (b) /proc scan for kaine.cycle
    if proc_root.exists():
        for pid_dir in proc_root.iterdir():
            if not pid_dir.is_dir() or not pid_dir.name.isdigit():
                continue
            pid = int(pid_dir.name)
            if pid == self_pid:
                continue
            cmdline_path = pid_dir / "cmdline"
            if not cmdline_path.exists():
                continue
            try:
                raw = cmdline_path.read_bytes()
            except OSError:
                continue
            args = [arg for arg in raw.decode("utf-8", errors="ignore").split("\x00") if arg]
            for i in range(len(args) - 1):
                if args[i] == "-m" and args[i + 1] == "kaine.cycle":
                    return f"entity running: kaine.cycle pid {pid}"
            for arg in args:
                if arg.endswith("kaine/cycle/__main__.py"):
                    return f"entity running: kaine cycle __main__ pid {pid}"

    return None


def letter_index(answer: str) -> int:
    return LETTER_TO_INDEX[answer]


def load_examples(path: Path) -> list[dict]:
    """Load and validate a JSONL file of K1-Jev training examples."""
    required = {"prompt", "answer", "n_options", "source", "question_id"}
    examples: list[dict] = []
    with path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"line {line_num}: invalid JSON: {exc}") from exc
            if not isinstance(record, dict):
                raise ValueError(f"line {line_num}: record is not an object")
            missing = required - record.keys()
            if missing:
                raise ValueError(f"line {line_num}: missing keys {sorted(missing)}")
            prompt = record["prompt"]
            if not isinstance(prompt, str) or not prompt.strip():
                raise ValueError(f"line {line_num}: prompt must be a non-empty string")
            answer = record["answer"]
            n_options = record["n_options"]
            if not isinstance(answer, str) or len(answer) != 1 or answer not in LETTERS:
                raise ValueError(f"line {line_num}: answer must be a single option letter")
            if not isinstance(n_options, int) or n_options < 1 or n_options > 52:
                raise ValueError(f"line {line_num}: n_options must be an integer 1..52")
            if letter_index(answer) >= n_options:
                raise ValueError(
                    f"line {line_num}: answer {answer!r} is not within n_options={n_options}"
                )
            examples.append(record)
    return examples


def check_prompt_lengths(split: str, token_lengths: list[int], max_len: int) -> None:
    """Refuse a split with an empty or over-long prompt; prompts are never truncated."""
    empty = [i for i, length in enumerate(token_lengths) if length == 0]
    over_long = [i for i, length in enumerate(token_lengths) if length > max_len]
    if empty or over_long:
        longest = max(token_lengths) if token_lengths else 0
        raise ValueError(
            f"{split}: found {len(empty)} empty and {len(over_long)} over-long prompts "
            f"(max_len={max_len}, longest={longest}); "
            f"offending indices (first 10): {sorted(empty + over_long)[:10]}"
        )


def bucket_batches(lengths: list[int], batch: int, seed: int) -> list[list[int]]:
    """Deterministically group indices into length-batched batches."""
    if not lengths or batch <= 0:
        return []
    rng = random.Random(seed)
    by_length: dict[int, list[int]] = {}
    for idx, length in enumerate(lengths):
        by_length.setdefault(length, []).append(idx)

    for bucket in by_length.values():
        rng.shuffle(bucket)

    # Batch in length order so each batch holds similar lengths (little
    # padding), then shuffle the order of whole batches.
    order: list[int] = []
    for length in sorted(by_length.keys()):
        order.extend(by_length[length])
    batches = [order[i : i + batch] for i in range(0, len(order), batch)]
    rng.shuffle(batches)
    return batches


def left_pad_batch(encoded: list[list[int]], pad_id: int) -> tuple[list[list[int]], list[list[int]]]:
    """Pad on the left to the longest sequence in the batch (never to a fixed
    max length), so every sequence's last real token sits at position -1."""
    batch_len = max(len(ids) for ids in encoded)
    input_ids = [[pad_id] * (batch_len - len(ids)) + ids for ids in encoded]
    mask = [[0] * (batch_len - len(ids)) + [1] * len(ids) for ids in encoded]
    return input_ids, mask


def warmup_steps(total_steps: int, warmup: float) -> int:
    return int(math.ceil(warmup * total_steps))


def option_loss(option_logits_rows, answer_indices):
    """Cross-entropy over option-letter logits.

    Accepts either a 2-D torch.Tensor (all rows have the same option count)
    or an iterable of 1-D row tensors with mixed option counts.
    """
    import torch
    import torch.nn.functional as F

    if isinstance(option_logits_rows, torch.Tensor):
        if not isinstance(answer_indices, torch.Tensor):
            answer_indices = torch.tensor(answer_indices, dtype=torch.long, device=option_logits_rows.device)
        else:
            answer_indices = answer_indices.to(option_logits_rows.device).long()
        return F.cross_entropy(option_logits_rows, answer_indices)

    losses = []
    for row, idx in zip(option_logits_rows, answer_indices):
        target = torch.tensor([idx], dtype=torch.long, device=row.device)
        losses.append(F.cross_entropy(row.unsqueeze(0), target))
    return torch.stack(losses).mean()


def refuse_out_path(out: Path) -> Path:
    """Reject output paths inside the repository checkout: model artifacts go
    outside it (on the bulk data drive), and never near entity state."""
    repo_root = Path(__file__).resolve().parents[2]
    resolved = out.resolve()
    if resolved == repo_root or repo_root in resolved.parents:
        raise ValueError(f"Refusing --out inside the repository: {out}")
    return resolved


def read_data_manifest(train_path: Path) -> dict:
    """The assembled-data manifest beside the training file. It names the
    schema the data was built from, which the run record must carry so a
    trained model is never served against a different schema."""
    manifest_path = train_path.parent / "manifest.json"
    if not manifest_path.exists():
        raise ValueError(f"no data manifest beside {train_path} (expected {manifest_path})")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for key in ("schema_version", "schema_digest"):
        if key not in manifest:
            raise ValueError(f"data manifest {manifest_path} lacks {key!r}")
    return manifest


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_head(repo_root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except Exception:
        return None


def _latest_checkpoint(out: Path) -> Path | None:
    cp_root = out / "checkpoints"
    if not cp_root.exists():
        return None
    dirs = [d for d in cp_root.iterdir() if d.is_dir() and d.name.startswith("step-")]
    if not dirs:
        return None

    def step_number(d: Path) -> int:
        return int(d.name.split("-", 1)[1])

    return max(dirs, key=step_number)


def _prune_old_checkpoints(out: Path, keep: int = 2) -> None:
    import shutil

    cp_root = out / "checkpoints"
    if not cp_root.exists():
        return
    dirs = sorted(
        (d for d in cp_root.iterdir() if d.is_dir() and d.name.startswith("step-")),
        key=lambda d: int(d.name.split("-", 1)[1]),
    )
    for old in dirs[:-keep]:
        shutil.rmtree(old, ignore_errors=True)


def _save_checkpoint(
    out: Path,
    step: int,
    model,
    optimizer,
    scheduler,
    data_order_seed: int,
    total_steps: int,
) -> Path:
    import shutil

    import torch

    cp_dir = out / "checkpoints" / f"step-{step}"
    if cp_dir.exists():
        shutil.rmtree(cp_dir, ignore_errors=True)
    cp_dir.mkdir(parents=True, exist_ok=True)

    model.save_pretrained(str(cp_dir))

    state = {
        "step": step,
        "total_steps": total_steps,
        "data_order_seed": data_order_seed,
        "optimizer": optimizer.state_dict(),
        "scheduler": scheduler.state_dict(),
        "random_state": random.getstate(),
        "rng_state": torch.get_rng_state(),
    }
    torch.save(state, cp_dir / "trainer_state.pt")
    _prune_old_checkpoints(out, keep=2)
    return cp_dir


def train(
    base: str,
    train_path: Path,
    dev_path: Path,
    out: Path,
    rank: int,
    alpha: int,
    lr: float,
    batch_size: int,
    epochs: int,
    max_len: int,
    warmup: float,
    seed: int,
    checkpoint_every_min: int,
    resume: bool,
    max_minutes: int,
    device: str,
    train_sha: str,
    dev_sha: str,
) -> dict:
    """Run SFT training and return the metrics dict for run.json."""
    import shutil

    import torch
    import torch.nn.functional as F
    from transformers import get_cosine_schedule_with_warmup, set_seed
    from unsloth import FastLanguageModel

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    set_seed(seed)
    random.seed(seed)
    torch.manual_seed(seed)

    train_ex = load_examples(train_path)
    dev_ex = load_examples(dev_path)

    model, tokenizer = FastLanguageModel.from_pretrained(
        base,
        dtype=torch.bfloat16,
        load_in_4bit=False,
        max_seq_length=max_len,
        local_files_only=True,
        device_map={"": device},
    )

    text_tokenizer = getattr(tokenizer, "tokenizer", None) or tokenizer
    train_lengths = [
        len(text_tokenizer.encode(ex["prompt"], add_special_tokens=False))
        for ex in train_ex
    ]
    dev_lengths = [
        len(text_tokenizer.encode(ex["prompt"], add_special_tokens=False))
        for ex in dev_ex
    ]
    check_prompt_lengths("train", train_lengths, max_len)
    check_prompt_lengths("dev", dev_lengths, max_len)
    pad_token_id = text_tokenizer.pad_token_id
    if pad_token_id is None:
        pad_token_id = text_tokenizer.eos_token_id
    if pad_token_id is None:
        pad_token_id = 0

    # Pre-compute single-token ids for option letters.
    letter_ids: list[int] = []
    for ch in LETTERS:
        ids = text_tokenizer.encode(ch, add_special_tokens=False)
        if len(ids) != 1:
            raise RuntimeError(f"letter {ch!r} tokenizes to {len(ids)} tokens, expected 1")
        letter_ids.append(ids[0])

    model = FastLanguageModel.get_peft_model(
        model,
        r=rank,
        lora_alpha=alpha,
        lora_dropout=0,
        target_modules=TARGETS,
        use_gradient_checkpointing="unsloth",
        random_state=seed,
    )

    lora_names = [name for name, module in model.named_modules() if hasattr(module, "lora_A")]
    for name in lora_names:
        if "visual" in name or "vision" in name:
            raise RuntimeError(f"LoRA module attached to vision tower: {name}")
    for target in TARGETS:
        if not any(name.endswith("." + target) for name in lora_names):
            raise RuntimeError(f"LoRA target {target!r} matched no module in {base}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr)

    lengths = train_lengths

    data_order_seed = seed
    start_step = 0

    if resume:
        cp_dir = _latest_checkpoint(out)
        if cp_dir is not None:
            state = torch.load(cp_dir / "trainer_state.pt", map_location="cpu")
            data_order_seed = state.get("data_order_seed", seed)
            start_step = state.get("step", 0)

            # Load adapter weights into the freshly-created default adapter.
            adapter_file = cp_dir / "adapter_model.safetensors"
            if not adapter_file.exists():
                adapter_file = cp_dir / "adapter_model.bin"
            if adapter_file.exists():
                if str(adapter_file).endswith(".safetensors"):
                    from safetensors.torch import load_file

                    adapter_weights = load_file(str(adapter_file))
                else:
                    adapter_weights = torch.load(adapter_file, map_location="cpu")
                from peft import set_peft_model_state_dict

                set_peft_model_state_dict(model, adapter_weights, adapter_name="default")

            optimizer.load_state_dict(state["optimizer"])
            # The scheduler is created below and loads its state there.

            if "random_state" in state:
                random.setstate(state["random_state"])
            if "rng_state" in state and state["rng_state"] is not None:
                torch.set_rng_state(state["rng_state"])
        else:
            resume = False

    all_batches: list[list[int]] = []
    for epoch in range(epochs):
        all_batches.extend(bucket_batches(lengths, batch_size, data_order_seed + epoch))
    total_steps = len(all_batches)

    scheduler = get_cosine_schedule_with_warmup(
        optimizer,
        num_warmup_steps=warmup_steps(total_steps, warmup),
        num_training_steps=total_steps,
    )

    if resume and cp_dir is not None:
        state = torch.load(cp_dir / "trainer_state.pt", map_location="cpu")
        if "scheduler" in state:
            scheduler.load_state_dict(state["scheduler"])

    model.train()

    start_time = time.time()
    last_checkpoint_time = start_time
    loss_sum = 0.0
    step = start_step

    status = "completed"
    device_type = device.split(":")[0] if ":" in device else device

    for step_idx in range(start_step, total_steps):
        batch_indices = all_batches[step_idx]
        batch_examples = [train_ex[i] for i in batch_indices]

        input_ids_list = []
        attn_mask_list = []
        n_options_list = []
        answer_indices_list = []

        encoded = []
        for ex in batch_examples:
            ids = text_tokenizer.encode(
                ex["prompt"],
                add_special_tokens=False,
            )
            encoded.append(ids)
            n_options_list.append(ex["n_options"])
            answer_indices_list.append(letter_index(ex["answer"]))
        input_ids_list, attn_mask_list = left_pad_batch(encoded, pad_token_id)

        input_ids = torch.tensor(input_ids_list, dtype=torch.long, device=device)
        attention_mask = torch.tensor(attn_mask_list, dtype=torch.long, device=device)

        with torch.autocast(device_type=device_type, dtype=torch.bfloat16):
            # Only the last position's logits are needed; materialising the
            # whole sequence would cost B x L x vocab in memory.
            outputs = model(
                input_ids=input_ids, attention_mask=attention_mask, logits_to_keep=1
            )
            logits = outputs.logits  # [B, 1, vocab]

        option_logits = []
        for i, n_opt in enumerate(n_options_list):
            option_logits.append(logits[i, -1, letter_ids[:n_opt]])

        loss = option_loss(option_logits, answer_indices_list)
        loss.backward()

        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        scheduler.step()
        optimizer.zero_grad()

        step = step_idx + 1
        loss_sum += loss.item()

        # Periodic checkpoint.
        if checkpoint_every_min > 0:
            elapsed_since_cp = time.time() - last_checkpoint_time
            if elapsed_since_cp >= checkpoint_every_min * 60:
                _save_checkpoint(
                    out,
                    step,
                    model,
                    optimizer,
                    scheduler,
                    data_order_seed,
                    total_steps,
                )
                last_checkpoint_time = time.time()

        # Time-bounded training window.
        if max_minutes > 0 and (time.time() - start_time) >= max_minutes * 60:
            _save_checkpoint(
                out,
                step,
                model,
                optimizer,
                scheduler,
                data_order_seed,
                total_steps,
            )
            status = "paused"
            break

    session_steps = step - start_step
    final_train_loss = loss_sum / session_steps if session_steps > 0 else None

    # Dev evaluation (up to 2,000 examples), only once training is complete;
    # a paused chunk saves its GPU time for training.
    dev_subset = dev_ex[:2000] if status == "completed" else []
    dev_losses = []
    dev_correct = 0
    model.eval()
    with torch.no_grad():
        for ex in dev_subset:
            ids = text_tokenizer.encode(
                ex["prompt"],
                add_special_tokens=False,
            )
            input_ids = torch.tensor([ids], dtype=torch.long, device=device)
            attention_mask = torch.tensor([[1] * len(ids)], dtype=torch.long, device=device)

            with torch.autocast(device_type=device_type, dtype=torch.bfloat16):
                outputs = model(
                    input_ids=input_ids, attention_mask=attention_mask, logits_to_keep=1
                )

            n_opt = ex["n_options"]
            opt_logits = outputs.logits[0, -1, letter_ids[:n_opt]]
            ans_idx = letter_index(ex["answer"])
            dev_losses.append(
                F.cross_entropy(
                    opt_logits.unsqueeze(0),
                    torch.tensor([ans_idx], device=device),
                ).item()
            )
            if opt_logits.argmax().item() == ans_idx:
                dev_correct += 1

    dev_loss = sum(dev_losses) / len(dev_losses) if dev_losses else None
    dev_accuracy = dev_correct / len(dev_subset) if dev_subset else None

    # Final outputs when training finished.
    merge_errors: list[str] = []
    if status == "completed":
        adapter_dir = out / "adapter"
        adapter_dir.mkdir(parents=True, exist_ok=True)
        model.save_pretrained(str(adapter_dir))

        merged_dir = out / "merged"
        merged_dir.mkdir(parents=True, exist_ok=True)
        try:
            model.save_pretrained_merged(str(merged_dir), text_tokenizer, save_method="merged_16bit")
        except Exception as exc:
            merge_errors.append(f"save_pretrained_merged: {type(exc).__name__}: {exc}")
            try:
                merged = model.merge_and_unload()
                merged.save_pretrained(str(merged_dir))
                text_tokenizer.save_pretrained(str(merged_dir))
            except Exception as exc2:
                merge_errors.append(f"merge_and_unload: {type(exc2).__name__}: {exc2}")
                shutil.rmtree(merged_dir, ignore_errors=True)
                # The adapter is saved, but without a merged model the export
                # step cannot run: report it as a failure, never as complete.
                status = "merge_failed"

    base_rev = None
    config = getattr(model, "config", None)
    if config is not None:
        base_rev = getattr(config, "_commit_hash", None)

    elapsed = time.time() - start_time

    return {
        "status": status,
        "merge_errors": merge_errors,
        "base": base,
        "base_revision": base_rev,
        "hyperparameters": {
            "rank": rank,
            "alpha": alpha,
            "lr": lr,
            "batch": batch_size,
            "epochs": epochs,
            "max_len": max_len,
            "warmup": warmup,
            "seed": seed,
            "device": device,
            "checkpoint_every_min": checkpoint_every_min,
            "max_minutes": max_minutes,
        },
        "seed": seed,
        "data_order_seed": data_order_seed,
        "train_sha256": train_sha,
        "dev_sha256": dev_sha,
        "steps_completed": step,
        "total_steps": total_steps,
        "final_train_loss": final_train_loss,
        "dev_loss": dev_loss,
        "dev_accuracy": dev_accuracy,
        "elapsed_seconds": elapsed,
        "git_head": _git_head(Path(__file__).resolve().parents[2]),
    }


def _write_run_json(out: Path, metrics: dict) -> None:
    with (out / "run.json").open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, default=str)


def main(argv: list[str] | None = None) -> None:
    # Running-entity guard comes first, before any heavy import.
    reason = entity_running()
    if reason:
        print(f"entity_running: {reason}", file=sys.stderr)
        sys.exit(3)

    args = parse_args(argv)

    repo_root = Path(__file__).resolve().parents[2]
    out = Path(args.out)

    try:
        out = refuse_out_path(out)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)

    train_path = Path(args.train)
    dev_path = Path(args.dev)
    if not train_path.exists() or not dev_path.exists():
        print("error: --train and --dev must exist", file=sys.stderr)
        sys.exit(2)

    try:
        # Validate examples and the data manifest before touching the GPU stack.
        _ = load_examples(train_path)
        _ = load_examples(dev_path)
        data_manifest = read_data_manifest(train_path)
    except ValueError as exc:
        print(f"error loading examples: {exc}", file=sys.stderr)
        sys.exit(2)

    train_sha = _sha256_file(train_path)
    dev_sha = _sha256_file(dev_path)

    out.mkdir(parents=True, exist_ok=True)

    # No network access.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    start_time = time.time()
    try:
        metrics = train(
            base=args.base,
            train_path=train_path,
            dev_path=dev_path,
            out=out,
            rank=args.rank,
            alpha=args.alpha,
            lr=args.lr,
            batch_size=args.batch,
            epochs=args.epochs,
            max_len=getattr(args, "max_len"),
            warmup=args.warmup,
            seed=args.seed,
            checkpoint_every_min=args.checkpoint_every_min,
            resume=args.resume,
            max_minutes=args.max_minutes,
            device=args.device,
            train_sha=train_sha,
            dev_sha=dev_sha,
        )
    except Exception as exc:  # noqa: BLE001
        elapsed = time.time() - start_time
        failed_metrics = {
            "status": "failed",
            "base": args.base,
            "base_revision": None,
            "reason": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
            "hyperparameters": {
                "rank": args.rank,
                "alpha": args.alpha,
                "lr": args.lr,
                "batch": args.batch,
                "epochs": args.epochs,
                "max_len": getattr(args, "max_len"),
                "warmup": args.warmup,
                "seed": args.seed,
                "device": args.device,
                "checkpoint_every_min": args.checkpoint_every_min,
                "max_minutes": args.max_minutes,
            },
            "seed": args.seed,
            "train_sha256": train_sha,
            "dev_sha256": dev_sha,
            "steps_completed": 0,
            "total_steps": 0,
            "final_train_loss": None,
            "dev_loss": None,
            "dev_accuracy": None,
            "elapsed_seconds": elapsed,
            "git_head": _git_head(repo_root),
        }
        failed_metrics["schema_version"] = data_manifest["schema_version"]
        failed_metrics["schema_digest"] = data_manifest["schema_digest"]
        _write_run_json(out, failed_metrics)
        print(traceback.format_exc(), file=sys.stderr)
        sys.exit(1)

    metrics["schema_version"] = data_manifest["schema_version"]
    metrics["schema_digest"] = data_manifest["schema_digest"]
    _write_run_json(out, metrics)
    # A run whose merged model could not be written is not usable for export.
    sys.exit(1 if metrics.get("status") == "merge_failed" else 0)


if __name__ == "__main__":
    main()
