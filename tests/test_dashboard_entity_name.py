# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.dashboard.app import create_app
from kaine.dashboard.bridge import BusBridge
from kaine.dashboard.config import DashboardConfig
from kaine.dashboard.conversation import ConversationState, read_entity_name
from kaine.dashboard.privacy import PrivacyFilter


def _event(source, type_, payload):
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


def _external_event(text="hi"):
    return Event(
        source="language",
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

    async def read_entries(self, stream, *, last_id, count, block_ms):
        entries = await self.read(stream, last_id=last_id, count=count, block_ms=block_ms)
        return entries, (entries[-1][0] if entries else None)

    async def current_workspace_id(self):
        return "0"

    async def last_entry_id(self, stream):
        entries = self.streams.get(stream, [])
        if not entries:
            return "0-0"
        return entries[-1][0]


class FakeRecentBus:
    def __init__(self, recents: dict[str, list[tuple[str, Event]]]) -> None:
        self._recents = recents

    async def recent(self, stream: str, count: int = 100) -> list[tuple[str, Event]]:
        return list(self._recents.get(stream, []))


class StubBus:
    async def read(self, stream, *, last_id, count, block_ms):
        return []

    async def current_workspace_id(self):
        return "0"


async def _make_app_client(*, state: ConversationState, startup=None):
    config = DashboardConfig(
        conversation_enabled=True,
        host_allowlist=("127.0.0.1", "localhost", "test"),
        operator_token="test-token",
    )
    bus = StubBus()
    privacy = PrivacyFilter()
    bridge = BusBridge(bus, privacy, streams=[], poll_interval_s=0.01)

    async def history_loader(n: int):
        return []

    app = create_app(
        config=config,
        bridge=bridge,
        history_loader=history_loader,
        metrics_snapshot=lambda: {"cycle_status": "not running"},
        conversation_state=state,
        startup=startup,
    )
    transport = httpx.ASGITransport(app=app)
    client = httpx.AsyncClient(transport=transport, base_url="http://test")
    return client, app


@pytest.mark.asyncio
async def test_observer_receives_raw_event_before_filter():
    bus = FakeBus()
    pf = PrivacyFilter()
    bridge = BusBridge(bus, pf, streams=["language.external"], poll_interval_s=0.01)
    bridge._cursors["language.external"] = "0"
    observed: list[Event] = []
    bridge.add_observer(observed.append)
    client = bridge.add_client("diagnostics")
    bus.push("language.external", _external_event("secret"))
    await bridge.start()
    try:
        entry_id, evt = await asyncio.wait_for(client.queue.get(), timeout=1.0)
        assert len(observed) == 1
        assert observed[0].payload == {"text": "secret", "metric": 1}
        assert evt.payload == {"metric": 1}
        assert "text" not in evt.payload
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_observer_called_when_no_client_connected():
    bus = FakeBus()
    pf = PrivacyFilter()
    bridge = BusBridge(bus, pf, streams=["language.external"], poll_interval_s=0.01)
    bridge._cursors["language.external"] = "0"
    seen: list[Event] = []
    got = asyncio.Event()

    def capture(event: Event) -> None:
        seen.append(event)
        got.set()

    bridge.add_observer(capture)
    bus.push("language.external", _external_event("alone"))
    await bridge.start()
    try:
        await asyncio.wait_for(got.wait(), timeout=1.0)
        assert len(seen) == 1
        assert seen[0].payload["text"] == "alone"
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_observer_failure_logged_and_others_continue(caplog):
    caplog.set_level(logging.WARNING)
    bus = FakeBus()
    pf = PrivacyFilter()
    bridge = BusBridge(bus, pf, streams=["language.external"], poll_interval_s=0.01)
    bridge._cursors["language.external"] = "0"
    first_called = False
    second_observed: list[Event] = []

    def fail(event: Event) -> None:
        nonlocal first_called
        first_called = True
        raise RuntimeError("boom")

    def capture(event: Event) -> None:
        second_observed.append(event)

    bridge.add_observer(fail)
    bridge.add_observer(capture)
    client = bridge.add_client("diagnostics")
    bus.push("language.external", _external_event("resilient"))
    await bridge.start()
    try:
        entry_id, evt = await asyncio.wait_for(client.queue.get(), timeout=1.0)
        assert first_called is True
        assert len(second_observed) == 1
        assert second_observed[0].payload["text"] == "resilient"
        assert evt.payload == {"metric": 1}
        assert any("dashboard bridge observer failed" in rec.message for rec in caplog.records)
    finally:
        await bridge.stop()


def test_observe_self_model_document_sets_name():
    state = ConversationState()
    state.observe(_event("self_model", "self_model.document", {"name": "Lyra"}))
    assert state.entity_name == "Lyra"


def test_observe_self_model_other_fields_leave_default():
    state = ConversationState()
    state.observe(
        _event("self_model", "self_model.document", {"values": {}, "behavioral_norms": []})
    )
    assert state.entity_name == "KAINE"


def test_observe_self_model_empty_or_whitespace_name_ignored():
    state = ConversationState()
    state.observe(_event("self_model", "self_model.document", {"name": ""}))
    assert state.entity_name == "KAINE"
    state.observe(_event("self_model", "self_model.document", {"name": "   "}))
    assert state.entity_name == "KAINE"


def test_observe_self_model_non_dict_payload_ignored():
    state = ConversationState()
    # Event validates its payload, so build one that skips validation.
    event = Event.model_construct(
        source="self_model",
        type="self_model.document",
        payload="not a dict",
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
        causal_parent=None,
    )
    state.observe(event)
    assert state.entity_name == "KAINE"


def test_observe_sleep_lifecycle_toggles_sleeping():
    state = ConversationState()
    assert state.sleeping is False
    state.observe(_event("sleep", "sleep.sleep.started", {}))
    assert state.sleeping is True
    state.observe(_event("sleep", "sleep.sleep.completed", {}))
    assert state.sleeping is False


def test_observe_unrelated_type_ignored():
    state = ConversationState()
    state.observe(_event("language", "external_speech", {"text": "hello"}))
    assert state.entity_name == "KAINE"
    assert state.sleeping is False


@pytest.mark.asyncio
async def test_backfill_newest_self_model_document_wins():
    bus = FakeRecentBus({
        "self_model.out": [
            ("3-0", _event("self_model", "self_model.document", {"name": "Newest"})),
            ("2-0", _event("self_model", "self_model.document", {"name": "Older"})),
        ]
    })
    state = ConversationState()
    await state.backfill(bus, scan=10)
    assert state.entity_name == "Newest"


@pytest.mark.asyncio
async def test_backfill_newest_sleep_lifecycle_decides_sleeping():
    bus = FakeRecentBus({
        "sleep.out": [
            ("3-0", _event("sleep", "sleep.sleep.started", {})),
            ("2-0", _event("sleep", "sleep.sleep.completed", {})),
        ]
    })
    state = ConversationState()
    await state.backfill(bus, scan=10)
    assert state.sleeping is True


@pytest.mark.asyncio
async def test_backfill_skips_non_matching_newer_types():
    bus = FakeRecentBus({
        "self_model.out": [
            ("3-0", _event("self_model", "self_model.heartbeat", {})),
            ("2-0", _event("self_model", "self_model.document", {"name": "Kaine"})),
        ],
        "sleep.out": [
            ("3-0", _event("sleep", "sleep.log", {})),
            ("2-0", _event("sleep", "sleep.sleep.completed", {})),
        ],
    })
    state = ConversationState()
    await state.backfill(bus, scan=10)
    assert state.entity_name == "Kaine"
    assert state.sleeping is False


@pytest.mark.asyncio
async def test_backfill_bus_error_leaves_state_unchanged():
    class RaisingBus:
        async def recent(self, stream: str, count: int = 100) -> list[tuple[str, Event]]:
            raise RuntimeError("redis down")

    state = ConversationState()
    await state.backfill(RaisingBus(), scan=10)
    assert state.entity_name == "KAINE"
    assert state.sleeping is False


@pytest.mark.asyncio
async def test_async_bus_recent_returns_newest_first():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    for i in range(3):
        await bus.publish(
            Event(
                source="self_model",
                type="self_model.document",
                payload={"name": f"Kaine {i}"},
                salience=0.0,
                timestamp=datetime.now(timezone.utc),
            )
        )
    recent = await bus.recent("self_model.out", count=2)
    assert len(recent) == 2
    assert recent[0][1].payload["name"] == "Kaine 2"
    assert recent[1][1].payload["name"] == "Kaine 1"
    assert await bus.recent("sleep.out", count=2) == []


def test_read_entity_name_from_self_model(tmp_path: Path):
    self_model = tmp_path / "self_model.json"
    self_model.write_text(json.dumps({"name": "Kaine Voxel"}))
    identity = tmp_path / "identity.json"
    assert read_entity_name(self_model, identity) == "Kaine Voxel"


def test_read_entity_name_empty_self_model_falls_through_to_identity(tmp_path: Path):
    self_model = tmp_path / "self_model.json"
    self_model.write_text(json.dumps({"name": ""}))
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({"name": "Kaine Nova"}))
    assert read_entity_name(self_model, identity) == "Kaine Nova"


