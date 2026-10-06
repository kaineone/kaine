# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""In-memory job runner for the browser setup server.

Jobs are long-running subprocesses started only by an explicit POST.  They run
with an argument list, never a shell string, and their output is kept in a
bounded in-memory deque for the session only.
"""

from __future__ import annotations

import asyncio
import codecs
import logging
import os
import signal
import subprocess
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Protocol


class ActivityHold(Protocol):
    activity_hold: int


READY_TIMEOUT_S = 30.0

BOOTSTRAP_SERVER_JOBS = frozenset({"redis", "qdrant"})

_log = logging.getLogger(__name__)


@dataclass(frozen=True)
class JobSpec:
    name: str
    title: str
    argv: tuple[str, ...]
    detach: bool = False
    ready_probe: Callable[[], bool] | None = None
    details: str = ""
    timeout_s: float | None = 3600.0
    exclusive: bool = False
    log_path: Path | None = None


@dataclass
class _Job:
    job_id: str
    name: str
    spec: JobSpec
    proc: asyncio.subprocess.Process | None = None
    popen: subprocess.Popen | None = None
    lines: deque[str] = field(default_factory=lambda: deque(maxlen=2000))
    total: int = 0
    status: str = "running"
    exit_code: int | None = None
    _new_line: asyncio.Event = field(default_factory=asyncio.Event)
    _done: asyncio.Event = field(default_factory=asyncio.Event)
    _hold_released: bool = False
    _tasks: list[asyncio.Task] = field(default_factory=list)
    _reader_task: asyncio.Task | None = None
    _stop_collecting: bool = False
    _timed_out: bool = False
    _cancelled: bool = False
    _shutdown_killed: bool = False

    def add_line(self, line: str) -> None:
        # Progress redraws: keep the last non-empty segment after any \r.
        if "\r" in line:
            for part in reversed(line.split("\r")):
                if part:
                    line = part
                    break
            else:
                line = ""
        # Stored lines must never contain \r or \n because SSE treats them as
        # field terminators.
        line = line.replace("\r", "").replace("\n", "")
        # Bound per-line memory.
        line = line[:4000]
        self.lines.append(line)
        self.total += 1
        self._new_line.set()


async def _killpg(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        _log.debug("os.killpg(%r, %r) raised PermissionError: %s", pgid, sig, exc)


def _group_alive(pgid: int) -> bool:
    """Return True if any process in ``pgid`` is still alive.

    ``PermissionError`` is treated as "still alive" so a single EPERM does not
    abort a shutdown loop.
    """
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError as exc:
        _log.debug("os.killpg(%r, 0) raised PermissionError: %s", pgid, exc)
        return True
    return True


async def _kill_group(pgid: int, *, grace_s: float = 5.0) -> None:
    if pgid is None:
        return
    await _killpg(pgid, signal.SIGTERM)
    deadline = time.monotonic() + grace_s
    while time.monotonic() < deadline:
        if not _group_alive(pgid):
            return
        await asyncio.sleep(0.1)
    await _killpg(pgid, signal.SIGKILL)
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if not _group_alive(pgid):
            return
        await asyncio.sleep(0.1)


class JobRunner:
    def __init__(
        self,
        repo_root: str | os.PathLike,
        hold: ActivityHold | None = None,
    ) -> None:
        self.repo_root = os.fspath(repo_root)
        self._hold = hold
        self._jobs: dict[str, _Job] = {}
        self._name_to_job_id: dict[str, str] = {}

    def __contains__(self, job_id: str) -> bool:
        return job_id in self._jobs

    def job_id_for_name(self, name: str) -> str | None:
        return self._name_to_job_id.get(name)

    def _inc_hold(self) -> None:
        if self._hold is not None:
            self._hold.activity_hold += 1

    def _dec_hold(self, job: _Job) -> None:
        if not job._hold_released:
            job._hold_released = True
            if self._hold is not None:
                self._hold.activity_hold = max(0, self._hold.activity_hold - 1)

    def status(self, job_id: str) -> dict[str, Any]:
        job = self._jobs[job_id]
        return {"status": job.status, "exit_code": job.exit_code}

    async def start(self, name: str, spec: JobSpec) -> str:
        running = [j for j in self._jobs.values() if j.status == "running"]
        if spec.exclusive and running:
            raise RuntimeError(
                f"job {name} is exclusive; another job is already running"
            )
        running_exclusive = [
            j for j in self._jobs.values() if j.status == "running" and j.spec.exclusive
        ]
        if running_exclusive:
            raise RuntimeError(
                f"an exclusive job is running; job {name} cannot start"
            )

        existing_id = self._name_to_job_id.get(name)
        if existing_id is not None and self._jobs[existing_id].status == "running":
            raise RuntimeError(f"job {name} is already running")

        job_id = uuid.uuid4().hex
        job = _Job(job_id=job_id, name=name, spec=spec)
        self._jobs[job_id] = job
        self._name_to_job_id[name] = job_id

        self._inc_hold()
        try:
            if spec.detach:
                if spec.ready_probe is None:
                    job.add_line("detached job has no ready probe")
                    job.status = "failed"
                    job._done.set()
                    job._new_line.set()
                    self._dec_hold(job)
                    return job_id

                try:
                    already_up = await asyncio.to_thread(spec.ready_probe)
                except Exception:
                    already_up = False
                if already_up:
                    job.add_line(
                        "port already in use; not started (is it already running?)"
                    )
                    job.status = "failed"
                    job._done.set()
                    job._new_line.set()
                    self._dec_hold(job)
                    return job_id

                if spec.log_path is not None:
                    log_dir = spec.log_path.parent
                    await asyncio.to_thread(
                        log_dir.mkdir, parents=True, exist_ok=True, mode=0o700
                    )
                    fd = await asyncio.to_thread(
                        os.open,
                        spec.log_path,
                        os.O_WRONLY | os.O_CREAT | os.O_APPEND,
                        0o600,
                    )
                    try:
                        popen = await asyncio.to_thread(
                            subprocess.Popen,
                            list(spec.argv),
                            cwd=self.repo_root,
                            env=os.environ.copy(),
                            stdin=subprocess.DEVNULL,
                            stdout=fd,
                            stderr=subprocess.STDOUT,
                            start_new_session=True,
                            close_fds=True,
                        )
                    finally:
                        await asyncio.to_thread(os.close, fd)
                    job.popen = popen
                    job.add_line(f"output is appended to {spec.log_path}")
                else:
                    popen = await asyncio.to_thread(
                        subprocess.Popen,
                        list(spec.argv),
                        cwd=self.repo_root,
                        env=os.environ.copy(),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        start_new_session=True,
                        close_fds=True,
                    )
                    job.popen = popen
                    job.add_line(
                        "output goes to the service's own log; this page only checks that it is listening"
                    )
            else:
                kwargs: dict[str, Any] = {
                    "cwd": self.repo_root,
                    "env": os.environ.copy(),
                    "stdout": asyncio.subprocess.PIPE,
                    "stderr": asyncio.subprocess.STDOUT,
                    "start_new_session": True,
                }
                proc = await asyncio.create_subprocess_exec(*spec.argv, **kwargs)
                job.proc = proc
                if spec.name in BOOTSTRAP_SERVER_JOBS:
                    job.add_line(
                        "on a native install without systemd, cancelling this "
                        "job also stops the server it starts (it is in the "
                        "job's process group). Docker and systemd-user servers "
                        "survive a cancel."
                    )
        except Exception as exc:
            job.add_line(f"could not start job: {exc}")
            job.status = "failed"
            job._done.set()
            job._new_line.set()
            self._dec_hold(job)
            return job_id

        if spec.detach:
            prober = asyncio.create_task(self._probe_ready(job))
            job._tasks.append(prober)
        else:
            reader = asyncio.create_task(self._reader(job))
            job._reader_task = reader
            job._tasks.append(reader)
            waiter = asyncio.create_task(self._wait(job))
            job._tasks.append(waiter)
            if spec.timeout_s is not None and spec.timeout_s > 0:
                watcher = asyncio.create_task(self._timeout_watcher(job))
                job._tasks.append(watcher)

        return job_id

    async def _reader(self, job: _Job) -> None:
        if job.proc is None or job.proc.stdout is None:
            return
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buffer = ""
        overflow = False
        consecutive_errors = 0
        last_redraw_time = -1.0
        while True:
            try:
                raw = await job.proc.stdout.read(65536)
                consecutive_errors = 0
            except Exception as exc:
                consecutive_errors += 1
                job.add_line(f"output could not be read: {type(exc).__name__}")
                if consecutive_errors >= 3:
                    break
                continue
            if not raw:
                break
            buffer += decoder.decode(raw)
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if overflow:
                    overflow = False
                    continue
                job.add_line(line)
            if "\r" in buffer:
                # Progress redraws: the text between the last two carriage
                # returns is the newest complete redraw, whether the program
                # writes "bar\r" or "\rbar". Show it at most every 0.5 s and
                # keep only the redraw still being written.
                head, _, tail = buffer.rpartition("\r")
                latest = head.rsplit("\r", 1)[-1]
                now = time.monotonic()
                if latest and now - last_redraw_time >= 0.5:
                    job.add_line(latest)
                    last_redraw_time = now
                buffer = tail
            if len(buffer) > 4000:
                if not overflow:
                    job.add_line(buffer[:4000])
                    overflow = True
                buffer = ""
        buffer += decoder.decode(b"", final=True)
        if buffer and not overflow:
            job.add_line(buffer)
        job._stop_collecting = True

    async def _wait(self, job: _Job) -> None:
        if job.proc is None:
            return
        exit_code = await job.proc.wait()
        if job._reader_task is not None and not job._reader_task.done():
            try:
                await job._reader_task
            except Exception:
                pass
        job.exit_code = exit_code
        if job._cancelled:
            job.status = "cancelled"
        elif job._timed_out:
            job.status = "failed"
            job.add_line(f"timed out after {job.spec.timeout_s} s")
        elif job._shutdown_killed:
            job.status = "failed"
            job.add_line("stopped by shutdown")
        else:
            job.status = "succeeded" if exit_code == 0 else "failed"
        job._done.set()
        job._new_line.set()
        self._dec_hold(job)

    async def _timeout_watcher(self, job: _Job) -> None:
        if job.spec.timeout_s is None or job.spec.timeout_s <= 0:
            return
        await asyncio.sleep(job.spec.timeout_s)
        if job.proc is None or job.proc.returncode is not None:
            return
        job._timed_out = True
        if job.proc.pid is not None:
            await _kill_group(job.proc.pid)
            await job.proc.wait()

    async def _probe_ready(self, job: _Job) -> None:
        probe = job.spec.ready_probe
        if probe is None or job.popen is None:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + READY_TIMEOUT_S
        while loop.time() < deadline:
            exited = job.popen.poll()
            if exited is not None:
                job.exit_code = exited
                job.status = "failed"
                job.add_line("exited before it was listening")
                job._done.set()
                job._new_line.set()
                self._dec_hold(job)
                return
            try:
                ok = await asyncio.to_thread(probe)
            except Exception:
                ok = False
            if ok:
                job.status = "succeeded"
                job._done.set()
                job._new_line.set()
                self._dec_hold(job)
                return
            await asyncio.sleep(0.5)

        # Stop it before reporting, so a finished job never leaves a process.
        if job.popen.pid is not None:
            await _kill_group(job.popen.pid)
            job.popen.poll()
        log_ref = f"see {job.spec.log_path}" if job.spec.log_path else "no log configured"
        job.add_line(
            f"not listening within {READY_TIMEOUT_S:.0f} s; stopped it ({log_ref})"
        )
        job.status = "failed"
        job._done.set()
        job._new_line.set()
        self._dec_hold(job)

    def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None or job.status != "running" or job.spec.detach:
            return False
        job._cancelled = True

        async def _do_cancel() -> None:
            if job.proc is not None and job.proc.pid is not None:
                await _kill_group(job.proc.pid)
                await job.proc.wait()

        task = asyncio.create_task(_do_cancel())
        job._tasks.append(task)
        return True

    def kill_all_sync(self) -> None:
        """Send SIGKILL to every running non-detached job's process group.

        Detached services are never touched.  This is intended for a forced
        server exit where the normal async shutdown cannot run.
        """
        for job in list(self._jobs.values()):
            if job.status != "running" or job.spec.detach:
                continue
            pgid = job.proc.pid if job.proc is not None else None
            if pgid is None:
                continue
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except PermissionError:
                pass

    async def shutdown(self) -> None:
        for job in list(self._jobs.values()):
            if job.status != "running" or job.spec.detach:
                continue
            job._shutdown_killed = True
            if job.proc is not None and job.proc.pid is not None:
                await _kill_group(job.proc.pid)
                await job.proc.wait()

    async def events(
        self,
        job_id: str,
        shutting_down: Callable[[], bool] | None = None,
    ) -> AsyncIterator[str | dict[str, Any]]:
        job = self._jobs[job_id]
        idx = 0
        while True:
            if shutting_down is not None and shutting_down():
                break
            first_held = job.total - len(job.lines)
            if idx < first_held:
                dropped = first_held - idx
                idx = first_held
                yield f"[{dropped} earlier lines dropped]"
                continue
            if idx < job.total:
                line = job.lines[idx - first_held]
                idx += 1
                yield line
                continue
            if job._done.is_set():
                break
            job._new_line.clear()
            if idx < job.total or job._done.is_set():
                continue
            try:
                await asyncio.wait_for(job._new_line.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

        payload: dict[str, Any] = {"status": job.status}
        if job.exit_code is not None:
            payload["exit_code"] = job.exit_code
        if job.status == "failed":
            payload["last_lines"] = list(job.lines)[-20:]
        yield payload
