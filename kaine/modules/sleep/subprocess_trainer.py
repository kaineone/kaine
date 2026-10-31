# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Runtime-venv bridge to the voice-alignment trainer script.

``SubprocessVoiceTrainer`` implements the same minimal :class:`Trainer`
protocol as :class:`~kaine.modules.sleep.voice_alignment.FakeTrainer`,
so it drops into the same slot in ``boot.py::make_sleep`` and the sleep module calls it
identically. It runs the real voice-alignment DPO in an operator-configured EXTERNAL
Python environment as a subprocess, or loads the same
``scripts/sleep_external_train.py`` by path and calls its entry point in a
worker thread inside this interpreter when ``run_in_process=True``. The two
environments share nothing but the filesystem. See
``openspec/changes/external-unsloth-trainer/design.md``.

This class:

  1. writes a job directory under ``trainer_workdir`` — ``pairs.jsonl`` (the DPO
     preference pairs) + ``job.json`` (base-model ref, hyper-params, the
     staging dir ``<job_dir>/out`` as the adapter output dir, the probe-set
     paths, a schema version);
  2. either invokes ``trainer_python scripts/sleep_external_train.py <job_dir>``
     as a subprocess with an explicit argv (NO shell), a timeout, and CWD =
     the job dir, or runs ``module.main([entry_script, job_dir])`` in a worker
     thread when ``run_in_process=True``; the trainer stages its candidate
     adapter under ``<job_dir>/out``, never in the entity's store;
  3. validates: exit code 0 / return code 0 AND ``result.json`` passing
     :func:`validate_trainer_result` (for an accepted run: every gate verdict,
     the recomputed abliteration veto, and a non-empty adapter dir inside the
     staging dir);
  4. only then promotes the staged adapter into the entity's store and swings
     ``current`` (:func:`promote_staged_adapter`), and returns a
     :class:`~kaine.modules.sleep.voice_alignment.TrainingResult` of the SAME
     shape on every backend. A refused result never reaches the store, and
     the refusal is written to the voice-alignment audit trail.

Fail loud, never fake: on ANY failure (non-zero exit/return code, timeout,
missing/!ok ``result.json``, a claimed-accepted run with a missing/empty
adapter dir or an adapter dir outside the output tree) it raises
:class:`SubprocessTrainerError`. There is no silent fallback to a no-op
success — that would be a pretend process (the load-bearing no-pretend
principle). A *clean* rejection (``ok=True, accepted=False``) is NOT
an error: it returns ``TrainingResult(accepted=False, ...)`` exactly like the
other backends, carrying the gate verdict reason.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import math
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from kaine.modules.sleep import adapter_store
from kaine.modules.sleep.hot_swap import dispatch as dispatch_hot_swap
from kaine.modules.sleep.voice_alignment import (
    DPOPair,
    TrainingResult,
    VoiceAlignmentConfig,
)
from kaine.modules.sleep.voice_audit import append_voice_audit

log = logging.getLogger(__name__)

#: The external entry script, resolved relative to the repo root (this file is
#: at kaine/modules/sleep/subprocess_trainer.py → parents[3] is the repo root).
EXTERNAL_ENTRY_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "sleep_external_train.py"
)

#: Job-spec schema version written into job.json and echoed in result.json.
#: Version 3: an accepted result carries the base-relative abliteration
#: record, and a result of any other version is refused.
SCHEMA_VERSION = 3

#: Default wall-clock ceiling for one training run (seconds). Training is
#: infrequent (once per consolidation); a generous default avoids killing a
#: legitimately long run while still bounding a hung process.
DEFAULT_TIMEOUT_S = 6 * 60 * 60


class SubprocessTrainerError(RuntimeError):
    """Raised when the trainer fails to produce a valid, verifiable adapter.
    Surfaced to the sleep module as a trainer error — never swallowed into a fake success.
    """


class TrainerResultRefusedError(SubprocessTrainerError):
    """The trainer reported an accepted adapter and the kaine side refused it.

    Raised by :func:`validate_trainer_result` for every check of an accepted
    result. The adapter is staged outside the entity's store and is never
    promoted; callers write the refusal to the voice-alignment audit trail.
    """


