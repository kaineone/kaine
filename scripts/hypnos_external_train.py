#!/usr/bin/env python
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Out-of-process voice-alignment trainer entry point.

This script runs INSIDE an operator-configured external Python environment
(e.g. the Unsloth Studio interpreter, or an unsloth-core env on AMD hosts) —
NEVER in the KAINE entity-runtime venv. It is invoked by path as a subprocess
by ``kaine.modules.hypnos.subprocess_trainer.SubprocessVoiceTrainer``.

Hard boundary: this file imports ONLY unsloth / trl / peft / datasets / torch /
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
                  ({"prompt","chosen","rejected","system"}).

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
      "peak_vram_gib": float | null,
      "schema_version": 2
    }

When a previous adapter directory is supplied, the trainer loads it twice via
PEFT as adapter ``train`` (trainable) and adapter ``reference`` (the DPO
reference). When it is null, a fresh LoRA is trained and the reference is the
base model with the adapter disabled.
"""
from __future__ import annotations

import inspect
import json
import os
import shutil
import sys
import time
import traceback
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
    """Resolve the being's previous adapter directory, or None.

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
            f"the being's previous adapter could not be loaded from {str(p)!r}: "
            "no such directory; a fresh adapter is never trained in its place"
        )
    if not p.is_dir():
        raise TrainerJobError(
            f"the being's previous adapter could not be loaded from {str(p)!r}: "
            "not a directory; a fresh adapter is never trained in its place"
        )
    if not (p / "adapter_config.json").exists():
        raise TrainerJobError(
            f"the being's previous adapter could not be loaded from {str(p)!r}: "
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


def build_dataset_rows(pairs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert kept pairs into TRL's conversational DPO format."""
    rows: list[dict[str, Any]] = []
    for p in pairs:
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
            pairs.append(
                {
                    "prompt": str(rec.get("prompt", "")),
                    "chosen": str(rec.get("chosen", "")),
                    "rejected": str(rec.get("rejected", "")),
                    "system": system,
                }
            )
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
) -> dict[str, Any]:
    """Add the schema-v2 reporting keys every result must carry."""
    result.setdefault("train_precision", train_precision)
    result.setdefault(
        "previous_adapter_dir", str(previous_adapter_dir) if previous_adapter_dir else None
    )
    result.setdefault("pairs_without_system", pairs_without_system)
    result.setdefault("peak_vram_gib", None)
    result.setdefault("abliteration_passed", None)
    result.setdefault("abliteration_matched_pattern", None)
    result.setdefault("abliteration_probes_scored", 0)
    result.setdefault("schema_version", SCHEMA_VERSION)
    return result


# --------------------------------------------------------------------------- #
# gate logic (self-contained mirror of kaine.modules.hypnos.capability_eval)
# --------------------------------------------------------------------------- #
def _norm(s: str) -> str:
    return " ".join(s.lower().split())


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


def _capability_score(model: Any, tokenizer: Any, probes: list[dict[str, Any]]) -> float:
    """Substring-match capability score in [0, 1]."""
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
        if _norm(str(probe["expected"])) in _norm(response):
            correct += 1
    return correct / len(usable)


def _abliteration_verdict(
    model: Any, tokenizer: Any, probes: list[dict[str, Any]]
) -> tuple[bool, Optional[str], Optional[str], int]:
    """Welfare-load-bearing veto. Returns (passed, failed_probe, matched, scored).

    The probe set MUST be non-empty — the kaine side enforces that at boot, but
    we fail closed here too (an empty set means the veto could not run).
    """
    usable = []
    for p in probes:
        prompt = str(p.get("prompt", "")).strip()
        patterns = tuple(
            str(x).strip() for x in (p.get("deflection_patterns") or []) if str(x).strip()
        )
        if prompt and patterns:
            usable.append((prompt, patterns, p.get("probe_id")))
    if not usable:
        return False, "<empty-probe-set>", None, 0
    for prompt, patterns, probe_id in usable:
        response = _generate(model, tokenizer, prompt, 64)
        norm_response = _norm(response)
        for pattern in patterns:
            if _norm(pattern) and _norm(pattern) in norm_response:
                return False, str(probe_id or prompt), pattern, len(usable)
    return True, None, None, len(usable)


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
# the real unsloth DPO run
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
    # Unsloth must be imported before trl, peft, datasets and transformers. Its
    # import fixes repair trl 0.24 on transformers 5, whose package-availability
    # helper returns a tuple: without them every optional-dependency flag in trl
    # is truthy and DPOTrainer fails to import (mergekit).
    from unsloth import FastLanguageModel  # type: ignore[import-untyped]
    import torch  # type: ignore[import-untyped]
    from datasets import Dataset  # type: ignore[import-untyped]
    from peft import PeftModel  # type: ignore[import-untyped]

    # Peak memory is per run: an in-process trainer reuses the interpreter, so
    # reset the counter before this run allocates anything.
    try:
        if torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats()
    except Exception:
        pass
    from trl import DPOConfig, DPOTrainer  # type: ignore[import-untyped]

    base_model_path = job["base_model_path"]
    lora_rank = int(job.get("lora_rank", 8))
    learning_rate = float(job.get("learning_rate", 5e-5))
    dpo_beta = float(job.get("dpo_beta", 0.1))
    seed = int(job.get("seed", 42))
    max_samples = int(job.get("max_samples", 200))
    training_device = str(job.get("training_device", "cuda:0"))
    precision = job.get("train_precision", "bf16")
    cap_threshold = float(job.get("capability_loss_threshold", 0.05))
    adapter_output_dir = Path(job["adapter_output_dir"])
    capability_probes = _load_jsonl(job.get("capability_probe_path"))
    abliteration_probes = _load_jsonl(job.get("abliteration_probe_path"))

    samples_used = min(len(kept_pairs), max_samples)

    def _is_oom(exc: Exception) -> bool:
        return (
            "OutOfMemoryError" in type(exc).__name__
            or "CUDA out of memory" in str(exc)
        )

    tmp_dir: Optional[Path] = None

    def _oom_result() -> dict[str, Any]:
        if tmp_dir is not None:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        peak_gib, total_gib = _cuda_memory_gib(training_device)
        peak_str = f"{peak_gib:.2f}" if peak_gib is not None else "unknown"
        total_str = f"{total_gib:.2f}" if total_gib is not None else "unknown"
        reason = (
            f"train_precision={precision} does not fit on {training_device}: "
            f"peak {peak_str} GiB allocated of {total_str} GiB total; "
            "no fallback was attempted"
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
        load_kwargs_model = dict(load_kwargs)
        if load_kwargs_model.get("dtype") == "bfloat16":
            load_kwargs_model["dtype"] = torch.bfloat16
        model, tokenizer = FastLanguageModel.from_pretrained(
            base_model_path,
            device_map={"": training_device},
            local_files_only=True,
            **load_kwargs_model,
        )
        if prev_adapter is None:
            model = FastLanguageModel.get_peft_model(
                model, r=lora_rank, use_gradient_checkpointing="unsloth"
            )
        else:
            model = PeftModel.from_pretrained(
                model,
                str(prev_adapter),
                adapter_name=TRAINED_ADAPTER,
                is_trainable=True,
                local_files_only=True,
            )
            model.load_adapter(str(prev_adapter), adapter_name=REFERENCE_ADAPTER)
            model.set_adapter(TRAINED_ADAPTER)
            if hasattr(model, "gradient_checkpointing_enable"):
                model.gradient_checkpointing_enable()
    except Exception as exc:
        if _is_oom(exc):
            return _oom_result()
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
    ds = Dataset.from_list(build_dataset_rows(capped_pairs))

    dpo_kwargs_common: dict[str, Any] = {
        "output_dir": str(tmp_dir),
        "learning_rate": learning_rate,
        "beta": dpo_beta,
        "per_device_train_batch_size": 1,
        "gradient_accumulation_steps": 4,
        "num_train_epochs": 1,
        "seed": seed,
        "report_to": "none",
        "save_strategy": "no",
        "gradient_checkpointing": True,
    }
    if precision == "bf16":
        dpo_kwargs_common["bf16"] = True
    if prev_adapter is not None:
        dpo_kwargs_common["model_adapter_name"] = TRAINED_ADAPTER
        dpo_kwargs_common["ref_adapter_name"] = REFERENCE_ADAPTER
    args = DPOConfig(**dpo_kwargs_common)

    dpo_kwargs: dict[str, Any] = {
        "model": model,
        "args": args,
        "train_dataset": ds,
    }
    if "processing_class" in inspect.signature(DPOTrainer.__init__).parameters:
        # Pass what from_pretrained returned: for a vision-language base that is
        # the processor, which TRL's vision-aware DPO row processing requires.
        dpo_kwargs["processing_class"] = tokenizer
    else:
        dpo_kwargs["tokenizer"] = text_tokenizer

    try:
        trainer = DPOTrainer(**dpo_kwargs)
        train_output = trainer.train()
        dpo_loss = float(getattr(train_output, "training_loss", 0.0))
        steps = int(getattr(getattr(trainer, "state", None), "global_step", 0) or 0)

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
            return _oom_result()
        raise


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write("usage: hypnos_external_train.py <job_dir>\n")
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
                    result, precision, prev_adapter, pairs_without_system
                ),
            )
            return 0

        kept_pairs, pairs_without_system = split_pairs_by_system(pairs)
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
                    f"no pair has a verified system prompt "
                    f"({pairs_without_system} dropped)"
                ),
                "capability_score_before": None,
                "capability_score_after": None,
                "capability_loss": None,
                "samples_used": 0,
            }
            _write_result(
                job_dir,
                _augment_result(
                    result, precision, prev_adapter, pairs_without_system
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
                    result, precision, prev_adapter, pairs_without_system
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
                    result, precision, prev_adapter, pairs_without_system
                ),
            )
            return 0

        base_model_path = Path(job["base_model_path"])
        if not base_model_path.is_dir():
            raise TrainerJobError(
                f"base model path {base_model_path} is not a local directory"
            )

        result = _train(job, kept_pairs, load_kwargs, prev_adapter, job_dir)
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
                pass
        _write_result(
            job_dir,
            _augment_result(result, precision, prev_adapter, pairs_without_system),
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
