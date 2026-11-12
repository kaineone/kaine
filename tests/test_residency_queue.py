# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import time

import pytest

from kaine.residency.queue import Job, Priority, WorkQueue


def test_submit_interactive():
    queue = WorkQueue()
    job = Job(name="interactive", priority=Priority.INTERACTIVE)
    queue.submit(job)
    assert queue.interactive_pending == 1


def test_submit_background():
    queue = WorkQueue()
    job = Job(name="background", priority=Priority.BACKGROUND)
    queue.submit(job)
    assert queue.background_pending == 1


def test_submit_full_returns_false():
    queue = WorkQueue(interactive_max=1)
    first = Job(name="first", priority=Priority.INTERACTIVE)
    second = Job(name="second", priority=Priority.INTERACTIVE)
    assert queue.submit(first) is True
    assert queue.submit(second) is False


def test_next_job_interactive_first():
    queue = WorkQueue()
    background = Job(name="background", priority=Priority.BACKGROUND)
    interactive = Job(name="interactive", priority=Priority.INTERACTIVE)
    queue.submit(background)
    queue.submit(interactive)
    result = queue.next_job()
    assert result is not None
    assert result.name == interactive.name


def test_next_job_empty():
    queue = WorkQueue()
    assert queue.next_job() is None


def test_next_job_background_when_no_interactive():
    queue = WorkQueue()
    background = Job(name="background", priority=Priority.BACKGROUND)
    queue.submit(background)
    result = queue.next_job()
    assert result is not None
    assert result.name == background.name


def test_deadline_miss_recorded(monkeypatch):
    queue = WorkQueue()
    job = Job(name="interactive", priority=Priority.INTERACTIVE, deadline=1000.0)
    queue.submit(job)
    monkeypatch.setattr(time, "monotonic", lambda: 1005.0)
    queue.next_job()
    misses = queue.deadline_misses
    assert len(misses) == 1
    assert misses[0].overshoot_seconds == 5.0


def test_no_deadline_miss_when_on_time(monkeypatch):
    queue = WorkQueue()
    job = Job(name="interactive", priority=Priority.INTERACTIVE, deadline=1000.0)
    queue.submit(job)
    monkeypatch.setattr(time, "monotonic", lambda: 999.0)
    queue.next_job()
    assert queue.deadline_misses == ()


def test_register_and_unregister_running():
    queue = WorkQueue()
    job = Job(name="background", priority=Priority.BACKGROUND)
    queue.register_running(job)
    assert queue.running_background == frozenset({"background"})
    queue.unregister_running("background")
    assert queue.running_background == frozenset()


@pytest.mark.asyncio
async def test_preempt_yields_on_cancel():
    queue = WorkQueue(grace_seconds=0.5, hard_timeout_seconds=1.0)
    job = Job(name="background", priority=Priority.BACKGROUND)
    queue.register_running(job)

    async def unregister_later():
        await asyncio.sleep(0.05)
        queue.unregister_running("background")

    task = asyncio.create_task(unregister_later())
    result = await queue.preempt(["background"])
    _ = await task
    assert result == ["background"]


@pytest.mark.asyncio
async def test_preempt_timeout_no_yield():
    queue = WorkQueue(grace_seconds=0.1, hard_timeout_seconds=0.2)
    job = Job(name="background", priority=Priority.BACKGROUND)
    queue.register_running(job)
    result = await queue.preempt(["background"])
    assert result == []


@pytest.mark.asyncio
async def test_preempt_sets_cancel_event():
    queue = WorkQueue(grace_seconds=0.1, hard_timeout_seconds=0.2)
    job = Job(name="background", priority=Priority.BACKGROUND)
    queue.register_running(job)
    task = asyncio.create_task(queue.preempt(["background"]))
    await asyncio.sleep(0.01)
    assert job.cancel.is_set()
    _ = await task


def test_background_deadline_not_recorded(monkeypatch):
    queue = WorkQueue()
    job = Job(name="background", priority=Priority.BACKGROUND, deadline=1000.0)
    queue.submit(job)
    monkeypatch.setattr(time, "monotonic", lambda: 1005.0)
    queue.next_job()
    assert queue.deadline_misses == ()
