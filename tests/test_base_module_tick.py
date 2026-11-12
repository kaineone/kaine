# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest

from kaine.bus.schema import Event
from kaine.modules.base import BaseModule, _current_tick

# ---------------------------------------------------------------------------
# Minimal fakes
# ---------------------------------------------------------------------------


class FakeBus:
    """Minimal AsyncBus-compatible mock for unit tests."""

    def __init__(self) -> None:
        self.published: list[Event] = []
        self._broadcasts: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, event: Event) -> str:
        self.published.append(event)
        return f"fake-{len(self.published)}"

    async def current_workspace_id(self) -> str:
        return "$"

    def add_broadcast(self, entry_id: str, payload: dict[str, Any]) -> None:
        self._broadcasts.append((entry_id, payload))

    async def subscribe_workspace(self, last_id: str = "$"):
        for entry_id, payload in self._broadcasts:
            yield entry_id, payload


class FakeModule(BaseModule):
    name: ClassVar[str] = "fake"

    def __init__(self, bus: FakeBus) -> None:
        super().__init__(bus)  # type: ignore[arg-type]
        self.workspace_calls: list[int] = []

    async def on_workspace(self, snapshot: Any) -> None:
        self.workspace_calls.append(snapshot.tick_index)


class PublishingModule(BaseModule):
    """Module that publishes an event during on_workspace."""

    name: ClassVar[str] = "publisher"

    def __init__(self, bus: FakeBus) -> None:
        super().__init__(bus)  # type: ignore[arg-type]

    async def on_workspace(self, snapshot: Any) -> None:
        await self.publish("publisher.heartbeat", {"tick": snapshot.tick_index}, salience=0.3)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_stamps_tick_from_context() -> None:
    bus = FakeBus()
    mod = FakeModule(bus)
    token = _current_tick.set(5)
    try:
        await mod.publish("fake.ping", {"val": 1}, salience=0.2)
    finally:
        _current_tick.reset(token)
    assert len(bus.published) == 1
    assert bus.published[0].tick == 5


@pytest.mark.asyncio
async def test_publish_increments_seq() -> None:
    bus = FakeBus()
    mod = FakeModule(bus)
    await mod.publish("fake.a", {}, salience=0.1)
    await mod.publish("fake.b", {}, salience=0.1)
    await mod.publish("fake.c", {}, salience=0.1)
    assert bus.published[0].seq == 0
    assert bus.published[1].seq == 1
    assert bus.published[2].seq == 2


@pytest.mark.asyncio
async def test_publish_tick_none_outside_workspace() -> None:
    bus = FakeBus()
    mod = FakeModule(bus)
    await mod.publish("fake.outside", {}, salience=0.1)
    assert bus.published[0].tick is None


@pytest.mark.asyncio
async def test_seq_resets_on_fresh_construction() -> None:
    bus = FakeBus()
    mod = FakeModule(bus)
    for _ in range(42):
        await mod.publish("fake.x", {}, salience=0.1)
    assert mod._seq == 42

    mod2 = FakeModule(bus)
    assert mod2._seq == 0


@pytest.mark.asyncio
async def test_track_associates_task_with_tick() -> None:
    bus = FakeBus()
    mod = FakeModule(bus)

    async def _noop() -> None:
        pass

    token = _current_tick.set(7)
    try:
        t = asyncio.create_task(_noop())
        mod.track(t)
    finally:
        _current_tick.reset(token)
    assert 7 in mod._tracked_tasks
    assert t in mod._tracked_tasks[7]
    _ = await t


@pytest.mark.asyncio
async def test_track_noop_outside_tick() -> None:
    bus = FakeBus()
    mod = FakeModule(bus)

    async def _noop() -> None:
        pass

    t = asyncio.create_task(_noop())
    mod.track(t)  # tick is None, should be a no-op
    assert mod._tracked_tasks == {}
    _ = await t


@pytest.mark.asyncio
async def test_tick_done_emitted_after_on_workspace() -> None:
    bus = FakeBus()
    mod = PublishingModule(bus)

    # Prepare a single broadcast payload (mimics what the workspace cycle sends).
    bus.add_broadcast("1-0", {"tick_index": 10, "selected": [], "inhibited": False})

    # Run the workspace loop: it will consume the one broadcast and then
    # the async-for ends (FakeBus yields a finite list).
    mod._workspace_cursor = "0"
    await mod._workspace_loop()

    # Expect at least: the module's own publish + tick_done.
    types = [e.type for e in bus.published]
    assert "publisher.heartbeat" in types
    assert "publisher.tick_done" in types
    # tick_done must come after the module's own event.
    heartbeat_idx = types.index("publisher.heartbeat")
    tick_done_idx = types.index("publisher.tick_done")
    assert tick_done_idx > heartbeat_idx

    # tick_done carries the tick number.
    tick_done_event = bus.published[tick_done_idx]
    assert tick_done_event.payload == {"tick": 10}
    assert tick_done_event.salience == 0.0


@pytest.mark.asyncio
async def test_tick_done_carries_tick_in_event() -> None:
    bus = FakeBus()
    mod = FakeModule(bus)
    bus.add_broadcast("1-0", {"tick_index": 3, "selected": [], "inhibited": False})
    mod._workspace_cursor = "0"
    await mod._workspace_loop()
    tick_done_events = [e for e in bus.published if e.type == "fake.tick_done"]
    assert len(tick_done_events) == 1
    assert tick_done_events[0].tick == 3


@pytest.mark.asyncio
async def test_workspace_loop_tracked_tasks_awaited() -> None:
    bus = FakeBus()
    completed = False

    class TrackingModule(BaseModule):
        name: ClassVar[str] = "tracker"

        def __init__(self, b: FakeBus) -> None:
            super().__init__(b)  # type: ignore[arg-type]

        async def on_workspace(self, snapshot: Any) -> None:
            nonlocal completed

            async def _side_effect() -> None:
                nonlocal completed
                completed = True

            t = asyncio.create_task(_side_effect())
            self.track(t)

    mod = TrackingModule(bus)
    bus.add_broadcast("1-0", {"tick_index": 1, "selected": [], "inhibited": False})
    mod._workspace_cursor = "0"
    await mod._workspace_loop()
    assert completed, "tracked task should have been awaited before tick_done"
