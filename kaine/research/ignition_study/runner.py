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
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote, urlsplit

from kaine.bus.config import load_bus_config, resolve_redis_auth
from kaine.bus.errors import BusConfigError
from kaine.cycle.preserve_watch import read_request, read_result
from kaine.research.ignition_study.overlay import IGNITION_LOG_DIR, build_overlay
from kaine.research.ignition_study.plan import (
    LOCK_FILE,
    STEPS_FILE,
    ensure_line_dir,
    load_plan,
    validate_redis_base_url,
    validate_redis_dbs,
)
from kaine.research.ignition_study.toml_writer import dumps

log = logging.getLogger(__name__)

#: The key that names the study owning a bus database on the Redis server.
STUDY_OWNER_KEY = "kaine:study:owner"

#: The runner's record of the cycle it started, in the step's working directory.
CHILD_FILE = ".study_child.json"

#: The longest birth bloom the womb accepts (``WombParams`` and
#: ``WombClock.begin_birth`` both bound ``birth_transition_seconds`` to (0, 30]).
BIRTH_BLOOM_MAX_SECONDS = 30.0


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


class StudyDatabaseClaimed(StudyError):
    """Raised when another study owns a bus database this study would flush."""


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
        birth_bloom_margin_seconds: float = 2.0,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        popen: Any = subprocess.Popen,
        run: Any = subprocess.run,
        flush_db: Callable[[str], None] | None = None,
        redis_client_factory: Callable[[str], Any] | None = None,
        cycle_alive: Callable[[int], bool] | None = None,
    ) -> None:
        self.study_dir = Path(study_dir).resolve()
        self.plan = load_plan(self.study_dir)
        try:
            validate_redis_base_url(self.plan["redis"]["base_url"])
        except ValueError as exc:
            raise StudyError(f"study.json: {exc}") from None
        # The runner flushes every study database, so a plan (even a
        # hand-edited study.json) naming the operator's bus is refused before
        # anything runs, and again before every flush.
        self._check_operator_bus()
        self.steps_path = self.study_dir / STEPS_FILE
        self.cycle_command = list(cycle_command or [sys.executable, "-m", "kaine.cycle"])
        self.control_command = list(
            control_command or [sys.executable, "-m", "kaine.cycle.control"]
        )
        self.poll_seconds = poll_seconds
        self.preserve_wait_seconds = preserve_wait_seconds
        self.birth_bloom_margin_seconds = birth_bloom_margin_seconds
        self.clock = clock
        self.wall_clock = wall_clock
        self.sleep = sleep
        self.popen = popen
        self._subprocess_run = run
        if flush_db is None:
            study_id = str(self.plan["study_id"])
            factory = redis_client_factory or _redis_client_from_url

            def _claim_and_flush(url: str) -> None:
                _claim_and_flush_redis_db(url, study_id, factory)

            flush_db = _claim_and_flush
        self.flush_db = flush_db
        self.cycle_alive = cycle_alive or _cycle_process_alive
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

        self.line_bundles: dict[tuple[str, int], str | None] = {}
        self.completed_steps: set[tuple[str, int]] = set()
        self.last_failed: dict[str, Any] | None = None

        for rec in self.steps:
            line = rec.get("line")
            step = rec.get("step")
            outcome = rec.get("outcome", "")
            if outcome == "complete":
                self.line_bundles[(line, step)] = rec.get("bundle")
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
        k = len(self.plan["order"])
        seq: list[tuple[str, int]] = [("gestation", 0), ("branch", 0), ("repeat", 0)]
        for i in range(1, k + 1):
            seq.append(("branch", i))
            seq.append(("accumulate", i))
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

        seed = self.line_bundles.get(("gestation", 0))
        for line, k in sequence:
            if (line, k) in self.completed_steps:
                continue

            if line == "gestation":
                revived_from: str | None = None
            elif line in ("branch", "repeat"):
                if seed is None:
                    raise StudyError("gestation has not completed")
                revived_from = seed
            elif line == "accumulate":
                if k == 1:
                    prior = self.line_bundles.get(("branch", 0))
                    if prior is None:
                        raise StudyError("branch 0 has not completed")
                else:
                    prior = self.line_bundles.get(("accumulate", k - 1))
                    if prior is None:
                        raise StudyError(f"accumulate {k - 1} has not completed")
                revived_from = prior
            else:
                raise StudyError(f"unknown line: {line}")

            return {"line": line, "k": k, "revived_from": revived_from, "is_retry": False}

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
                # Closing the file below releases the lock whether or not the
                # explicit unlock succeeded.
                log.debug("explicit study-lock unlock failed", exc_info=True)
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

    def _line_dir(self, line: str, k: int) -> Path:
        if line == "branch":
            return self.study_dir / "branch" / str(k)
        return self.study_dir / line

    def _ensure_step_dir(self, line: str, k: int) -> Path:
        return ensure_line_dir(
            self.study_dir, line, k, Path(self.plan["repo_root"])
        )

    def _read_birth_bloom_deadline(self, line_dir: Path) -> float | None:
        """``birth_bloom_ends_at`` from the step's stage file, as a wall-clock
        timestamp, or ``None`` when the file or the field is absent or bad."""
        path = line_dir / "state" / "lifecycle" / "stage.json"
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        ends_at = data.get("birth_bloom_ends_at")
        if not isinstance(ends_at, str):
            return None
        try:
            # ISO-8601 UTC, with or without a trailing 'Z'.
            if ends_at.endswith("Z"):
                ends_at = ends_at[:-1] + "+00:00"
            dt = datetime.fromisoformat(ends_at)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()

    def _birth_bloom_over(
        self, line_dir: Path, first_embodied_wall: float, fallback_seconds: float
    ) -> bool:
        """Whether the birth bloom has ended: at the stage file's
        ``birth_bloom_ends_at`` when it has one, else ``fallback_seconds``
        after the runner first saw the embodied stage."""
        now = self.wall_clock()
        deadline = self._read_birth_bloom_deadline(line_dir)
        if deadline is not None:
            return now >= deadline
        return now - first_embodied_wall >= fallback_seconds

    def _birth_bloom_fallback_seconds(self, line_dir: Path, env: Mapping[str, str]) -> float:
        """How long to wait after the embodied stage when the stage file does
        not name the bloom's end: the child's own
        ``[perception_feed.womb].birth_transition_seconds`` (loaded exactly as
        the cycle loads it from the step's working directory) plus the margin.
        When that value cannot be resolved, the longest bloom the womb accepts
        plus the margin, so the seed is never preserved mid-bloom."""
        from kaine.boot import _womb_params
        from kaine.config import load_runtime_config

        cfg = line_dir / "config"
        try:
            config = load_runtime_config(
                cfg / "kaine.toml",
                cfg / "kaine.operator.toml",
                env=dict(env),
                profiles_dir=cfg / "profiles",
            )
            feed = config.get("perception_feed") or {}
            if not isinstance(feed, dict):
                raise ValueError("[perception_feed] must be a table")
            seconds = float(_womb_params(feed).birth_transition_seconds)
        except Exception as exc:
            log.warning(
                "birth bloom length unresolved (%s); waiting the %.0f s maximum",
                type(exc).__name__,
                BIRTH_BLOOM_MAX_SECONDS,
            )
            seconds = BIRTH_BLOOM_MAX_SECONDS
        return seconds + self.birth_bloom_margin_seconds

    def _check_operator_bus(self) -> None:
        """Refuse when a study database is the operator's bus database, as the
        bus itself resolves it from the operator's configuration now."""
        operator_dbs = _operator_bus_dbs(Path(self.plan["repo_root"]), os.environ)
        try:
            validate_redis_dbs(self.plan["redis"]["db"], operator_dbs)
        except ValueError as exc:
            raise StudyError(f"study.json: {exc}") from None

    def _step_dirs(self) -> list[Path]:
        seen: list[Path] = []
        for line, k in self._step_sequence():
            d = self._line_dir(line, k)
            if d not in seen:
                seen.append(d)
        return seen

    def _refuse_if_cycle_running(self) -> None:
        """Refuse to flush or start anything while a cycle this study started
        may still be running: the child left running after a failed timeout
        preservation, or one a killed runner never saw exit.  Its identity is
        checked by ``cycle_alive`` (``/proc/<pid>/cmdline``), never by pid
        alone."""
        candidates: list[tuple[int, str]] = []
        for rec in self.steps:
            if rec.get("outcome") == "failed:critical":
                pid = rec.get("pid")
                if isinstance(pid, int) and not isinstance(pid, bool):
                    candidates.append((pid, f"{rec.get('line')} step {rec.get('step')}"))
        for d in self._step_dirs():
            where = str(d.relative_to(self.study_dir))
            for path in (d / CHILD_FILE, d / "state" / "cycle" / "runtime.json"):
                pid = _read_pid(path)
                if pid is not None:
                    candidates.append((pid, where))
        for pid, where in candidates:
            if pid > 0 and self.cycle_alive(pid):
                raise StudyError(
                    f"a cycle this study started may still be running ({where}, "
                    f"pid {pid}); stop it before running the study again"
                )

    def _adopt_birth_preservation(
        self, line_dir: Path, modules_set: set[str]
    ) -> dict[str, Any] | None:
        """A gestation whose birth preservation succeeded before the runner
        could record it: its record, built from the preservation pair on disk,
        or ``None`` when there is no such preservation."""
        state = line_dir / "state" / "cycle"
        req = read_request(state / "preserve_request.json")
        res = read_result(state / "preserve_result.json")
        if (
            req is None
            or res is None
            or req.reason != "birth"
            or res.get("request_id") != req.request_id
            or not res.get("ok")
        ):
            return None
        bundle = res.get("bundle")
        if not isinstance(bundle, str) or not bundle or not Path(bundle).is_dir():
            return None
        outcome = "complete"
        world_model_captured: bool | None = None
        if "phantasia" in modules_set:
            extra_outcome, world_model_captured = _check_phantasia_manifest(bundle)
            if extra_outcome:
                outcome = extra_outcome
        overlay_path = line_dir / "config" / "kaine.operator.toml"
        try:
            overlay_hash: str | None = hashlib.sha256(overlay_path.read_bytes()).hexdigest()
        except OSError:
            overlay_hash = None
        return {
            "line": "gestation",
            "step": 0,
            "modules": sorted(modules_set),
            "world_model_captured": world_model_captured,
            "started_at": None,
            "ended_at": res.get("finished_at"),
            "exit_code": None,
            "revived_from": None,
            "preservation_id": res.get("preservation_id"),
            "bundle": bundle,
            "run_id": None,
            "ignition_log_dir": str(line_dir / IGNITION_LOG_DIR),
            "overlay_sha256": overlay_hash,
            "outcome": outcome,
            "adopted": True,
        }

    def _finish_record(self, record: dict[str, Any]) -> dict[str, Any]:
        self._append_step(record)
        line, k, outcome = record["line"], record["step"], record["outcome"]
        if outcome == "complete":
            self.line_bundles[(line, k)] = record["bundle"]
            self.completed_steps.add((line, k))
            if (
                self.last_failed
                and self.last_failed["line"] == line
                and self.last_failed["step"] == k
            ):
                self.last_failed = None
            return record
        self.last_failed = record
        raise StudyHalted(record)

    def _run_step(self, step: dict[str, Any]) -> dict[str, Any]:
        line = step["line"]
        k = step["k"]
        line_dir = self._ensure_step_dir(line, k)
        step_kind = "gestation" if line == "gestation" else "viewing"
        repo_root = Path(self.plan["repo_root"])

        # Nothing is flushed, adopted or started while a cycle the study
        # started may still hold a study database or a step directory.
        self._refuse_if_cycle_running()

        overlay, modules_set, models_dir = build_overlay(
            self.plan,
            line,
            step_kind,
            k,
            repo_root,
            repo_root / "config" / "kaine.toml",
            repo_root / "config" / "kaine.operator.toml",
        )

        # A runner that died after the seed's birth preservation succeeded,
        # but before recording it, left the seed on disk: adopt it rather than
        # gestate a second being.
        if (
            step_kind == "gestation"
            and not step.get("is_retry")
            and not any(rec.get("line") == "gestation" for rec in self.steps)
        ):
            adopted = self._adopt_birth_preservation(line_dir, modules_set)
            if adopted is not None:
                log.info("Adopting the recorded birth preservation %s", adopted["bundle"])
                return self._finish_record(adopted)

        overlay_toml = dumps(overlay)
        overlay_hash = hashlib.sha256(overlay_toml.encode()).hexdigest()

        operator_path = line_dir / "config" / "kaine.operator.toml"
        _write_text_atomic(operator_path, overlay_toml)

        env = dict(os.environ)
        env["KAINE_RESEARCH_MODE"] = "1"

        username, password = resolve_redis_auth(
            env, secrets_toml=repo_root / "config" / "secrets.toml"
        )
        if not password:
            raise StudyError(
                "no Redis password found for the study runner; set KAINE_REDIS_PASSWORD "
                "or add the password to config/secrets.toml [redis].password"
            )
        parsed = urlsplit(self.plan["redis"]["base_url"])
        quoted_password = quote(password, safe="")
        if username:
            auth = f"{quote(username, safe='')}:{quoted_password}@"
        else:
            auth = f":{quoted_password}@"
        redis_url = (
            f"{parsed.scheme}://{auth}{parsed.netloc}/"
            f"{self.plan['redis']['db'][line]}"
        )
        env["KAINE_REDIS_URL"] = redis_url
        env["KAINE_MODELS_DIR"] = models_dir

        bloom_fallback = (
            self._birth_bloom_fallback_seconds(line_dir, env)
            if step_kind == "gestation"
            else 0.0
        )

        # The operator's configuration can change during a multi-day study:
        # check it again immediately before the flush.  The check reads the
        # runner's own environment, never the child's ``env`` above.
        self._check_operator_bus()

        # Every step starts on an empty bus: flush the step's own study
        # database (never the operator's; see validate_redis_dbs), which this
        # study claims on the server so no other study flushes it.
        db = self.plan["redis"]["db"][line]
        try:
            self.flush_db(redis_url)
        except StudyError:
            raise
        except Exception as exc:
            # The URL carries the password: name the database, not the URL.
            raise StudyError(
                f"could not flush bus database {db} before {line} step {k}: "
                f"{type(exc).__name__}"
            ) from None

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
        child_pid = getattr(proc, "pid", None)
        child_path = line_dir / CHILD_FILE
        if isinstance(child_pid, int):
            _write_text_atomic(
                child_path, json.dumps({"pid": child_pid, "started_at": started_at})
            )

        run_id: str | None = None
        exit_code: int | None = None
        timeout_requested = False
        birth_requested = False
        first_embodied_wall: float | None = None

        start_clock = self.clock()
        budget = (
            self.plan["gestation_budget_seconds"]
            if step_kind == "gestation"
            else self.plan["viewing_budget_seconds"]
        )
        last_check = start_clock - self.poll_seconds

        # The runner never sends SIGKILL.  A process that is still running
        # after a failed timeout preservation is left for the operator.
        while True:
            ret = proc.poll()
            if ret is not None:
                exit_code = ret
                child_path.unlink(missing_ok=True)
                break

            now = self.clock()
            if now - last_check >= self.poll_seconds:
                last_check = now
                runtime = self._read_runtime(line_dir)
                if runtime:
                    run_id = runtime.get("run_id") or run_id
                    stage = (runtime.get("developmental_stage") or {}).get("stage")
                    if (
                        step_kind == "gestation"
                        and stage == "embodied"
                        and not birth_requested
                    ):
                        if first_embodied_wall is None:
                            first_embodied_wall = self.wall_clock()
                        # The seed is the being once its birth bloom is over.
                        if self._birth_bloom_over(
                            line_dir, first_embodied_wall, bloom_fallback
                        ):
                            birth_requested = True
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
                        # The study halts on this record until the operator
                        # retries it, and no later run touches this step's
                        # database while the child is alive.
                        critical = {
                            "line": line,
                            "step": k,
                            "modules": sorted(modules_set),
                            "world_model_captured": None,
                            "started_at": started_at,
                            "ended_at": _utc_iso(),
                            "exit_code": None,
                            "revived_from": step.get("revived_from"),
                            "preservation_id": None,
                            "bundle": None,
                            "run_id": run_id,
                            "ignition_log_dir": str(line_dir / IGNITION_LOG_DIR),
                            "overlay_sha256": overlay_hash,
                            "outcome": "failed:critical",
                            "pid": child_pid,
                        }
                        self._append_step(critical)
                        self.last_failed = critical
                        raise StudyCritical(
                            f"timeout preservation failed for {line} step {k}; "
                            f"pid {child_pid} is still running"
                        )

            self.sleep(self.poll_seconds)

        ended_at = _utc_iso()
        request, result = self._read_preserve_pair(
            line_dir, prior_request_id=prior_request_id
        )

        bundle = result.get("bundle") if result else None
        preservation_id = result.get("preservation_id") if result else None

        outcome = self._determine_outcome(
            step_kind,
            exit_code,
            request,
            result,
            timeout_requested,
            revived_from=step.get("revived_from"),
        )

        world_model_captured: bool | None = None
        if "phantasia" in modules_set:
            world_model_captured = False
            if outcome == "complete" and bundle:
                extra_outcome, captured = _check_phantasia_manifest(bundle)
                if extra_outcome:
                    outcome = extra_outcome
                world_model_captured = captured

        record: dict[str, Any] = {
            "line": line,
            "step": k,
            "modules": sorted(modules_set),
            "world_model_captured": world_model_captured,
            "started_at": started_at,
            "ended_at": ended_at,
            "exit_code": exit_code,
            "revived_from": step.get("revived_from"),
            "preservation_id": preservation_id,
            "bundle": bundle,
            "run_id": run_id,
            "ignition_log_dir": str(line_dir / IGNITION_LOG_DIR),
            "overlay_sha256": overlay_hash,
            "outcome": outcome,
            "pid": child_pid,
        }

        return self._finish_record(record)

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
        k = len(self.plan["order"])
        total = 3 + 2 * k
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