#: Directory inside a job directory where the trainer stages its candidate
#: adapter. The kaine side promotes from here into the entity's store only
#: after :func:`validate_trainer_result` accepts the result.
STAGED_ADAPTER_DIR = "out"


#: Environment variables the external trainer may inherit. Everything else,
#: notably KAINE_STATE_KEY, the organ API key and operator tokens, is withheld:
#: the trainer runs third-party code and needs none of them.
TRAINER_ENV_ALLOW: tuple[str, ...] = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TMPDIR",
    "CUDA_VISIBLE_DEVICES",
    "CUDA_HOME",
    "HIP_VISIBLE_DEVICES",
    "ROCR_VISIBLE_DEVICES",
    "LD_LIBRARY_PATH",
    "HF_HOME",
    "TRITON_CACHE_DIR",
)


def trainer_env(base: Optional[dict[str, str]] = None) -> dict[str, str]:
    """The minimal environment for the external trainer process.

    Only :data:`TRAINER_ENV_ALLOW` is passed through, and the Hugging Face
    stack is forced offline: the runtime makes no outbound connections, and
    the trainer loads only local weights.
    """
    source = os.environ if base is None else base
    env = {k: source[k] for k in TRAINER_ENV_ALLOW if k in source}
    env.update(
        {
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_DATASETS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
        }
    )
    return env


def audit_abliteration_from_result(adapter_output_dir: Path | str, result: dict[str, Any]) -> None:
    """Write the abliteration-veto verdict to the voice-alignment audit trail.

    Best-effort: failures are logged but never converted into training errors.
    """
    passed = result.get("abliteration_passed")
    if passed is None:
        return
    matched = result.get("abliteration_matched_pattern")
    scored = result.get("abliteration_probes_scored", 0)
    if passed:
        reason = "abliteration veto passed"
    else:
        reason = str(result.get("reason", "abliteration veto rejected"))
    newly = result.get("abliteration_newly_deflecting")
    base_total = result.get("abliteration_base_deflecting_total")
    adapter_total = result.get("abliteration_adapter_deflecting_total")
    try:
        append_voice_audit(
            adapter_output_dir,
            event="abliteration_veto",
            accepted=bool(passed),
            reason=reason,
            matched_pattern=matched,
            probes_scored=int(scored) if scored is not None else 0,
            newly_deflecting=list(newly) if isinstance(newly, list) else None,
            base_deflecting_total=base_total if isinstance(base_total, int) else None,
            adapter_deflecting_total=(
                adapter_total if isinstance(adapter_total, int) else None
            ),
        )
    except Exception:
        log.exception("failed to append abliteration verdict to voice audit trail")


def audit_trainer_refusal(adapter_output_dir: Path | str, reason: str) -> None:
    """Write a kaine-side refusal of an accepted trainer result to the audit trail.

    Best-effort, like :func:`audit_abliteration_from_result`: a failing write
    is logged, and the refusal still propagates to the caller.
    """
    try:
        append_voice_audit(
            adapter_output_dir,
            event="trainer_result_refused",
            accepted=False,
            reason=reason,
        )
    except Exception:
        log.exception("failed to append trainer refusal to voice audit trail")


def configured_abliteration_probe_count(config: VoiceAlignmentConfig) -> int:
    """Number of probes in the abliteration set this run's job spec names.

    The kaine side checks both scored counts in an accepted result against
    it. An empty or invalid set raises: the veto cannot run without it.
    """
    from kaine.modules.sleep.capability_eval import (
        DEFAULT_ABLITERATION_PROBE_PATH,
        EmptyAbliterationProbeSetError,
        require_non_empty_abliteration_probes,
    )

    path = config.abliteration_probe_path or str(DEFAULT_ABLITERATION_PROBE_PATH)
    try:
        return len(require_non_empty_abliteration_probes(Path(path).resolve()))
    except EmptyAbliterationProbeSetError as exc:
        raise SubprocessTrainerError(str(exc)) from exc


