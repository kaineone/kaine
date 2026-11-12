# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import enum
import time
from dataclasses import dataclass, field


class Priority(enum.Enum):
    INTERACTIVE = "interactive"
    BACKGROUND = "background"


@dataclass
class DeadlineMiss:
    job_name: str
    deadline: float
    dispatched_at: float
    overshoot_seconds: float


@dataclass
class Job:
    name: str
    priority: Priority
    footprint_bytes: int = 0
    deadline: float | None = None
    cancel: asyncio.Event = field(default_factory=asyncio.Event)


class WorkQueue:
    def __init__(
        self,
        interactive_max: int = 16,
        background_max: int = 64,
        grace_seconds: float = 2.0,
        hard_timeout_seconds: float = 10.0,
    ) -> None:
        self._interactive: asyncio.Queue[Job] = asyncio.Queue(maxsize=interactive_max)
        self._background: asyncio.Queue[Job] = asyncio.Queue(maxsize=background_max)
        self._running_background: dict[str, Job] = {}
        self._deadline_misses: list[DeadlineMiss] = []
        self._grace_seconds = grace_seconds
        self._hard_timeout_seconds = hard_timeout_seconds

    def submit(self, job: Job) -> bool:
        queue = self._interactive if job.priority is Priority.INTERACTIVE else self._background
        try:
            queue.put_nowait(job)
        except asyncio.QueueFull:
            return False
        return True

    def next_job(self) -> Job | None:
        try:
            job = self._interactive.get_nowait()
        except asyncio.QueueEmpty:
            try:
                job = self._background.get_nowait()
            except asyncio.QueueEmpty:
                return None
        if job.priority is Priority.INTERACTIVE and job.deadline is not None:
            self.record_dispatch(job)
        return job

    def record_dispatch(self, job: Job) -> None:
        now = time.monotonic()
        if job.deadline is not None and now > job.deadline:
            self._deadline_misses.append(
                DeadlineMiss(job.name, job.deadline, now, now - job.deadline)
            )

    def register_running(self, job: Job) -> None:
        self._running_background[job.name] = job

    def unregister_running(self, name: str) -> None:
        self._running_background.pop(name, None)

    async def preempt(self, names: list[str]) -> list[str]:
        yielded: list[str] = []
        for name in names:
            job = self._running_background.get(name)
            if job is None:
                continue
            job.cancel.set()

            grace_deadline = time.monotonic() + self._grace_seconds
            while name in self._running_background and time.monotonic() < grace_deadline:
                await asyncio.sleep(0.1)
            if name not in self._running_background:
                yielded.append(name)
                continue

            hard_deadline = time.monotonic() + (self._hard_timeout_seconds - self._grace_seconds)
            while name in self._running_background and time.monotonic() < hard_deadline:
                await asyncio.sleep(0.1)
            if name not in self._running_background:
                yielded.append(name)

        return yielded

    @property
    def deadline_misses(self) -> tuple[DeadlineMiss, ...]:
        return tuple(self._deadline_misses)

    @property
    def interactive_pending(self) -> int:
        return self._interactive.qsize()

    @property
    def background_pending(self) -> int:
        return self._background.qsize()

    @property
    def running_background(self) -> frozenset[str]:
        return frozenset(self._running_background)
