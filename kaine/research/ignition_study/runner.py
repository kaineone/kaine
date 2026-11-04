# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Study runner: process control, resume, locking, and step recording."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import shutil
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote, urlsplit

from kaine import legacy_aliases, legacy_names
from kaine.bus.config import load_bus_config, resolve_redis_auth
from kaine.bus.errors import BusConfigError
from kaine.cycle.control_state import read_control
from kaine.cycle.preserve_watch import read_request, read_result
from kaine.research.ignition_study.overlay import (
    IGNITION_LOG_DIR,
    SUPERVISOR_INCIDENT_DIR,
    build_overlay,
)
from kaine.research.ignition_study.plan import (
    LOCK_FILE,
    STEPS_FILE,
    ensure_line_dir,
    load_plan,
    validate_progressive_redis_db,
    validate_redis_base_url,
    validate_redis_dbs,
)
from kaine.research.ignition_study.toml_writer import dumps

log = logging.getLogger(__name__)

#: Slack for file mtimes, which on many kernels come from a coarse clock and
#: can trail the wall clock by up to a tick. A verdict left over from an
#: earlier step is minutes or hours older, so a 2 s window still rejects stale
#: files while accepting recently-written verdicts.
VIABILITY_MTIME_SLACK_S = 2.0

#: The key that names the study owning a bus database on the Redis server.
STUDY_OWNER_KEY = "kaine:study:owner"

#: The runner's record of the cycle it started, in the step's working directory.
CHILD_FILE = ".study_child.json"

#: The longest maturation bloom the stimulus source accepts (``StimulusSourceParams`` and
#: ``StimulusSourceClock.begin_maturation`` both bound ``maturation_transition_seconds`` to (0, 30]).
MATURATION_BLOOM_MAX_SECONDS = 30.0

#: Written into a step's working directory while the child's cycle is frozen by the
#: welfare safety net, so ``status`` can show it before the step ends.
WELFARE_FREEZE_FILE = ".study_welfare_freeze.json"

#: Written into a step's working directory just before the maturation preservation
#: is requested, with the reference state, so a restarted runner that adopts that
#: preservation records the seed's maturation reference correctly.
MATURATION_REFERENCE_FILE = ".study_maturation_reference.json"

#: How long the runner waits, after the maturation bloom ends, for the individuation
#: maturation reference (reference document plus ledger) before it preserves the seed
#: without it.  The capture is 12 prompts x 16 answers of up to 160 tokens, 192 sequential
#: organ requests: at a slow 20 tokens/s about 26 minutes, and the scheduler's own limit for
#: one capture attempt is ``capture_deadline_s`` = 5400 s.  The wait is that limit plus 1800 s
#: for the scheduler's blocked retry (300 s) and a restart of an attempt cut by a sleep.
MATURATION_REFERENCE_WAIT_SECONDS = 7200.0

#: The cycle's welfare exposure record, relative to a step's working directory.
EXPOSURE_FILE = "state/welfare/exposure.json"

#: The operator's answers to welfare holds, in the study directory.
WELFARE_ACKS_FILE = "welfare_acks.jsonl"

#: The decisions ``ack-welfare`` accepts.
WELFARE_DECISIONS = ("continue", "stop")

#: Why the runner holds after a step (content-free labels).
HOLD_REASONS = (
    "missing",
    "unreadable",
    "other_run",
    "other_boot",
    "incomplete_coverage",
    "indicator_crossing",
    "protective_response",
    "stimulus_control_first_hours",
)

#: Hold reasons that show the welfare net acted or an indicator crossed during
#: the boot. A failed step carrying one is not retried until a person answers
#: it, because the review must happen before the entity is booted again. The
#: other reasons (a record missing after a crash, for example) are shown in
#: ``status`` but do not block a retry.
REVIEW_HOLD_REASONS = ("indicator_crossing", "protective_response", "stimulus_control_first_hours")

#: A step recorded while its child was still running (a failed timeout or
#: disk-low preservation). Its child writes the exposure record only when it
#: exits, so the runner reads the record later, before anything boots again.
CRITICAL_OUTCOME = "failed:critical"

#: Where the runner keeps a copy of a step's exposure record before a boot in
#: the same step directory deletes it (relative to the step directory).
EXPOSURE_ARCHIVE_DIR = "welfare_exposure_archive"

#: ``maturation_reference`` values in a development step record.
REFERENCE_COMPLETE = "complete"
REFERENCE_MISSING = "missing"
REFERENCE_NOT_ENABLED = "not_enabled"

_STIMULUS_FIRST_HOURS_RELPATH = "state/lifecycle/stimulus_control_first_hours.json"


class StudyComplete(Exception):
    """Raised when every planned step is already recorded as complete."""


class StudyHalted(Exception):
    """Raised when a step fails and the runner refuses to continue."""

    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record


class StudyCritical(Exception):
    """Raised when a timeout preservation fails and the operator must decide."""


class StudyWelfareHold(Exception):
    """Raised when a completed step's welfare exposure holds the run for review.

    The next step does not start until the operator answers with
    ``ack-welfare``.
    """

    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record


class StudyLocked(Exception):
    """Raised when another runner already holds the study lock."""


class StudyError(Exception):
    """Raised for plan/resume preconditions that prevent running."""


class StudyDatabaseClaimed(StudyError):
    """Raised when another study owns a bus database this study would flush."""


