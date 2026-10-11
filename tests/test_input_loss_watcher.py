# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the running input-loss caretaker notice.

Silence is measured in unfrozen seconds from an injected ``UnfrozenClock``
driven by a fake monotonic; ``_baseline`` anchors every stream at the start,
as ``run`` does.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from kaine.cycle.input_check import InputLossWatcher
from kaine.cycle.unfrozen_clock import UnfrozenClock


class _FakeMono:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _latest_returning(entries: dict[str, tuple[str, Any]]) -> Any:
    async def _latest(stream: str) -> tuple[str, Any] | None:
        return entries.get(stream)

    return _latest


def _record_into(calls: list):
    """An awaitable on_loss callback that records each call."""

    async def _on_loss() -> None:
        calls.append(None)

    return _on_loss


@pytest.fixture
def _watcher_factory(fake_async_bus):
    def _make(streams, threshold_s, poll_s=0.01):
        fake = _FakeMono()
        clock = UnfrozenClock(
            lambda: False, unknown_counts_as="unfrozen", monotonic=fake, poll_s=0.0
        )
        watcher = InputLossWatcher(
            fake_async_bus,
            streams,
            threshold_s=threshold_s,
            on_loss=lambda: (_ for _ in ()).throw(AssertionError("on_loss not replaced")),
            poll_s=poll_s,
            unfrozen_clock=clock,
        )
        watcher._fake_mono = fake
        return watcher

    return _make


async def test_fresh_streams_no_loss(fake_async_bus, monkeypatch, _watcher_factory):
    watcher = _watcher_factory(["topos.out", "audition.out"], threshold_s=10.0)
    monkeypatch.setattr(
        fake_async_bus,
        "latest",
        _latest_returning({"topos.out": ("1000-0", None), "audition.out": ("900-0", None)}),
    )
    await watcher._baseline()
    calls: list[None] = []
    watcher._on_loss = _record_into(calls)  # type: ignore[assignment]

    watcher._fake_mono.value = 9.9
    assert not await watcher._poll_once(0)
    assert not calls


async def test_all_stale_notifies_once(fake_async_bus, monkeypatch, _watcher_factory):
    watcher = _watcher_factory(["topos.out", "audition.out"], threshold_s=1.0)
    monkeypatch.setattr(
        fake_async_bus,
        "latest",
        _latest_returning({"topos.out": ("1000-0", None), "audition.out": ("1000-0", None)}),
    )
    await watcher._baseline()
    calls: list[None] = []
    watcher._on_loss = _record_into(calls)  # type: ignore[assignment]

    watcher._fake_mono.value = 0.9
    assert not await watcher._poll_once(0)
    assert not calls

    watcher._fake_mono.value = 1.1
    assert await watcher._poll_once(0)
    assert len(calls) == 1

    watcher._fake_mono.value = 5.0
    assert not await watcher._poll_once(0)
    assert len(calls) == 1


async def test_rearm_after_fresh_then_loss_again(fake_async_bus, monkeypatch, _watcher_factory):
    watcher = _watcher_factory(["topos.out", "audition.out"], threshold_s=1.0)
    monkeypatch.setattr(
        fake_async_bus,
        "latest",
        _latest_returning({"topos.out": ("1000-0", None), "audition.out": ("1000-0", None)}),
    )
    await watcher._baseline()
    calls: list[None] = []
    watcher._on_loss = _record_into(calls)  # type: ignore[assignment]

    watcher._fake_mono.value = 1.1
    await watcher._poll_once(0)
    assert len(calls) == 1

    # A new topos entry is fresh activity: the watcher re-arms.
    monkeypatch.setattr(
        fake_async_bus,
        "latest",
        _latest_returning({"topos.out": ("2000-0", None), "audition.out": ("1000-0", None)}),
    )
    watcher._fake_mono.value = 1.5
    assert not await watcher._poll_once(0)
    assert len(calls) == 1

    watcher._fake_mono.value = 2.6
    assert await watcher._poll_once(0)
    assert len(calls) == 2


async def test_empty_stream_recent_start_not_lost(fake_async_bus, monkeypatch, _watcher_factory):
    watcher = _watcher_factory(["topos.out"], threshold_s=10.0)
    monkeypatch.setattr(fake_async_bus, "latest", _latest_returning({}))
    await watcher._baseline()
    calls: list[None] = []
    watcher._on_loss = _record_into(calls)  # type: ignore[assignment]

    watcher._fake_mono.value = 9.999
    assert not await watcher._poll_once(0)
    assert not calls

    watcher._fake_mono.value = 10.001
    assert await watcher._poll_once(0)
    assert len(calls) == 1


async def test_bus_error_skipped(fake_async_bus, monkeypatch, _watcher_factory):
    watcher = _watcher_factory(["topos.out"], threshold_s=1.0)

    async def _bad_latest(stream: str) -> Any:
        raise RuntimeError("redis down")

    monkeypatch.setattr(fake_async_bus, "latest", _bad_latest)
    await watcher._baseline()
    calls: list[None] = []
    watcher._on_loss = _record_into(calls)  # type: ignore[assignment]

    watcher._fake_mono.value = 2.0
    assert not await watcher._poll_once(0)
    assert not calls


async def test_run_loop_respects_stop_event(fake_async_bus, monkeypatch, _watcher_factory):
    watcher = _watcher_factory(["topos.out"], threshold_s=10.0, poll_s=0.01)
    monkeypatch.setattr(
        fake_async_bus, "latest", _latest_returning({"topos.out": ("1000-0", None)})
    )
    calls: list[None] = []
    watcher._on_loss = _record_into(calls)  # type: ignore[assignment]

    stop = asyncio.Event()
    task = asyncio.create_task(watcher.run(stop))
    await asyncio.sleep(0.05)
    assert not calls
    stop.set()
    await asyncio.wait_for(task, timeout=5)


async def test_entry_older_than_start_gets_the_boot_grace(
    fake_async_bus, monkeypatch, _watcher_factory
):
    """A stream whose newest entry predates the watcher's start (left over from
    a previous run) is measured from the start, so slow boot-time model loading
    is not reported as lost input."""
    watcher = _watcher_factory(["topos.out"], threshold_s=10.0)
    monkeypatch.setattr(
        fake_async_bus, "latest", _latest_returning({"topos.out": ("5-0", None)})
    )
    watcher._fake_mono.value = 1.0
    await watcher._baseline()
    calls: list[None] = []
    watcher._on_loss = _record_into(calls)  # type: ignore[assignment]

    watcher._fake_mono.value = 10.999
    assert not await watcher._poll_once(0)
    assert not calls
    watcher._fake_mono.value = 11.001
    assert await watcher._poll_once(0)
    assert len(calls) == 1
