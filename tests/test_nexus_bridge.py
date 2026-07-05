# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.nexus.bridge import BusBridge, SSEClient, event_to_sse_payload
from kaine.nexus.privacy import PrivacyFilter


def _event(text="hi"):
    return Event(
        source="lingua",
        type="external_speech",
        payload={"text": text, "metric": 1},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


class FakeBus:
    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, Event]]] = {}
        self._next_id = 1

    def push(self, stream: str, event: Event) -> str:
        entry_id = f"{self._next_id}-0"
        self._next_id += 1
        self.streams.setdefault(stream, []).append((entry_id, event))
        return entry_id

    async def read(self, stream, *, last_id, count, block_ms):
        entries = self.streams.get(stream, [])
        if last_id == "$":
            return []
        start = 0
        if last_id != "0":
            for i, (eid, _) in enumerate(entries):
                if eid == last_id:
                    start = i + 1
                    break
        return entries[start : start + count]

    async def current_workspace_id(self):
        return "0"


@pytest.mark.asyncio
async def test_bridge_content_strips_for_any_client():
    # There is no unfiltered surface: even an arbitrarily-named client gets the
    # content-stripped payload. The bridge never serves raw cognitive content.
    bus = FakeBus()
    pf = PrivacyFilter()
    bridge = BusBridge(bus, pf, streams=["lingua.external"], poll_interval_s=0.01)
    bridge._cursors["lingua.external"] = "0"
    client = bridge.add_client("diagnostics")
    bus.push("lingua.external", _event("hello"))
    await bridge.start()
    try:
        entry_id, evt = await asyncio.wait_for(client.queue.get(), timeout=1.0)
        assert evt.payload == {"metric": 1}
        assert "text" not in evt.payload
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_bridge_strips_for_diagnostics_client():
    bus = FakeBus()
    pf = PrivacyFilter()
    bridge = BusBridge(bus, pf, streams=["lingua.external"], poll_interval_s=0.01)
    bridge._cursors["lingua.external"] = "0"
    client = bridge.add_client("diagnostics")
    bus.push("lingua.external", _event("secret"))
    await bridge.start()
    try:
        _, evt = await asyncio.wait_for(client.queue.get(), timeout=1.0)
        assert evt.payload == {"metric": 1}
        assert "text" not in evt.payload
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_bridge_fans_out_to_multiple_clients_all_scrubbed():
    # Every client — regardless of count — receives the SCRUBBED payload; there
    # is no longer a surface that gets full content.
    bus = FakeBus()
    pf = PrivacyFilter()
    bridge = BusBridge(bus, pf, streams=["lingua.external"], poll_interval_s=0.01)
    bridge._cursors["lingua.external"] = "0"
    a = bridge.add_client("diagnostics")
    b = bridge.add_client("diagnostics")
    bus.push("lingua.external", _event("hello"))
    await bridge.start()
    try:
        _, a_evt = await asyncio.wait_for(a.queue.get(), timeout=1.0)
        _, b_evt = await asyncio.wait_for(b.queue.get(), timeout=1.0)
        assert "text" not in a_evt.payload
        assert "text" not in b_evt.payload
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_bridge_remove_client_stops_delivery():
    bus = FakeBus()
    pf = PrivacyFilter()
    bridge = BusBridge(bus, pf, streams=["lingua.external"], poll_interval_s=0.01)
    bridge._cursors["lingua.external"] = "0"
    client = bridge.add_client("diagnostics")
    bridge.remove_client(client)
    bus.push("lingua.external", _event("hello"))
    await bridge.start()
    try:
        await asyncio.sleep(0.05)
        assert client.queue.empty()
    finally:
        await bridge.stop()


def test_event_to_sse_payload_serializes_timestamp():
    evt = _event()
    out = event_to_sse_payload("1-0", evt)
    assert out["id"] == "1-0"
    assert out["source"] == "lingua"
    assert isinstance(out["timestamp"], str)


@pytest.mark.asyncio
async def test_sse_client_push_drops_when_full():
    client = SSEClient(surface="diagnostics", queue=asyncio.Queue(maxsize=1))
    await client.push("1", _event())
    await client.push("2", _event())
    # second push should be dropped silently — not raise.
    assert client.queue.qsize() == 1


