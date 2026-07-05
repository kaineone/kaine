# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Test fakes for the cognitive cycle.

These are intentionally minimal — full Syneidesis and ModuleRegistry land in
their own Phase 1 changes. Tests for the cycle treat both as collaborators
that match the protocols in kaine.cycle.protocols.
"""
from __future__ import annotations

from typing import Any

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot


class FakeSyneidesis:
    def __init__(self, *, raise_on_tick: int | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.raise_on_tick = raise_on_tick

    async def select(
        self,
        events: list[tuple[str, Event]],
        context: dict[str, Any],
    ) -> WorkspaceSnapshot:
        self.calls.append(
            {
                "events": list(events),
                "context": dict(context),
                "tick_index": context.get("tick_index"),
            }
        )
        if (
            self.raise_on_tick is not None
            and context.get("tick_index") == self.raise_on_tick
        ):
            raise RuntimeError(f"forced failure on tick {self.raise_on_tick}")
        return WorkspaceSnapshot(
            tick_index=context.get("tick_index", 0),
            selected_events=list(events[:5]),
            salience_scores={
                entry_id: ev.salience for entry_id, ev in events[:5]
            },
        )


class FakeRegistry:
    def __init__(self, streams: list[str]) -> None:
        self._streams = list(streams)

    def active_streams(self) -> list[str]:
        return list(self._streams)

    def set_streams(self, streams: list[str]) -> None:
        self._streams = list(streams)


class FakeClock:
    """A deterministic clock + sleep pair for testing pacing.

    Time only advances when `sleep` is awaited (or `advance` is called
    directly), so tests stay snappy while exercising real timing logic.
    """

    def __init__(self, start: float = 0.0) -> None:
        self._now = start
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._now += seconds


class FailingReadBus:
    """Wraps a real AsyncBus and forces .read() to raise for one stream."""

    def __init__(self, real_bus, fail_stream: str) -> None:
        self._real = real_bus
        self._fail_stream = fail_stream

    @property
    def config(self):
        return self._real.config

    @property
    def client(self):
        return self._real.client

    async def read(self, stream, last_id="0", count=100, block_ms=0):
        if stream == self._fail_stream:
            raise RuntimeError(f"forced read failure for {stream}")
        return await self._real.read(stream, last_id=last_id, count=count, block_ms=block_ms)

    async def read_entries(self, stream, last_id="0", count=100, block_ms=0):
        if stream == self._fail_stream:
            raise RuntimeError(f"forced read failure for {stream}")
        return await self._real.read_entries(
            stream, last_id=last_id, count=count, block_ms=block_ms
        )

    async def publish(self, event):
        return await self._real.publish(event)

    async def publish_workspace(self, snapshot, source="syneidesis"):
        return await self._real.publish_workspace(snapshot, source=source)

    async def close(self):
        return await self._real.close()
