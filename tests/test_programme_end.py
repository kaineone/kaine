# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import hashlib
import logging
from pathlib import Path

import pytest

from kaine.cycle.__main__ import _start_programme_end_watcher
from kaine.cycle.programme_end import ProgrammeEndWatcher
from kaine.modules.topos.feed import PlaylistClock

pytestmark = pytest.mark.asyncio


class _FakeClock:
    def __init__(self, *, started: bool = False, paused: bool = False, index: int = -1):
        self.started = started
        self.paused = paused
        self._index = index
        self._t = 0.0

    def locate(self):
        return (self._index, 0.0, 1.0)

    def monotonic(self):
        return self._t

    def advance(self, dt: float) -> None:
        self._t += dt


def _collect(bucket):
    """An async notify (the caretaker's send_event is async) that records events."""

    async def _notify(event: str) -> None:
        bucket.append(event)

    return _notify


def _watcher(
    clock,
    item_count: int,
    *,
    writes=None,
    freezes=None,
    notifies=None,
    notify=None,
    read_result=None,
    sleep=None,
    poll_seconds: float = 1.0,
    result_timeout_seconds: float = 10.0,
):
    writes = writes if writes is not None else []
    freezes = freezes if freezes is not None else []
    notifies = notifies if notifies is not None else []

    async def fake_sleep(dt: float) -> None:
        clock.advance(dt)

    return ProgrammeEndWatcher(
        clock,
        item_count,
        write_request=writes.append,
        read_result=read_result if read_result is not None else lambda: None,
        freeze=lambda reason, source: freezes.append((reason, source)),
        notify=notify if notify is not None else _collect(notifies),
        sleep=sleep if sleep is not None else fake_sleep,
        poll_seconds=poll_seconds,
        result_timeout_seconds=result_timeout_seconds,
        clock_fn=clock.monotonic,
    )


async def test_no_action_before_end():
    clock = _FakeClock(started=True, paused=False, index=0)
    writes, freezes, notifies = [], [], []
    watcher = _watcher(clock, 2, writes=writes, freezes=freezes, notifies=notifies)
    finished = await watcher.step()
    assert finished is False
    assert not writes
    assert not freezes
    assert not notifies


async def test_no_action_while_paused_at_or_past_end():
    clock = _FakeClock(started=True, paused=True, index=2)
    writes, freezes, notifies = [], [], []
    watcher = _watcher(clock, 2, writes=writes, freezes=freezes, notifies=notifies)
    finished = await watcher.step()
    assert finished is False
    assert not writes
    assert not freezes
    assert not notifies


async def test_no_action_before_clock_starts():
    clock = _FakeClock(started=False, paused=False, index=2)
    writes, freezes, notifies = [], [], []
    watcher = _watcher(clock, 2, writes=writes, freezes=freezes, notifies=notifies)
    finished = await watcher.step()
    assert finished is False
    assert not writes
    assert not freezes
    assert not notifies


async def test_end_writes_one_request_with_stop_and_reason():
    clock = _FakeClock(started=True, paused=False, index=2)

    writes = []

    def read_result():
        if writes:
            return {"request_id": writes[-1].request_id, "ok": True}
        return None

    watcher = _watcher(clock, 2, writes=writes, read_result=read_result)
    finished = await watcher.step()

    assert finished is True
    assert len(writes) == 1
    request = writes[0]
    assert request.reason == "programme end"
    assert request.stop is True

    # A second step after the end is a no-op.
    assert await watcher.step() is True
    assert len(writes) == 1


async def test_ok_result_ends_watcher_without_freeze_or_notify(caplog):
    caplog.set_level(logging.DEBUG, logger="kaine.cycle.programme_end")
    clock = _FakeClock(started=True, paused=False, index=2)

    writes = []

    def read_result():
        if writes:
            return {"request_id": writes[-1].request_id, "ok": True}
        return None

    freezes = []
    notifies = []
    watcher = _watcher(
        clock,
        2,
        writes=writes,
        freezes=freezes,
        notifies=notifies,
        read_result=read_result,
    )
    finished = await watcher.step()

    assert finished is True
    assert not freezes
    assert not notifies
    assert not any(r.levelno == logging.CRITICAL for r in caplog.records)


async def test_failed_result_freezes_logs_critical_and_notifies(caplog):
    caplog.set_level(logging.DEBUG, logger="kaine.cycle.programme_end")
    clock = _FakeClock(started=True, paused=False, index=2)

    writes = []

    def read_result():
        if writes:
            return {
                "request_id": writes[-1].request_id,
                "ok": False,
                "error": "disk full",
            }
        return None

    freezes = []
    notifies = []

    async def notify(event: str) -> None:
        notifies.append(event)

    watcher = _watcher(
        clock,
        2,
        writes=writes,
        freezes=freezes,
        read_result=read_result,
        notify=notify,
    )
    finished = await watcher.step()

    assert finished is True
    assert len(writes) == 1
    assert len(freezes) == 1
    reason, source = freezes[0]
    assert source == "programme_end"
    assert "preservation failed" in reason
    assert "disk full" in reason
    assert notifies == ["programme_end_preserve_failed"]
    assert any(
        r.levelno == logging.CRITICAL and "disk full" in r.message
        for r in caplog.records
    )


