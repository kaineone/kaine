import asyncio
import time
from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.cycle.engine import CognitiveCycle
from kaine.cycle.types import WorkspaceSnapshot


class FakeBus:
    def __init__(self):
        self._published = []
        self._streams = {}
        self._workspace_broadcasts = []
        self._next_id = 1

    async def publish(self, event):
        self._published.append(event)
        stream = f"{event.source}.out"
        if stream not in self._streams:
            self._streams[stream] = []
        eid = str(self._next_id)
        self._next_id += 1
        self._streams[stream].append((eid, event))
        return eid

    async def publish_workspace(self, payload):
        self._workspace_broadcasts.append(payload)
        eid = str(self._next_id)
        self._next_id += 1
        return eid

    async def read_entries(self, stream, last_id="0", count=100, block_ms=0):
        entries = self._streams.get(stream, [])
        result = [(eid, ev) for eid, ev in entries if int(eid) > int(last_id)][:count]
        last_scanned = result[-1][0] if result else None
        return result, last_scanned

    async def current_workspace_id(self):
        return "0"

    def inject_entry(self, stream, event):
        if stream not in self._streams:
            self._streams[stream] = []
        eid = str(self._next_id)
        self._next_id += 1
        self._streams[stream].append((eid, event))
        return eid


class FakeWorkspace:
    async def select(self, events, context=None):
        ctx = context or {}
        return WorkspaceSnapshot(
            tick_index=ctx.get("tick_index", 0),
            selected_events=[(f"fake-{i}", ev) for i, (_, ev) in enumerate(events)] if events else [],
            inhibited=False,
            is_experiential=ctx.get("is_experiential", False),
            salience_scores={},
            metadata={},
            published_at=None,
        )


class FakeRegistry:
    def __init__(self, streams=None):
        self._streams = streams or []

    def active_streams(self):
        return list(self._streams)

    def all_modules(self):
        return iter([])


def make_event(source, event_type, payload=None, tick=None, seq=None):
    return Event(
        source=source,
        type=event_type,
        payload=payload or {},
        salience=0.0,
        timestamp=datetime.now(timezone.utc),
        tick=tick,
        seq=seq,
    )


@pytest.mark.asyncio
async def test_lockstep_requires_deterministic():
    bus = FakeBus()
    workspace = FakeWorkspace()
    registry = FakeRegistry()

    with pytest.raises(ValueError):
        CognitiveCycle(
            bus,
            workspace,
            registry,
            lockstep=True,
            clock=time.monotonic,
            sleep=asyncio.sleep,
        )


@pytest.mark.asyncio
async def test_lockstep_constructor_stores_params():
    bus = FakeBus()
    workspace = FakeWorkspace()
    registry = FakeRegistry()

    cycle = CognitiveCycle(
        bus,
        workspace,
        registry,
        deterministic=True,
        lockstep=True,
        lockstep_timeout_s=60.0,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    )

    assert cycle._lockstep is True
    assert cycle._lockstep_timeout_s == 60.0


@pytest.mark.asyncio
async def test_set_lockstep_participants():
    bus = FakeBus()
    workspace = FakeWorkspace()
    registry = FakeRegistry()

    cycle = CognitiveCycle(
        bus,
        workspace,
        registry,
        deterministic=True,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    )

    cycle.set_lockstep_participants(["interoception", "vision"])

    assert cycle._lockstep_participants == {"interoception", "vision"}
    assert "interoception.out" in cycle._tick_done_cursors
    assert "vision.out" in cycle._tick_done_cursors


@pytest.mark.asyncio
async def test_tick_start_published_in_lockstep():
    bus = FakeBus()
    workspace = FakeWorkspace()
    registry = FakeRegistry()

    cycle = CognitiveCycle(
        bus,
        workspace,
        registry,
        deterministic=True,
        lockstep=True,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    )

    await cycle.run_forever(max_ticks=1)

    assert any(
        event.type == "cycle.tick_start" and event.payload == {"tick": 0}
        for event in bus._published
    )


@pytest.mark.asyncio
async def test_no_tick_start_without_lockstep():
    bus = FakeBus()
    workspace = FakeWorkspace()
    registry = FakeRegistry()

    cycle = CognitiveCycle(
        bus,
        workspace,
        registry,
        deterministic=True,
        lockstep=False,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    )

    await cycle.run_forever(max_ticks=1)

    assert not any(event.type == "cycle.tick_start" for event in bus._published)


@pytest.mark.asyncio
async def test_lockstep_intake_sorting():
    bus = FakeBus()
    registry = FakeRegistry(["interoception.out"])

    class RecordingWorkspace(FakeWorkspace):
        def __init__(self):
            super().__init__()
            self.received = None

        async def select(self, events, context=None):
            self.received = list(events)
            return await super().select(events, context)

    workspace = RecordingWorkspace()

    # Inject in unsorted order.
    e_late = make_event("alpha", "data", tick=2, seq=1)
    e_first = make_event("alpha", "data", tick=1, seq=2)
    e_between = make_event("beta", "data", tick=1, seq=1)

    bus.inject_entry("interoception.out", e_late)
    bus.inject_entry("interoception.out", e_first)
    bus.inject_entry("interoception.out", e_between)

    cycle = CognitiveCycle(
        bus,
        workspace,
        registry,
        deterministic=True,
        lockstep=True,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    )

    await cycle.tick()

    received = workspace.received
    assert received is not None
    keys = [(ev.tick, ev.source, ev.seq) for _, ev in received]
    assert keys == [
        (e_first.tick, e_first.source, e_first.seq),
        (e_between.tick, e_between.source, e_between.seq),
        (e_late.tick, e_late.source, e_late.seq),
    ]


@pytest.mark.asyncio
async def test_logical_entry_id_format():
    bus = FakeBus()
    workspace = FakeWorkspace()
    registry = FakeRegistry()

    cycle = CognitiveCycle(
        bus,
        workspace,
        registry,
        deterministic=True,
        lockstep=True,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    )

    event = make_event("interoception", "data", tick=5, seq=0)
    snapshot = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[("original-entry", event)],
        inhibited=False,
        is_experiential=False,
        salience_scores={},
        metadata={},
        published_at=None,
    )

    payload = cycle._snapshot_to_payload(snapshot, True)

    assert payload["selected"][0]["entry_id"] == "5-interoception-0"


@pytest.mark.asyncio
async def test_barrier_completes_when_tick_done_received():
    bus = FakeBus()
    workspace = FakeWorkspace()
    registry = FakeRegistry(["interoception.out"])

    cycle = CognitiveCycle(
        bus,
        workspace,
        registry,
        deterministic=True,
        lockstep=True,
        clock=time.monotonic,
        sleep=asyncio.sleep,
    )
    cycle.set_lockstep_participants(["interoception"])

    tick_done = Event(
        source="interoception",
        type="interoception.tick_done",
        payload={"tick": 0},
        salience=0.0,
        timestamp=datetime.now(timezone.utc),
        tick=0,
        seq=0,
    )
    bus.inject_entry("interoception.out", tick_done)

    await asyncio.wait_for(cycle._await_barrier(0), timeout=1.0)
