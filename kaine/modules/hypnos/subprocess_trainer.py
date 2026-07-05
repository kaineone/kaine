# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Out-of-process voice-alignment trainer (the kaine-side bridge).

``SubprocessVoiceTrainer`` implements the same minimal :class:`Trainer`
protocol as :class:`~kaine.modules.hypnos.unsloth_trainer.UnslothDPOTrainer`,
so it drops into the same slot in ``boot.py::make_hypnos`` and Hypnos calls it
identically. It runs the real unsloth DPO in an operator-configured EXTERNAL
Python environment as a subprocess, because the trainer's torch/CUDA stack is
incompatible with the entity-runtime venv (different Python ABI, different
torch/CUDA). See ``openspec/changes/external-unsloth-trainer/design.md``.

The two environments share nothing but the filesystem. This class:

  1. writes a job directory under ``trainer_workdir`` — ``pairs.jsonl`` (the DPO
     preference pairs) + ``job.json`` (base-model ref, hyper-params, adapter
     output dir, the probe-set paths, a schema version);
  2. invokes ``trainer_python scripts/hypnos_external_train.py <job_dir>`` with
     an explicit argv (NO shell), a timeout, and CWD = the job dir (so unsloth's
     ``unsloth_compiled_cache/`` lands in the job dir, not the repo);
  3. validates: exit code 0 AND ``result.json.ok`` AND a non-empty adapter dir
     (when the run reports acceptance) → returns a
     :class:`~kaine.modules.hypnos.voice_alignment.TrainingResult` of the SAME
     shape the in-process trainer returns, so the downstream summary/telemetry
     in ``module.py`` is unchanged.

Fail loud, never fake: on ANY failure (non-zero exit, timeout, missing/!ok
``result.json``, a claimed-accepted run with a missing/empty adapter dir) it
raises :class:`SubprocessTrainerError`. There is no silent fallback to a no-op
success — that would be a pretend process (the load-bearing no-pretend
principle). A *clean* rejection (the external gates rejected the adapter) is NOT
an error: it returns ``TrainingResult(accepted=False, ...)`` exactly as the
in-process trainer does, carrying the gate verdict reason.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Any, Optional

from kaine.modules.hypnos.voice_alignment import (
    DPOPair,
    TrainingResult,
    VoiceAlignmentConfig,
)

log = logging.getLogger(__name__)

#: The external entry script, resolved relative to the repo root (this file is
#: at kaine/modules/hypnos/subprocess_trainer.py → parents[3] is the repo root).
EXTERNAL_ENTRY_SCRIPT = (
    Path(__file__).resolve().parents[3] / "scripts" / "hypnos_external_train.py"
)

#: Job-spec schema version written into job.json and echoed in result.json.
SCHEMA_VERSION = 1

#: Default wall-clock ceiling for one training subprocess (seconds). Training is
#: infrequent (once per consolidation); a generous default avoids killing a
#: legitimately long run while still bounding a hung process.
DEFAULT_TIMEOUT_S = 6 * 60 * 60


class SubprocessTrainerError(RuntimeError):
    """Raised when the external training subprocess fails to produce a valid,
    verifiable adapter. Surfaced to Hypnos as a trainer error — never swallowed
    into a fake success."""