def promote_staged_adapter(staged_dir: Path, store_dir: Path, *, job_dir: Path) -> Path:
    """Copy a validated, staged adapter into the entity's store and point `current` at it.

    Call only after :func:`validate_trainer_result` has accepted the result.
    The copy lands in a ``.tmp`` directory first; :func:`adapter_store.promote`
    then moves it into place and swings ``current``. On any failure the copy is
    removed, ``current`` keeps its previous target, and
    :class:`SubprocessTrainerError` is raised.
    """
    ts = staged_dir.name
    tmp = adapter_store.tmp_dir_for(store_dir, ts)
    final = adapter_store.final_dir_for(store_dir, ts)
    final_existed = final.exists()
    try:
        shutil.copytree(
            staged_dir,
            tmp,
            symlinks=False,
            ignore=shutil.ignore_patterns("checkpoint-*"),
        )
        return adapter_store.promote(tmp, final)
    except Exception as exc:
        if tmp.exists():
            shutil.rmtree(tmp, ignore_errors=True)
        current = adapter_store.current_path(store_dir)
        if (
            not final_existed
            and final.exists()
            and (current is None or current != final.resolve())
        ):
            # Moved into place but `current` never swung to it: remove it so
            # the store holds no adapter that was not promoted.
            shutil.rmtree(final, ignore_errors=True)
        raise SubprocessTrainerError(
            f"adapter promotion failed for {staged_dir}: "
            f"{type(exc).__name__}: {exc} (job {job_dir})"
        ) from exc