def _redis_client_from_url(url: str) -> Any:
    import redis

    return redis.Redis.from_url(url)


def _claim_and_flush_redis_db(
    url: str, study_id: str, client_factory: Callable[[str], Any]
) -> None:
    """FLUSHDB on the one database ``url`` names, claimed for ``study_id``.

    The database carries :data:`STUDY_OWNER_KEY`.  Another study's name there
    refuses the flush; otherwise the flush and the re-claim run as one
    transaction watched on the key, so no other study can claim the database
    between the check and the flush.  The URL carries the password, so it is
    never logged."""
    import redis

    client = client_factory(url)
    try:
        with client.pipeline(transaction=True) as pipe:
            pipe.watch(STUDY_OWNER_KEY)
            owner = pipe.get(STUDY_OWNER_KEY)
            if isinstance(owner, bytes):
                owner = owner.decode("utf-8", "replace")
            if owner is not None and owner != study_id:
                raise StudyDatabaseClaimed(
                    f"bus database {urlsplit(url).path.strip('/') or '0'} belongs "
                    f"to study {owner!r}; refusing to flush it"
                )
            pipe.multi()
            pipe.flushdb()
            pipe.set(STUDY_OWNER_KEY, study_id)
            try:
                pipe.execute()
            except redis.WatchError:
                raise StudyDatabaseClaimed(
                    "another process changed the bus database's owner during "
                    "the flush; refusing to continue"
                ) from None
    finally:
        client.close()


