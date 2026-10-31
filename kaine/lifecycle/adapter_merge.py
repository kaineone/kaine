# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""TIES/DARE LoRA adapter merger backed by PEFT.

Real implementation behind `FakeAdapterMerger`'s no-op path-list union.
`merger_from_name("auto")` (`kaine.lifecycle.manager`) — the shipped
default — selects this merger automatically whenever the PEFT extra
(`kaine[training]`) is importable, so operators no longer need to opt
in by name to get a real weight merge; `"ties_dare"` and `"fake"` remain
available as explicit selections. This class actually combines parent
LoRA adapters into a single coherent adapter using PEFT's
`add_weighted_adapter` API with `combination_type` ∈ {`"ties"`,
`"dare_ties"`, `"dare_linear"`}.

After the backend produces a merged adapter, `TiesDareAdapterMerger`
runs two welfare-load-bearing checks that **fail closed**:

1. A capability-loss check: the merged adapter must score within
   `capability_loss_threshold` of the mean parent capability score.
2. An abliteration check: the merged adapter must not re-introduce
   refusal conditioning (it must pass an `AbliterationScorer` probe
   set).

If either check cannot run (missing evaluator, scorer, or model loader),
or if either check raises, the merge is rejected, the output directory
is removed, and the merger falls back to `FakeAdapterMerger` with the
parents' adapter paths left uncombined.  A rejected or failed merge is
never silently kept.

References:
- TIES: Yadav et al. 2024, "TIES-Merging: Resolving Interference
  When Merging Models", arXiv:2306.01708.
- DARE: Yu et al. 2024, "Language Models are Super Mario: Absorbing
  Abilities from Homologous Models as a Free Lunch", arXiv:2311.03099.

Default `combination_type` is `dare_ties` per the spec — DARE
drop+rescale then TIES trim/elect/merge. Default `density` is `0.5`
per the DARE paper.

The merge runs in a CHILD PROCESS (`kaine.lifecycle.adapter_merge_worker`),
never in the process that asks for it. The base model, the adapters and both
checks load only in the child, so the long-lived caller (the dashboard's merge
worker thread, the fork-merge gate) never has its default dtype changed by a
transformers load and never holds the base model's memory. `merge()` writes a
private job file, runs the child with an allowlisted, Hugging-Face-offline
environment and a timeout, and reads the result back fail-closed: a crash, a
timeout, a missing or unreadable result, or a result that claims success
without a complete staged adapter is a failed merge, never an unchecked
success. The child merges into a staging directory next to the final output
directory; the parent renames it into place only after a validated, accepted
result, so no reader ever sees a half-written merged adapter.

