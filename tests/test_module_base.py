# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import json
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.base import BaseModule


class _NamedEcho(BaseModule):
    name = "echo-test"

    def __init__(self, bus):
        super().__init__(bus)
        self.seen: list[WorkspaceSnapshot] = []
        self.errors_on: set[int] = set()

    async def on_workspace(self, snapshot):
        if snapshot.tick_index in self.errors_on:
            raise RuntimeError("forced")
        self.seen.append(snapshot)


class _Unnamed(BaseModule):
    pass


@pytest.fixture
async def real_bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.mark.asyncio
async def test_unnamed_subclass_fails_at_construction(real_bus):
    with pytest.raises(TypeError):
        _Unnamed(real_bus)


@pytest.mark.asyncio
async def test_publish_routes_to_named_stream(real_bus: AsyncBus):
    mod = _NamedEcho(real_bus)
    entry_id = await mod.publish("t.event", {"v": 1}, salience=0.4)
    assert entry_id
    entries = await real_bus.read("echo-test.out", last_id="0")
    assert len(entries) == 1
    _, event = entries[0]
    assert event.source == "echo-test"
    assert event.type == "t.event"
    assert event.payload == {"v": 1}
    assert event.salience == 0.4


@pytest.mark.asyncio
async def test_on_workspace_invoked_for_each_broadcast(real_bus: AsyncBus):
    mod = _NamedEcho(real_bus)
    await mod.initialize()
    try:
        # Publish three workspace snapshots via syneidesis source.
        for i in range(3):
            await real_bus.publish_workspace(
                {
                    "tick_index": i,
                    "selected": [],
                    "inhibited": False,
                    "is_experiential": True,
                }
            )
        for _ in range(50):
            if len(mod.seen) >= 3:
                break
            await asyncio.sleep(0.01)
        assert len(mod.seen) == 3
        assert [s.tick_index for s in mod.seen] == [0, 1, 2]
    finally:
        await mod.shutdown()


@pytest.mark.asyncio
async def test_on_workspace_error_does_not_stop_subscription(real_bus: AsyncBus):
    mod = _NamedEcho(real_bus)
    mod.errors_on = {1}
    await mod.initialize()
    try:
        for i in range(3):
            await real_bus.publish_workspace(
                {
                    "tick_index": i,
                    "selected": [],
                    "inhibited": False,
                    "is_experiential": True,
                }
            )
        for _ in range(50):
            if len(mod.seen) >= 2:
                break
            await asyncio.sleep(0.01)
        # tick 1 errored, ticks 0 and 2 should be recorded.
        recorded = [s.tick_index for s in mod.seen]
        assert 0 in recorded
        assert 2 in recorded
        assert 1 not in recorded
    finally:
        await mod.shutdown()


@pytest.mark.asyncio
async def test_snapshot_reconstructs_selected_events(real_bus: AsyncBus):
    mod = _NamedEcho(real_bus)
    await mod.initialize()
    try:
        now = datetime.now(timezone.utc).isoformat()
        await real_bus.publish_workspace(
            {
                "tick_index": 9,
                "inhibited": False,
                "is_experiential": True,
                "selected": [
                    {
                        "entry_id": "1-0",
                        "source": "soma",
                        "type": "wellness.update",
                        "salience": 0.8,
                        "payload": {"score": 0.9},
                        "timestamp": now,
                        "causal_parent": None,
                    }
                ],
                "salience_scores": {"1-0": 0.8},
                "metadata": {"note": "hi"},
            }
        )
        for _ in range(50):
            if mod.seen:
                break
            await asyncio.sleep(0.01)
        assert mod.seen, "consumer task never received a snapshot"
        snap = mod.seen[-1]
        assert snap.tick_index == 9
        assert len(snap.selected_events) == 1
        _, ev = snap.selected_events[0]
        assert ev.source == "soma"
        assert ev.payload == {"score": 0.9}
        assert snap.metadata == {"note": "hi"}
    finally:
        await mod.shutdown()


@pytest.mark.asyncio
async def test_default_ser_de_roundtrips_empty_state(real_bus: AsyncBus):
    mod = _NamedEcho(real_bus)
    state = mod.serialize()
    assert state == {}
    mod.deserialize(state)


@pytest.mark.asyncio
async def test_publish_validates_event_fields(real_bus: AsyncBus):
    mod = _NamedEcho(real_bus)
    from kaine.bus import EventValidationError
    with pytest.raises(EventValidationError):
        await mod.publish("t", {"x": 1}, salience=1.5)