def _operator_bus_dbs(repo_root: Path, env: Mapping[str, str]) -> set[int]:
    """The database numbers the operator's own bus uses: 0 and the database
    ``load_bus_config`` resolves from the operator's configuration (the
    repository's ``config/kaine.toml``, ``config/kaine.operator.toml`` and
    ``config/secrets.toml``, and ``env``, the runner's own environment).

    Raises :class:`StudyError` when that database cannot be determined; the
    message names no secret."""
    from redis.connection import parse_url

    cfg = repo_root / "config"
    operator_toml = cfg / "kaine.operator.toml"
    # load_bus_config falls back to the shipped configuration when the
    # operator file cannot be parsed; the runner cannot tell which database
    # the operator meant, so it refuses.
    if operator_toml.exists():
        try:
            with open(operator_toml, "rb") as fh:
                tomllib.load(fh)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise StudyError(
                "cannot determine the operator's bus database: "
                f"{operator_toml} could not be read ({type(exc).__name__})"
            ) from None
    try:
        bus = load_bus_config(
            kaine_toml=cfg / "kaine.toml",
            secrets_toml=cfg / "secrets.toml",
            env=dict(env),
            operator_toml=operator_toml,
        )
        if bus.url_override:
            # redis-py's own reading: ``?db=`` wins over the path.
            db = int(parse_url(bus.url_override).get("db", 0))
        else:
            db = int(bus.db)
    except BusConfigError as exc:
        # The bus names only the places it looked for a password.
        raise StudyError(
            f"cannot determine the operator's bus database: {exc}"
        ) from None
    except Exception as exc:
        # An override URL carries the password, and the redis-py messages
        # can quote it: name the error type only.
        raise StudyError(
            "cannot determine the operator's bus database from its "
            f"configuration ({type(exc).__name__}); refusing to flush any database"
        ) from None
    return {0, db}