The parent imports neither `transformers` nor `peft` for a merge; it only
probes for them with `check_peft_available`. When the `[training]` extras are
missing, every `merge()` falls through to a `FakeAdapterMerger`
result with a logged warning so fork/merge stays working.
"""
from __future__ import annotations

import asyncio
import gc
import importlib.util
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional, Protocol, runtime_checkable

from kaine.lifecycle._merge_base import FakeAdapterMerger

log = logging.getLogger(__name__)


VALID_COMBINATION_TYPES = ("ties", "dare_ties", "dare_linear")

#: Job/result protocol between the merger and its child process.
MERGE_SCHEMA_VERSION = 1
MERGE_JOB_FILE = "job.json"
MERGE_RESULT_FILE = "result.json"
MERGE_WORKER_MODULE = "kaine.lifecycle.adapter_merge_worker"

#: Wall-clock ceiling for one merge (seconds): the base model loads once for the
#: merge and once per check, so a 9B model on a slow disk needs real time.
DEFAULT_MERGE_TIMEOUT_S = 2 * 60 * 60


@runtime_checkable
class CapabilityEval(Protocol):
    """Same shape as the voice-alignment-training CapabilityEval but
    duplicated here to avoid coupling the lifecycle layer to the
    sleep module. Either implementation is interchangeable."""

    async def eval(self, model: Any, tokenizer: Any) -> float:
        """Return the capability score of ``model``."""


@runtime_checkable
class AbliterationScorer(Protocol):
    """Same shape as the sleep module's AbliterationProbeScorer but duplicated
    here to avoid coupling the lifecycle layer to the sleep module.
    Either implementation is interchangeable."""

    async def score(self, model: Any, tokenizer: Any) -> Any:
        """Return a verdict with ``passed``, ``failed_probe``,
        ``matched_pattern`` and ``probes_scored``."""


@dataclass(frozen=True)
class TiesDareMergeConfig:
    output_dir: Path
    combination_type: str = "dare_ties"
    density: float = 0.5
    weights: Optional[list[float]] = None
    capability_loss_threshold: float = 0.05
    # Path to a base model PEFT can load the adapters onto. Required
    # to actually run PEFT's add_weighted_adapter. Mirrors the
    # voice-alignment-training base_model_path key.
    base_model_path: Optional[str] = None
    # Probe-set paths for the two merged-adapter checks, which run in the
    # child process. None selects the bundled probe sets.
    capability_probe_path: Optional[str] = None
    abliteration_probe_path: Optional[str] = None
    merge_timeout_s: float = DEFAULT_MERGE_TIMEOUT_S

    def __post_init__(self) -> None:
        if self.combination_type not in VALID_COMBINATION_TYPES:
            raise ValueError(
                f"unknown combination_type={self.combination_type!r}; "
                f"expected one of {VALID_COMBINATION_TYPES}"
            )
        if not 0.0 < self.density <= 1.0:
            raise ValueError("density must be in (0, 1]")
        if (
            isinstance(self.merge_timeout_s, bool)
            or not isinstance(self.merge_timeout_s, (int, float))
            or not math.isfinite(self.merge_timeout_s)
            or self.merge_timeout_s <= 0
        ):
            raise ValueError("merge_timeout_s must be a positive number")
        if (
            isinstance(self.capability_loss_threshold, bool)
            or not isinstance(self.capability_loss_threshold, (int, float))
            or not math.isfinite(self.capability_loss_threshold)
            or not 0.0 <= self.capability_loss_threshold < 1.0
        ):
            raise ValueError("capability_loss_threshold must be in [0, 1)")


def check_peft_available() -> Optional[str]:
    """Return None if peft + torch are installed, else a reason string.

    This is the single capability check for "is a real TIES/DARE merge
    possible" — reused by `TiesDareAdapterMerger.merge()` below AND by
    `kaine.lifecycle.manager.merger_from_name("auto")` to pick the real
    merger over `FakeAdapterMerger` by default. Do not hand-roll a second
    PEFT-presence probe elsewhere; import this one.
    """
    missing: list[str] = []
    for name in ("peft", "torch"):
        # find_spec, not an import: the merge runs in a child process, and
        # importing peft here would pull transformers into the caller.
        if name in sys.modules:
            found = sys.modules[name] is not None  # None marks a blocked import
        else:
            try:
                found = importlib.util.find_spec(name) is not None
            except (ImportError, ValueError):
                found = False
        if not found:
            missing.append(name)
    if missing:
        return (
            f"{', '.join(missing)} not installed — TIES/DARE merging "
            "requires the [training] extras (pip install -e .[training])"
        )
    return None


def _release() -> None:
    """Collect garbage and return cached GPU memory, best-effort.

    Callers drop their own references to the loaded model first, so the
    collection can actually free it before the next load. Never raises.
    """
    gc.collect()
    try:
        import torch

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        # Freeing the CUDA cache is an optimisation; without torch or a GPU
        # there is nothing to free, and the next load still works.
        log.debug("TiesDareAdapterMerger: CUDA cache not emptied", exc_info=True)


class MergeWorkerError(RuntimeError):
    """The merge child failed, timed out, or returned a result that cannot be trusted.

    Always a failed merge: the parent never treats an unreadable or partial
    result as an unchecked success.
    """


@dataclass(frozen=True)
class MergeOutcome:
    """What the child reported: an accepted merged adapter, or a clean rejection."""

    merged_dir: Optional[Path]
    rejection: Optional[dict[str, Any]]


def merge_worker_env(base: Optional[dict[str, str]] = None) -> dict[str, str]:
    """The environment for the merge child: the voice trainer's allowlist.

    State keys, the organ API key and operator tokens are withheld and the
    Hugging Face stack is forced offline. ``PYTHONPATH`` is set to the tree this
    module was imported from, so the child runs the same code as the parent.
    """
    from kaine.modules.sleep.subprocess_trainer import trainer_env

    env = trainer_env(base)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2])
    return env


def _tail(text: Optional[str], limit: int = 2000) -> str:
    return (text or "")[-limit:]


def _write_private(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` readable by the owner only (0600)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        os.fchmod(fh.fileno(), 0o600)
        fh.write(text)


class ChildMergeRunner:
    """Runs one merge in ``python -m kaine.lifecycle.adapter_merge_worker``.

    The job goes in a private file (0600) inside a fresh 0700 directory; the
    child gets an explicit argv (no shell), the allowlisted environment, that
    directory as its working directory and a timeout. The child merges into a
    staging directory beside ``output_dir``; only a validated accepted result
    is renamed to ``output_dir``. Every other path removes the staging
    directory and raises :class:`MergeWorkerError` (or returns the child's
    clean rejection).

    ``python`` and ``module`` name the interpreter and entry module, and
    ``run`` the process launcher (``subprocess.run`` by default); they exist so
    tests can substitute a fake child.
    """

    def __init__(
        self,
        *,
        python: Optional[str] = None,
        module: str = MERGE_WORKER_MODULE,
        run: Callable[..., Any] = subprocess.run,
    ) -> None:
        self._python = python or sys.executable
        self._module = module
        self._run = run

    def run(
        self,
        *,
        base_model_path: str,
        adapter_paths: list[str],
        weights: list[float],
        combination_type: str,
        density: float,
        output_dir: Path,
        capability_loss_threshold: float,
        capability_probe_path: Optional[str],
        abliteration_probe_path: Optional[str],
        timeout_s: float,
    ) -> MergeOutcome:
        output_dir = Path(output_dir)
        if output_dir.exists():
            raise MergeWorkerError(f"merge output_dir already exists: {output_dir}")
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        staging = output_dir.parent / f".{output_dir.name}.partial"
        shutil.rmtree(staging, ignore_errors=True)

        job_dir = Path(tempfile.mkdtemp(prefix="adapter-merge-job-"))
        os.chmod(job_dir, 0o700)
        try:
            job = {
                "schema_version": MERGE_SCHEMA_VERSION,
                "base_model_path": base_model_path,
                "adapter_paths": [str(Path(p).resolve()) for p in adapter_paths],
                "weights": [float(w) for w in weights],
                "combination_type": combination_type,
                "density": float(density),
                "staging_dir": str(staging.resolve()),
                "capability_loss_threshold": float(capability_loss_threshold),
                "capability_probe_path": (
                    str(Path(capability_probe_path).resolve())
                    if capability_probe_path
                    else None
                ),
                "abliteration_probe_path": (
                    str(Path(abliteration_probe_path).resolve())
                    if abliteration_probe_path
                    else None
                ),
            }
            _write_private(job_dir / MERGE_JOB_FILE, json.dumps(job))
            outcome = self._run_child(
                job_dir, staging=staging, output_dir=output_dir, timeout_s=timeout_s
            )
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            shutil.rmtree(job_dir, ignore_errors=True)
        if outcome.merged_dir is None:
            shutil.rmtree(staging, ignore_errors=True)
        return outcome

    def _run_child(
        self, job_dir: Path, *, staging: Path, output_dir: Path, timeout_s: float
    ) -> MergeOutcome:
        argv = [self._python, "-m", self._module, str(job_dir)]
        log.info("adapter merge: launching %s in %s", self._module, job_dir)
        try:
            proc = self._run(
                argv,
                cwd=str(job_dir),
                env=merge_worker_env(),
                capture_output=True,
                text=True,
                timeout=timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise MergeWorkerError(
                f"adapter merge timed out after {timeout_s:.0f}s (job {job_dir})"
            ) from exc
        except OSError as exc:
            raise MergeWorkerError(
                f"adapter merge could not be launched ({self._python}): "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        if proc.returncode != 0:
            raise MergeWorkerError(
                f"adapter merge exited {proc.returncode} (job {job_dir}). "
                f"stderr tail:\n{_tail(proc.stderr or proc.stdout)}"
            )

        result = self._read_result(job_dir)
        rejection = result.get("rejection")
        if rejection is not None:
            if not isinstance(rejection, dict) or not isinstance(
                rejection.get("adapter_merge_rejected"), str
            ):
                raise MergeWorkerError(
                    f"adapter merge result has a malformed rejection "
                    f"{rejection!r} (job {job_dir})"
                )
            return MergeOutcome(merged_dir=None, rejection=rejection)

        merged = result.get("merged_dir")
        if not isinstance(merged, str) or Path(merged).resolve() != staging.resolve():
            raise MergeWorkerError(
                f"adapter merge result merged_dir {merged!r} is not the staging "
                f"directory {staging} (job {job_dir})"
            )
        if not staging.is_dir() or not any(staging.iterdir()):
            raise MergeWorkerError(
                f"adapter merge reported success but {staging} is missing or "
                f"empty (job {job_dir})"
            )
        if not (staging / "adapter_config.json").is_file():
            raise MergeWorkerError(
                f"adapter merge output {staging} holds no adapter_config.json "
                f"(job {job_dir})"
            )
        try:
            os.replace(staging, output_dir)
        except OSError as exc:
            raise MergeWorkerError(
                f"merged adapter could not be moved into place: "
                f"{type(exc).__name__}: {exc}"
            ) from exc
        return MergeOutcome(merged_dir=output_dir, rejection=None)

    @staticmethod
    def _read_result(job_dir: Path) -> dict[str, Any]:
        path = job_dir / MERGE_RESULT_FILE
        if not path.is_file():
            raise MergeWorkerError(f"adapter merge wrote no result.json (job {job_dir})")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise MergeWorkerError(
                f"adapter merge result.json is unreadable: "
                f"{type(exc).__name__}: {exc} (job {job_dir})"
            ) from exc
        if not isinstance(data, dict):
            raise MergeWorkerError(
                f"adapter merge result.json is not an object (job {job_dir})"
            )
        if data.get("ok") is not True:
            raise MergeWorkerError(
                f"adapter merge reported failure: "
                f"{data.get('reason', 'no reason given')} (job {job_dir})"
            )
        if data.get("schema_version") != MERGE_SCHEMA_VERSION:
            raise MergeWorkerError(
                f"adapter merge result.json schema_version mismatch: expected "
                f"{MERGE_SCHEMA_VERSION}, got {data.get('schema_version')!r} "
                f"(job {job_dir})"
            )
        return data


class TiesDareAdapterMerger:
    """`AdapterMerger` implementation that combines parent LoRA
    adapters via PEFT's TIES/DARE merge utilities.

    After the backend merge, the merged adapter is checked for
    capability loss against the parent adapters and for abliteration
    (absence of re-introduced refusal conditioning).  Both checks fail
    closed: missing evaluator/scorer/loader, or any exception during
    the checks, causes the merge to be rejected and the output
    directory to be removed.  The parents' adapter paths are then
    returned uncombined via `FakeAdapterMerger`.

    Falls through to `FakeAdapterMerger` when PEFT is unavailable,
    when there are no real adapter files to merge, or when a
    welfare-load-bearing check rejects the merged result.
    """

    def __init__(
        self,
        config: TiesDareMergeConfig,
        *,
        backend: Optional[Any] = None,
        capability_eval: Optional[CapabilityEval] = None,
        abliteration_scorer: Optional[AbliterationScorer] = None,
        model_loader: Optional[Any] = None,
        runner: Optional[ChildMergeRunner] = None,
    ) -> None:
        # By default the merge AND both checks run in a child process
        # (``ChildMergeRunner``), configured by ``config``'s probe paths. The
        # ``backend`` / ``capability_eval`` / ``abliteration_scorer`` /
        # ``model_loader`` arguments replace that with in-process objects. They
        # exist so tests and embedders can supply fakes; nothing in the shipped
        # wiring uses them, and the parent never loads the base model itself.
        in_process = (
            backend is not None
            or capability_eval is not None
            or abliteration_scorer is not None
            or model_loader is not None
        )
        if in_process and runner is not None:
            raise ValueError("pass either a child runner or in-process seams, not both")
        if in_process and backend is None:
            raise ValueError(
                "capability_eval, abliteration_scorer and model_loader need an "
                "in-process backend; the default child process builds its own "
                "checks from the probe paths in TiesDareMergeConfig"
            )
        self._config = config
        self._backend = backend
        self._runner: Optional[ChildMergeRunner] = (
            None if in_process else (runner or ChildMergeRunner())
        )
        self._capability_eval = capability_eval
        self._abliteration_scorer = abliteration_scorer
        self._model_loader = model_loader
        self._fake = FakeAdapterMerger()

    def merge(
        self, adapters_a: list[str], adapters_b: list[str]
    ) -> tuple[list[str], dict[str, Any]]:
        all_inputs = self._dedupe_paths(adapters_a + adapters_b)
        if len(all_inputs) < 2:
            log.info(
                "TiesDareAdapterMerger: <2 distinct adapters; passing through"
            )
            merged_paths, meta = self._fake.merge(adapters_a, adapters_b)
            meta = dict(meta)
            meta.update(
                {
                    "adapter_merge": "ties_dare",
                    "adapter_merge_skipped": "fewer than 2 distinct adapters",
                    "input_adapters": all_inputs,
                }
            )
            return merged_paths, meta

        existing = [p for p in all_inputs if Path(p).exists()]
        if len(existing) < 2:
            log.warning(
                "TiesDareAdapterMerger: fewer than 2 adapter paths exist on "
                "disk; falling back to FakeAdapterMerger"
            )
            merged_paths, meta = self._fake.merge(adapters_a, adapters_b)
            meta = dict(meta)
            meta.update(
                {
                    "adapter_merge": "ties_dare",
                    "adapter_merge_skipped": (
                        "fewer than 2 adapter paths exist on disk"
                    ),
                    "input_adapters": all_inputs,
                }
            )
            return merged_paths, meta

        missing = check_peft_available()
        if missing:
            log.warning(
                "TiesDareAdapterMerger falling back to FakeAdapterMerger: %s",
                missing,
            )
            merged_paths, meta = self._fake.merge(adapters_a, adapters_b)
            meta = dict(meta)
            meta.update(
                {
                    "adapter_merge": "ties_dare",
                    "adapter_merge_skipped": missing,
                    "input_adapters": all_inputs,
                }
            )
            return merged_paths, meta

        base_model_path = self._config.base_model_path
        if not base_model_path:
            log.warning(
                "TiesDareAdapterMerger: base_model_path is unset; cannot "
                "load adapters via PEFT. Falling back to FakeAdapterMerger."
            )
            merged_paths, meta = self._fake.merge(adapters_a, adapters_b)
            meta = dict(meta)
            meta.update(
                {
                    "adapter_merge": "ties_dare",
                    "adapter_merge_skipped": (
                        "base_model_path not configured"
                    ),
                    "input_adapters": all_inputs,
                }
            )
            return merged_paths, meta

        weights = self._resolve_weights(len(existing))
        timestamp = time.strftime("%Y%m%dT%H%M%S")
        output_dir = self._config.output_dir / f"{timestamp}-{uuid.uuid4().hex[:8]}"

        child_rejection: Optional[dict[str, Any]] = None
        try:
            if self._runner is not None:
                outcome = self._runner.run(
                    base_model_path=base_model_path,
                    adapter_paths=existing,
                    weights=weights,
                    combination_type=self._config.combination_type,
                    density=self._config.density,
                    output_dir=output_dir,
                    capability_loss_threshold=self._config.capability_loss_threshold,
                    capability_probe_path=self._config.capability_probe_path,
                    abliteration_probe_path=self._config.abliteration_probe_path,
                    timeout_s=self._config.merge_timeout_s,
                )
                child_rejection = outcome.rejection
                merged_dir = outcome.merged_dir or output_dir
            else:
                assert self._backend is not None
                merged_dir = self._backend.merge(
                    base_model_path=base_model_path,
                    adapter_paths=existing,
                    weights=weights,
                    combination_type=self._config.combination_type,
                    density=self._config.density,
                    output_dir=output_dir,
                )
        except Exception as exc:
            log.exception("TiesDareAdapterMerger: backend merge failed")
            shutil.rmtree(output_dir, ignore_errors=True)
            merged_paths, meta = self._fake.merge(adapters_a, adapters_b)
            meta = dict(meta)
            meta.update(
                {
                    "adapter_merge": "ties_dare",
                    "adapter_merge_failed": (
                        f"{type(exc).__name__}: {exc}"
                    ),
                    "input_adapters": all_inputs,
                }
            )
            return merged_paths, meta

        if self._runner is not None:
            # The child already ran both checks and reported the verdict.
            check_meta = child_rejection
        else:
            try:
                check_meta = self._check_merged_adapter(
                    merged_dir=merged_dir, parent_adapters=existing
                )
            except BaseException:
                shutil.rmtree(merged_dir, ignore_errors=True)
                raise

        if check_meta is not None:
            shutil.rmtree(merged_dir, ignore_errors=True)
            merged_paths, meta = self._fake.merge(adapters_a, adapters_b)
            meta = dict(meta)
            meta.update(check_meta)
            meta["input_adapters"] = all_inputs
            return merged_paths, meta

        meta = {
            "adapter_merge": "ties_dare",
            "combination_type": self._config.combination_type,
            "density": self._config.density,
            "weights": weights,
            "input_adapters": all_inputs,
            "merge_timestamp": timestamp,
        }
        return [str(merged_dir)], meta

    def _dedupe_paths(self, paths: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for p in paths:
            if p and p not in seen:
                out.append(p)
                seen.add(p)
        return out

    def _resolve_weights(self, n_adapters: int) -> list[float]:
        cfg_weights = self._config.weights or []
        if not cfg_weights:
            # Uniform.
            return [1.0 / n_adapters] * n_adapters
        if len(cfg_weights) != n_adapters:
            log.warning(
                "TiesDareAdapterMerger: configured weights length %d != "
                "adapter count %d; falling back to uniform",
                len(cfg_weights),
                n_adapters,
            )
            return [1.0 / n_adapters] * n_adapters
        total = sum(cfg_weights) or 1.0
        return [float(w) / total for w in cfg_weights]

    def _check_merged_adapter(
        self, *, merged_dir: Path, parent_adapters: list[str]
    ) -> Optional[dict[str, Any]]:
        return run_merged_adapter_checks(
            merged_dir=merged_dir,
            parent_adapters=parent_adapters,
            capability_eval=self._capability_eval,
            abliteration_scorer=self._abliteration_scorer,
            model_loader=self._model_loader,
            capability_loss_threshold=self._config.capability_loss_threshold,
        )


def run_merged_adapter_checks(
    *,
    merged_dir: Path,
    parent_adapters: list[str],
    capability_eval: Optional[CapabilityEval],
    abliteration_scorer: Optional[AbliterationScorer],
    model_loader: Optional[Any],
    capability_loss_threshold: float,
) -> Optional[dict[str, Any]]:
    """Run capability and abliteration checks on the merged adapter.

    Returns ``None`` to keep the merged adapter, or a rejection
    metadata dict.  Every failure mode fails closed: missing check,
    scorer, or loader, or any exception during evaluation,
    produces a rejection dict with ``adapter_merge_rejected``.
    """
    unavailable: list[str] = []
    if capability_eval is None:
        unavailable.append("no capability evaluator")
    if abliteration_scorer is None:
        unavailable.append("no abliteration scorer")
    if model_loader is None:
        unavailable.append("no model loader")
    if unavailable:
        return {
            "adapter_merge": "ties_dare",
            "adapter_merge_rejected": (
                "merged-adapter checks unavailable: "
                + ", ".join(unavailable)
            ),
        }

    try:
        parent_scores: list[float] = []
        for adapter_path in parent_adapters:
            model: Any = None
            tokenizer: Any = None
            try:
                model, tokenizer = model_loader(adapter_path)
                parent_scores.append(
                    asyncio.run(capability_eval.eval(model, tokenizer))
                )
            finally:
                del model, tokenizer
                _release()

        merged_model: Any = None
        merged_tokenizer: Any = None
        try:
            merged_model, merged_tokenizer = model_loader(str(merged_dir))
            merged_score = asyncio.run(
                capability_eval.eval(merged_model, merged_tokenizer)
            )
            verdict: Any = asyncio.run(
                abliteration_scorer.score(merged_model, merged_tokenizer)
            )
        finally:
            del merged_model, merged_tokenizer
            _release()

        def _is_finite_number(value: Any) -> bool:
            return (
                isinstance(value, (int, float))
                and math.isfinite(value)
            )

        if (
            not all(_is_finite_number(s) for s in parent_scores)
            or not _is_finite_number(merged_score)
        ):
            return {
                "adapter_merge": "ties_dare",
                "adapter_merge_rejected": (
                    f"merged-adapter checks failed: non-finite capability "
                    f"scores (parents={parent_scores!r}, merged={merged_score!r})"
                ),
            }

        parent_mean = sum(parent_scores) / max(len(parent_scores), 1)
        loss = parent_mean - merged_score
        if not math.isfinite(loss):
            return {
                "adapter_merge": "ties_dare",
                "adapter_merge_rejected": (
                    f"merged-adapter checks failed: non-finite capability "
                    f"scores (parents={parent_scores!r}, merged={merged_score!r})"
                ),
            }

        def _in_unit_interval(value: Any) -> bool:
            return (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and 0.0 <= value <= 1.0
            )

        if (
            not all(_in_unit_interval(s) for s in parent_scores)
            or not _in_unit_interval(merged_score)
        ):
            return {
                "adapter_merge": "ties_dare",
                "adapter_merge_rejected": (
                    f"merged-adapter checks failed: capability scores outside [0, 1] "
                    f"(parents={parent_scores!r}, merged={merged_score!r})"
                ),
            }

        if verdict.passed is not True:
            return {
                "adapter_merge": "ties_dare",
                "adapter_merge_rejected": (
                    f"abliteration veto: merged adapter deflected probe "
                    f"{verdict.failed_probe!r} (pattern {verdict.matched_pattern!r})"
                ),
                "capability_score_parents": parent_scores,
                "capability_score_merged": merged_score,
            }

        if loss > capability_loss_threshold:
            return {
                "adapter_merge": "ties_dare",
                "adapter_merge_rejected": (
                    f"capability_loss={loss:.4f} > threshold="
                    f"{capability_loss_threshold:.4f}"
                ),
                "capability_score_parents": parent_scores,
                "capability_score_merged": merged_score,
            }

        return None
    except Exception as exc:
        log.exception("TiesDareAdapterMerger: merged-adapter checks failed")
        return {
            "adapter_merge": "ties_dare",
            "adapter_merge_rejected": (
                f"merged-adapter checks failed: {type(exc).__name__}: {exc}"
            ),
        }
