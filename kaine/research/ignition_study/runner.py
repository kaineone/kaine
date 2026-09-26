# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Study runner: process control, resume, locking, and step recording."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from kaine.cycle.preserve_watch import read_request, read_result
from kaine.research.ignition_study.overlay import build_overlay
from kaine.research.ignition_study.plan import LOCK_FILE, STEPS_FILE, load_plan
from kaine.research.ignition_study.toml_writer import dumps

log = logging.getLogger(__name__)


class StudyComplete(Exception):
    """Raised when every planned step is already recorded as complete."""


class StudyHalted(Exception):
    """Raised when a step fails and the runner refuses to continue."""

    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record


class StudyCritical(Exception):
    """Raised when a timeout preservation fails and the operator must decide."""


class StudyLocked(Exception):
    """Raised when another runner already holds the study lock."""


class StudyError(Exception):
    """Raised for plan/resume preconditions that prevent running."""


class StudyRunner:
    """Drive a module-ignition study from its plan and recorded steps."""

    def __init__(
        self,
        study_dir: Path | str,
        *,
        cycle_command: list[str] | None = None,
        control_command: list[str] | None = None,
        poll_seconds: float = 5.0,
        preserve_wait_seconds: float = 600.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        popen: Any = subprocess.Popen,
        run: Any = subprocess.run,
    ) -> None:
        self.study_dir = Path(study_dir).resolve()
        self.plan = load_plan(self.study_dir)
        self.steps_path = self.study_dir / STEPS_FILE
        self.cycle_command = list(cycle_command or [sys.executable, "-m", "kaine.cycle"])
        self.control_command = list(
            control_command or [sys.executable, "-m", "kaine.cycle.control"]
        )
        self.poll_seconds = poll_seconds
        self.preserve_wait_seconds = preserve_wait_seconds
        self.clock = clock
        self.sleep = sleep
        self.popen = popen
        self._subprocess_run = run
        self._lock_fd: Any | None = None
        self._load_state()

    # --------------------------------------------------------------------- #
    # State
    # --------------------------------------------------------------------- #

    def _load_state(self) -> None:
        self.steps: list[dict[str, Any]] = []
        if self.steps_path.exists():
            for line in self.steps_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self.steps.append(json.loads(line))
                except json.JSONDecodeError:
                    log.warning("Ignoring malformed steps.jsonl line: %s", line)

        self.line_bundles: dict[str, str | None] = {}
        self.completed_steps: set[tuple[str, int]] = set()
        self.last_failed: dict[str, Any] | None = None

        for rec in self.steps:
            line = rec.get("line")
            step = rec.get("step")
            outcome = rec.get("outcome", "")
            if outcome == "complete":
                self.line_bundles[line] = rec.get("bundle")
                self.completed_steps.add((line, step))
            elif isinstance(outcome, str) and outcome.startswith("failed"):
                self.last_failed = rec

        # A retry that completed clears the earlier failure.
        if (
            self.last_failed
            and (self.last_failed["line"], self.last_failed["step"])
            in self.completed_steps
        ):
            self.last_failed = None

    def _step_sequence(self) -> list[tuple[str, int]]:
        seq: list[tuple[str, int]] = [("gestation", 0)]
        for k in range(self.plan["viewings_per_line"]):
            seq.append(("main", k))
            seq.append(("control", k))
        return seq

    def _next_step(self, retry_failed: bool = False) -> dict[str, Any]:
        sequence = self._step_sequence()

        if retry_failed and self.last_failed:
            rec = self.last_failed
            return {
                "line": rec["line"],
                "k": rec["step"],
                "revived_from": rec.get("revived_from"),
                "is_retry": True,
            }

        if self.last_failed:
            raise StudyHalted(self.last_failed)

        for line, k in sequence:
            if (line, k) in self.completed_steps:
                continue

            if line == "gestation":
                revived_from: str | None = None
            elif k == 0:
                p0 = self.line_bundles.get("gestation")
                if p0 is None:
                    raise StudyError("gestation has not completed")
                revived_from = p0
            else:
                prior = self.line_bundles.get(line)
                if prior is None:
                    raise StudyError(f"{line} has no prior bundle")
                revived_from = prior

            return {"line": line, "k": k, "revived_from": revived_from}

        raise StudyComplete()

    # --------------------------------------------------------------------- #
    # Locking
    # --------------------------------------------------------------------- #

    def _acquire_lock(self) -> None:
        import fcntl

        lock_path = self.study_dir / LOCK_FILE
        self._lock_fd = open(lock_path, "w")
        try:
            fcntl.flock(self._lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, BlockingIOError) as exc:
            self._lock_fd.close()
            self._lock_fd = None
            raise StudyLocked(
                f"Study {self.study_dir} is already being run by another process"
            ) from exc

    def _release_lock(self) -> None:
        import fcntl

        if self._lock_fd is not None:
            try:
                fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            self._lock_fd.close()
            self._lock_fd = None

    # --------------------------------------------------------------------- #
    # Running
    # --------------------------------------------------------------------- #

    def run(self, retry_failed: bool = False) -> None:
        """Run or resume the study until it completes or halts."""
        self._acquire_lock()
        try:
            while True:
                step = self._next_step(retry_failed)
                retry_failed = False
                self._run_step(step)
        finally:
            self._release_lock()

    def _run_step(self, step: dict[str, Any]) -> dict[str, Any]:
        line = step["line"]
        k = step["k"]
        line_dir = self.study_dir / line
        step_kind = "gestation" if line == "gestation" else "viewing"
        repo_root = Path(self.plan["repo_root"])

        overlay, modules_set, models_dir = build_overlay(
            self.plan,
            line,
            step_kind,
            k,
            repo_root,
            repo_root / "config" / "kaine.toml",
            repo_root / "config" / "kaine.operator.toml",
        )
        overlay_toml = dumps(overlay)
        overlay_hash = hashlib.sha256(overlay_toml.encode()).hexdigest()

        operator_path = line_dir / "config" / "kaine.operator.toml"
        _write_text_atomic(operator_path, overlay_toml)

        env = dict(os.environ)
        env["KAINE_RESEARCH_MODE"] = "1"
        env["KAINE_REDIS_URL"] = (
            f"{self.plan['redis']['base_url']}/{self.plan['redis']['db'][line]}"
        )
        env["KAINE_MODELS_DIR"] = models_dir

        argv = list(self.cycle_command)
        if step_kind == "viewing":
            argv.extend(["--revive", step["revived_from"]])

        # Remember the request id already on disk for this line, if any.
        # A step only owns a preservation pair that was produced while it ran.
        prior_request_path = line_dir / "state" / "cycle" / "preserve_request.json"
        prior_request = read_request(prior_request_path)
        prior_request_id = prior_request.request_id if prior_request else None

        started_at = _utc_iso()
        proc = self.popen(argv, cwd=str(line_dir), env=env)

        run_id: str | None = None
        exit_code: int | None = None
        timeout_requested = False
        birth_preserved = False

        start_clock = self.clock()
        budget = (
            self.plan["gestation_budget_seconds"]
            if step_kind == "gestation"
            else self.plan["viewing_budget_seconds"]
        )
        last_check = start_clock - self.poll_seconds

        try:
            while True:
                ret = proc.poll()
                if ret is not None:
                    exit_code = ret
                    break

                now = self.clock()
                if now - last_check >= self.poll_seconds:
                    last_check = now
                    runtime = self._read_runtime(line_dir)
                    if runtime:
                        run_id = runtime.get("run_id") or run_id
                        if step_kind == "gestation":
                            stage = (
                                runtime.get("developmental_stage") or {}
                            ).get("stage")
                            if stage == "embodied" and not birth_preserved:
                                birth_preserved = True
                                _, _, _, ok = self._request_preserve(
                                    line_dir,
                                    "birth",
                                    stop=True,
                                    wait=self.preserve_wait_seconds,
                                )
                                if not ok:
                                    log.error(
                                        "Birth preservation request did not succeed for %s",
                                        line,
                                    )

                    elapsed = now - start_clock
                    if elapsed > budget and not timeout_requested:
                        timeout_requested = True
                        _, _, _, ok = self._request_preserve(
                            line_dir,
                            "timeout",
                            stop=True,
                            wait=self.preserve_wait_seconds,
                        )
                        if not ok:
                            log.critical(
                                "Timeout preservation failed for %s; the process is still "
                                "running and the operator must decide what to do.",
                                line,
                            )
                            raise StudyCritical(
                                f"timeout preservation failed for {line}"
                            )

                self.sleep(self.poll_seconds)

        finally:
            # The runner never sends SIGKILL.  A process that is still running
            # after a failed timeout preservation is left for the operator.
            pass

        ended_at = _utc_iso()
        request, result = self._read_preserve_pair(
            line_dir, prior_request_id=prior_request_id
        )
        outcome = self._determine_outcome(
            step_kind,
            exit_code,
            request,
            result,
            timeout_requested,
            revived_from=step.get("revived_from"),
        )

        bundle = result.get("bundle") if result else None
        preservation_id = result.get("preservation_id") if result else None

        record: dict[str, Any] = {
            "line": line,
            "step": k,
            "modules": sorted(modules_set),
            "started_at": started_at,
            "ended_at": ended_at,
            "exit_code": exit_code,
            "revived_from": step.get("revived_from"),
            "preservation_id": preservation_id,
            "bundle": bundle,
            "run_id": run_id,
            "ignition_log_dir": str(line_dir / "data" / "ignition"),
            "overlay_sha256": overlay_hash,
            "outcome": outcome,
        }

        self._append_step(record)

        if outcome == "complete":
            self.line_bundles[line] = bundle
            self.completed_steps.add((line, k))
            if (
                self.last_failed
                and self.last_failed["line"] == line
                and self.last_failed["step"] == k
            ):
                self.last_failed = None
        else:
            self.last_failed = record
            raise StudyHalted(record)

        return record

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #

    def _read_runtime(self, line_dir: Path) -> dict[str, Any] | None:
        path = line_dir / "state" / "cycle" / "runtime.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _request_preserve(
        self,
        line_dir: Path,
        reason: str,
        stop: bool,
        wait: float,
    ) -> tuple[int, Any | None, dict[str, Any] | None, bool]:
        argv = [*self.control_command, "preserve", "--reason", reason]
        if stop:
            argv.append("--stop")
        argv.extend(["--wait", str(wait)])

        # The control CLI writes a fresh request.  Do not accept a result
        # against a request that was already on disk before we called it.
        prior_request_path = line_dir / "state" / "cycle" / "preserve_request.json"
        prior_request = read_request(prior_request_path)
        prior_request_id = prior_request.request_id if prior_request else None

        completed = self._subprocess_run(
            argv,
            cwd=str(line_dir),
            check=False,
            capture_output=True,
            text=True,
        )

        req_path = line_dir / "state" / "cycle" / "preserve_request.json"
        res_path = line_dir / "state" / "cycle" / "preserve_result.json"
        req = read_request(req_path)
        res = read_result(res_path)
        matched = bool(
            req
            and res
            and res.get("request_id") == req.request_id
            and res.get("ok")
            and req.request_id != prior_request_id
        )
        return completed.returncode, req, res, matched

    def _read_preserve_pair(
        self,
        line_dir: Path,
        prior_request_id: str | None = None,
    ) -> tuple[Any | None, dict[str, Any] | None]:
        req_path = line_dir / "state" / "cycle" / "preserve_request.json"
        res_path = line_dir / "state" / "cycle" / "preserve_result.json"
        req = read_request(req_path)
        res = read_result(res_path)
        if req is None or res is None:
            return req, res
        if res.get("request_id") != req.request_id:
            return req, None
        if prior_request_id is not None and req.request_id == prior_request_id:
            log.warning(
                "Ignoring stale preservation request %s from a previous step",
                req.request_id,
            )
            return req, None
        return req, res

    def _determine_outcome(
        self,
        step_kind: str,
        exit_code: int | None,
        request: Any | None,
        result: dict[str, Any] | None,
        timeout_requested: bool,
        revived_from: str | None,
    ) -> str:
        if timeout_requested:
            if (
                result
                and result.get("ok")
                and request
                and request.reason == "timeout"
            ):
                return "failed:timeout"
            return "failed:timeout_unpreserved"

        if exit_code is None:
            return "failed:running"

        if exit_code != 0:
            return f"failed:exit:{exit_code}"

        if request is None or result is None:
            return "failed:missing_preservation"

        if not result.get("ok"):
            return "failed:preservation"

        bundle = result.get("bundle")
        if not bundle or bundle == revived_from:
            return "failed:stale_bundle"

        expected_reason = "birth" if step_kind == "gestation" else "programme end"
        if request.reason != expected_reason:
            return f"failed:reason:{request.reason}"

        return "complete"

    def _append_step(self, record: dict[str, Any]) -> None:
        with open(self.steps_path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")
        self.steps.append(record)

    # --------------------------------------------------------------------- #
    # Status
    # --------------------------------------------------------------------- #

    def status(self) -> str:
        """Return a human-readable progress summary."""
        total = 1 + 2 * self.plan["viewings_per_line"]
        completed = sum(
            1 for s in self.steps if s.get("outcome") == "complete"
        )
        failed = [s for s in self.steps if str(s.get("outcome", "")).startswith("failed")]
        lines = [
            f"Study {self.plan['study_id']} at {self.study_dir}",
            f"Completed {completed}/{total} steps",
        ]
        if failed:
            last = failed[-1]
            lines.append(
                f"Halted: {last['outcome']} at {last['line']} step {last['step']}"
            )
        try:
            nxt = self._next_step()
            lines.append(f"Next: {nxt['line']} step {nxt['k']}")
        except StudyComplete:
            lines.append("Next: none")
        except StudyHalted:
            lines.append(
                f"Next: retry failed step with --retry-failed "
                f"({self.last_failed['line']} step {self.last_failed['step']})"
            )
        return "\n".join(lines)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_text_atomic(path: Path, text: str) -> None:
    """Write ``text`` atomically, owner-only: the operator overlay it carries
    can hold the operator's inference keys."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(tmp, 0o600)
    tmp.replace(path)