def test_read_entity_name_identity_without_name_returns_none(tmp_path: Path):
    self_model = tmp_path / "self_model.json"
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({"id": "x"}))
    assert read_entity_name(self_model, identity) is None


def test_read_entity_name_both_absent_returns_none(tmp_path: Path):
    self_model = tmp_path / "self_model.json"
    identity = tmp_path / "identity.json"
    assert read_entity_name(self_model, identity) is None


def test_read_entity_name_corrupt_self_model_falls_through_to_identity(tmp_path: Path):
    self_model = tmp_path / "self_model.json"
    self_model.write_bytes(b"{not json")
    identity = tmp_path / "identity.json"
    identity.write_text(json.dumps({"name": "Kaine Backup"}))
    assert read_entity_name(self_model, identity) == "Kaine Backup"


@pytest.mark.asyncio
async def test_create_app_startup_hook_runs():
    ran = False

    async def startup() -> None:
        nonlocal ran
        ran = True

    state = ConversationState()
    state.observe(_event("self_model", "self_model.document", {"name": "Lyra"}))
    client, app = await _make_app_client(state=state, startup=startup)
    async with client:
        async with app.router.lifespan_context(app):
            assert ran is True
            r = await client.get("/", headers={"Authorization": "Bearer test-token"})
            assert r.status_code == 200
            assert "Lyra" in r.text