def _write_private(path: Path, text: str) -> None:
    """Write ``text`` to ``path`` readable by the owner only (0600)."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        os.fchmod(fh.fileno(), 0o600)
        fh.write(text)


def scrub_job_inputs(job_dir: Path) -> None:
    """Delete a job's sensitive inputs once the trainer has finished with them.

    ``pairs.jsonl`` holds the entity's prompts, utterances and decrypted system
    prompts, and ``previous_adapter/`` is a copy of its learned voice. The
    external trainer cannot import kaine to decrypt, so they are plaintext
    while it runs; they must not outlive the run.
    """
    if job_dir.is_symlink():
        return
    pairs_path = job_dir / "pairs.jsonl"
    try:
        pairs_path.unlink()
    except FileNotFoundError:
        # Already scrubbed: nothing of the pairs is left to remove.
        pass
    shutil.rmtree(job_dir / "previous_adapter", ignore_errors=True)


def _sweep_stale_workdir(
    workdir: Path,
    adapter_output_dir: Optional[Path] = None,
) -> None:
    """Remove leftover sensitive inputs and abandoned temporary adapter dirs.

    Called from ``__init__`` (when we already know the workdir) and from
    ``train()`` (when we also know the adapter output dir so we can sweep
    ``*.tmp``).  Never removes anything else.
    """
    if workdir.exists():
        for entry in workdir.iterdir():
            if entry.is_symlink():
                continue
            if not entry.is_dir():
                continue
            if (entry / "pairs.jsonl").exists() or (entry / "previous_adapter").exists():
                scrub_job_inputs(entry)
    if adapter_output_dir is not None and adapter_output_dir.exists():
        for entry in adapter_output_dir.iterdir():
            if entry.is_symlink():
                continue
            if entry.is_dir() and entry.name.endswith(".tmp"):
                shutil.rmtree(entry, ignore_errors=True)


def _check_relative_abliteration(result: dict[str, Any], job_dir: Path) -> None:
    """Recompute the relative abliteration veto from an accepted result.

    The kaine side does not trust the trainer's ``abliteration_passed`` alone:
    it rebuilds the base and adapter per-probe outcomes from the result,
    applies :func:`relative_abliteration_verdict` itself, and requires the
    reported newly-deflecting list and both totals to agree. A missing or
    malformed outcome fails closed.
    """
    from kaine.modules.sleep.capability_eval import (
        abliteration_outcome_from_record,
        relative_abliteration_verdict,
    )

    if result.get("abliteration_base_error") is not None:
        raise SubprocessTrainerError(
            f"accepted result reports a base-scoring error "
            f"{result.get('abliteration_base_error')!r} (job {job_dir})"
        )
    base = abliteration_outcome_from_record(
        result.get("abliteration_base_deflecting"),
        result.get("abliteration_base_probes_scored"),
    )
    adapter = abliteration_outcome_from_record(
        result.get("abliteration_adapter_deflecting"),
        result.get("abliteration_probes_scored"),
    )
    verdict = relative_abliteration_verdict(base, adapter)
    if not verdict.passed:
        raise SubprocessTrainerError(
            f"accepted result fails the relative abliteration veto: "
            f"{verdict.reason} (job {job_dir})"
        )
    newly = result.get("abliteration_newly_deflecting")
    if newly != []:
        raise SubprocessTrainerError(
            f"accepted result has abliteration_newly_deflecting={newly!r}; "
            f"must be an empty list (job {job_dir})"
        )
    for key, expected in (
        ("abliteration_base_deflecting_total", verdict.base_total),
        ("abliteration_adapter_deflecting_total", verdict.adapter_total),
    ):
        reported = result.get(key)
        if (
            not isinstance(reported, int)
            or isinstance(reported, bool)
            or reported != expected
        ):
            raise SubprocessTrainerError(
                f"accepted result has {key}={reported!r}; its per-probe "
                f"outcome gives {expected!r} (job {job_dir})"
            )


def validate_trainer_result(
    result: dict[str, Any],
    *,
    job_dir: Path,
    adapter_root: Path,
    capability_loss_threshold: float,
    abliteration_probe_count: int,
) -> dict[str, Any]:
    """Strict, single-point validation for every trainer backend.

    A result is accepted only when every gate verdict is exactly what the
    kaine side expects.  A clean rejection (``ok=True, accepted=False``) is
    returned unchanged.  Anything else raises :class:`SubprocessTrainerError`;
    a refused accepted result raises its subclass
    :class:`TrainerResultRefusedError`. ``abliteration_probe_count`` is the
    size of the configured abliteration probe set: an accepted result must
    have scored exactly that many probes on the base and on the adapter.
    """
    if not isinstance(result, dict):
        raise SubprocessTrainerError(
            f"external trainer result.json is not an object (job {job_dir})"
        )

    ok = result.get("ok")

    if ok is not True:
        reason = result.get("reason", "no reason given")
        raise SubprocessTrainerError(
            f"external trainer reported failure: {reason}"
        )

    schema_version = result.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise SubprocessTrainerError(
            f"external trainer result.json schema_version mismatch: "
            f"expected {SCHEMA_VERSION}, got {schema_version!r} (job {job_dir})"
        )

    accepted = result.get("accepted")

    if ok is True and accepted is False:
        return result

    if accepted is not True:
        raise SubprocessTrainerError(
            f"external trainer result has ok=True but accepted={accepted!r}; "
            f"expected a clean rejection (accepted=False) or an accepted result "
            f"(job {job_dir})"
        )

    # From here on the run claims to have produced an accepted adapter. Every
    # check that fails is a kaine-side refusal: the staged adapter is never
    # promoted.
    try:
        _check_accepted_result(
            result,
            job_dir=job_dir,
            adapter_root=adapter_root,
            capability_loss_threshold=capability_loss_threshold,
            abliteration_probe_count=abliteration_probe_count,
        )
    except SubprocessTrainerError as exc:
        raise TrainerResultRefusedError(str(exc)) from exc
    return result


def _check_accepted_result(
    result: dict[str, Any],
    *,
    job_dir: Path,
    adapter_root: Path,
    capability_loss_threshold: float,
    abliteration_probe_count: int,
) -> None:
    """Every check an accepted result must pass; raises on the first failure."""
    if result.get("abliteration_passed") is not True:
        raise SubprocessTrainerError(
            f"accepted result has abliteration_passed="
            f"{result.get('abliteration_passed')!r}; must be True (job {job_dir})"
        )

    scored = result.get("abliteration_probes_scored")
    if not isinstance(scored, int) or isinstance(scored, bool) or scored < 1:
        raise SubprocessTrainerError(
            f"accepted result has abliteration_probes_scored={scored!r}; "
            f"must be an int >= 1 (job {job_dir})"
        )

    _check_relative_abliteration(result, job_dir)

    for key in ("abliteration_probes_scored", "abliteration_base_probes_scored"):
        if result.get(key) != abliteration_probe_count:
            raise SubprocessTrainerError(
                f"accepted result has {key}={result.get(key)!r}; the configured "
                f"abliteration probe set has {abliteration_probe_count} probes "
                f"(job {job_dir})"
            )

    cap_loss = result.get("capability_loss")
    if (
        not isinstance(cap_loss, (int, float))
        or isinstance(cap_loss, bool)
        or not math.isfinite(cap_loss)
    ):
        raise SubprocessTrainerError(
            f"accepted result has non-finite capability_loss {cap_loss!r} "
            f"(job {job_dir})"
        )
    if cap_loss > capability_loss_threshold:
        raise SubprocessTrainerError(
            f"accepted result capability_loss {cap_loss} exceeds threshold "
            f"{capability_loss_threshold} (job {job_dir})"
        )

    adapter_dir = result.get("adapter_dir")
    if not isinstance(adapter_dir, str) or not adapter_dir:
        raise SubprocessTrainerError(
            f"accepted result has missing or non-string adapter_dir "
            f"(job {job_dir})"
        )

    adapter_path = Path(adapter_dir)
    if not adapter_path.is_absolute():
        adapter_path = (job_dir / adapter_path).resolve()
    else:
        adapter_path = adapter_path.resolve()

    root_resolved = adapter_root.resolve()
    if (
        not adapter_path.is_relative_to(root_resolved)
        or adapter_path == root_resolved
    ):
        raise SubprocessTrainerError(
            f"accepted result adapter_dir {adapter_path} is not strictly inside "
            f"adapter_root {root_resolved} (job {job_dir})"
        )

    if not adapter_path.is_dir() or not any(adapter_path.iterdir()):
        raise SubprocessTrainerError(
            f"accepted result adapter_dir {adapter_path} is missing or empty "
            f"(job {job_dir})"
        )

    if not (adapter_path / "adapter_config.json").is_file():
        raise SubprocessTrainerError(
            f"accepted result adapter_dir {adapter_path} has no "
            f"adapter_config.json (job {job_dir})"
        )



def _pair_record(p: DPOPair) -> dict[str, Any]:
    """One pairs.jsonl record. The own-turn fields are written only for an
    own-turn pair, so a plain pair's record is unchanged."""
    record: dict[str, Any] = {
        "prompt": p.prompt,
        "chosen": p.chosen,
        "rejected": p.rejected,
        "system": p.system,
    }
    if p.own_turn:
        record["own_turn"] = True
        if p.user_turn is not None:
            record["user_turn"] = p.user_turn
    return record


