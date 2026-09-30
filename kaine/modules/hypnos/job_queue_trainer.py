# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Job-queue voice-alignment trainer (containerized cycle side).

JobQueueVoiceTrainer implements the same minimal Trainer protocol as
:class:`~kaine.modules.hypnos.subprocess_trainer.SubprocessVoiceTrainer` and the
in-process trainer, so it drops into the same slot in ``boot.py::make_hypnos``.
Instead of running unsloth itself, it writes the same filesystem job spec into a
shared jobs directory, marks the directory READY, and polls asynchronously for
``result.json`` produced by the ``kaine-trainer`` container service.

Fail loud, never fake: timeouts, failed ``result.json``, and adapter-dir
containment violations raise :class:`SubprocessTrainerError`. Clean rejections
(``ok=True, accepted=False``) return a ``TrainingResult`` with ``accepted=False``.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import shutil
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from kaine.modules.hypnos import adapter_store, hot_swap
from kaine.modules.hypnos.subprocess_trainer import (
    SubprocessTrainerError,
    _read_result,
    result_to_training_result,
    write_job_spec,
)
from kaine.modules.hypnos.voice_alignment import (
    DPOPair,
    TrainingResult,
    VoiceAlignmentConfig,
)

log = logging.getLogger(__name__)


class JobQueueVoiceTrainer:
    """Runtime-venv bridge to the kaine-trainer container service."""

    def __init__(
        self,
        *,
        jobs_dir: Path | str,
        timeout_s: float,
        poll_interval_s: float = 2.0,
        organ_adapters_dir: Optional[Path] = None,
        organ_url: Optional[str] = None,
        organ_api_key: Optional[str] = None,
    ) -> None:
        self._jobs_dir = Path(jobs_dir)
        self._timeout_s = float(timeout_s)
        self._poll_interval_s = float(poll_interval_s)
        if self._timeout_s <= 0:
            raise ValueError("timeout_s must be > 0")
        self._organ_adapters_dir = organ_adapters_dir
        self._organ_url = organ_url
        self._organ_api_key = organ_api_key

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
                "JobQueueVoiceTrainer needs base_model_path; set "
                "[hypnos.voice_alignment].base_model_path"
            )

        job_dir = self._make_job_dir()
        job_name = job_dir.name
        out_dir = Path(config.adapter_output_dir)

        write_job_spec(
            job_dir,
            pairs,
            config,
            base_path=base_path,
            adapter_output_dir="out",
        )

        self._write_ready_atomic(job_dir)

        try:
            result = await self._poll_for_result(job_dir, job_name)
        finally:
            self._delete_pairs(job_dir)

        if not result.get("ok"):
            raise SubprocessTrainerError(
                f"external trainer reported failure (ok != true): "
                f"{result.get('reason', 'no reason given')} (job {job_dir})"
            )

        if not result.get("accepted"):
            return result_to_training_result(
                result,
                samples_used=len(pairs),
                adapter_path=None,
                metadata={"backend": "job_queue"},
            )

        adapter_dir, final = self._promote_adapter(result, job_dir, out_dir)

        hot_swap_status: dict[str, Any] = {
            "mode": config.hot_swap_mode,
            "ok": True,
        }
        try:
            hot_swap_status = await hot_swap.dispatch(
                mode=config.hot_swap_mode,
                adapter_output_dir=out_dir,
                adapter_path=final,
                reload_endpoint_url=config.reload_endpoint_url,
                restart_service_unit=config.restart_service_unit,
                organ_adapters_dir=self._organ_adapters_dir,
                organ_url=self._organ_url,
                organ_api_key=self._organ_api_key,
            )
        except Exception:
            log.warning(
                "voice alignment: hot-swap failed after adapter promotion",
                exc_info=True,
            )
            hot_swap_status = {"mode": config.hot_swap_mode, "ok": False}

        metadata: dict[str, Any] = {
            "backend": "job_queue",
            "hot_swap": hot_swap_status,
        }
        return result_to_training_result(
            result,
            samples_used=len(pairs),
            adapter_path=final,
            metadata=metadata,
        )

    # --------------------------------------------------------------------- #
    # job directory lifecycle
    # --------------------------------------------------------------------- #
    def _make_job_dir(self) -> Path:
        stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        job_id = f"{stamp}-{uuid.uuid4().hex[:8]}"
        self._jobs_dir.mkdir(parents=True, mode=0o700, exist_ok=True)
        job_dir = self._jobs_dir / job_id
        job_dir.mkdir(mode=0o700, exist_ok=True)
        return job_dir

    def _write_ready_atomic(self, job_dir: Path) -> None:
        ready_tmp = job_dir / "READY.tmp"
        ready = job_dir / "READY"
        ready_tmp.write_text("", encoding="utf-8")
        os.replace(ready_tmp, ready)

    def _write_cancelled(self, job_dir: Path) -> None:
        (job_dir / "CANCELLED").write_text("", encoding="utf-8")

    def _delete_pairs(self, job_dir: Path) -> None:
        pairs_path = job_dir / "pairs.jsonl"
        if pairs_path.exists():
            pairs_path.unlink()

    # --------------------------------------------------------------------- #
    # polling + result validation
    # --------------------------------------------------------------------- #
    async def _poll_for_result(
        self, job_dir: Path, job_name: str
    ) -> dict[str, Any]:
        result_path = job_dir / "result.json"
        deadline = time.monotonic() + self._timeout_s
        while True:
            if result_path.exists():
                return _read_result(job_dir)
            if time.monotonic() >= deadline:
                self._write_cancelled(job_dir)
                raise SubprocessTrainerError(
                    f"did not finish job {job_name} within "
                    f"{self._timeout_s:.0f} s (is the kaine-trainer service running?)"
                )
            await asyncio.sleep(self._poll_interval_s)

    def _resolve_validated_adapter_dir(
        self, result: dict[str, Any], job_dir: Path
    ) -> Path:
        job_dir_resolved = job_dir.resolve()
        adapter_dir_rel = result.get("adapter_dir")
        if not adapter_dir_rel:
            raise SubprocessTrainerError(
                f"external trainer reported accepted but no adapter_dir "
                f"(job {job_dir})"
            )
        adapter_dir = (job_dir / str(adapter_dir_rel)).resolve()
        if not adapter_dir.is_relative_to(job_dir_resolved):
            raise SubprocessTrainerError(
                f"external trainer reported adapter_dir {adapter_dir} which is "
                f"outside the job directory {job_dir_resolved} (job {job_dir})"
            )
        if not adapter_dir.is_dir() or not any(adapter_dir.iterdir()):
            raise SubprocessTrainerError(
                f"external trainer reported adapter_dir {adapter_dir} but it "
                f"is missing or empty (job {job_dir})"
            )

        gguf_file = adapter_dir / "adapter.gguf"
        if not gguf_file.is_file():
            raise SubprocessTrainerError(
                f"external trainer reported adapter_dir {adapter_dir} but it "
                f"does not contain adapter.gguf (job {job_dir})"
            )

        expected_sha = result.get("gguf_sha256")
        if expected_sha:
            actual_sha = _sha256_file(gguf_file)
            if actual_sha != expected_sha:
                raise SubprocessTrainerError(
                    f"adapter.gguf sha256 mismatch for {adapter_dir}: "
                    f"expected {expected_sha}, got {actual_sha} (job {job_dir})"
                )
        return adapter_dir

    # --------------------------------------------------------------------- #
    # promotion
    # --------------------------------------------------------------------- #
    def _promote_adapter(
        self,
        result: dict[str, Any],
        job_dir: Path,
        out_dir: Path,
    ) -> tuple[Path, Path]:
        adapter_dir = self._resolve_validated_adapter_dir(result, job_dir)
        ts = adapter_dir.name
        tmp = adapter_store.tmp_dir_for(out_dir, ts)
        final = adapter_store.final_dir_for(out_dir, ts)

        try:
            shutil.copytree(
                adapter_dir,
                tmp,
                symlinks=False,
                ignore=shutil.ignore_patterns("checkpoint-*"),
            )
            final = adapter_store.promote(tmp, final)
        except Exception as exc:
            if tmp.exists():
                shutil.rmtree(tmp, ignore_errors=True)
            raise SubprocessTrainerError(
                f"adapter promotion failed for {adapter_dir}: "
                f"{type(exc).__name__}: {exc} (job {job_dir})"
            ) from exc
        return adapter_dir, final


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()
