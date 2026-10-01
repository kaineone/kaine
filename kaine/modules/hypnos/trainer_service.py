# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Lightweight trainer-service job runner for the ``kaine-trainer`` container.

This module runs inside the trainer container and polls a shared jobs volume for
voice-alignment training jobs written by the KAINE cycle. It sees only the jobs
volume — never entity state — and does not need access to the Docker socket or
to host network ports. For each job it waits until the organ reports itself
asleep and the training GPU has enough free VRAM, then invokes the external
training script, optionally converts a promoted adapter to GGUF, writes
``result.json``, and deletes the job's preference pairs. The preference pairs are
entity language and are removed as soon as a job ends, regardless of outcome.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

LOGGER = logging.getLogger("kaine_trainer_service")


# --------------------------------------------------------------------------- #
# public API used by the service loop and by tests
# --------------------------------------------------------------------------- #
def find_ready_jobs(jobs_dir: Path | str) -> list[Path]:
    """Return direct, non-symlinked job directories that are ready to run.

    A directory is ready when it contains a regular (non-symlink) ``READY`` file
    and does not contain ``CLAIMED``, ``CANCELLED`` or ``result.json``.
    """
    root = Path(jobs_dir)
    ready: list[Path] = []
    for entry in root.iterdir():
        if not entry.is_dir() or entry.is_symlink():
            continue
        ready_file = entry / "READY"
        if not ready_file.is_file() or ready_file.is_symlink():
            continue
        if (
            (entry / "CLAIMED").exists()
            or (entry / "CANCELLED").exists()
            or (entry / "result.json").exists()
        ):
            continue
        ready.append(entry)
    return sorted(ready, key=lambda p: p.name)


def claim(job_dir: Path | str) -> bool:
    """Atomically rename ``READY`` to ``CLAIMED``; return True iff we won."""
    src = Path(job_dir) / "READY"
    dst = Path(job_dir) / "CLAIMED"
    try:
        os.rename(src, dst)
    except OSError:
        return False
    return True


def wait_for_device(
    organ_probe: Callable[[], bool],
    vram_probe: Callable[[], int],
    *,
    min_free_mib: int,
    wait_s: float,
    poll_s: float,
    sleep: Callable[[float], Any],
    clock: Callable[[], float],
) -> tuple[bool, str]:
    """Wait until the organ is asleep and the training device has enough VRAM.

    Returns ``(True, status)`` once both conditions hold, or ``(False, reason)``
    after ``wait_s`` have elapsed, where ``reason`` names the failing condition
    and the last observed values.
    """
    start = clock()

    while True:
        try:
            organ_ok = organ_probe()
            organ_reason = "awake" if not organ_ok else "asleep"
        except Exception as exc:  # noqa: BLE001 - collapse probe errors to status
            organ_ok = False
            organ_reason = type(exc).__name__

        try:
            vram = vram_probe()
        except Exception:  # noqa: BLE001
            vram = 0

        if organ_ok and vram >= min_free_mib:
            return (True, f"organ asleep, {vram} MiB free")

        elapsed = clock() - start
        if elapsed >= wait_s:
            parts: list[str] = []
            if not organ_ok:
                parts.append(f"organ awake ({organ_reason})")
            if vram < min_free_mib:
                parts.append(
                    f"insufficient VRAM: {vram} MiB free (need {min_free_mib})"
                )
            return (False, "; ".join(parts))

        remaining = max(0.0, min(poll_s, wait_s - elapsed))
        sleep(remaining)