def _read_pid(path: Path) -> int | None:
    """The ``pid`` a JSON file records, or ``None``."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    pid = data.get("pid") if isinstance(data, dict) else None
    if isinstance(pid, int) and not isinstance(pid, bool):
        return pid
    return None


def _cycle_process_alive(pid: int) -> bool:
    """Whether ``pid`` is a running KAINE cycle: its ``/proc/<pid>/cmdline``
    names ``kaine.cycle``.  A pid alone is never trusted.  Where the command
    line cannot be read, a live pid counts as a cycle."""
    proc = Path("/proc")
    if not (proc / "self" / "cmdline").exists():
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True
        return True
    try:
        cmdline = (proc / str(pid) / "cmdline").read_bytes()
    except FileNotFoundError:
        return False
    except OSError:
        return (proc / str(pid)).exists()
    # A zombie's command line is empty: it has exited.
    return b"kaine.cycle" in cmdline


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _check_phantasia_manifest(bundle_path: str) -> tuple[str | None, bool | None]:
    """Return an extra outcome and captured flag for a Phantasia bundle."""
    manifest_path = Path(bundle_path) / "manifest.json"
    try:
        text = manifest_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return "failed:manifest_unreadable", False
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return "failed:manifest_unreadable", False
    if not isinstance(data, dict):
        return "failed:manifest_unreadable", False
    captured = data.get("world_model_captured")
    if captured is True:
        return None, True
    return "failed:world_model_not_captured", False


def _write_text_atomic(path: Path, text: str) -> None:
    """Write ``text`` atomically, owner-only: the operator overlay it carries
    can hold the operator's inference keys."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(tmp, 0o600)
    tmp.replace(path)