# The free-disk probe a runner uses when none is injected. A module-level name
# (resolved when a runner is built) so tests can pin it instead of reading the
# host's real disk.
_default_disk_usage = shutil.disk_usage


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
        maturation_bloom_margin_seconds: float = 2.0,
        maturation_reference_wait_seconds: float = MATURATION_REFERENCE_WAIT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
        popen: Any = subprocess.Popen,
        run: Any = subprocess.run,
        flush_db: Callable[[str], None] | None = None,
        redis_client_factory: Callable[[str], Any] | None = None,
        disk_usage: Callable[[Path], Any] | None = None,
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
        self.maturation_bloom_margin_seconds = maturation_bloom_margin_seconds
        self.maturation_reference_wait_seconds = maturation_reference_wait_seconds
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
        self.disk_usage = disk_usage or _default_disk_usage
        self.cycle_alive = cycle_alive or _cycle_process_alive
        self._lock_fd: Any | None = None
        self._move_old_line_dirs()
        self._load_state()

    # --------------------------------------------------------------------- #
    # State
    # --------------------------------------------------------------------- #

    def _move_old_line_dirs(self) -> None:
        for entry in legacy_aliases.active(legacy_names.STAGE_VALUES):
            old = entry["old"]
            new = entry["new"]
            old_dir = self.study_dir / old
            if not (old_dir.is_symlink() or old_dir.exists()):
                continue
            if old_dir.is_symlink():
                raise StudyError(
                    f"study {self.study_dir}: {old}/ is a symlink; move it aside and re-run"
                )
            new_dir = self.study_dir / new
            if new_dir.exists():
                raise StudyError(
                    f"study {self.study_dir} holds both {old}/ and {new}/; move one aside and re-run"
                )
            os.rename(old_dir, new_dir)
            log.info("Renamed study line directory %s -> %s", old_dir, new_dir)

    def _map_bundle_path(self, path: str) -> str:
        p = Path(path)
        for entry in legacy_aliases.active(legacy_names.STAGE_VALUES):
            old_dir = self.study_dir / entry["old"]
            try:
                rel = p.relative_to(old_dir)
            except ValueError:
                continue
            return str(self.study_dir / entry["new"] / rel)
        return path

    def _load_state(self) -> None:
        self.steps: list[dict[str, Any]] = []
        if self.steps_path.exists():
            for line in self.steps_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    log.warning("Ignoring malformed steps.jsonl line: %s", line)
                    continue
                record = legacy_aliases.map_study_step(record)
                if isinstance(record.get("bundle"), str):
                    record["bundle"] = self._map_bundle_path(record["bundle"])
                self.steps.append(record)

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

        # The operator's answers to welfare holds.
        self.welfare_acks: list[dict[str, Any]] = []
        acks_path = self.study_dir / WELFARE_ACKS_FILE
        if acks_path.exists():
            for raw in acks_path.read_text().splitlines():
                if not raw.strip():
                    continue
                try:
                    ack = json.loads(raw)
                except json.JSONDecodeError:
                    log.warning("Ignoring malformed %s line", WELFARE_ACKS_FILE)
                    continue
                if isinstance(ack, dict) and ack.get("decision") in WELFARE_DECISIONS:
                    self.welfare_acks.append(ack)
        self.stopped_lines: set[str] = set()
        for ack in self.welfare_acks:
            if ack.get("decision") == "stop":
                self.stopped_lines |= _lines_ended_by(ack.get("line"), ack.get("step"))

    def _step_sequence(self) -> list[tuple[str, int]]:
        if self.plan.get("protocol") == "progressive":
            return self._progressive_step_sequence()
        k = len(self.plan["order"])
        seq: list[tuple[str, int]] = [("development", 0), ("branch", 0), ("repeat", 0)]
        for i in range(1, k + 1):
            seq.append(("branch", i))
            seq.append(("accumulate", i))
        return seq

    def _progressive_step_sequence(self) -> list[tuple[str, int]]:
        steps = self.plan["steps"]
        return [(s["kind"], s["step_index"]) for s in steps]

    def _disk_floor_bytes(self, total: float) -> float:
        """Minimum free bytes the study requires on its filesystem."""
        min_free_gb = float(self.plan.get("min_free_gb", 20.0))
        return max(min_free_gb * (2**30), total * 0.05)

    def _next_step(self, retry_failed: bool = False) -> dict[str, Any]:
        sequence = self._step_sequence()

        if retry_failed and self.last_failed:
            rec = self.last_failed
            if rec.get("line") in self.stopped_lines:
                raise StudyError(
                    f"{rec.get('line')} step {rec.get('step')} is not retried: its line "
                    f"was stopped after a welfare review"
                )
            self._resolve_critical_exposure()
            held = self.failed_welfare_hold() or self.pending_welfare_hold()
            if held is not None:
                raise StudyWelfareHold(held)
            return {
                "line": rec["line"],
                "k": rec["step"],
                "revived_from": rec.get("revived_from"),
                "is_retry": True,
            }

        if self.last_failed and self.last_failed.get("line") not in self.stopped_lines:
            raise StudyHalted(self.last_failed)

        held = self.pending_welfare_hold()
        if held is not None:
            raise StudyWelfareHold(held)

        if self.plan.get("protocol") == "progressive":
            return self._next_progressive_step(sequence)
        return self._next_branching_step(sequence)

    def _next_progressive_step(
        self, sequence: list[tuple[str, int]]
    ) -> dict[str, Any]:
        steps = self.plan["steps"]
        steps_by_index = {s["step_index"]: s for s in steps}
        for kind, step_index in sequence:
            if (kind, step_index) in self.completed_steps:
                continue
            if kind in self.stopped_lines:
                continue
            step_def = steps_by_index[step_index]
            if step_index == 0:
                revived_from: str | None = None
            else:
                prior_bundle = self.line_bundles.get(
                    (steps_by_index[step_index - 1]["kind"], step_index - 1)
                )
                if prior_bundle is None:
                    raise StudyError(
                        f"step {step_index - 1} has not completed; "
                        f"cannot start step {step_index}"
                    )
                revived_from = prior_bundle
            return {
                "line": kind,
                "k": step_index,
                "revived_from": revived_from,
                "progressive_step": step_def,
                "is_retry": False,
            }
        raise StudyComplete()

    def _next_branching_step(
        self, sequence: list[tuple[str, int]]
    ) -> dict[str, Any]:
        seed = self.line_bundles.get(("development", 0))
        for line, k in sequence:
            if (line, k) in self.completed_steps:
                continue
            if line in self.stopped_lines:
                continue

            if line == "development":
                revived_from: str | None = None
            elif line in ("branch", "repeat"):
                if seed is None:
                    raise StudyError("development has not completed")
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
        if self.plan.get("protocol") == "progressive":
            from kaine.research.ignition_study.plan import step_dir_name
            return self.study_dir / step_dir_name(self.plan, k)
        if line == "branch":
            return self.study_dir / "branch" / str(k)
        return self.study_dir / line

    def _ensure_step_dir(self, line: str, k: int) -> Path:
        if self.plan.get("protocol") == "progressive":
            from kaine.research.ignition_study.plan import step_dir_name
            d = self.study_dir / step_dir_name(self.plan, k)
            d.mkdir(parents=True, exist_ok=True)
            return d
        return ensure_line_dir(
            self.study_dir, line, k, Path(self.plan["repo_root"])
        )

    def _read_maturation_bloom_deadline(self, line_dir: Path) -> float | None:
        """``maturation_bloom_ends_at`` from the step's stage file, as a wall-clock
        timestamp, or ``None`` when the file or the field is absent or bad."""
        path = line_dir / "state" / "lifecycle" / "stage.json"
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        data = legacy_aliases.map_stage_record(data)
        ends_at = data.get("maturation_bloom_ends_at")
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

    def _maturation_bloom_over(
        self, line_dir: Path, first_embodied_wall: float, fallback_seconds: float
    ) -> bool:
        """Whether the maturation bloom has ended: at the stage file's
        ``maturation_bloom_ends_at`` when it has one, else ``fallback_seconds``
        after the runner first saw the embodied stage."""
        now = self.wall_clock()
        deadline = self._read_maturation_bloom_deadline(line_dir)
        if deadline is not None:
            return now >= deadline
        return now - first_embodied_wall >= fallback_seconds

    @staticmethod
    def _maturation_reference_complete(runtime: dict[str, Any]) -> bool:
        """Whether the child's individuation maturation reference is complete.

        Reads the content-free ``individuation`` block the cycle writes into
        ``state/cycle/runtime.json``. The block is true only when the scheduler
        reports a present reference, a readable ledger, and the ledger file on
        disk, and the reference kind is ``maturation``.  A capture downgraded
        during sleep has kind ``capture`` and does not count as the maturation
        reference; the runner keeps waiting for a maturation reference or times
        out. The caller must pass a ``runtime.json`` that has already been
        guarded against stale files from earlier children.
        """
        if not isinstance(runtime, dict):
            return False
        block = runtime.get("individuation")
        if not isinstance(block, dict):
            return False
        return bool(block.get("reference_complete")) and block.get("reference_kind") == "maturation"

    @staticmethod
    def _maturation_reference_downgraded(runtime: dict[str, Any]) -> bool:
        """Whether a maturation capture was downgraded to a plain capture.

        If the child slept during the individuation maturation capture, the
        scheduler records ``reference_complete`` true but with
        ``reference_kind == "capture"``.  The runner must not preserve such a
        seed as complete; it is treated as a missing maturation reference.
        """
        if not isinstance(runtime, dict):
            return False
        block = runtime.get("individuation")
        if not isinstance(block, dict):
            return False
        return bool(block.get("reference_complete")) and block.get("reference_kind") == "capture"

    def _maturation_bloom_fallback_seconds(self, line_dir: Path, env: Mapping[str, str]) -> float:
        """How long to wait after the embodied stage when the stage file does
        not name the bloom's end: the child's own
        ``[perception_feed.stimulus_source].maturation_transition_seconds`` (loaded exactly as
        the cycle loads it from the step's working directory) plus the margin.
        When that value cannot be resolved, the longest bloom the stimulus source accepts
        plus the margin, so the seed is never preserved mid-bloom."""
        from kaine.boot import _stimulus_source_params
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
            seconds = float(_stimulus_source_params(feed).maturation_transition_seconds)
        except Exception as exc:
            log.warning(
                "maturation bloom length unresolved (%s); waiting the %.0f s maximum",
                type(exc).__name__,
                MATURATION_BLOOM_MAX_SECONDS,
            )
            seconds = MATURATION_BLOOM_MAX_SECONDS
        return seconds + self.maturation_bloom_margin_seconds

    def _resolve_redis_db(self, line: str) -> int:
        """Return the Redis database number for a step on *line*.

        Progressive plans store a single int; branching plans store a
        per-line dict.
        """
        db = self.plan["redis"]["db"]
        if isinstance(db, int):
            return db
        return db[line]

    def _check_operator_bus(self) -> None:
        """Refuse when a study database is the operator's bus database, as the
        bus itself resolves it from the operator's configuration now."""
        operator_dbs = _operator_bus_dbs(Path(self.plan["repo_root"]), os.environ)
        db = self.plan["redis"]["db"]
        try:
            if isinstance(db, int):
                validate_progressive_redis_db(db, operator_dbs)
            else:
                validate_redis_dbs(db, operator_dbs)
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

    def _adopt_maturation_preservation(
        self, line_dir: Path, modules_set: set[str]
    ) -> dict[str, Any] | None:
        """A developmental phase whose maturation preservation succeeded before the runner
        could record it: its record, built from the preservation pair on disk,
        or ``None`` when there is no such preservation."""
        state = line_dir / "state" / "cycle"
        req = read_request(state / "preserve_request.json")
        res = read_result(state / "preserve_result.json")
        if (
            req is None
            or res is None
            or req.reason != "maturation"
            or res.get("request_id") != req.request_id
            or not res.get("ok")
        ):
            return None
        bundle = res.get("bundle")
        if not isinstance(bundle, str) or not bundle or not Path(bundle).is_dir():
            return None
        outcome = "complete"
        world_model_captured: bool | None = None
        if "world_model" in modules_set:
            extra_outcome, world_model_captured = _check_world_model_manifest(bundle)
            if extra_outcome:
                outcome = extra_outcome
        marker = line_dir / MATURATION_REFERENCE_FILE
        try:
            marker_data = json.loads(marker.read_text(encoding="utf-8"))
            maturation_reference = (
                marker_data["state"]
                if isinstance(marker_data, dict)
                and isinstance(marker_data.get("state"), str)
                else REFERENCE_MISSING
            )
        except (OSError, ValueError, KeyError, TypeError):
            maturation_reference = REFERENCE_MISSING
        if maturation_reference == REFERENCE_MISSING:
            outcome = "failed:maturation_reference_missing"
        overlay_path = line_dir / "config" / "kaine.operator.toml"
        try:
            overlay_hash: str | None = hashlib.sha256(overlay_path.read_bytes()).hexdigest()
        except OSError:
            overlay_hash = None
        return {
            "line": "development",
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
            "maturation_reference": maturation_reference,
            "adopted": True,
        }

    def _apply_exposure(self, record: dict[str, Any]) -> None:
        """Copy the step's bound exposure record into ``record``, or mark the hold.

        The record is accepted only when its ``run_id`` is the step's and its
        ``boot_started_at`` is not before the step's start. The run holds when
        the record is missing, unreadable, bound to another run or boot,
        incomplete in coverage, or shows any indicator crossing.
        """
        line_dir = self._line_dir(record["line"], record["step"])
        exposure, reasons = read_step_exposure(
            line_dir, run_id=record.get("run_id"), since_iso=record.get("started_at")
        )
        if exposure is not None:
            record["welfare_exposure"] = exposure
        if reasons:
            record["welfare_hold"] = {"reasons": reasons}

    def pending_welfare_hold(self) -> dict[str, Any] | None:
        """The latest completed step record whose welfare hold is unanswered."""
        for rec in reversed(self.steps):
            if rec.get("outcome") != "complete":
                continue
            if not isinstance(rec.get("welfare_hold"), dict):
                continue
            if self._welfare_ack_for(rec) is not None:
                continue
            return rec
        return None

    def critical_exposure_unread(self) -> bool:
        """True while the last failed step is a critical one whose exposure
        record the runner has not read yet."""
        rec = self.last_failed
        return (
            rec is not None
            and rec.get("outcome") == CRITICAL_OUTCOME
            and not rec.get("exposure_read")
        )

    def _resolve_critical_exposure(self) -> None:
        """Read a critical step's exposure record once its child has exited.

        The critical record was written while the child still ran, so it holds
        no exposure. Once no cycle of the study runs, the child's record is
        read and bound to the critical record's run and start, and the step is
        recorded again with it (same line, step and ``ended_at``, so an answer
        to the hold matches). Any hold reason, a missing or unreadable record
        included, then blocks the retry until a person answers it.
        """
        if not self.critical_exposure_unread():
            return
        self._refuse_if_cycle_running()
        resolved = dict(self.last_failed)
        resolved.pop("welfare_hold", None)
        resolved.pop("welfare_exposure", None)
        self._archive_exposure(self._line_dir(resolved["line"], resolved["step"]))
        self._apply_exposure(resolved)
        resolved["exposure_read"] = True
        self._append_step(resolved)
        self.last_failed = resolved

    def _archive_exposure(self, line_dir: Path) -> None:
        """Copy the step directory's exposure record aside before a boot deletes it.

        Every boot deletes ``state/welfare/exposure.json``; the copy keeps a
        record the runner may not have bound yet. A copy that cannot be made
        refuses the boot (fail closed: a record must never be lost unread).
        """
        source = Path(line_dir) / EXPOSURE_FILE
        if not source.exists():
            return
        archive = Path(line_dir) / EXPOSURE_ARCHIVE_DIR
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        try:
            archive.mkdir(parents=True, exist_ok=True)
            target = archive / f"exposure-{stamp}.json"
            tmp = archive / f".exposure-{stamp}.tmp"
            tmp.write_bytes(source.read_bytes())
            os.chmod(tmp, 0o600)
            os.replace(tmp, target)
        except OSError as exc:
            raise StudyError(
                f"cannot keep a copy of {source} before the next boot deletes it: {exc}"
            ) from exc

    def failed_welfare_hold(self) -> dict[str, Any] | None:
        """The failed step record awaiting a retry whose welfare hold must be
        answered first: one naming a reason in ``REVIEW_HOLD_REASONS``, or a
        critical step with any hold reason, with no answer recorded for it."""
        rec = self.last_failed
        if rec is None or self._welfare_ack_for(rec) is not None:
            return None
        hold = rec.get("welfare_hold")
        if not isinstance(hold, dict):
            return None
        reasons = hold.get("reasons")
        if not isinstance(reasons, list) or not reasons:
            # A hold whose reasons cannot be read cannot show that nothing happened.
            return rec
        if rec.get("outcome") == CRITICAL_OUTCOME:
            # Its child ran on after the runner gave up on it: a record that is
            # missing or cannot be bound cannot show that nothing happened.
            return rec
        if any(r in REVIEW_HOLD_REASONS or r not in HOLD_REASONS for r in reasons):
            return rec
        return None

    def unanswered_failed_hold(self) -> dict[str, Any] | None:
        """The failed step record awaiting a retry with any unanswered welfare
        hold, including the status-only ones."""
        rec = self.last_failed
        if rec is None or not isinstance(rec.get("welfare_hold"), dict):
            return None
        if self._welfare_ack_for(rec) is not None:
            return None
        return rec

    def _welfare_ack_for(self, rec: dict[str, Any]) -> dict[str, Any] | None:
        for ack in self.welfare_acks:
            if (
                ack.get("line") == rec.get("line")
                and ack.get("step") == rec.get("step")
                and ack.get("step_ended_at") == rec.get("ended_at")
            ):
                return ack
        return None

    def acknowledge_welfare(self, line: str, k: int, decision: str) -> dict[str, Any]:
        """Record the operator's answer to a welfare hold; never touches a step's state.

        ``continue`` releases the hold; ``stop`` ends the step's line (and any
        line that continues its entity) and leaves every preservation in place.
        """
        if decision not in WELFARE_DECISIONS:
            raise StudyError(f"decision must be one of {', '.join(WELFARE_DECISIONS)}")
        self._resolve_critical_exposure()
        candidates = [
            rec
            for rec in (self.pending_welfare_hold(), self.unanswered_failed_hold())
            if rec is not None
        ]
        held = next(
            (rec for rec in candidates if rec.get("line") == line and rec.get("step") == k),
            None,
        )
        if held is None:
            pending = (
                ", ".join(f"{rec['line']}/{rec['step']}" for rec in candidates) or "none"
            )
            raise StudyError(
                f"no welfare hold is pending for {line}/{k} (pending: {pending})"
            )
        ack = {
            "line": line,
            "step": k,
            "decision": decision,
            "acknowledged_at": _utc_iso(),
            "step_ended_at": held.get("ended_at"),
            "reasons": list((held.get("welfare_hold") or {}).get("reasons") or []),
        }
        with open(self.study_dir / WELFARE_ACKS_FILE, "a") as f:
            f.write(json.dumps(ack) + "\n")
        self.welfare_acks.append(ack)
        if decision == "stop":
            self.stopped_lines |= _lines_ended_by(line, k)
        return ack

    def _finish_record(self, record: dict[str, Any]) -> dict[str, Any]:
        self._apply_exposure(record)
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
        step_kind = "development" if line in ("development", "seed") else "viewing"
        repo_root = Path(self.plan["repo_root"])

        # Nothing is flushed, adopted or started while a cycle the study
        # started may still hold a study database or a step directory.
        self._refuse_if_cycle_running()
        # The boot deletes the directory's exposure record; keep a copy first.
        self._archive_exposure(line_dir)

        overlay, modules_set, models_dir = build_overlay(
            self.plan,
            line,
            step_kind,
            k,
            repo_root,
            repo_root / "config" / "kaine.toml",
            repo_root / "config" / "kaine.operator.toml",
            progressive_step=step.get("progressive_step"),
        )

        # A runner that died after the seed's maturation preservation succeeded,
        # but before recording it, left the seed on disk: adopt it rather than
        # develop a second entity.
        if (
            step_kind == "development"
            and not step.get("is_retry")
            and not any(rec.get("line") == "development" for rec in self.steps)
        ):
            adopted = self._adopt_maturation_preservation(line_dir, modules_set)
            if adopted is not None:
                prog = step.get("progressive_step")
                if prog is not None:
                    adopted["step_index"] = prog["step_index"]
                    adopted["modules_added"] = sorted(prog.get("modules_added", []))
                log.info("Adopting the recorded maturation preservation %s", adopted["bundle"])
                return self._finish_record(adopted)

        overlay_toml = dumps(overlay)
        overlay_hash = hashlib.sha256(overlay_toml.encode()).hexdigest()

        operator_path = line_dir / "config" / "kaine.operator.toml"
        _write_text_atomic(operator_path, overlay_toml)

        env = dict(os.environ)
        # The child's data root is its line directory via the overlay; never let
        # an ambient KAINE_DATA_ROOT override that sandbox.
        env.pop("KAINE_DATA_ROOT", None)
        # The step's overlay is its study configuration; an ambient KAINE_STUDY
        # would override it.
        env.pop("KAINE_STUDY", None)
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
            f"{self._resolve_redis_db(line)}"
        )
        env["KAINE_REDIS_URL"] = redis_url
        env["KAINE_MODELS_DIR"] = models_dir

        bloom_fallback = (
            self._maturation_bloom_fallback_seconds(line_dir, env)
            if step_kind == "development"
            else 0.0
        )

        # The operator's configuration can change during a multi-day study:
        # check it again immediately before the flush.  The check reads the
        # runner's own environment, never the child's ``env`` above.
        self._check_operator_bus()

        # Guard the filesystem that holds the study directory before any
        # flush or spawn.  Nothing is recorded if the guard fails.
        usage = self.disk_usage(self.study_dir)
        floor = self._disk_floor_bytes(float(usage.total))
        if float(usage.free) < floor:
            free_gib = float(usage.free) / (2**30)
            required_gib = floor / (2**30)
            raise StudyError(
                f"free disk space at {self.study_dir} is {free_gib:.1f} GiB, "
                f"below required floor {required_gib:.1f} GiB"
            )

        # Every step starts on an empty bus: flush the step's own study
        # database (never the operator's; see validate_redis_dbs), which this
        # study claims on the server so no other study flushes it.
        try:
            self.flush_db(redis_url)
        except StudyError:
            raise
        except Exception as exc:
            raise StudyError(
                f"could not flush bus database {self._resolve_redis_db(line)} "
                f"before {line} step {k}: {type(exc).__name__}"
            ) from None

        argv = list(self.cycle_command)
        if step_kind == "viewing":
            argv.extend(["--revive", step["revived_from"]])

        # Remember the request id already on disk for this line, if any.
        # A step only owns a preservation pair that was produced while it ran.
        prior_request_path = line_dir / "state" / "cycle" / "preserve_request.json"
        prior_request = read_request(prior_request_path)
        prior_request_id = prior_request.request_id if prior_request else None

        # A runtime.json already on disk belongs to an earlier child (a retry
        # after a failed timeout preservation, or a killed runner).  It is
        # metadata, not the entity's state: it stays where it is, and the loop
        # below never acts on it.
        stale_runtime = self._read_runtime(line_dir)

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
        disk_low_requested = False
        disk_low_preserved: bool | None = None
        maturation_requested = False
        # The welfare safety net froze the child (read from its control.json each
        # poll).  The runner never lifts it: it names it and leaves the decision.
        welfare_freeze: dict[str, Any] | None = None
        (line_dir / WELFARE_FREEZE_FILE).unlink(missing_ok=True)
        (line_dir / MATURATION_REFERENCE_FILE).unlink(missing_ok=True)
        # Whether the child runs the individuation producer, which captures the
        # maturation reference; the overlay's [individuation].enabled decides.
        expect_reference = _individuation_enabled(repo_root, overlay)
        reference_state: str | None = None
        reference_wait_elapsed = 0.0
        reference_wait_last: float | None = None
        first_embodied_wall: float | None = None
        warned_about_welfare_freeze_hold = False
        unviable_verdict: dict[str, Any] | None = None
        unviable_terminated = False
        extra_viability: dict[str, Any] | None = None
        # A verdict file older than this step (by more than the mtime slack)
        # belongs to an earlier attempt.
        step_started_wall = self.wall_clock()

        start_clock = self.clock()
        budget = (
            self.plan["development_budget_seconds"]
            if step_kind == "development"
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
                runtime = self._read_child_runtime(line_dir, child_pid, stale_runtime)
                if runtime:
                    run_id = runtime.get("run_id") or run_id
                    stage = (runtime.get("developmental_stage") or {}).get("stage")
                    if (
                        step_kind == "development"
                        and stage == "embodied"
                        and not maturation_requested
                    ):
                        if first_embodied_wall is None:
                            first_embodied_wall = self.wall_clock()
                        # The seed is the entity once its maturation bloom is over.
                        welfare_held = False
                        if self._maturation_bloom_over(
                            line_dir, first_embodied_wall, bloom_fallback
                        ):
                            welfare_held = (
                                self._welfare_freeze_entry(line_dir) is not None
                            )
                            # The individuation maturation reference is part of
                            # the seed and cannot be regenerated, so the seed is
                            # preserved only once the reference and its ledger are
                            # on disk, or the bounded wait has run out.
                            if not expect_reference:
                                reference_state = REFERENCE_NOT_ENABLED
                            elif self._maturation_reference_complete(runtime):
                                reference_state = REFERENCE_COMPLETE
                            else:
                                if reference_state is None:
                                    if self._maturation_reference_downgraded(runtime):
                                        reference_state = REFERENCE_MISSING
                                        log.error(
                                            "A sleep during the maturation capture made it a "
                                            "plain capture, so the seed is preserved without "
                                            "its maturation reference and the step is recorded "
                                            "as failed."
                                        )
                                    else:
                                        if (
                                            reference_wait_last is not None
                                            and not welfare_held
                                        ):
                                            reference_wait_elapsed += (
                                                now - reference_wait_last
                                            )
                                        reference_wait_last = now
                                        if (
                                            reference_wait_elapsed
                                            >= self.maturation_reference_wait_seconds
                                        ):
                                            reference_state = REFERENCE_MISSING
                                            log.error(
                                                "The maturation reference of %s did not complete "
                                                "within %.0f s; the seed is preserved without it "
                                                "and the step is recorded as failed.",
                                                line,
                                                self.maturation_reference_wait_seconds,
                                            )
                        if reference_state is not None and not welfare_held:
                            maturation_requested = True
                            _write_text_atomic(
                                line_dir / MATURATION_REFERENCE_FILE,
                                json.dumps({"state": reference_state}),
                            )
                            _, _, _, ok = self._request_preserve(
                                line_dir,
                                "maturation",
                                stop=True,
                                wait=self.preserve_wait_seconds,
                            )
                            if not ok:
                                log.error(
                                    "Maturation preservation request did not succeed for %s",
                                    line,
                                )
                        elif welfare_held and not warned_about_welfare_freeze_hold:
                            warned_about_welfare_freeze_hold = True
                            log.warning(
                                "Maturation preservation of %s waits for a person to "
                                "answer the welfare freeze before the step can end.",
                                line,
                            )

                if runtime:
                    welfare_freeze = self._note_welfare_freeze(
                        line, k, line_dir, welfare_freeze
                    )

                usage = self.disk_usage(self.study_dir)
                floor = self._disk_floor_bytes(float(usage.total))
                if (
                    float(usage.free) < floor
                    and not disk_low_requested
                    and not timeout_requested
                ):
                    disk_low_requested = True
                    _, disk_low_result, _, disk_low_matched = self._request_preserve(
                        line_dir,
                        "disk_low",
                        stop=True,
                        wait=self.preserve_wait_seconds,
                    )
                    disk_low_preserved = (
                        bool(disk_low_result.get("ok"))
                        if disk_low_result
                        else disk_low_matched
                    )
                    if not disk_low_matched:
                        log.critical(
                            "Disk-low preservation failed for %s; the process is still "
                            "running and the operator must decide what to do.",
                            line,
                        )
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
                            f"disk_low preservation failed for {line} step {k}; "
                            f"pid {child_pid} is still running"
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

            if step_kind == "development" and unviable_verdict is None and not timeout_requested and not maturation_requested and not disk_low_requested and first_embodied_wall is None:
                viability_path = line_dir / "state" / "lifecycle" / "development_viability.json"
                try:
                    if viability_path.stat().st_mtime < step_started_wall - VIABILITY_MTIME_SLACK_S:
                        raise FileNotFoundError("verdict predates this step")
                    viability_data = json.loads(viability_path.read_text())
                except FileNotFoundError:
                    # No verdict yet, or one left from an earlier attempt.
                    viability_data = None
                except Exception:
                    # A verdict that exists but cannot be read is retried next
                    # poll; say so instead of treating it silently as none.
                    log.warning(
                        "Development viability verdict for %s step %s could not be read",
                        line,
                        k,
                        exc_info=True,
                    )
                    viability_data = None
                if isinstance(viability_data, dict) and viability_data.get("verdict") == "unviable":
                    unviable_verdict = viability_data
                    log.warning(
                        "Development viability watch declared unviable for %s step %s "
                        "(rule %s): %s",
                        line,
                        k,
                        unviable_verdict.get("rule", "unknown"),
                        unviable_verdict.get("reason", ""),
                    )
            if unviable_verdict is not None and not unviable_terminated:
                try:
                    proc.terminate()
                    unviable_terminated = True
                except Exception:
                    log.warning(
                        "Failed to terminate development process for %s step %s",
                        line,
                        k,
                        exc_info=True,
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
            disk_low_requested=disk_low_requested,
            disk_low_preserved=disk_low_preserved,
        )

        if reference_state == REFERENCE_MISSING and outcome == "complete":
            outcome = "failed:maturation_reference_missing"

        if unviable_verdict is not None and not maturation_requested:
            outcome = "failed:development_unviable"
            extra_viability = unviable_verdict
            try:
                _write_unviable_note(
                    line_dir,
                    unviable_verdict,
                    line=line,
                    step=k,
                    run_id=run_id,
                )
            except Exception:
                log.warning(
                    "Failed to write unviable development note for %s step %s",
                    line,
                    k,
                    exc_info=True,
                )
        # A welfare freeze still held when the step ends names the outcome: the
        # step did not fail on time or disk, the entity was frozen for its welfare
        # and a person has to answer it.  An earlier freeze that has since been
        # lifted by a named override is recorded and does not change the outcome.
        # Only a freeze noticed on the running child counts: a control file left
        # by an earlier child must not rename the failure of one that never booted.
        # A supervisor escalation of this boot names the outcome: the supervisor
        # preserved the entity, shut it down and wrote escalation.json. The cycle
        # clears the file at every boot and the record must be dated inside this
        # step, so a previous attempt's escalation is never read as this one's.
        supervisor_escalation = read_step_escalation(line_dir, since_iso=started_at)
        if supervisor_escalation is not None:
            outcome = "failed:supervisor"
        welfare_held = (
            self._welfare_freeze_entry(line_dir) if welfare_freeze is not None else None
        )
        if welfare_held is not None and outcome != "complete":
            outcome = "failed:welfare"
        (line_dir / WELFARE_FREEZE_FILE).unlink(missing_ok=True)
        stimulus_first_hours_verdict: dict[str, Any] | None = None
        stimulus_path = line_dir / _STIMULUS_FIRST_HOURS_RELPATH
        try:
            if stimulus_path.stat().st_mtime < step_started_wall - VIABILITY_MTIME_SLACK_S:
                raise FileNotFoundError("verdict predates this step")
            stimulus_data = json.loads(stimulus_path.read_text())
        except FileNotFoundError:
            stimulus_data = None
        except Exception:
            log.warning(
                "stimulus_control_first_hours verdict for %s step %s could not be read",
                line,
                k,
                exc_info=True,
            )
            stimulus_data = None
        if isinstance(stimulus_data, dict) and stimulus_data.get("verdict") == "stopped":
            stimulus_first_hours_verdict = stimulus_data
            outcome = "failed:stimulus_control_first_hours"
        world_model_captured: bool | None = None
        if "world_model" in modules_set:
            world_model_captured = False
            if outcome == "complete" and bundle:
                extra_outcome, captured = _check_world_model_manifest(bundle)
                if extra_outcome:
                    outcome = extra_outcome
                world_model_captured = captured

        progressive = step.get("progressive_step")
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

        if progressive is not None:
            record["step_index"] = progressive["step_index"]
            record["modules_added"] = sorted(progressive.get("modules_added", []))

        if extra_viability is not None:
            record["viability"] = extra_viability

        if welfare_freeze is not None:
            record["welfare_freeze"] = dict(welfare_freeze, held_at_end=welfare_held is not None)

        if supervisor_escalation is not None:
            record["supervisor_escalation"] = supervisor_escalation

        if stimulus_first_hours_verdict is not None:
            record["stimulus_control_first_hours"] = stimulus_first_hours_verdict
            hold = record.get("welfare_hold")
            if isinstance(hold, dict) and isinstance(hold.get("reasons"), list):
                hold["reasons"].append("stimulus_control_first_hours")
            else:
                record["welfare_hold"] = {"reasons": ["stimulus_control_first_hours"]}

        if outcome == "complete":
            # A module restart is the architecture's own fault handling and does
            # not fail the step; the count is recorded so the analysis lists it.
            restarts, unreadable = count_supervisor_restarts(
                line_dir / SUPERVISOR_INCIDENT_DIR, since_iso=started_at
            )
            record["supervisor_restarts"] = restarts
            if unreadable:
                record["supervisor_restarts_unreadable_lines"] = unreadable

        if disk_low_requested:
            record["disk_low_preserved"] = bool(disk_low_preserved)

        if reference_state is not None:
            record["maturation_reference"] = reference_state

        return self._finish_record(record)

    # --------------------------------------------------------------------- #
    # Helpers
    # --------------------------------------------------------------------- #

    @staticmethod
    def _welfare_freeze_entry(line_dir: Path) -> dict[str, Any] | None:
        """The ``welfare`` entry of the child's freeze stack, or ``None``."""
        control = read_control(line_dir / "state" / "cycle" / "control.json")
        for entry in control.stack:
            if entry.get("source") == "welfare":
                return entry
        return None

    @staticmethod
    def _welfare_freeze_summary(entry: dict[str, Any]) -> dict[str, Any]:
        return {"since": entry.get("frozen_at"), "reason": entry.get("reason")}

    def _note_welfare_freeze(
        self,
        line: str,
        k: int,
        line_dir: Path,
        seen: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Surface a welfare freeze on the running child; never lift it.

        Logs it once, and keeps ``WELFARE_FREEZE_FILE`` in the step directory
        while it is held, for ``status``.  Returns the first summary seen."""
        entry = self._welfare_freeze_entry(line_dir)
        marker = line_dir / WELFARE_FREEZE_FILE
        if entry is None:
            marker.unlink(missing_ok=True)
            return seen
        summary = self._welfare_freeze_summary(entry)
        if (
            seen is None
            or summary.get("since") != seen.get("since")
            or summary.get("reason") != seen.get("reason")
        ):
            log.critical(
                "The welfare safety net froze %s step %s (since %s: %s). The entity was "
                "preserved first and stays frozen; the runner does not lift it. A person "
                "must answer it (override the welfare freeze by name, or stop the step).",
                line,
                k,
                summary["since"],
                summary["reason"],
            )
            _write_text_atomic(marker, json.dumps(summary))
            return summary
        return seen

    def _read_runtime(self, line_dir: Path) -> dict[str, Any] | None:
        path = line_dir / "state" / "cycle" / "runtime.json"
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None

    def _read_child_runtime(
        self,
        line_dir: Path,
        child_pid: Any,
        stale: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """runtime.json only when it belongs to the child this attempt started:
        it names ``child_pid`` (the cycle records its own pid) and is not the
        record left by an earlier child, which a reused pid could otherwise
        pass for this one.  Anything else is treated as absent, so an earlier
        child's stage never triggers a preservation of this one."""
        if not isinstance(child_pid, int) or isinstance(child_pid, bool):
            return None
        runtime = self._read_runtime(line_dir)
        if not isinstance(runtime, dict):
            return None
        pid = runtime.get("pid")
        if not isinstance(pid, int) or isinstance(pid, bool) or pid != child_pid:
            return None
        if stale is not None and runtime == stale:
            return None
        return runtime

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
        disk_low_requested: bool = False,
        disk_low_preserved: bool | None = None,
    ) -> str:
        if disk_low_requested:
            return "failed:disk_low"

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

        expected_reason = "maturation" if step_kind == "development" else "programme end"
        if legacy_aliases.map_stored_value(request.reason) != expected_reason:
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
            escalation = last.get("supervisor_escalation")
            if last.get("outcome") == "failed:supervisor" and isinstance(escalation, dict):
                if escalation.get("unreadable"):
                    lines.append(
                        "Supervisor escalation: the step's escalation record exists but "
                        "cannot be read. Check the step's state/cycle/escalation.json and "
                        "the supervisor's incident log before retrying the step."
                    )
                elif escalation.get("module") == "welfare_monitor":
                    lines.append(
                        f"Welfare monitor lost: the welfare monitor stopped watching, so "
                        f"the entity was preserved first (snapshot "
                        f"{escalation.get('snapshot_id')}) and shut down. Check the cycle "
                        f"log for the welfare monitor's errors, then retry the step."
                    )
                else:
                    lines.append(
                        f"Supervisor escalation: module {escalation.get('module')} after "
                        f"{escalation.get('attempts')} restart attempt(s); the entity was "
                        f"preserved first (snapshot {escalation.get('snapshot_id')}) and shut "
                        f"down. Check the host and the module, then retry the step."
                    )
            freeze = last.get("welfare_freeze")
            if last.get("outcome") == "failed:welfare" and isinstance(freeze, dict):
                lines.append(
                    f"Welfare freeze: held by the welfare safety net since "
                    f"{freeze.get('since')} ({freeze.get('reason')}); the entity was "
                    f"preserved first and the runner does not lift it. Override the "
                    f"welfare freeze by name, then retry the step."
                )
        for line_name, step_k in self._step_sequence():
            marker = self._line_dir(line_name, step_k) / WELFARE_FREEZE_FILE
            if not marker.exists():
                continue
            try:
                live = json.loads(marker.read_text())
            except (OSError, json.JSONDecodeError):
                lines.append(f"Welfare freeze marker unreadable: {line_name} step {step_k}")
                continue
            lines.append(
                f"Welfare freeze (running): {line_name} step {step_k} is frozen by the "
                f"welfare safety net since {live.get('since')} ({live.get('reason')}); "
                f"it waits for a person."
            )
        held = self.pending_welfare_hold()
        if held is not None:
            reasons = ", ".join((held.get("welfare_hold") or {}).get("reasons") or [])
            lines.append(
                f"Welfare hold: {held['line']} step {held['step']} ({reasons}); the next "
                f"step does not start until a person answers: python -m "
                f"kaine.research.ignition_study ack-welfare --study-dir {self.study_dir} "
                f"--step {held['line']}/{held['step']} --decision continue|stop"
            )
        if self.critical_exposure_unread():
            rec = self.last_failed
            lines.append(
                f"Welfare exposure unread: critical {rec['line']} step {rec['step']}; its "
                f"cycle may still run and writes its exposure record when it exits. Stop "
                f"it; --retry-failed then reads the record first and holds for review "
                f"when it is missing or shows the welfare net acting."
            )
        failed_hold = self.unanswered_failed_hold()
        if failed_hold is not None:
            lines.append(failed_hold_line(failed_hold, self.study_dir, self.failed_welfare_hold() is not None))
        if self.stopped_lines:
            lines.append(
                "Stopped after a welfare review: " + ", ".join(sorted(self.stopped_lines))
            )
        try:
            nxt = self._next_step()
            lines.append(f"Next: {nxt['line']} step {nxt['k']}")
        except StudyWelfareHold:
            lines.append("Next: held for welfare review")
        except StudyComplete:
            lines.append("Next: none")
        except StudyHalted:
            if self.failed_welfare_hold() is not None:
                lines.append(
                    f"Next: answer the welfare hold, then retry the failed step with "
                    f"--retry-failed ({self.last_failed['line']} step "
                    f"{self.last_failed['step']})"
                )
            else:
                lines.append(
                    f"Next: retry failed step with --retry-failed "
                    f"({self.last_failed['line']} step {self.last_failed['step']})"
                )
        return "\n".join(lines)


def failed_hold_line(rec: dict[str, Any], study_dir: Path, blocks_retry: bool) -> str:
    """The operator-facing line for a failed step's unanswered welfare hold."""
    reasons = ", ".join(str(r) for r in ((rec.get("welfare_hold") or {}).get("reasons") or []))
    command = (
        f"python -m kaine.research.ignition_study ack-welfare --study-dir {study_dir} "
        f"--step {rec['line']}/{rec['step']} --decision continue|stop"
    )
    if blocks_retry:
        return (
            f"Welfare hold: failed {rec['line']} step {rec['step']} ({reasons}); the welfare "
            f"net acted or an indicator crossed during this boot, so --retry-failed "
            f"refuses until a person answers: {command}"
        )
    return (
        f"Welfare hold: failed {rec['line']} step {rec['step']} ({reasons}); review "
        f"before retrying (a retry is not blocked), or answer: {command}"
    )


def _individuation_enabled(repo_root: Path, overlay: Mapping[str, Any]) -> bool:
    """Whether the child's resolved configuration (the shipped file layered
    with the step overlay) enables the individuation producer."""
    from kaine.config import deep_merge

    try:
        base = tomllib.loads((repo_root / "config" / "kaine.toml").read_text())
    except (OSError, tomllib.TOMLDecodeError):
        base = {}
    section = deep_merge(base, dict(overlay)).get("individuation")
    return isinstance(section, dict) and section.get("enabled") is True


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


def _lines_ended_by(line: Any, step: Any) -> set[str]:
    """The lines a ``stop`` on (line, step) ends: the line, and any line that
    continues its entity (every line starts from the developmental seed; the
    accumulate line continues branch 0)."""
    if line == "development":
        return {"development", "branch", "repeat", "accumulate"}
    ended = {str(line)}
    if line == "branch" and step == 0:
        ended.add("accumulate")
    return ended


def _is_count(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_number(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
    )


def read_step_exposure(
    line_dir: Path, *, run_id: str | None, since_iso: str | None
) -> tuple[dict[str, Any] | None, list[str]]:
    """Read and check a step's exposure record.

    Returns ``(record or None, hold reasons)``. The record is returned only
    when it is bound to this step's run and boot; the reasons name every
    cause to hold (fail closed: a missing, unreadable or unbound record holds).
    """
    path = Path(line_dir) / EXPOSURE_FILE
    if not path.exists():
        return None, ["missing"]
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None, ["unreadable"]
    if not isinstance(data, dict) or data.get("schema") != 1:
        return None, ["unreadable"]
    if not isinstance(run_id, str) or not run_id or data.get("run_id") != run_id:
        return None, ["other_run"]
    booted = _parse_iso(data.get("boot_started_at"))
    if booted is None or not _not_before(booted, since_iso) or _parse_iso(since_iso) is None:
        return None, ["other_boot"]
    reasons: list[str] = []
    monitor = data.get("monitor")
    covered = data.get("covered_awake_seconds")
    restarts = data.get("producer_restarts")
    interval = data.get("affect_summary_interval_s")
    # The tally counts wall seconds; the monitor's spans count awake entity
    # seconds, which run ahead of wall time when the entity is dilated. The
    # comparison uses the monitor's count converted to wall seconds, so like
    # is compared with like at every time scale.
    if (
        not isinstance(monitor, dict)
        or not _is_number(monitor.get("awake_seconds"))
        or not _is_number(monitor.get("awake_wall_seconds"))
        # An indicator poll that raised counted nothing for its interval.
        or not _is_count(monitor.get("indicator_poll_failures"))
        or monitor["indicator_poll_failures"] > 0
    ):
        reasons.append("incomplete_coverage")
    elif (
        not _is_count(restarts)
        or restarts > 0
        or not _is_number(covered)
        or not _is_number(interval)
        or float(covered) < float(monitor["awake_wall_seconds"]) - float(interval)
    ):
        reasons.append("incomplete_coverage")
    if isinstance(monitor, dict):
        crossed = False
        for key in ("rests_requested", "freezes_placed"):
            value = monitor.get(key)
            # A count that is not a count cannot show that nothing crossed.
            if not _is_count(value) or value > 0:
                crossed = True
        indicators = monitor.get("indicators")
        if not isinstance(indicators, dict) or not indicators:
            if "incomplete_coverage" not in reasons:
                reasons.append("incomplete_coverage")
        else:
            for entry in indicators.values():
                if not isinstance(entry, dict):
                    crossed = True
                    continue
                for key in ("crossings", "rests_requested", "freezes_placed"):
                    value = entry.get(key)
                    if not _is_count(value) or value > 0:
                        crossed = True
        if crossed:
            reasons.append("indicator_crossing")
        # Every protective response the net took, by reason label. With
        # action "end" an unavailable-indicators or distress response places
        # no freeze and requests no rest, so only this count shows it. A value
        # that is not a dict of counts cannot show that nothing happened.
        responses = monitor.get("responses")
        if not isinstance(responses, dict) or responses:
            reasons.append("protective_response")
    return data, reasons


#: A step's escalation record, relative to its working directory.
ESCALATION_FILE = "state/cycle/escalation.json"

#: Slack for comparing a record's timestamp with the step's start (clock tick).
_STEP_TIME_SLACK_S = 2.0


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _not_before(value: datetime, since_iso: str | None) -> bool:
    """True when ``value`` is not earlier than the step's start (with slack)."""
    since = _parse_iso(since_iso)
    if since is None:
        return True
    return (value - since).total_seconds() >= -_STEP_TIME_SLACK_S


def read_step_escalation(line_dir: Path, *, since_iso: str | None) -> dict[str, Any] | None:
    """The content-free fields of this boot's supervisor escalation, or ``None``.

    The cycle clears ``escalation.json`` at every boot and the supervisor writes
    it only when it escalates, so a record with ``escalated`` true and an
    ``escalated_at`` inside the step is this boot's. A record dated before the
    step belongs to an earlier attempt and is ignored. A file that exists but
    cannot be read, or an escalation without a readable time, counts as this
    boot's (fail closed: the run halts for the operator). The free-text message
    is left out.
    """
    path = Path(line_dir) / ESCALATION_FILE
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {"unreadable": True}
    if not isinstance(data, dict):
        return {"unreadable": True}
    if data.get("escalated") is not True:
        return None
    escalated_at = _parse_iso(data.get("escalated_at"))
    if escalated_at is not None and not _not_before(escalated_at, since_iso):
        return None
    attempts = data.get("attempts")
    module = data.get("module")
    snapshot_id = data.get("snapshot_id")
    return {
        "module": module if isinstance(module, str) else None,
        "attempts": attempts if isinstance(attempts, int) and not isinstance(attempts, bool) else None,
        "snapshot_id": snapshot_id if isinstance(snapshot_id, str) else None,
        "escalated_at": data.get("escalated_at") if escalated_at is not None else None,
    }


def count_supervisor_restarts(
    incident_dir: Path, *, since_iso: str | None
) -> tuple[int | None, int]:
    """Count the supervisor's ``restart`` transitions in a step's incident log.

    Returns ``(count, unreadable_lines)``. Only records stamped at or after the
    step's start count, because the incident log is never cleared and keeps an
    earlier attempt's records. Lines are read through the process's state
    encryptor: a line it cannot decrypt or parse makes the count unknown
    (``None``), never a silent zero. The analysis, which installs the operator's
    state key, counts again for a step whose count is unknown.
    """
    from kaine.security.crypto import get_state_encryptor

    incident_dir = Path(incident_dir)
    if not incident_dir.is_dir():
        return 0, 0
    encryptor = get_state_encryptor()
    restarts = 0
    unreadable = 0
    for path in sorted(incident_dir.glob("incidents-*.jsonl")):
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            unreadable += 1
            continue
        for raw in lines:
            if not raw.strip():
                continue
            try:
                record = json.loads(encryptor.decrypt_text(raw))
            except Exception:
                unreadable += 1
                continue
            if not isinstance(record, dict) or record.get("transition") != "restart":
                continue
            ts = _parse_iso(record.get("ts"))
            if ts is None:
                unreadable += 1
                continue
            if _not_before(ts, since_iso):
                restarts += 1
    if unreadable:
        return None, unreadable
    return restarts, 0


def _check_world_model_manifest(bundle_path: str) -> tuple[str | None, bool | None]:
    """Return an extra outcome and captured flag for a world model bundle."""
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


def _write_unviable_note(
    line_dir: Path,
    verdict: dict,
    *,
    line: str,
    step: int,
    run_id: str | None,
) -> Path:
    note_path = line_dir / "ENDED-NOTE.md"
    rule = verdict.get("rule", "unknown")
    reason = verdict.get("reason", "")
    lived_hours = verdict.get("lived_hours", "unknown")
    evidence = verdict.get("evidence", {})
    when = datetime.now(timezone.utc).isoformat()
    evidence_lines = (
        "\n".join(f"- {key}: {value}" for key, value in evidence.items())
        if isinstance(evidence, dict)
        else f"- evidence: {evidence}"
    )
    text = (
        f"# Development ended: it could not reach maturation\n\n"
        f"- When: {when}\n"
        f"- Line: {line}\n"
        f"- Step: {step}\n"
        f"- Run id: {run_id}\n\n"
        f"## Viability verdict\n\n"
        f"- Rule: {rule}\n"
        f"- Reason: {reason}\n"
        f"- Lived hours: {lived_hours}\n\n"
        f"## Evidence\n\n{evidence_lines}\n\n"
        f"## What happened\n\n"
        f"The development owner's viability watch judged, from the entrainment "
        f"measurements, that the entity could not complete development within its "
        f"budget. The cycle was stopped without a preservation bundle (operator "
        f"policy for entities that do not complete development). All of this "
        f"step's data is kept in this directory.\n\n"
        f"See the development chapter of the KAINE book (Readiness markers; How "
        f"entrainment is measured; Viability watch).\n"
    )
    _write_text_atomic(note_path, text)
    return note_path
