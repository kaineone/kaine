# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for the consolidated StreamSubscriberObserver base class."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.evaluation._base import StreamSubscriberObserver


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _event(n: int, stream: str = "a.out") -> Event:
    # bus.publish writes to module_stream(source), so the source names the stream.
    return Event(
        source=stream.removesuffix(".out"),
        type=f"evt.{n}",
        payload={"stream": stream, "n": n},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


async def _wait_until(predicate, timeout: float = 2.0, interval: float = 0.05) -> None:
    async def _poll():
        while not predicate():
            await asyncio.sleep(interval)

    await asyncio.wait_for(_poll(), timeout=timeout)


class _RecordingObserver(StreamSubscriberObserver):
    name = "recording"

    def __init__(self, bus, streams: tuple[str, ...], **kwargs) -> None:
        super().__init__(bus, **kwargs)
        self.streams = streams
        self._cursors = {}
        self.seen: list[tuple[str, str, Event]] = []

    async def handle(self, stream: str, entry_id: str, event: Event) -> None:
        self.seen.append((stream, entry_id, event))


@pytest.mark.asyncio
async def test_single_stream_receives_published_events_in_order(bus):
    observer = _RecordingObserver(bus, streams=("a.out",), poll_interval_s=0.05)
    await bus.publish(_event(1, "a.out"))
    await bus.publish(_event(2, "a.out"))

    await observer.start()
    try:
        await _wait_until(lambda: len(observer.seen) == 2)
        assert [event.type for _, _, event in observer.seen] == ["evt.1", "evt.2"]
    finally:
        await observer.stop()


@pytest.mark.asyncio
async def test_multi_stream_tracks_per_stream_cursors(bus):
    observer = _RecordingObserver(bus, streams=("a.out", "b.out"), poll_interval_s=0.05)
    await bus.publish(_event(1, "a.out"))
    await bus.publish(_event(1, "b.out"))
    await bus.publish(_event(2, "a.out"))
    await bus.publish(_event(2, "b.out"))

    await observer.start()
    try:
        await _wait_until(lambda: len(observer.seen) == 4)
        by_stream: dict[str, list[str]] = {}
        for stream, _, event in observer.seen:
            by_stream.setdefault(stream, []).append(event.type)
        assert by_stream.get("a.out") == ["evt.1", "evt.2"]
        assert by_stream.get("b.out") == ["evt.1", "evt.2"]
    finally:
        await observer.stop()


@pytest.mark.asyncio
async def test_read_failure_on_one_stream_does_not_block_other(bus, monkeypatch):
    observer = _RecordingObserver(bus, streams=("a.out", "b.out"), poll_interval_s=0.05)
    await bus.publish(_event(1, "a.out"))
    await bus.publish(_event(1, "b.out"))
    await bus.publish(_event(2, "a.out"))
    await bus.publish(_event(2, "b.out"))

    orig = bus.read_entries
    b_failures = 0

    async def patched(stream, last_id="0", count=100, block_ms=0):
        nonlocal b_failures
        if stream == "b.out" and b_failures == 0:
            b_failures += 1
            raise RuntimeError("simulated b.out read failure")
        return await orig(stream, last_id, count, block_ms)

    monkeypatch.setattr(bus, "read_entries", patched)

    await observer.start()
    try:
        await _wait_until(
            lambda: len([s for s, _, _ in observer.seen if s == "a.out"]) == 2
        )
        await _wait_until(lambda: len(observer.seen) == 4)
        by_stream: dict[str, list[str]] = {}
        for stream, _, event in observer.seen:
            by_stream.setdefault(stream, []).append(event.type)
        assert by_stream.get("a.out") == ["evt.1", "evt.2"]
        assert by_stream.get("b.out") == ["evt.1", "evt.2"]
    finally:
        await observer.stop()


@pytest.mark.asyncio
async def test_restarted_observer_does_not_reprocess_events(bus):
    observer = _RecordingObserver(bus, streams=("a.out",), poll_interval_s=0.05)
    await bus.publish(_event(1, "a.out"))

    await observer.start()
    try:
        await _wait_until(lambda: len(observer.seen) == 1)
    finally:
        await observer.stop()

    # Restart with no new events: the cursor must persist and nothing is replayed.
    await observer.start()
    try:
        with pytest.raises(asyncio.TimeoutError):
            await _wait_until(lambda: len(observer.seen) != 1, timeout=0.3)
        assert len(observer.seen) == 1

        # A new event after restart is processed exactly once.
        await bus.publish(_event(2, "a.out"))
        await _wait_until(lambda: len(observer.seen) == 2)
        assert [event.type for _, _, event in observer.seen] == ["evt.1", "evt.2"]
    finally:
        await observer.stop()


@pytest.mark.asyncio
async def test_a_persistently_failing_stream_never_starves_the_others(bus, monkeypatch):
    """b.out is polled first and fails on every read; a.out must still be read
    on every poll."""
    observer = _RecordingObserver(bus, streams=("b.out", "a.out"), poll_interval_s=0.05)
    await bus.publish(_event(1, "a.out"))
    await bus.publish(_event(2, "a.out"))

    orig = bus.read_entries

    async def patched(stream, last_id="0", count=100, block_ms=0):
        if stream == "b.out":
            raise RuntimeError("b.out is down")
        return await orig(stream, last_id, count, block_ms)

    monkeypatch.setattr(bus, "read_entries", patched)

    await observer.start()
    try:
        await _wait_until(lambda: len(observer.seen) == 2)
        assert [event.type for _, _, event in observer.seen] == ["evt.1", "evt.2"]
    finally:
        await observer.stop()