class SubprocessVoiceTrainer:
    """Runtime-venv bridge to an external unsloth trainer env.

    Constructed by ``boot.py::make_hypnos`` when
    ``[hypnos.voice_alignment].trainer_backend == "subprocess"``. The two-layer
    operator gate (config ``enabled`` + the approval env var) is enforced by the
    orchestrator before ``train`` is ever called, exactly as for the in-process
    trainer.
    """

    def __init__(
        self,
        *,
        trainer_python: str,
        trainer_workdir: Path | str,
        entry_script: Path | str = EXTERNAL_ENTRY_SCRIPT,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self._trainer_python = str(trainer_python)
        self._trainer_workdir = Path(trainer_workdir)
        self._entry_script = Path(entry_script)
        self._timeout_s = float(timeout_s)

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
                "[hypnos.voice_alignment].base_model_path"
            )

        job_dir = self._make_job_dir()
        self._write_pairs(job_dir, pairs)
        self._write_job(job_dir, config, base_path=base_path)

        result = self._run_subprocess(job_dir, samples_used=len(pairs))
        return self._to_training_result(result, samples_used=len(pairs))

    # --------------------------------------------------------------------- #
    # job-spec writing
    # --------------------------------------------------------------------- #
    def _make_job_dir(self) -> Path:
        stamp = time.strftime("%Y%m%dT%H%M%S")
        job_dir = self._trainer_workdir / f"job-{stamp}-{int(time.time() * 1000) % 1000:03d}"
        job_dir.mkdir(parents=True, exist_ok=True)
        return job_dir

    def _write_pairs(self, job_dir: Path, pairs: list[DPOPair]) -> None:
        lines = [
            json.dumps({"prompt": p.prompt, "chosen": p.chosen, "rejected": p.rejected})
            for p in pairs
        ]
        (job_dir / "pairs.jsonl").write_text(
            "\n".join(lines) + ("\n" if lines else ""), encoding="utf-8"
        )

    def _write_job(
        self, job_dir: Path, config: VoiceAlignmentConfig, *, base_path: str
    ) -> None:
        # Resolve probe paths to the same defaults the in-process trainer uses so
        # the external gates score against the identical sets. Imported lazily to
        # keep this module's import graph light.
        from kaine.modules.hypnos.capability_eval import (
            DEFAULT_ABLITERATION_PROBE_PATH,
            DEFAULT_PROBE_PATH,
        )

        capability_probe_path = (
            config.capability_probe_path or str(DEFAULT_PROBE_PATH)
        )
        abliteration_probe_path = (
            config.abliteration_probe_path or str(DEFAULT_ABLITERATION_PROBE_PATH)
        )
        job = {
            "schema_version": SCHEMA_VERSION,
            "base_model_path": str(base_path),
            "adapter_output_dir": str(config.adapter_output_dir.resolve()),
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
        (job_dir / "job.json").write_text(
            json.dumps(job, indent=2), encoding="utf-8"
        )

    # --------------------------------------------------------------------- #
    # subprocess invocation + validation
    # --------------------------------------------------------------------- #
    def _run_subprocess(self, job_dir: Path, *, samples_used: int) -> dict[str, Any]:
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
            proc = subprocess.run(
                argv,
                cwd=str(job_dir),  # unsloth_compiled_cache/ lands in the job dir
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

        result = self._read_result(job_dir)
        if not result.get("ok"):
            raise SubprocessTrainerError(
                f"external trainer reported failure (ok != true): "
                f"{result.get('reason', 'no reason given')} (job {job_dir})"
            )

        # A claimed-accepted run MUST have produced a non-empty adapter dir.
        if result.get("accepted"):
            adapter_dir = result.get("adapter_dir")
            if not adapter_dir:
                raise SubprocessTrainerError(
                    f"external trainer reported accepted but no adapter_dir "
                    f"(job {job_dir})"
                )
            adapter_path = Path(adapter_dir)
            if not adapter_path.is_dir() or not any(adapter_path.iterdir()):
                raise SubprocessTrainerError(
                    f"external trainer reported adapter_dir {adapter_path} but it "
                    f"is missing or empty (job {job_dir})"
                )
        return result

    def _read_result(self, job_dir: Path) -> dict[str, Any]:
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

    # --------------------------------------------------------------------- #
    # result mapping
    # --------------------------------------------------------------------- #
    def _to_training_result(
        self, result: dict[str, Any], *, samples_used: int
    ) -> TrainingResult:
        accepted = bool(result.get("accepted"))
        adapter_dir = result.get("adapter_dir")
        adapter_path: Optional[Path] = (
            Path(adapter_dir) if (accepted and adapter_dir) else None
        )

        def _maybe_float(key: str) -> Optional[float]:
            val = result.get(key)
            return None if val is None else float(val)

        cap_loss_raw = result.get("capability_loss")
        capability_loss = 0.0 if cap_loss_raw is None else float(cap_loss_raw)
        return TrainingResult(
            accepted=accepted,
            adapter_path=adapter_path,
            capability_loss=capability_loss,
            reason=str(result.get("reason", "")),
            samples_used=int(result.get("samples_used", samples_used)),
            dpo_loss=_maybe_float("dpo_loss"),
            capability_score_before=_maybe_float("capability_score_before"),
            capability_score_after=_maybe_float("capability_score_after"),
            metadata={
                "backend": "subprocess",
                "steps": int(result.get("steps", 0)),
            },
        )