@pytest.mark.asyncio
async def test_create_app_startup_failure_still_serves_request():
    async def boom() -> None:
        raise RuntimeError("startup failed")

    state = ConversationState()
    state.observe(_event("self_model", "self_model.document", {"name": "Nova"}))
    client, app = await _make_app_client(state=state, startup=boom)
    async with client:
        async with app.router.lifespan_context(app):
            r = await client.get("/", headers={"Authorization": "Bearer test-token"})
            assert r.status_code == 200
            assert "Nova" in r.text


async def _diagnostics_client(state: ConversationState):
    config = DashboardConfig(
        conversation_enabled=False,
        diagnostics_enabled=True,
        host_allowlist=("127.0.0.1", "localhost", "test"),
        operator_token="test-token",
    )
    bridge = BusBridge(StubBus(), PrivacyFilter(), streams=[], poll_interval_s=0.01)

    async def history_loader(n: int):
        return []

    app = create_app(
        config=config,
        bridge=bridge,
        history_loader=history_loader,
        metrics_snapshot=lambda: {"cycle_status": "not running"},
        conversation_state=state,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def _watching_state(tmp_path: Path, interval_s: float = 0.0) -> tuple[ConversationState, Path]:
    identity = tmp_path / "entity.json"
    state = ConversationState()
    state.watch_name_files(tmp_path / "self_model.json", identity, interval_s=interval_s)
    return state, identity


@pytest.mark.asyncio
async def test_header_shows_name_with_conversation_disabled(tmp_path: Path):
    state, identity = _watching_state(tmp_path)
    identity.write_text('{"name": "Kaine Whipple"}')
    async with await _diagnostics_client(state) as client:
        for path in ("/diagnostics/",):
            resp = await client.get(path)
            assert resp.status_code == 200, path
            assert 'id="header-entity-name" data-entity-name>Kaine Whipple<' in resp.text, path


@pytest.mark.asyncio
async def test_header_placeholder_then_name_without_restart(tmp_path: Path):
    state, identity = _watching_state(tmp_path)
    async with await _diagnostics_client(state) as client:
        first = await client.get("/diagnostics/")
        assert 'data-entity-name>KAINE<' in first.text
        assert (await client.get("/diagnostics/entity-name.json")).json() == {"name": "KAINE"}

        identity.write_text('{"name": "Kaine Whipple"}')
        second = await client.get("/diagnostics/")
        assert 'data-entity-name>Kaine Whipple<' in second.text
        assert (await client.get("/diagnostics/entity-name.json")).json() == {
            "name": "Kaine Whipple"
        }


def test_name_refresh_is_throttled_and_follows_changes(tmp_path: Path, monkeypatch):
    import kaine.dashboard.conversation as conv

    clock = [100.0]
    monkeypatch.setattr(conv.time, "monotonic", lambda: clock[0])
    state, identity = _watching_state(tmp_path, interval_s=10.0)
    identity.write_text('{"name": "First"}')
    assert state.current_name() == "KAINE"  # within the interval, not yet checked
    clock[0] += 10.0
    assert state.current_name() == "First"
    identity.write_text('{"name": "Second"}')
    clock[0] += 1.0
    assert state.current_name() == "First"
    clock[0] += 10.0
    assert state.current_name() == "Second"


@pytest.mark.asyncio
async def test_header_name_is_html_escaped():
    state = ConversationState()
    state.entity_name = "<b>x</b> & <script>1</script>"
    async with await _diagnostics_client(state) as client:
        text = (await client.get("/diagnostics/")).text
    assert "<script>1</script>" not in text
    assert "<b>x</b>" not in text
    assert "&lt;b&gt;x&lt;/b&gt; &amp; &lt;script&gt;1&lt;/script&gt;" in text
