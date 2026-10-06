# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine.residency.inflight using real threads and real asyncio."""

import asyncio
import concurrent.futures
import threading

import pytest

from kaine.residency.inflight import InflightGate


def test_normal_run():
    async def _test():
        gate = InflightGate()
        ticket = gate.admit()

        def fn(x, y):
            assert gate.inflight == 1
            return x + y

        result = await asyncio.wait_for(gate.run(ticket, None, fn, 2, 3), 5)
        assert result == 5
        await asyncio.wait_for(gate.wait_idle(), 5)
        assert gate.inflight == 0

    asyncio.run(_test())


def test_cancelled_while_running():
    async def _test():
        gate = InflightGate()
        blocker = threading.Event()
        started = threading.Event()

        def fn():
            started.set()
            blocker.wait()

        ticket = gate.admit()
        task = asyncio.create_task(gate.run(ticket, None, fn))

        try:
            await asyncio.wait_for(asyncio.to_thread(started.wait), 5)

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # Expected or irrelevant here: the test asserts on state, not on this outcome.
                pass

            assert gate.inflight == 1

            waiter = asyncio.create_task(asyncio.wait_for(gate.wait_idle(), 5))
            await asyncio.sleep(0.1)
            assert not waiter.done()
            assert gate.inflight == 1

            blocker.set()
            await waiter
            assert gate.inflight == 0
        finally:
            blocker.set()

    asyncio.run(_test())


def test_cancelled_before_start():
    async def _test():
        gate = InflightGate()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        first_started = threading.Event()
        first_blocker = threading.Event()
        second_called = False

        def first_fn():
            first_started.set()
            first_blocker.wait()
            return 1

        def second_fn():
            nonlocal second_called
            second_called = True
            return 2

        first_ticket = gate.admit()
        first_task = asyncio.create_task(gate.run(first_ticket, executor, first_fn))

        try:
            await asyncio.wait_for(asyncio.to_thread(first_started.wait), 5)

            second_ticket = gate.admit()
            second_task = asyncio.create_task(gate.run(second_ticket, executor, second_fn))

            await asyncio.sleep(0)
            second_task.cancel()
            try:
                await second_task
            except asyncio.CancelledError:
                # Expected or irrelevant here: the test asserts on state, not on this outcome.
                pass

            assert gate.inflight == 1
            assert not second_called

            first_blocker.set()
            await asyncio.wait_for(first_task, 5)
            await asyncio.wait_for(gate.wait_idle(), 5)
            assert gate.inflight == 0
        finally:
            first_blocker.set()
            executor.shutdown(wait=False)

    asyncio.run(_test())


def test_exception_in_fn():
    async def _test():
        gate = InflightGate()

        def fn():
            raise ValueError("boom")

        ticket = gate.admit()
        with pytest.raises(ValueError, match="boom"):
            await asyncio.wait_for(gate.run(ticket, None, fn), 5)

        await asyncio.wait_for(gate.wait_idle(), 5)
        assert gate.inflight == 0

    asyncio.run(_test())


def test_executor_shutdown():
    async def _test():
        gate = InflightGate()
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        executor.shutdown(wait=False)

        def fn():
            return 1

        ticket = gate.admit()
        with pytest.raises(RuntimeError):
            await asyncio.wait_for(gate.run(ticket, executor, fn), 5)

        await asyncio.wait_for(gate.wait_idle(), 5)
        assert gate.inflight == 0

    asyncio.run(_test())


def test_double_release():
    async def _test():
        gate = InflightGate()
        ticket = gate.admit()
        ticket.release()
        assert gate.inflight == 0
        ticket.release()
        assert gate.inflight == 0
        await asyncio.wait_for(gate.wait_idle(), 5)

    asyncio.run(_test())


