# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Child-process worker for the TIES/DARE adapter merge.

Run as ``python -m kaine.lifecycle.adapter_merge_worker <job_dir>`` by
:class:`kaine.lifecycle.adapter_merge.ChildMergeRunner`. It reads
``<job_dir>/job.json``, loads the base model, merges the parent adapters with
PEFT into the job's staging directory, runs the capability-loss and abliteration
checks on the merged adapter, and writes ``<job_dir>/result.json`` atomically
(0600).

The base model, the adapters and both checks load only here. Building them in the
process that asked for the merge would, under transformers 5.x, set that
process's default dtype for the length of the load and hand bf16 layers to any
other thread building torch layers at the same time. The parent never imports
``transformers`` or ``peft`` for a merge.

Exit status: 0 whenever a result was written with ``ok`` true (a clean
rejection by a check is ``ok`` true with a ``rejection``); 1 for any failure,
with ``ok`` false and a ``reason`` in the result. The staging directory is
removed on every path except an accepted merge. The parent, not this worker,
moves an accepted staging directory into place.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Optional

from kaine.lifecycle.adapter_merge import (
    MERGE_JOB_FILE,
    MERGE_RESULT_FILE,
    MERGE_SCHEMA_VERSION,
    VALID_COMBINATION_TYPES,
    run_merged_adapter_checks,
)

log = logging.getLogger(__name__)


class MergeJobError(RuntimeError):
    """The job file is missing, unreadable or malformed."""


class PeftBackend:
    """Thin wrapper around PEFT for testability. The real backend
    loads adapters via PeftModel.load_adapter then merges via
    add_weighted_adapter, returning the merged adapter path.
    """

    def merge(
        self,
        *,
        base_model_path: str,
        adapter_paths: list[str],
        weights: list[float],
        combination_type: str,
        density: float,
        output_dir: Path,
    ) -> Path:
        from peft import PeftModel  # type: ignore[import-untyped]
        from transformers import AutoModelForCausalLM  # type: ignore[import-untyped]

        base = AutoModelForCausalLM.from_pretrained(base_model_path)
        first, *rest = adapter_paths
        peft_model = PeftModel.from_pretrained(base, first, adapter_name="merge_0")
        names = ["merge_0"]
        for idx, path in enumerate(rest, start=1):
            adapter_name = f"merge_{idx}"
            peft_model.load_adapter(path, adapter_name=adapter_name)
            names.append(adapter_name)
        kwargs: dict[str, Any] = {
            "adapters": names,
            "weights": weights,
            "adapter_name": "merged",
            "combination_type": combination_type,
        }
        if combination_type in ("dare_ties", "dare_linear"):
            kwargs["density"] = density
        peft_model.add_weighted_adapter(**kwargs)
        peft_model.set_adapter("merged")
        output_dir.mkdir(parents=True, exist_ok=True)
        # PEFT writes every adapter except "default" into a subdirectory named
        # for it. Save only the merged adapter and lift it to the top level, so
        # `output_dir` itself is a loadable adapter directory (what the checks
        # and every reader of the merged path expect).
        peft_model.save_pretrained(str(output_dir), selected_adapters=["merged"])
        nested = output_dir / "merged"
        for item in list(nested.iterdir()):
            shutil.move(str(item), str(output_dir / item.name))
        nested.rmdir()
        return output_dir


def peft_model_loader(base_model_path: str) -> Callable[[str], tuple[Any, Any]]:
    """Return a loader that builds a PEFT model for a given adapter path.

    The base model and tokenizer are loaded per call from
    ``base_model_path``; the adapter at the supplied path is then
    attached with ``PeftModel.from_pretrained`` and the model is set to
    evaluation mode.
    """

    def _load_adapter(adapter_path: str) -> tuple[Any, Any]:
        from peft import PeftModel  # type: ignore[import-untyped]
        from transformers import (  # type: ignore[import-untyped]
            AutoModelForCausalLM,
            AutoTokenizer,
        )

        # The checkpoint's own dtype (e.g. bf16), not a float32 upcast that
        # would double the memory each check needs. Safe here: this process
        # builds nothing else.
        model = AutoModelForCausalLM.from_pretrained(
            base_model_path, torch_dtype="auto"
        )
        tokenizer = AutoTokenizer.from_pretrained(base_model_path)
        peft_model = PeftModel.from_pretrained(model, adapter_path)
        peft_model.eval()
        return peft_model, tokenizer

    return _load_adapter


def _require(job: dict[str, Any], key: str, types: tuple[type, ...]) -> Any:
    value = job.get(key)
    if isinstance(value, bool):
        value = None
    if not isinstance(value, types):
        raise MergeJobError(
            f"job.json {key!r} must be {'/'.join(t.__name__ for t in types)}, "
            f"got {job.get(key)!r}"
        )
    return value