def run_job(
    job_dir: Path | str,
    cfg: Any,
    runner: Callable[..., Any],
    organ_probe: Callable[[], bool],
    vram_probe: Callable[[], int],
    sleep: Callable[[float], Any],
    clock: Callable[[], float],
) -> dict[str, Any]:
    """Run a single claimed job and write its ``result.json``.

    This function never raises: every claimed job ends with a ``result.json``.
    The job's ``pairs.jsonl`` is always deleted before returning.
    """
    job_dir = Path(job_dir)

    def _finalize(result: dict[str, Any]) -> dict[str, Any]:
        pairs = job_dir / "pairs.jsonl"
        if pairs.exists() or pairs.is_symlink():
            try:
                pairs.unlink()
            except OSError:
                LOGGER.error("could not delete preference pairs %s; delete it by hand — it holds entity language", pairs, exc_info=True)
        tmp = job_dir / "result.json.tmp"
        out = job_dir / "result.json"
        tmp.write_text(json.dumps(result, indent=2), encoding="utf-8")
        os.replace(tmp, out)
        return result

    try:
        job_file = job_dir / "job.json"
        pairs_file = job_dir / "pairs.jsonl"

        if (
            job_file.is_symlink()
            or not job_file.is_file()
            or pairs_file.is_symlink()
            or not pairs_file.is_file()
        ):
            return _finalize(
                {"ok": False, "reason": "symlinked or missing job file"}
            )

        job = json.loads(job_file.read_text(encoding="utf-8"))

        adapter_output_dir = (job_dir / job["adapter_output_dir"]).resolve()
        if not _is_inside(adapter_output_dir, job_dir.resolve()):
            return _finalize(
                {
                    "ok": False,
                    "reason": "adapter_output_dir outside the job directory",
                }
            )

        ready, reason = wait_for_device(
            organ_probe,
            vram_probe,
            min_free_mib=cfg.min_free_mib,
            wait_s=cfg.organ_wait_s,
            poll_s=cfg.poll_s,
            sleep=sleep,
            clock=clock,
        )
        if not ready:
            return _finalize({"ok": False, "reason": reason})

        # Run the external training script.
        train_cmd = [
            cfg.trainer_python,
            str(cfg.train_script),
            str(job_dir),
        ]
        train_rc: int | None = None
        try:
            train_res = runner(train_cmd, cwd=job_dir, timeout=cfg.job_timeout_s)
            train_rc = train_res.returncode
        except subprocess.TimeoutExpired:
            return _finalize({"ok": False, "reason": "training timed out"})

        result_path = job_dir / "result.json"
        if train_rc != 0 or not result_path.is_file():
            return _finalize(
                {
                    "ok": False,
                    "reason": f"training exited {train_rc} without a valid result.json",
                }
            )

        try:
            result: dict[str, Any] = json.loads(
                result_path.read_text(encoding="utf-8")
            )
        except Exception:  # noqa: BLE001
            return _finalize(
                {
                    "ok": False,
                    "reason": f"training exited {train_rc} without a valid result.json",
                }
            )

        # Optional GGUF conversion for a promoted, in-job adapter.
        if result.get("ok") and result.get("adapter_dir"):
            adapter_dir = Path(result["adapter_dir"]).resolve()
            if not _is_inside(adapter_dir, job_dir.resolve()):
                result["ok"] = False
                result["reason"] = "adapter_dir outside the job directory"
            elif not adapter_dir.is_dir() or not any(adapter_dir.iterdir()):
                result["ok"] = False
                result["reason"] = "adapter directory missing or empty"
            else:
                gguf_file = adapter_dir / "adapter.gguf"
                conv_cmd = [
                    cfg.trainer_python,
                    str(cfg.converter),
                    "--base",
                    job["base_model_path"],
                    "--outfile",
                    str(gguf_file),
                    "--outtype",
                    "f16",
                    str(adapter_dir),
                ]
                conv_rc: int | None = None
                try:
                    conv_res = runner(conv_cmd, cwd=job_dir, timeout=3600)
                    conv_rc = conv_res.returncode
                except subprocess.TimeoutExpired:
                    conv_rc = -1

                if conv_rc == 0 and gguf_file.is_file():
                    result["gguf"] = "adapter.gguf"
                    result["gguf_sha256"] = _sha256_file(gguf_file)
                else:
                    result["ok"] = False
                    result["reason"] = f"gguf conversion failed (exit {conv_rc})"

        # The cycle and the trainer container mount the shared jobs volume at
        # different absolute paths. Report adapter_dir relative to the job dir so
        # the cycle resolves it against its own mount.
        if result.get("adapter_dir"):
            adapter_dir = Path(result["adapter_dir"]).resolve()
            if _is_inside(adapter_dir, job_dir.resolve()):
                result["adapter_dir"] = str(adapter_dir.relative_to(job_dir.resolve()))
        return _finalize(result)

    except Exception as exc:  # noqa: BLE001 - guarantee a result.json
        return _finalize(
            {
                "ok": False,
                "reason": f"trainer service error: {type(exc).__name__}: {exc}",
            }
        )


