# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus import Event, ReservedStreamError
from kaine.bus.client import AsyncBus, _decode_entry, _decode_event
from kaine.bus.config import BusConfig
from kaine.bus.errors import BusSecurityError
from kaine.bus.schema import WORKSPACE_STREAM


def _event(source: str = "soma", salience: float = 0.42, **payload) -> Event:
    return Event(
        source=source,
        type="test.event",
        payload=payload or {"x": 1},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_publish_then_read_returns_event(fake_async_bus: AsyncBus):
    ev = _event(salience=0.7)
    entry_id = await fake_async_bus.publish(ev)
    assert entry_id

    entries = await fake_async_bus.read("soma.out", last_id="0", count=10)
    assert len(entries) == 1
    _, got = entries[0]
    assert got.source == "soma"
    assert got.type == "test.event"
    assert got.salience == 0.7
    assert got.payload == {"x": 1}


@pytest.mark.asyncio
async def test_nested_payload_roundtrips(fake_async_bus: AsyncBus):
    payload = {"a": [1, 2, {"b": True, "c": None}], "d": "kaine"}
    ev = Event(
        source="soma",
        type="t",
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await fake_async_bus.publish(ev)
    entries = await fake_async_bus.read("soma.out")
    _, got = entries[0]
    assert got.payload == payload


@pytest.mark.asyncio
async def test_float_salience_full_precision(fake_async_bus: AsyncBus):
    target = 0.30000000000000004
    ev = Event(
        source="soma",
        type="t",
        payload={},
        salience=target,
        timestamp=datetime.now(timezone.utc),
    )
    await fake_async_bus.publish(ev)
    _, got = (await fake_async_bus.read("soma.out"))[0]
    assert got.salience == target


def _raw(salience: str = "0.5", timestamp: str = "2026-01-01T00:00:00+00:00") -> dict:
    return {
        "source": "soma",
        "type": "legacy.event",
        "salience": salience,
        "timestamp": timestamp,
        "causal_parent": "",
        "payload": "{}",
    }


def test_decode_event_tolerates_empty_salience():
    ev = _decode_event(_raw(salience=""))
    assert ev.salience == 0.0
    assert ev.source == "soma"


def test_decode_event_keeps_valid_salience():
    assert _decode_event(_raw(salience="0.73")).salience == 0.73


def test_decode_entry_skips_undecodable():
    # A malformed timestamp makes _decode_event raise; _decode_entry must
    # log+skip (return None) rather than propagate.
    assert _decode_entry("1-0", _raw(timestamp="not-a-timestamp")) is None
    # A well-formed entry still decodes to (id, Event).
    decoded = _decode_entry("2-0", _raw(salience="0.4"))
    assert decoded is not None and decoded[0] == "2-0"


@pytest.mark.asyncio
async def test_read_tolerates_empty_salience_entry(fake_async_bus: AsyncBus):
    stream = "soma.out"
    # Inject a legacy entry with empty salience directly (bypassing publish
    # validation), then a normal published event after it.
    await fake_async_bus._client.xadd(stream, _raw(salience=""))
    await fake_async_bus.publish(_event(salience=0.5))
    entries = await fake_async_bus.read(stream, last_id="0", count=10)
    assert len(entries) == 2
    assert entries[0][1].salience == 0.0  # legacy entry, decoded to floor
    assert entries[1][1].salience == 0.5


@pytest.mark.asyncio
async def test_read_skips_poison_entry_without_wedging(fake_async_bus: AsyncBus):
    stream = "soma.out"
    # An undecodable (bad timestamp) entry followed by a valid one.
    await fake_async_bus._client.xadd(stream, _raw(timestamp="not-a-timestamp"))
    await fake_async_bus.publish(_event(salience=0.6))
    entries = await fake_async_bus.read(stream, last_id="0", count=10)
    # Poison entry is omitted; the valid event is still returned, so a
    # consumer's cursor can advance past the bad entry.
    assert len(entries) == 1
    assert entries[0][1].salience == 0.6


@pytest.mark.asyncio
async def test_read_entries_reports_last_scanned_for_all_poison_batch(
    fake_async_bus: AsyncBus,
):
    stream = "soma.out"
    # An entire batch of undecodable entries (bad timestamps) and nothing
    # decodable: read returns no events, but read_entries still reports the
    # last scanned id so a cursor-advancing consumer can move past them
    # instead of re-reading the same poison batch forever.
    await fake_async_bus._client.xadd(stream, _raw(timestamp="nope"))
    id2 = await fake_async_bus._client.xadd(stream, _raw(timestamp="nope"))
    decoded, last_scanned = await fake_async_bus.read_entries(
        stream, last_id="0", count=64
    )
    assert decoded == []
    assert last_scanned == id2


@pytest.mark.asyncio
async def test_workspace_stream_reserved_for_syneidesis(fake_async_bus: AsyncBus):
    with pytest.raises(ReservedStreamError):
        await fake_async_bus.publish_workspace({"x": 1}, source="soma")


@pytest.mark.asyncio
async def test_syneidesis_publish_workspace(fake_async_bus: AsyncBus):
    entry_id = await fake_async_bus.publish_workspace({"focus": "soma", "k": 5})
    assert entry_id
    length = await fake_async_bus.length(WORKSPACE_STREAM)
    assert length == 1


@pytest.mark.asyncio
async def test_maxlen_trim_approximate(monkeypatch, bus_config_with_password):
    import fakeredis.aioredis

    cfg = BusConfig(
        password="t",
        audit_required=False,
        default_maxlen=50,
    )
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(cfg, client=client)
    try:
        for i in range(500):
            await bus.publish(_event(salience=(i % 100) / 100.0))
        length = await bus.length("soma.out")
        assert length <= 100, f"expected <=100 after trim, got {length}"
        assert length >= 40, f"expected at least near cap, got {length}"
    finally:
        await bus.close()


class _AuditFakeClient:
    """Minimal stub satisfying just what AsyncBus.audit needs."""

    def __init__(self, *, bind: str | None, requirepass: str | None) -> None:
        self._bind = bind
        self._requirepass = requirepass

    async def config_get(self, key: str) -> dict[str, str]:
        if key == "bind":
            return {"bind": self._bind} if self._bind is not None else {}
        if key == "requirepass":
            return {"requirepass": self._requirepass} if self._requirepass is not None else {"requirepass": ""}
        return {}

    async def aclose(self) -> None:
        return


@pytest.mark.asyncio
async def test_audit_skips_bind_check_for_loopback_host():
    cfg = BusConfig(host="127.0.0.1", port=6479, password="x")
    bus = AsyncBus(cfg, client=_AuditFakeClient(bind="0.0.0.0", requirepass="x"))  # type: ignore[arg-type]
    try:
        await bus.audit()
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_audit_rejects_external_bind_when_host_is_not_loopback():
    cfg = BusConfig(host="10.0.0.5", port=6379, password="x")
    bus = AsyncBus(cfg, client=_AuditFakeClient(bind="0.0.0.0", requirepass="x"))  # type: ignore[arg-type]
    try:
        with pytest.raises(BusSecurityError):
            await bus.audit()
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_audit_rejects_missing_requirepass_on_loopback():
    cfg = BusConfig(host="127.0.0.1", port=6479, password=None)
    bus = AsyncBus(cfg, client=_AuditFakeClient(bind="127.0.0.1", requirepass=""))  # type: ignore[arg-type]
    try:
        with pytest.raises(BusSecurityError):
            await bus.audit()
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_audit_rejects_missing_requirepass_on_non_loopback():
    cfg = BusConfig(host="10.0.0.5", port=6379, password=None)
    bus = AsyncBus(cfg, client=_AuditFakeClient(bind="127.0.0.1", requirepass=""))  # type: ignore[arg-type]
    try:
        with pytest.raises(BusSecurityError):
            await bus.audit()
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_audit_accepts_loopback_bind_on_loopback_host():
    cfg = BusConfig(host="localhost", port=6479, password="x")
    bus = AsyncBus(
        cfg, client=_AuditFakeClient(bind="127.0.0.1 -::1", requirepass="x")  # type: ignore[arg-type]
    )
    try:
        await bus.audit()
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_singleton_returns_same_instance(monkeypatch, tmp_path):
    import textwrap

    import fakeredis.aioredis

    from kaine.bus.client import _BUS_LOCK  # noqa: F401  (assert lock exists)
    from kaine.bus import client as client_mod

    secrets = tmp_path / "secrets.toml"
    secrets.write_text(
        textwrap.dedent(
            """
            [redis]
            password = "x"
            """
        )
    )
    kaine_toml = tmp_path / "kaine.toml"
    kaine_toml.write_text("[bus]\naudit_required = false\n")

    def _loader():
        from kaine.bus.config import load_bus_config

        return load_bus_config(kaine_toml=kaine_toml, secrets_toml=secrets, env={})

    monkeypatch.setattr(client_mod, "load_bus_config", _loader)

    fake_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    a = await client_mod.get_bus(client=fake_client)
    b = await client_mod.get_bus(client=fake_client)
    assert a is b
