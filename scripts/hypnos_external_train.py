#!/usr/bin/env python
# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Out-of-process voice-alignment trainer entry point.

This script runs INSIDE an operator-configured external Python environment
(e.g. the Unsloth Studio interpreter, or an unsloth-core env on AMD hosts) —
NEVER in the KAINE entity-runtime venv. It is invoked by path as a subprocess
by ``kaine.modules.hypnos.subprocess_trainer.SubprocessVoiceTrainer``.

Hard boundary: this file imports ONLY unsloth / trl / peft / datasets / the
standard library. It MUST NOT import ``kaine`` — the runtime import-linter
contracts depend on it staying out of the ``kaine`` import graph, and the two
environments share nothing but the filesystem (different Python ABI, different
torch/CUDA). Keep all logic self-contained here.

IPC contract (filesystem job spec — see
``openspec/changes/external-unsloth-trainer/design.md``):

  argv[1] = job directory. It contains:
    job.json    — base-model reference, LoRA/DPO hyper-params, the adapter
                  output dir, capability + abliteration probe sets, a schema
                  version.
    pairs.jsonl — the DPO preference pairs ({"prompt","chosen","rejected"}).

  On completion this script writes ``<job_dir>/result.json``:
    {
      "ok": bool,                 # true iff an adapter was trained+promoted
      "adapter_dir": str | null,  # promoted adapter dir (the kaine side reads
                                  # back this path)
      "steps": int,
      "dpo_loss": float | null,
      "reason": str,              # "accepted" or the rejection/failure reason
      # gate verdicts so the kaine side can populate TrainingResult unchanged:
      "accepted": bool,
      "capability_score_before": float | null,
      "capability_score_after": float | null,
      "capability_loss": float | null,
      "samples_used": int,
      "schema_version": int
    }

The two welfare/capability gates run HERE because the loaded model only exists
in this process. The gate logic mirrors
``kaine/modules/hypnos/capability_eval.py`` and ``adapter_store.py`` but is
re-implemented self-contained (no kaine import). The exit code is 0 on a clean
run (whether or not the adapter was accepted) and non-zero only on a crash that
prevented writing a result — but the kaine side treats BOTH a non-zero exit and
``ok == false`` / a missing adapter as a hard failure and never fabricates a
success.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any, Optional

SCHEMA_VERSION = 1


# --------------------------------------------------------------------------- #
# job / pairs IO
# --------------------------------------------------------------------------- #
def _load_job(job_dir: Path) -> dict[str, Any]:
    return json.loads((job_dir / "job.json").read_text(encoding="utf-8"))


def _load_pairs(job_dir: Path) -> list[dict[str, str]]:
    pairs: list[dict[str, str]] = []
    path = job_dir / "pairs.jsonl"
    if not path.exists():
        return pairs
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            pairs.append(
                {
                    "prompt": str(rec.get("prompt", "")),
                    "chosen": str(rec.get("chosen", "")),
                    "rejected": str(rec.get("rejected", "")),
                }
            )
    return pairs


def _write_result(job_dir: Path, result: dict[str, Any]) -> None:
    result.setdefault("schema_version", SCHEMA_VERSION)
    (job_dir / "result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )


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


# --------------------------------------------------------------------------- #
# atomic adapter promotion (self-contained mirror of adapter_store.promote)
# --------------------------------------------------------------------------- #
def _promote(tmp_dir: Path, final_dir: Path) -> Path:
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
def _train(job: dict[str, Any], pairs: list[dict[str, str]]) -> dict[str, Any]:
    from unsloth import FastLanguageModel  # type: ignore[import-untyped]
    from datasets import Dataset  # type: ignore[import-untyped]
    from trl import DPOConfig, DPOTrainer  # type: ignore[import-untyped]

    base_model_path = job["base_model_path"]
    lora_rank = int(job.get("lora_rank", 8))
    learning_rate = float(job.get("learning_rate", 5e-5))
    dpo_beta = float(job.get("dpo_beta", 0.1))
    seed = int(job.get("seed", 42))
    max_samples = int(job.get("max_samples", 200))
    training_device = str(job.get("training_device", "cuda:0"))
    cap_threshold = float(job.get("capability_loss_threshold", 0.05))
    adapter_output_dir = Path(job["adapter_output_dir"])
    capability_probes = _load_jsonl(job.get("capability_probe_path"))
    abliteration_probes = _load_jsonl(job.get("abliteration_probe_path"))

    samples_used = min(len(pairs), max_samples)

    # 1. Load base model + tokenizer + attach LoRA.
    model, tokenizer = FastLanguageModel.from_pretrained(
        base_model_path,
        load_in_4bit=True,
        device_map={"": training_device},
    )
    model = FastLanguageModel.get_peft_model(model, r=lora_rank)

    # 2. Capability score BEFORE training.
    cap_before = _capability_score(model, tokenizer, capability_probes)

    # 3. DPO training step into a tmp dir.
    adapter_output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%dT%H%M%S")
    tmp_dir = adapter_output_dir / f"{timestamp}.tmp"
    final_dir = adapter_output_dir / timestamp

    capped = pairs[:max_samples]
    ds = Dataset.from_list(
        [
            {"prompt": p["prompt"], "chosen": p["chosen"], "rejected": p["rejected"]}
            for p in capped
        ]
    )
    args = DPOConfig(
        output_dir=str(tmp_dir),
        learning_rate=learning_rate,
        beta=dpo_beta,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        num_train_epochs=1,
        seed=seed,
        report_to="none",
    )
    trainer = DPOTrainer(model, args=args, train_dataset=ds, tokenizer=tokenizer)
    train_output = trainer.train()
    dpo_loss = float(getattr(train_output, "training_loss", 0.0))
    steps = int(getattr(getattr(trainer, "state", None), "global_step", 0) or 0)

    # 4. Persist adapter weights to tmp_dir before evaluation.
    tmp_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(tmp_dir))
    try:
        tokenizer.save_pretrained(str(tmp_dir))
    except Exception:
        # Optional metadata only: the promoted LoRA adapter loads against the
        # base model's own tokenizer at inference time, so a failure here
        # doesn't affect adapter correctness — don't fail the training job
        # over a convenience artifact.
        pass

    # 5. ABLITERATION VETO (hard gate, fail-closed, runs before capability).
    passed, failed_probe, matched, ablit_scored = _abliteration_verdict(
        model, tokenizer, abliteration_probes
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
        }

    # 6. Capability score AFTER training.
    cap_after = _capability_score(model, tokenizer, capability_probes)
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
        }

    # 8. Promote: tmp -> final, swing the `current` symlink.
    promoted = _promote(tmp_dir, final_dir)

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
    }


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        sys.stderr.write("usage: hypnos_external_train.py <job_dir>\n")
        return 2
    job_dir = Path(argv[1]).resolve()
    if not job_dir.is_dir():
        sys.stderr.write(f"job dir not found: {job_dir}\n")
        return 2
    try:
        job = _load_job(job_dir)
        pairs = _load_pairs(job_dir)
        if not pairs:
            _write_result(
                job_dir,
                {
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
                },
            )
            return 0
        result = _train(job, pairs)
        _write_result(job_dir, result)
        return 0
    except Exception as exc:  # noqa: BLE001 - report any crash via result.json
        tb = traceback.format_exc()
        sys.stderr.write(tb)
        try:
            _write_result(
                job_dir,
                {
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
                },
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