def serve(
    cfg: Any,
    *,
    once: bool = False,
    find_jobs: Callable[[Path | str], list[Path]] | None = None,
    claim_fn: Callable[[Path | str], bool] | None = None,
    run_job_fn: Callable[..., dict[str, Any]] | None = None,
    sleep: Callable[[float], Any] | None = None,
    clock: Callable[[], float] | None = None,
    runner: Callable[..., Any] | None = None,
    organ_probe: Callable[[], bool] | None = None,
    vram_probe: Callable[[], int] | None = None,
    logger: logging.Logger | None = None,
) -> None:
    """Poll the jobs directory and run at most one ready job per iteration."""
    find_jobs = find_jobs or find_ready_jobs
    claim_fn = claim_fn or claim
    run_job_fn = run_job_fn or run_job
    sleep = sleep or time.sleep
    clock = clock or time.monotonic
    runner = runner or _default_runner
    organ_probe = organ_probe or _default_organ_probe(cfg)
    vram_probe = vram_probe or _default_vram_probe(cfg.device_index)
    logger = logger or LOGGER

    while True:
        jobs = find_jobs(cfg.jobs_dir)
        if jobs:
            job = jobs[0]
            job_id = job.name
            logger.info("Claiming job %s", job_id)
            if claim_fn(job):
                logger.info("Running job %s", job_id)
                result = run_job_fn(
                    job,
                    cfg,
                    runner,
                    organ_probe,
                    vram_probe,
                    sleep,
                    clock,
                )
                logger.info(
                    "Job %s finished ok=%s reason=%s",
                    job_id,
                    result.get("ok"),
                    result.get("reason"),
                )
            else:
                logger.info("Job %s already claimed", job_id)

            if once:
                break
        else:
            if once:
                break
        sleep(cfg.poll_s)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    repo = Path(__file__).resolve().parents[3]
    default_train_script = repo / "scripts" / "hypnos_external_train.py"

    parser = argparse.ArgumentParser(description="kaine-trainer service")
    parser.add_argument(
        "--jobs",
        dest="jobs_dir",
        default=os.environ.get("KAINE_TRAINER_JOBS_DIR"),
        help="jobs volume directory (also env KAINE_TRAINER_JOBS_DIR)",
    )
    parser.add_argument(
        "--trainer-python",
        dest="trainer_python",
        default=os.environ.get("KAINE_TRAINER_PYTHON", "/opt/trainer/bin/python"),
        help="trainer Python interpreter (also env KAINE_TRAINER_PYTHON)",
    )
    parser.add_argument(
        "--train-script",
        dest="train_script",
        default=str(default_train_script),
        help="path to hypnos_external_train.py",
    )
    parser.add_argument(
        "--converter",
        dest="converter",
        default=os.environ.get(
            "KAINE_LORA_CONVERTER", "/opt/llama.cpp/convert_lora_to_gguf.py"
        ),
        help="llama.cpp LoRA converter (also env KAINE_LORA_CONVERTER)",
    )
    parser.add_argument(
        "--organ-url",
        dest="organ_url",
        default=os.environ.get("KAINE_ORGAN_URL", "http://kaine-model-server:8080"),
        help="organ model-server URL (also env KAINE_ORGAN_URL)",
    )
    parser.add_argument(
        "--device-index",
        dest="device_index",
        type=int,
        default=0,
        help="CUDA device index for nvidia-smi",
    )
    parser.add_argument(
        "--min-free-mib",
        dest="min_free_mib",
        type=int,
        default=7000,
        help="minimum free VRAM in MiB",
    )
    parser.add_argument(
        "--organ-wait-s",
        dest="organ_wait_s",
        type=float,
        default=1800.0,
        help="seconds to wait for the organ to fall asleep",
    )
    parser.add_argument(
        "--poll-s",
        dest="poll_s",
        type=float,
        default=5.0,
        help="seconds between directory polls",
    )
    parser.add_argument(
        "--job-timeout-s",
        dest="job_timeout_s",
        type=float,
        default=21600.0,
        help="seconds before killing a training subprocess",
    )
    parser.add_argument(
        "--once",
        dest="once",
        action="store_true",
        help="process at most one job then exit (useful for tests)",
    )

    args = parser.parse_args(argv)
    if not args.jobs_dir:
        sys.stderr.write("--jobs / KAINE_TRAINER_JOBS_DIR is required\n")
        return 2

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    organ_probe = _default_organ_probe(args)
    vram_probe = _default_vram_probe(args.device_index)
    runner = _default_runner

    try:
        serve(
            args,
            once=args.once,
            organ_probe=organ_probe,
            vram_probe=vram_probe,
            runner=runner,
        )
    except KeyboardInterrupt:
        LOGGER.info("trainer service stopped")
    return 0


# --------------------------------------------------------------------------- #
# internal helpers
# --------------------------------------------------------------------------- #
def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _default_organ_probe(cfg: Any) -> Callable[[], bool]:
    url = f"{cfg.organ_url.rstrip('/')}/props"
    api_key = os.environ.get("KAINE_MODEL_SERVER_API_KEY")

    def probe() -> bool:
        try:
            req = urllib.request.Request(url, method="GET")
            if api_key:
                req.add_header("Authorization", f"Bearer {api_key}")
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("is_sleeping"))
        except Exception:  # noqa: BLE001
            return False

    return probe


def _default_vram_probe(device_index: int) -> Callable[[], int]:
    def probe() -> int:
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=memory.free",
                    "--format=csv,noheader,nounits",
                    "-i",
                    str(device_index),
                ],
                capture_output=True,
                text=True,
                timeout=10.0,
                check=False,
            )
            if result.returncode != 0:
                return 0
            line = result.stdout.strip().splitlines()[0].strip()
            return int(line)
        except Exception:  # noqa: BLE001
            return 0

    return probe


def _default_runner(cmd: list[str], *, cwd: Path | str, timeout: float) -> Any:
    log_path = Path(cwd) / "trainer.log"
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(f"\n--- timeout: {' '.join(cmd)}\n")
            fh.write(exc.stdout or "")
        raise
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(f"\n--- {' '.join(cmd)}\n")
        fh.write(proc.stdout or "")
    return proc


if __name__ == "__main__":
    raise SystemExit(main())