def write_job_spec(
    job_dir: Path,
    pairs: list[DPOPair],
    config: VoiceAlignmentConfig,
    *,
    base_path: str,
    adapter_output_dir: str,
) -> None:
    """Write the filesystem job spec consumed by the external trainer.

    ``adapter_output_dir`` is written verbatim (the caller decides whether it is
    an absolute host path or a path relative to the job directory).
    """
    lines = [json.dumps(_pair_record(p)) for p in pairs]
    _write_private(job_dir / "pairs.jsonl", "\n".join(lines) + ("\n" if lines else ""))

    # Resolve probe paths to the same defaults every backend uses so the
    # external gates score against the identical sets. Imported lazily to
    # keep this module's import graph light.
    from kaine.modules.sleep.capability_eval import (
        DEFAULT_ABLITERATION_PROBE_PATH,
        DEFAULT_PROBE_PATH,
    )

    capability_probe_path = (
        config.capability_probe_path or str(DEFAULT_PROBE_PATH)
    )
    abliteration_probe_path = (
        config.abliteration_probe_path or str(DEFAULT_ABLITERATION_PROBE_PATH)
    )

    adapter_store_dir = Path(config.adapter_output_dir)
    current = adapter_store.current_path(adapter_store_dir)
    current_link = adapter_store_dir / "current"
    previous_adapter_dir = None
    if current_link.is_symlink() or current_link.exists():
        if current is None:
            raise SubprocessTrainerError(
                f"the entity's current adapter could not be read ({current_link} "
                "does not resolve); refusing to train a fresh adapter in its place"
            )
        try:
            shutil.copytree(current, job_dir / "previous_adapter")
        except Exception as exc:
            raise SubprocessTrainerError(
                f"the entity's current adapter could not be read ({current}: "
                f"{type(exc).__name__}: {exc}); refusing to train a fresh adapter "
                "in its place"
            ) from exc
        previous_adapter_dir = "previous_adapter"

    job = {
        "schema_version": SCHEMA_VERSION,
        "base_model_path": str(base_path),
        "adapter_output_dir": str(adapter_output_dir),
        "previous_adapter_dir": previous_adapter_dir,
        "train_precision": str(config.train_precision),
        "lora_rank": int(config.lora_rank),
        "learning_rate": float(config.learning_rate),
        "dpo_beta": float(config.dpo_beta),
        "seed": int(config.seed),
        "max_samples": int(config.max_samples),
        "training_device": str(config.training_device),
        "capability_loss_threshold": float(config.capability_loss_threshold),
        "capability_probe_path": str(Path(capability_probe_path).resolve()),
        "abliteration_probe_path": str(Path(abliteration_probe_path).resolve()),
    }
    _write_private(job_dir / "job.json", json.dumps(job, indent=2))


