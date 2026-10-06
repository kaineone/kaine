# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""In-memory job runner for the browser setup server.

Jobs are long-running subprocesses started only by an explicit POST.  They run
with an argument list, never a shell string, and their output is kept in a
bounded in-memory deque for the session only.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Protocol


class ActivityHold(Protocol):
    activity_hold: int


@dataclass(frozen=True)
class JobSpec:
    name: str
    title: str
    argv: tuple[str, ...]
    detach: bool = False
    ready_probe: Callable[[], bool] | None = None
    details: str = ""


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

                # Honest readiness: do not start if the probe is already passing.
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

                # Detached services must survive the setup process exiting.
                # asyncio's subprocess transport closes its pipes when the event
                # loop shuts down, killing a still-running child, so use plain
                # subprocess.Popen and keep the object alive on the job record.
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
            else:
                kwargs: dict[str, Any] = {
                    "cwd": self.repo_root,
                    "env": os.environ.copy(),
                    "stdout": asyncio.subprocess.PIPE,
                    "stderr": asyncio.subprocess.STDOUT,
                }
                proc = await asyncio.create_subprocess_exec(*spec.argv, **kwargs)
                job.proc = proc
        except Exception as exc:
            job.add_line(f"could not start job: {exc}")
            job.status = "failed"
            job._done.set()
            job._new_line.set()
            self._dec_hold(job)
            return job_id

        if spec.detach:
            job.add_line(
                "output goes to the service's own log; this page only checks that it is listening"
            )
            prober = asyncio.create_task(self._probe_ready(job))
            job._tasks.append(prober)
        else:
            reader = asyncio.create_task(self._reader(job))
            job._reader_task = reader
            job._tasks.append(reader)
            waiter = asyncio.create_task(self._wait(job))
            job._tasks.append(waiter)

        return job_id

    async def _reader(self, job: _Job) -> None:
        if job.proc is None or job.proc.stdout is None:
            return
        while True:
            try:
                raw = await job.proc.stdout.readline()
            except Exception:
                break
            if not raw:
                break
            job.add_line(raw.decode("utf-8", errors="replace"))

    async def _wait(self, job: _Job) -> None:
        if job.proc is None:
            return
        exit_code = await job.proc.wait()
        # Drain any trailing output before declaring the job done.
        if job._reader_task is not None and not job._reader_task.done():
            try:
                await job._reader_task
            except Exception:
                pass
        job.exit_code = exit_code
        job.status = "succeeded" if exit_code == 0 else "failed"
        job._done.set()
        job._new_line.set()
        self._dec_hold(job)

    async def _probe_ready(self, job: _Job) -> None:
        probe = job.spec.ready_probe
        if probe is None or job.popen is None:
            return
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 30.0
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

        job.status = "failed"
        job.add_line("ready probe timed out after 30 s")
        job._done.set()
        job._new_line.set()
        self._dec_hold(job)

    async def events(self, job_id: str) -> AsyncIterator[str | dict[str, Any]]:
        job = self._jobs[job_id]
        idx = 0
        while True:
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