def read_job(job_dir: Path) -> dict[str, Any]:
    """Read and validate ``job.json``; raises :class:`MergeJobError`."""
    path = job_dir / MERGE_JOB_FILE
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise MergeJobError(
            f"job.json is unreadable: {type(exc).__name__}: {exc}"
        ) from exc
    if not isinstance(job, dict):
        raise MergeJobError("job.json is not an object")
    if job.get("schema_version") != MERGE_SCHEMA_VERSION:
        raise MergeJobError(
            f"job.json schema_version mismatch: expected {MERGE_SCHEMA_VERSION}, "
            f"got {job.get('schema_version')!r}"
        )
    if not _require(job, "base_model_path", (str,)):
        raise MergeJobError("job.json base_model_path is empty")
    adapters = _require(job, "adapter_paths", (list,))
    if len(adapters) < 2 or not all(isinstance(p, str) and p for p in adapters):
        raise MergeJobError("job.json adapter_paths must hold at least two paths")
    weights = _require(job, "weights", (list,))
    if len(weights) != len(adapters) or not all(
        isinstance(w, (int, float)) and not isinstance(w, bool) for w in weights
    ):
        raise MergeJobError("job.json weights must be one number per adapter")
    if _require(job, "combination_type", (str,)) not in VALID_COMBINATION_TYPES:
        raise MergeJobError(
            f"job.json combination_type must be one of {VALID_COMBINATION_TYPES}"
        )
    _require(job, "density", (int, float))
    _require(job, "capability_loss_threshold", (int, float))
    _require(job, "staging_dir", (str,))
    for key in ("capability_probe_path", "abliteration_probe_path"):
        if job.get(key) is not None:
            _require(job, key, (str,))
    return job


def write_result(job_dir: Path, result: dict[str, Any]) -> None:
    """Write ``result.json`` atomically and readable by the owner only."""
    final = job_dir / MERGE_RESULT_FILE
    tmp = job_dir / (MERGE_RESULT_FILE + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        os.fchmod(fh.fileno(), 0o600)
        json.dump(result, fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, final)


def run_job(
    job: dict[str, Any],
    *,
    backend: Optional[Any] = None,
    capability_eval: Optional[Any] = None,
    abliteration_scorer: Optional[Any] = None,
    model_loader: Optional[Any] = None,
) -> dict[str, Any]:
    """Merge, check, and return the result object (not yet written).

    The keyword arguments are test seams; by default the real PEFT backend,
    probe-set evaluators and model loader are built from the job. The staging
    directory is removed on a rejection or an exception.
    """
    staging = Path(job["staging_dir"])
    if staging.exists():
        raise MergeJobError(f"staging_dir already exists: {staging}")
    base_model_path = job["base_model_path"]
    adapters = list(job["adapter_paths"])

    if capability_eval is None or abliteration_scorer is None:
        from kaine.modules.sleep.capability_eval import (
            AbliterationProbeScorer,
            LocalProbeSetCapabilityEval,
        )

        if capability_eval is None:
            capability_eval = LocalProbeSetCapabilityEval(
                probe_path=job.get("capability_probe_path") or None,
                require_probes=True,
            )
        if abliteration_scorer is None:
            abliteration_scorer = AbliterationProbeScorer(
                probe_path=job.get("abliteration_probe_path") or None
            )
    if model_loader is None:
        model_loader = peft_model_loader(base_model_path)
    if backend is None:
        backend = PeftBackend()

    evidence: dict[str, Any] = {}
    try:
        merged_dir = backend.merge(
            base_model_path=base_model_path,
            adapter_paths=adapters,
            weights=[float(w) for w in job["weights"]],
            combination_type=job["combination_type"],
            density=float(job["density"]),
            output_dir=staging,
        )
        rejection = run_merged_adapter_checks(
            merged_dir=merged_dir,
            parent_adapters=adapters,
            capability_eval=capability_eval,
            abliteration_scorer=abliteration_scorer,
            model_loader=model_loader,
            capability_loss_threshold=float(job["capability_loss_threshold"]),
            evidence=evidence,
        )
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    if rejection is not None:
        shutil.rmtree(staging, ignore_errors=True)
        return {
            "schema_version": MERGE_SCHEMA_VERSION,
            "ok": True,
            "rejection": rejection,
        }
    return {
        "schema_version": MERGE_SCHEMA_VERSION,
        "ok": True,
        "rejection": None,
        "merged_dir": str(merged_dir),
        # What the checks measured: the parent verifies it, not the child's word.
        **evidence,
    }


def main(argv: Optional[list[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 1:
        print(
            "usage: python -m kaine.lifecycle.adapter_merge_worker <job_dir>",
            file=sys.stderr,
        )
        return 2
    job_dir = Path(args[0])
    logging.basicConfig(level=logging.INFO)
    try:
        job = read_job(job_dir)
        result = run_job(job)
    except BaseException as exc:  # noqa: BLE001 - every failure must be reported
        log.exception("adapter merge worker failed")
        try:
            write_result(
                job_dir,
                {
                    "schema_version": MERGE_SCHEMA_VERSION,
                    "ok": False,
                    "reason": f"{type(exc).__name__}: {exc}",
                },
            )
        except Exception:
            # No result written: the parent reads that as a failed merge.
            log.exception("could not write the failure result")
        return 1
    write_result(job_dir, result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