# ---------------------------------------------------------------------------
# Filter-once-per-event (task 1.2): BusBridge._dispatch must call the privacy
# filter exactly ONCE per bus event regardless of client count, and every
# client must receive output IDENTICAL to what today's per-client filtering
# produced (same scrub, same result — see the filter_for_diagnostics/`filter`
# contract in kaine/privacy_filter.py, where `surface` is accepted but ignored).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dispatch_calls_privacy_filter_once_per_event_not_once_per_client(
    monkeypatch,
):
    # PrivacyFilter is a frozen dataclass — instance attribute assignment (e.g.
    # `pf.filter = ...`) would raise FrozenInstanceError, so the call-counting
    # wrapper is installed on the CLASS via monkeypatch (auto-restored).
    bus = FakeBus()
    pf = PrivacyFilter()
    calls: list[Event] = []
    orig_filter = PrivacyFilter.filter

    def counting_filter(self, event, *, surface="diagnostics"):
        calls.append(event)
        return orig_filter(self, event, surface=surface)

    monkeypatch.setattr(PrivacyFilter, "filter", counting_filter)

    bridge = BusBridge(bus, pf, streams=["lingua.external"], poll_interval_s=0.01)
    bridge._cursors["lingua.external"] = "0"
    clients = [bridge.add_client("diagnostics") for _ in range(5)]
    bus.push("lingua.external", _event("hello"))
    await bridge.start()
    try:
        for c in clients:
            await asyncio.wait_for(c.queue.get(), timeout=1.0)
        # Five clients subscribed, but the filter ran exactly once for the one
        # published event — the whole point of task 1.2.
        assert len(calls) == 1
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_dispatch_output_identical_across_all_clients_and_matches_direct_filter():
    # The single filtered-once Event fanned out to N clients must be exactly
    # what PrivacyFilter.filter() would have produced per-client (no drift
    # introduced by sharing one filtered instance instead of recomputing it).
    bus = FakeBus()
    pf = PrivacyFilter()
    bridge = BusBridge(bus, pf, streams=["lingua.external"], poll_interval_s=0.01)
    bridge._cursors["lingua.external"] = "0"
    clients = [bridge.add_client("diagnostics") for _ in range(3)]
    raw_event = _event("hello secret")
    bus.push("lingua.external", raw_event)
    expected = pf.filter(raw_event, surface="diagnostics")
    await bridge.start()
    try:
        received = []
        for c in clients:
            _, evt = await asyncio.wait_for(c.queue.get(), timeout=1.0)
            received.append(evt)
        for evt in received:
            assert evt.payload == expected.payload == {"metric": 1}
            assert "text" not in evt.payload
        # Every client got the SAME filtered object (identity, not just
        # equality) — proof the scrub ran once and was fanned out, not
        # recomputed per client.
        assert all(evt is received[0] for evt in received)
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_dispatch_skips_filter_when_no_clients(monkeypatch):
    # No wasted filtering work when nobody is listening.
    bus = FakeBus()
    pf = PrivacyFilter()
    calls: list[Event] = []
    orig_filter = PrivacyFilter.filter

    def counting_filter(self, event, *, surface="diagnostics"):
        calls.append(event)
        return orig_filter(self, event, surface=surface)

    monkeypatch.setattr(PrivacyFilter, "filter", counting_filter)
    bridge = BusBridge(bus, pf, streams=["lingua.external"], poll_interval_s=0.01)
    bridge._cursors["lingua.external"] = "0"
    bus.push("lingua.external", _event("hello"))
    await bridge.start()
    try:
        await asyncio.sleep(0.05)
        assert calls == []
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_publish_synthetic_goes_through_the_same_filter_once_fanout_path():
    bus = FakeBus()
    pf = PrivacyFilter()
    bridge = BusBridge(bus, pf, streams=[], poll_interval_s=0.01)
    a = bridge.add_client("diagnostics")
    b = bridge.add_client("diagnostics")
    await bridge.publish_synthetic(
        source="nexus", type="nexus.snapshot", payload={"metrics": {"a": 1}}
    )
    _, evt_a = await asyncio.wait_for(a.queue.get(), timeout=1.0)
    _, evt_b = await asyncio.wait_for(b.queue.get(), timeout=1.0)
    assert evt_a.source == "nexus"
    assert evt_a.type == "nexus.snapshot"
    assert evt_a.payload == {"metrics": {"a": 1}}
    assert evt_a is evt_b