async def test_timeout_freezes_logs_critical_and_notifies(caplog):
    caplog.set_level(logging.DEBUG, logger="kaine.cycle.programme_end")
    clock = _FakeClock(started=True, paused=False, index=2)

    writes = []
    freezes = []
    notifies = []

    async def notify(event: str) -> None:
        notifies.append(event)

    watcher = _watcher(
        clock,
        2,
        writes=writes,
        freezes=freezes,
        notifies=notifies,
        read_result=lambda: None,
        poll_seconds=1.0,
        result_timeout_seconds=5.0,
    )
    finished = await watcher.step()

    assert finished is True
    assert len(writes) == 1
    assert len(freezes) == 1
    assert freezes[0][1] == "programme_end"
    assert notifies == ["programme_end_preserve_failed"]
    assert any(
        r.levelno == logging.CRITICAL and "timed out" in r.message
        for r in caplog.records
    )


async def test_run_returns_after_handling_end():
    clock = _FakeClock(started=True, paused=False, index=2)

    writes = []

    def read_result():
        if writes:
            return {"request_id": writes[-1].request_id, "ok": True}
        return None

    watcher = _watcher(clock, 2, writes=writes, read_result=read_result)
    stop = asyncio.Event()

    await watcher.run(stop)

    assert len(writes) == 1


async def test_run_respects_stop_event():
    clock = _FakeClock(started=True, paused=False, index=0)
    sleeps = 0

    async def counting_sleep(dt: float) -> None:
        nonlocal sleeps
        sleeps += 1
        clock.advance(dt)

    watcher = ProgrammeEndWatcher(
        clock,
        2,
        write_request=lambda _req: None,
        read_result=lambda: None,
        freeze=lambda _r, _s: None,
        notify=None,
        sleep=counting_sleep,
        poll_seconds=1.0,
        result_timeout_seconds=10.0,
        clock_fn=clock.monotonic,
    )

    stop = asyncio.Event()
    stop.set()
    await watcher.run(stop)
    assert sleeps == 0


def _make_manifest(tmp_path: Path, n: int = 2) -> Path:
    entries = []
    for i in range(n):
        media = tmp_path / f"media{i}.bin"
        data = f"media{i}".encode()
        media.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        entries.append((str(media), digest, 30.0))

    manifest = tmp_path / "playlist.toml"
    lines = []
    for path, digest, fps in entries:
        lines.extend(
            [
                "[[item]]",
                f'path = "{path}"',
                f'sha256 = "{digest}"',
                f"fps = {fps}",
                "",
            ]
        )
    manifest.write_text("\n".join(lines), encoding="utf-8")
    return manifest


async def test_start_programme_end_watcher_without_clock_returns_none():
    assert _start_programme_end_watcher({}, notify=None, stop_event=asyncio.Event()) is None


async def test_start_programme_end_watcher_with_clock_and_manifest(tmp_path):
    manifest = _make_manifest(tmp_path, n=2)
    time_source = [0.0]

    clock = PlaylistClock(2, clock=lambda: time_source[0])
    cfg = {
        "perception_feed": {
            "_shared_playlist_clock": clock,
            "playlist_manifest": str(manifest),
        }
    }
    stop = asyncio.Event()
    stop.set()

    task = _start_programme_end_watcher(cfg, notify=None, stop_event=stop)
    assert task is not None
    assert task.get_name() == "cycle.programme_end"

    await task


@pytest.mark.asyncio
async def test_a_stale_ok_result_from_an_earlier_request_does_not_count(caplog):
    # A viewing's line directory keeps the previous viewing's result file; an
    # ok result for another request id must never be taken as this end's.
    caplog.set_level(logging.DEBUG, logger="kaine.cycle.programme_end")
    clock = _FakeClock(started=True, paused=False, index=2)
    stale = {"request_id": "b" * 32, "ok": True, "bundle": "/old"}
    writes = []
    freezes = []
    watcher = _watcher(
        clock,
        2,
        writes=writes,
        freezes=freezes,
        read_result=lambda: stale,
        result_timeout_seconds=5.0,
    )

    assert await watcher.step() is True
    assert len(writes) == 1 and writes[0].request_id != stale["request_id"]
    assert len(freezes) == 1, "a stale result must end in the failure freeze"


@pytest.mark.asyncio
async def test_start_programme_end_watcher_needs_the_shared_clock(tmp_path):
    cfg = {"perception_feed": {"playlist_manifest": str(tmp_path / "missing.toml")}}
    assert _start_programme_end_watcher(cfg, notify=None, stop_event=asyncio.Event()) is None