def test_two_concurrent_jobs_one_cancelled():
    async def _test():
        gate = InflightGate()
        blocker1 = threading.Event()
        blocker2 = threading.Event()
        started1 = threading.Event()
        started2 = threading.Event()

        def fn1():
            started1.set()
            blocker1.wait()
            return 1

        def fn2():
            started2.set()
            blocker2.wait()
            return 2

        ticket1 = gate.admit()
        ticket2 = gate.admit()
        task1 = asyncio.create_task(gate.run(ticket1, None, fn1))
        task2 = asyncio.create_task(gate.run(ticket2, None, fn2))

        try:
            await asyncio.wait_for(asyncio.to_thread(started1.wait), 5)
            await asyncio.wait_for(asyncio.to_thread(started2.wait), 5)
            assert gate.inflight == 2

            task1.cancel()
            try:
                await task1
            except asyncio.CancelledError:
                # Expected or irrelevant here: the test asserts on state, not on this outcome.
                pass

            assert gate.inflight == 2

            blocker2.set()
            result2 = await asyncio.wait_for(task2, 5)
            assert result2 == 2

            waiter = asyncio.create_task(asyncio.wait_for(gate.wait_idle(), 5))
            await asyncio.sleep(0.1)
            assert not waiter.done()

            blocker1.set()
            await waiter
            assert gate.inflight == 0
        finally:
            blocker1.set()
            blocker2.set()

    asyncio.run(_test())


def test_construction_outside_loop():
    gate = InflightGate()
    assert gate.inflight == 0


def test_successive_asyncio_runs():
    gate = InflightGate()

    async def work():
        ticket = gate.admit()

        def fn():
            return 7

        result = await asyncio.wait_for(gate.run(ticket, None, fn), 5)
        assert result == 7
        await asyncio.wait_for(gate.wait_idle(), 5)
        assert gate.inflight == 0

    asyncio.run(work())
    asyncio.run(work())


def test_wait_idle_from_different_loop_while_inflight_raises():
    gate = InflightGate()
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    blocker = threading.Event()
    started = threading.Event()
    ticket = None

    async def first():
        nonlocal ticket
        ticket = gate.admit()

        def fn():
            started.set()
            blocker.wait()

        task = asyncio.create_task(gate.run(ticket, executor, fn))
        await asyncio.wait_for(asyncio.to_thread(started.wait), 5)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            # Expected or irrelevant here: the test asserts on state, not on this outcome.
            pass

    asyncio.run(first())
    assert gate.inflight == 1

    async def second():
        with pytest.raises(
            RuntimeError,
            match="InflightGate used from a different event loop while work is in flight",
        ):
            await gate.wait_idle()

    try:
        asyncio.run(second())
    finally:
        blocker.set()
        if ticket is not None:
            ticket.release()
        executor.shutdown(wait=False)
        assert gate.inflight == 0


def test_abandoned_job_never_runs_fn():
    class _ManualExecutor(concurrent.futures.Executor):
        def __init__(self):
            self._pending = []

        def submit(self, fn, /, *args, **kwargs):
            future = concurrent.futures.Future()
            future.set_running_or_notify_cancel()
            self._pending.append((future, fn, args, kwargs))
            return future

        def run_pending(self):
            for future, fn, args, kwargs in self._pending:
                try:
                    result = fn(*args, **kwargs)
                # Like a real executor: every exception, BaseException included,
                # is delivered to the future.
                except BaseException as exc:
                    future.set_exception(exc)
                else:
                    future.set_result(result)
            self._pending.clear()

        def shutdown(self, wait=True, *, cancel_futures=False):
            pass

    async def _test():
        gate = InflightGate()
        ex = _ManualExecutor()
        calls = []

        def fn():
            calls.append(True)

        ticket = gate.admit()
        task = asyncio.create_task(gate.run(ticket, ex, fn))
        await asyncio.sleep(0)
        assert ex._pending
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert gate.inflight == 0

        await asyncio.to_thread(ex.run_pending)
        assert calls == []
        assert gate.inflight == 0

    asyncio.run(_test())
