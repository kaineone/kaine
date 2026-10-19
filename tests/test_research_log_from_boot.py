# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Regression tests for research event log boot cursor behaviour."""

import asyncio
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.evaluation.config import EvaluationConfig, ResearchEventLogConfig
from kaine.evaluation.observers.research_event_observer import ResearchEventObserver
from kaine.evaluation.registry import SidecarRegistry


def _event(source: str, type_: str, payload: dict) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


class FakeBus:
    """Minimal bus double; tracks publish to assert read-only behaviour."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, Event]]] = {}
        self._next = 1
        self.published: list[Event] = []  # guard: must stay empty

    def push(self, stream: str, event: Event) -> str:
        eid = f"{self._next}-0"
        self._next += 1
        self.streams.setdefault(stream, []).append((eid, event))
        return eid

    async def read(self, stream, *, last_id="0", count=100, block_ms=0):
        entries = self.streams.get(stream, [])
        if last_id == "$":
            return []
        start = 0
        if last_id not in ("0", "0-0"):
            for i, (eid, _) in enumerate(entries):
                if eid == last_id:
                    start = i + 1
                    break
        return entries[start : start + count]

    async def read_entries(self, stream, last_id="0", count=100, block_ms=0):
        entries = await self.read(stream, last_id=last_id, count=count, block_ms=block_ms)
        last_scanned = entries[-1][0] if entries else None
        return entries, last_scanned

    async def subscribe_workspace(self, last_id="$", count=32, poll_interval_s=0.05):
        idx = 0
        while True:
            entries = self.streams.get("workspace.broadcast", [])
            while idx < len(entries):
                eid, event = entries[idx]
                idx += 1
                yield eid, dict(event.payload or {})
            await asyncio.sleep(poll_interval_s)

    async def current_workspace_id(self):
        return "0"

    async def publish(self, event: Event) -> str:
        self.published.append(event)
        return "fake-id"


class TailFakeBus(FakeBus):
    """Bus double that can report the newest entry id of a stream."""

    async def last_entry_id(self, stream: str) -> str:
        entries = self.streams.get(stream, [])
        if not entries:
            return "0-0"
        return entries[-1][0]


class FakeSink:
    """In-memory sink collecting written rows (no encryption / disk)."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def write(self, entry: dict) -> None:
        self.rows.append(entry)


def _affect_state_event() -> Event:
    return _event(
        "affect",
        "affect.state",
        {
            "state": {"valence": 0.1, "arousal": 0.3, "dominance": 0.0},
            "emotion": "neutral",
        },
    )


@pytest.mark.asyncio
async def test_tail_start_skips_the_previous_runs_entries():
    bus = TailFakeBus()
    sink = FakeSink()
    for _ in range(2):
        bus.push("affect.out", _affect_state_event())
    obs = ResearchEventObserver(
        bus, sink, poll_interval_s=0.02, start_at_tail=True
    )
    await obs.start()
    bus.push("affect.out", _affect_state_event())
    await asyncio.sleep(0.2)
    await obs.stop()
    assert len(sink.rows) == 1


@pytest.mark.asyncio
async def test_tail_start_on_an_empty_stream_reads_from_the_head():
    bus = TailFakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(
        bus, sink, poll_interval_s=0.02, start_at_tail=True
    )
    await obs.start()
    bus.push("affect.out", _affect_state_event())
    await asyncio.sleep(0.2)
    await obs.stop()
    assert len(sink.rows) == 1


@pytest.mark.asyncio
async def test_default_still_reads_the_backlog():
    bus = FakeBus()
    sink = FakeSink()
    for _ in range(2):
        bus.push("affect.out", _affect_state_event())
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    await obs.start()
    await asyncio.sleep(0.2)
    await obs.stop()
    assert len(sink.rows) == 2


@pytest.mark.asyncio
async def test_tail_lookup_failure_reads_from_the_head():
    class FailingTailBus(TailFakeBus):
        async def last_entry_id(self, stream: str) -> str:
            raise RuntimeError("tail lookup refused")

    bus = FailingTailBus()
    sink = FakeSink()
    bus.push("affect.out", _affect_state_event())
    obs = ResearchEventObserver(
        bus, sink, poll_interval_s=0.02, start_at_tail=True
    )
    await obs.start()
    await asyncio.sleep(0.2)
    await obs.stop()
    assert len(sink.rows) == 1


def test_sidecar_builds_the_research_observer_at_the_tail(tmp_path):
    bus = FakeBus()
    config = EvaluationConfig.from_mapping({"enabled": False})
    research_cfg = ResearchEventLogConfig(
        enabled=True, log_dir=str(tmp_path / "research_events")
    )
    registry = SidecarRegistry(
        bus=bus, config=config, research_event_log_config=research_cfg
    )
    registry.build()
    obs = next(o for o in registry.observers if o.name == "research_event_log")
    assert obs._start_at_tail is True


@pytest.mark.asyncio
async def test_tail_start_with_the_real_bus_skips_the_previous_run():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    for _ in range(2):
        await bus.publish(_affect_state_event())
    sink = FakeSink()
    obs = ResearchEventObserver(
        bus, sink, poll_interval_s=0.02, start_at_tail=True
    )
    await obs.start()
    await bus.publish(_affect_state_event())
    await asyncio.sleep(0.3)
    await obs.stop()
    await bus.close()
    affect_state_rows = [
        r for r in sink.rows if r.get("event_type") == "affect.state"
    ]
    assert len(affect_state_rows) == 1