def _read_result(job_dir: Path) -> dict[str, Any]:
    """Read and minimally validate result.json from a finished job directory."""
    result_path = job_dir / "result.json"
    if not result_path.is_file():
        raise SubprocessTrainerError(
            f"external trainer wrote no result.json (job {job_dir})"
        )
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SubprocessTrainerError(
            f"external trainer result.json is unreadable: "
            f"{type(exc).__name__}: {exc} (job {job_dir})"
        ) from exc
    if not isinstance(data, dict):
        raise SubprocessTrainerError(
            f"external trainer result.json is not an object (job {job_dir})"
        )
    return data


def result_to_training_result(
    result: dict[str, Any],
    *,
    samples_used: int,
    adapter_path: Optional[Path],
    metadata: Optional[dict[str, Any]] = None,
) -> TrainingResult:
    """Map a validated result.json object to the canonical TrainingResult.

    Keeps every existing validation message and field-mapping behaviour.
    """
    if not isinstance(result, dict):
        raise SubprocessTrainerError(
            "external trainer result.json is not an object"
        )

    accepted = result.get("accepted") is True
    if accepted:
        if adapter_path is None:
            raise SubprocessTrainerError(
                "external trainer reported accepted but no adapter_path mapped"
            )
        if not adapter_path.is_dir() or not any(adapter_path.iterdir()):
            raise SubprocessTrainerError(
                f"external trainer reported adapter_path {adapter_path} but it "
                f"is missing or empty"
            )

    def _maybe_float(key: str) -> Optional[float]:
        val = result.get(key)
        if val is None:
            return None
        if isinstance(val, bool) or not isinstance(val, (int, float)):
            raise SubprocessTrainerError(
                f"external trainer result {key} is not a finite numeric value: {val!r}"
            )
        return float(val)

    final_metadata: dict[str, Any] = dict(metadata or {})
    final_metadata.setdefault(
        "steps", int(result.get("steps", 0))
    )

    return TrainingResult(
        accepted=accepted,
        adapter_path=adapter_path,
        # The measured loss is reported on every outcome (a rejection's
        # evidence); an accepted result was already validated as finite.
        capability_loss=_maybe_float("capability_loss") or 0.0,
        reason=str(result.get("reason", "")),
        samples_used=int(result.get("samples_used", samples_used)),
        dpo_loss=_maybe_float("dpo_loss"),
        capability_score_before=_maybe_float("capability_score_before"),
        capability_score_after=_maybe_float("capability_score_after"),
        metadata=final_metadata,
    )


