# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the running input-loss caretaker notice."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from kaine.cycle.input_check import InputLossWatcher


class _FakeTime:
    def __init__(self, value: int) -> None:
        self.value = value

    async def __call__(self) -> int:
        return self.value


def _latest_returning(entries: dict[str, tuple[str, Any]]) -> Any:
    async def _latest(stream: str) -> tuple[str, Any] | None:
        return entries.get(stream)

    return _latest


@pytest.fixture
def _watcher_factory(fake_async_bus, monkeypatch):
    def _make(streams, threshold_s, poll_s=0.01):
        monkeypatch.setattr(fake_async_bus, "server_time_ms", _FakeTime(0))
        watcher = InputLossWatcher(
            fake_async_bus,
            streams,
            threshold_s=threshold_s,
            on_loss=lambda: (_ for _ in ()).throw(
                AssertionError("on_loss not replaced")
            ),
            poll_s=poll_s,
        )
        watcher._start_ms = 0
        return watcher

    return _make


async def test_fresh_streams_no_loss(fake_async_bus, monkeypatch, _watcher_factory):
    watcher = _watcher_factory(["topos.out", "audition.out"], threshold_s=10.0)
    monkeypatch.setattr(
        fake_async_bus,
        "latest",
        _latest_returning(
            {"topos.out": ("1000-0", None), "audition.out": ("900-0", None)}
        ),
    )

    calls: list[None] = []
    watcher._on_loss = lambda: (calls.append(None) for _ in ()).throw(StopIteration) or None
    watcher._on_loss = lambda: calls.append(None) or None  # type: ignore[assignment]

    became = await watcher._poll_once(1100)
    assert not became
    assert not calls


async def test_all_stale_notifies_once(fake_async_bus, monkeypatch, _watcher_factory):
    watcher = _watcher_factory(["topos.out", "audition.out"], threshold_s=1.0)
    monkeypatch.setattr(
        fake_async_bus,
        "latest",
        _latest_returning(
            {"topos.out": ("1000-0", None), "audition.out": ("1000-0", None)}
        ),
    )

    calls: list[None] = []
    watcher._on_loss = lambda: calls.append(None) or None  # type: ignore[assignment]

    # Still fresh.
    became = await watcher._poll_once(1500)
    assert not became
    assert not calls

    # First loss.
    became = await watcher._poll_once(2100)
    assert became
    assert len(calls) == 1

    # Remaining stale does not re-notify.
    became = await watcher._poll_once(5000)
    assert not became
    assert len(calls) == 1


async def test_rearm_after_fresh_then_loss_again(
    fake_async_bus, monkeypatch, _watcher_factory
):
    watcher = _watcher_factory(["topos.out", "audition.out"], threshold_s=1.0)
    monkeypatch.setattr(
        fake_async_bus,
        "latest",
        _latest_returning(
            {"topos.out": ("1000-0", None), "audition.out": ("1000-0", None)}
        ),
    )

    calls: list[None] = []
    watcher._on_loss = lambda: calls.append(None) or None  # type: ignore[assignment]

    await watcher._poll_once(2100)
    assert len(calls) == 1

    # One stream becomes fresh; this re-arms the watcher.
    monkeypatch.setattr(
        fake_async_bus,
        "latest",
        _latest_returning(
            {"topos.out": ("2000-0", None), "audition.out": ("1000-0", None)}
        ),
    )
    became = await watcher._poll_once(2500)
    assert not became
    assert len(calls) == 1

    # Then go stale again.
    became = await watcher._poll_once(3100)
    assert became
    assert len(calls) == 2


async def test_empty_stream_recent_start_not_lost(
    fake_async_bus, monkeypatch, _watcher_factory
):
    watcher = _watcher_factory(["topos.out"], threshold_s=10.0)
    watcher._start_ms = 1000
    monkeypatch.setattr(fake_async_bus, "latest", _latest_returning({}))

    calls: list[None] = []
    watcher._on_loss = lambda: calls.append(None) or None  # type: ignore[assignment]

    # Just under the threshold since boot.
    became = await watcher._poll_once(10999)
    assert not became
    assert not calls

    # Past the threshold since boot.
    became = await watcher._poll_once(11001)
    assert became
    assert len(calls) == 1


async def test_bus_error_skipped(fake_async_bus, monkeypatch, _watcher_factory):
    watcher = _watcher_factory(["topos.out"], threshold_s=1.0)

    async def _bad_latest(stream: str) -> Any:
        raise RuntimeError("redis down")

    monkeypatch.setattr(fake_async_bus, "latest", _bad_latest)

    calls: list[None] = []
    watcher._on_loss = lambda: calls.append(None) or None  # type: ignore[assignment]

    # Should not raise and should not call on_loss.
    became = await watcher._poll_once(2000)
    assert not became
    assert not calls


async def test_run_loop_respects_stop_event(fake_async_bus, monkeypatch, _watcher_factory):
    watcher = _watcher_factory(["topos.out"], threshold_s=10.0, poll_s=0.01)
    monkeypatch.setattr(
        fake_async_bus, "latest", _latest_returning({"topos.out": ("1000-0", None)})
    )

    calls: list[None] = []
    watcher._on_loss = lambda: calls.append(None) or None  # type: ignore[assignment]

    stop = asyncio.Event()
    task = asyncio.create_task(watcher.run(stop))
    await asyncio.sleep(0.05)
    assert not calls

    stop.set()
    await task


async def test_entry_older_than_start_gets_the_boot_grace(
    fake_async_bus, monkeypatch, _watcher_factory
):
    """A stream whose newest entry predates the watcher's start (left over from
    a previous run) is measured from the start, so slow boot-time model loading
    is not reported as lost input."""
    watcher = _watcher_factory(["topos.out"], threshold_s=10.0)
    watcher._start_ms = 1000
    monkeypatch.setattr(
        fake_async_bus, "latest", _latest_returning({"topos.out": ("5-0", None)})
    )

    calls: list[None] = []
    watcher._on_loss = lambda: calls.append(None) or None  # type: ignore[assignment]

    assert not await watcher._poll_once(10999)
    assert not calls
    assert await watcher._poll_once(11001)
    assert len(calls) == 1
