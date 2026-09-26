# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the operator preservation request watcher."""
from __future__ import annotations

import asyncio

import pytest

from kaine.cycle.control_state import read_control
from kaine.cycle.preserve_watch import (
    PRESERVE_FREEZE_SOURCE,
    PreserveRequestWatcher,
    read_result,
    write_request,
    write_result,
)


class _FakeResult:
    def __init__(self, ok: bool = True, preservation_id: str = "pid1"):
        self.ok = ok
        self.preservation_id = preservation_id


def _as_async(fn):
    # The watcher's contract: preserve is an async callable. Tests pass plain
    # functions for brevity; wrap them to honour the contract.
    if asyncio.iscoroutinefunction(fn):
        return fn

    async def wrapper(reason):
        return fn(reason)

    return wrapper


def _make_watcher(tmp_path, **kwargs):
    defaults = {
        "preserve": lambda reason: _FakeResult(),
        "bundle_for": lambda result: f"/backups/{result.preservation_id}",
        "is_paused": lambda: True,
        "request_stop": lambda: None,
        "request_path": tmp_path / "request.json",
        "result_path": tmp_path / "result.json",
        "control_path": tmp_path / "control.json",
        "poll_seconds": 0.05,
        "pause_timeout_seconds": 0.1,
    }
    defaults.update(kwargs)
    defaults["preserve"] = _as_async(defaults["preserve"])
    return PreserveRequestWatcher(**defaults)


@pytest.mark.asyncio
async def test_watcher_handles_request_and_writes_result(tmp_path):
    preserve_calls = []
    watcher = _make_watcher(
        tmp_path,
        preserve=lambda reason: (preserve_calls.append(reason), _FakeResult())[1],
    )
    req = write_request_for_test(tmp_path, "test-reason", stop=False)

    await watcher.step()

    assert preserve_calls == ["test-reason"]
    result = read_result(watcher._result_path)
    assert result is not None
    assert result["request_id"] == req.request_id
    assert result["ok"] is True
    assert result["bundle"] == "/backups/pid1"
    assert result["error"] is None
    assert tuple(read_control(watcher._control_path).stack) == ()


@pytest.mark.asyncio
async def test_watcher_stop_keeps_freeze_and_requests_stop(tmp_path):
    stopped = []
    watcher = _make_watcher(
        tmp_path,
        preserve=lambda reason: _FakeResult(ok=True, preservation_id="pid2"),
        request_stop=lambda: stopped.append(True),
    )
    write_request_for_test(tmp_path, "stop-test", stop=True)

    await watcher.step()

    assert stopped == [True]
    stack = read_control(watcher._control_path).stack
    assert len(stack) == 1
    assert stack[0]["source"] == PRESERVE_FREEZE_SOURCE
    result = read_result(watcher._result_path)
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_watcher_failed_preserve_writes_failure_and_pops_freeze(tmp_path):
    def boom(reason):
        raise RuntimeError("disk full")

    watcher = _make_watcher(tmp_path, preserve=boom)
    write_request_for_test(tmp_path, "fail-test", stop=False)

    await watcher.step()

    result = read_result(watcher._result_path)
    assert result is not None
    assert result["ok"] is False
    assert "RuntimeError" in result["error"]
    assert "disk full" in result["error"]
    assert tuple(read_control(watcher._control_path).stack) == ()


@pytest.mark.asyncio
async def test_watcher_ignores_already_handled_request_id(tmp_path):
    calls = []
    watcher = _make_watcher(
        tmp_path,
        preserve=lambda reason: (calls.append(reason), _FakeResult())[1],
    )
    write_request_for_test(tmp_path, "dup-test", stop=False)

    await watcher.step()
    assert calls == ["dup-test"]
    await watcher.step()
    assert calls == ["dup-test"]


@pytest.mark.asyncio
async def test_watcher_does_not_rehandle_existing_result(tmp_path):
    calls = []
    req = write_request_for_test(tmp_path, "prior-test", stop=False)
    write_result(
        {
            "request_id": req.request_id,
            "ok": True,
            "preservation_id": "pid0",
            "bundle": "/backups/pid0",
            "error": None,
        },
        tmp_path / "result.json",
    )
    watcher = _make_watcher(
        tmp_path,
        preserve=lambda reason: (calls.append(reason), _FakeResult())[1],
    )
    await watcher.step()
    assert calls == []


@pytest.mark.asyncio
async def test_watcher_ignores_malformed_request(tmp_path):
    calls = []
    (tmp_path / "request.json").write_text("not-json")
    watcher = _make_watcher(
        tmp_path,
        preserve=lambda reason: (calls.append(reason), _FakeResult())[1],
    )
    await watcher.step()
    assert calls == []


@pytest.mark.asyncio
async def test_watcher_run_loops_until_stop_event(tmp_path):
    calls = []
    watcher = _make_watcher(
        tmp_path,
        preserve=lambda reason: (calls.append(reason), _FakeResult())[1],
        poll_seconds=0.01,
    )
    write_request_for_test(tmp_path, "loop-test", stop=False)
    stop_event = asyncio.Event()

    async def stop_soon():
        await asyncio.sleep(0.05)
        stop_event.set()

    task = asyncio.create_task(watcher.run(stop_event))
    await stop_soon()
    await task

    assert len(calls) >= 1


def write_request_for_test(tmp_path, reason, stop):
    from kaine.cycle.preserve_watch import new_request

    req = new_request(reason, stop)
    write_request(req, tmp_path / "request.json")
    return req


@pytest.mark.asyncio
async def test_a_failed_result_write_still_releases_the_freeze(tmp_path, monkeypatch):
    import kaine.cycle.preserve_watch as pw

    def broken_write(result, path=None):
        raise OSError("disk full")

    monkeypatch.setattr(pw, "write_result", broken_write)
    watcher = _make_watcher(tmp_path)
    write_request_for_test(tmp_path, "write-fails", stop=False)

    await watcher.step()
    await watcher.step()  # the same request must not be handled again

    assert tuple(read_control(watcher._control_path).stack) == ()


@pytest.mark.asyncio
async def test_watcher_retries_failed_freeze_release(tmp_path, monkeypatch):
    import kaine.cycle.preserve_watch as pw

    real_pop_freeze = pw.pop_freeze
    call_count = 0

    def flaky_pop_freeze(path=None, source=None):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("cannot release freeze")
        return real_pop_freeze(path, source=source)

    monkeypatch.setattr(pw, "pop_freeze", flaky_pop_freeze)

    watcher = _make_watcher(
        tmp_path,
        preserve=lambda reason: _FakeResult(ok=True, preservation_id="pid1"),
    )

    req1 = write_request_for_test(tmp_path, "first", stop=False)
    await watcher.step()

    assert watcher._last_handled_id == req1.request_id
    assert tuple(read_control(watcher._control_path).stack) != ()
    assert watcher._release_pending is True

    req2 = write_request_for_test(tmp_path, "second", stop=False)
    await watcher.step()

    assert watcher._release_pending is False
    assert tuple(read_control(watcher._control_path).stack) == ()
    assert watcher._last_handled_id == req1.request_id

    await watcher.step()

    assert watcher._last_handled_id == req2.request_id
    result = read_result(watcher._result_path)
    assert result is not None
    assert result["request_id"] == req2.request_id
    assert result["ok"] is True
    assert tuple(read_control(watcher._control_path).stack) == ()