class SubprocessVoiceTrainer:
    """Runtime-venv bridge to the voice-alignment trainer script.

    Constructed by ``boot.py::make_sleep`` when
    ``[sleep.voice_alignment].trainer_backend`` is ``"subprocess"`` or
    ``"in_process"``. The two-layer operator gate (config ``enabled`` + the
    approval env var) is enforced by the orchestrator before ``train`` is ever
    called.
    """

    def __init__(
        self,
        *,
        trainer_python: Optional[str] = None,
        trainer_workdir: Path | str,
        run_in_process: bool = False,
        entry_script: Path | str = EXTERNAL_ENTRY_SCRIPT,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        if not run_in_process and trainer_python is None:
            raise ValueError("trainer_python is required when run_in_process is False")
        self._trainer_python = trainer_python
        self._trainer_workdir = Path(trainer_workdir)
        self.run_in_process = run_in_process
        self._entry_script = Path(entry_script)
        self._timeout_s = float(timeout_s)
        self._inprocess_module: Any = None
        _sweep_stale_workdir(self._trainer_workdir)

    async def train(
        self,
        pairs: list[DPOPair],
        config: VoiceAlignmentConfig,
    ) -> TrainingResult:
        if not pairs:
            return TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason="no DPO pairs to train on",
                samples_used=0,
            )
        base_path = config.base_model_path
        if not base_path:
            raise SubprocessTrainerError(
                "SubprocessVoiceTrainer needs base_model_path; set "
                "[sleep.voice_alignment].base_model_path"
            )

        _sweep_stale_workdir(
            self._trainer_workdir, Path(config.adapter_output_dir)
        )

        store_dir = Path(config.adapter_output_dir)
        probe_count = configured_abliteration_probe_count(config)
        job_dir = self._make_job_dir()
        # The trainer stages its candidate inside the job directory; the
        # entity's store and its `current` link change only below, after the
        # result passes validation.
        stage_dir = job_dir / STAGED_ADAPTER_DIR
        adapter_path: Optional[Path] = None
        try:
            try:
                write_job_spec(
                    job_dir,
                    pairs,
                    config,
                    base_path=base_path,
                    adapter_output_dir=str(stage_dir.resolve()),
                )
                run = self._run_in_process if self.run_in_process else self._run_subprocess
                result = await run(
                    job_dir,
                    samples_used=len(pairs),
                    adapter_root=stage_dir,
                    capability_loss_threshold=float(config.capability_loss_threshold),
                    abliteration_probe_count=probe_count,
                )
                audit_abliteration_from_result(store_dir, result)
            except TrainerResultRefusedError as exc:
                audit_trainer_refusal(store_dir, str(exc))
                raise
            finally:
                scrub_job_inputs(job_dir)

            if result.get("accepted") is True:
                staged = Path(str(result.get("adapter_dir"))).resolve()
                adapter_path = promote_staged_adapter(staged, store_dir, job_dir=job_dir)
        finally:
            # Nothing staged outlives the run: a refused or failed candidate is
            # gone, and an accepted one now lives in the store.
            shutil.rmtree(stage_dir, ignore_errors=True)

        hot_swap_status: Optional[dict[str, Any]] = None
        if result.get("accepted") is True and config.hot_swap_mode != "organ_adapter":
            # Boot refuses organ_adapter for non-job-queue backends; guard defensively.
            try:
                hot_swap_status = await dispatch_hot_swap(
                    mode=config.hot_swap_mode,
                    adapter_output_dir=Path(config.adapter_output_dir),
                    adapter_path=adapter_path,
                    reload_endpoint_url=config.reload_endpoint_url,
                    restart_service_unit=config.restart_service_unit,
                )
            except Exception:
                log.exception("hot_swap dispatch raised; adapter remains promoted")
                hot_swap_status = {"mode": config.hot_swap_mode, "ok": False}

        evicted: list[Path] = []
        if result.get("accepted") is True and int(config.adapter_retention) > 0:
            try:
                evicted = adapter_store.prune(
                    Path(config.adapter_output_dir),
                    keep=int(config.adapter_retention),
                )
            except Exception:
                log.exception("adapter retention prune failed")

        metadata: dict[str, Any] = {
            "backend": "in_process" if self.run_in_process else "subprocess",
        }
        if hot_swap_status is not None:
            metadata["hot_swap"] = hot_swap_status
        if evicted:
            metadata["evicted_adapters"] = [str(p) for p in evicted]

        return result_to_training_result(
            result,
            samples_used=len(pairs),
            adapter_path=adapter_path,
            metadata=metadata,
        )

    # --------------------------------------------------------------------- #
    # job-spec writing
    # --------------------------------------------------------------------- #
    def _make_job_dir(self) -> Path:
        stamp = time.strftime("%Y%m%dT%H%M%S")
        job_dir = self._trainer_workdir / f"job-{stamp}-{int(time.time() * 1000) % 1000:03d}"
        self._trainer_workdir.mkdir(parents=True, mode=0o700, exist_ok=True)
        job_dir.mkdir(mode=0o700, exist_ok=True)
        os.chmod(job_dir, 0o700)
        return job_dir

    # --------------------------------------------------------------------- #
    # subprocess invocation
    # --------------------------------------------------------------------- #
    async def _run_subprocess(
        self,
        job_dir: Path,
        *,
        samples_used: int,
        adapter_root: Path,
        capability_loss_threshold: float,
        abliteration_probe_count: int,
    ) -> dict[str, Any]:
        assert self._trainer_python is not None
        if not self._entry_script.is_file():
            raise SubprocessTrainerError(
                f"external trainer entry script missing: {self._entry_script}"
            )
        argv = [self._trainer_python, str(self._entry_script), str(job_dir)]
        log.info(
            "voice alignment: launching external trainer (%s) in %s",
            self._trainer_python,
            job_dir,
        )
        try:
            proc = await asyncio.to_thread(
                subprocess.run,
                argv,
                cwd=str(job_dir),  # the trainer runs inside its own job dir
                env=trainer_env(),
                capture_output=True,
                text=True,
                timeout=self._timeout_s,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SubprocessTrainerError(
                f"external trainer timed out after {self._timeout_s:.0f}s "
                f"(job {job_dir})"
            ) from exc
        except OSError as exc:
            raise SubprocessTrainerError(
                f"external trainer could not be launched ({self._trainer_python}): "
                f"{type(exc).__name__}: {exc}"
            ) from exc

        if proc.returncode != 0:
            tail = (proc.stderr or proc.stdout or "")[-2000:]
            raise SubprocessTrainerError(
                f"external trainer exited {proc.returncode} (job {job_dir}). "
                f"stderr tail:\n{tail}"
            )

        result = _read_result(job_dir)
        return validate_trainer_result(
            result,
            job_dir=job_dir,
            adapter_root=adapter_root,
            capability_loss_threshold=capability_loss_threshold,
            abliteration_probe_count=abliteration_probe_count,
        )

    # --------------------------------------------------------------------- #
    # in-process invocation
    # --------------------------------------------------------------------- #
    async def _run_in_process(
        self,
        job_dir: Path,
        *,
        samples_used: int,
        adapter_root: Path,
        capability_loss_threshold: float,
        abliteration_probe_count: int,
    ) -> dict[str, Any]:
        if not self._entry_script.is_file():
            raise SubprocessTrainerError(
                f"in-process trainer entry script missing: {self._entry_script}"
            )

        if self._inprocess_module is None:
            spec = importlib.util.spec_from_file_location(
                "kaine_inprocess_trainer_script", self._entry_script
            )
            if spec is None or spec.loader is None:
                raise SubprocessTrainerError(
                    f"could not create module spec for {self._entry_script}"
                )
            module = importlib.util.module_from_spec(spec)
            self._inprocess_module = module
            try:
                spec.loader.exec_module(module)
            except Exception as exc:
                self._inprocess_module = None
                raise SubprocessTrainerError(
                    f"in-process trainer script failed to load: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc

        log.info(
            "voice alignment: running trainer script in-process (%s) for %s",
            self._entry_script,
            job_dir,
        )
        try:
            rc = await asyncio.wait_for(
                asyncio.to_thread(
                    self._inprocess_module.main,
                    [str(self._entry_script), str(job_dir)],
                ),
                timeout=self._timeout_s,
            )
        except asyncio.TimeoutError as exc:
            (job_dir / "CANCELLED").write_text("", encoding="utf-8")
            raise SubprocessTrainerError(
                f"in-process trainer timed out after {self._timeout_s:.0f}s; "
                "the training thread cannot be killed and may still hold the GPU"
            ) from exc
        except Exception as exc:
            raise SubprocessTrainerError(
                f"in-process trainer raised {type(exc).__name__}: {exc}"
            ) from exc

        if rc != 0:
            # The script writes a crash result before returning non-zero;
            # carry its reason so the failure is diagnosable.
            reason = "no result.json"
            try:
                reason = str(_read_result(job_dir).get("reason") or reason)
            except Exception:
                # No readable result: keep "no result.json" as the reason.
                pass
            raise SubprocessTrainerError(
                f"in-process trainer exited {rc} (job {job_dir}): {reason}"
            )

        result = _read_result(job_dir)
        return validate_trainer_result(
            result,
            job_dir=job_dir,
            adapter_root=adapter_root,
            capability_loss_threshold=capability_loss_threshold,
            abliteration_probe_count=abliteration_probe_count,
        )
