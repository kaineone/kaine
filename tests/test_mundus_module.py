# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline tests for the Mundus embodiment control plane — no viewer/grid needed.

The OpenSim adapter is exercised through a fake shim (a plain TCP client speaking
the length-prefixed MessagePack frame contract), so we cover the full KAINE-side
bridge: perception frames → bus events, and intent.avatar.* / mirrored speech →
action frames. The body-agnostic core is exercised through the transport-free
stub adapter for the continuous-setpoint path the OpenSim body does not have.
"""
from __future__ import annotations

import asyncio
import socket
import struct
from datetime import datetime, timezone

import msgpack
import pytest

from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.modules.mundus import (
    ACTION_DEFAULT_EXPOSED,
    FEED_EVENT,
    EmbodimentCapabilities,
    FeedFrame,
    Mundus,
    OpenSimAdapter,
    StubAdapter,
    read_frame,
    write_frame,
)


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _mundus(bus, *, port=None, expose=None, mirror_speech=True,
            speech_stream="lingua.external", locus_reader=None,
            enabled=True):
    """Build a Mundus core wired to a fresh OpenSim adapter on `port`."""
    if port is None:
        port = _free_port()
    return Mundus(
        bus,
        adapter=OpenSimAdapter("127.0.0.1", port),
        enabled=enabled,
        expose=expose,
        mirror_speech=mirror_speech,
        speech_stream=speech_stream,
        locus_reader=locus_reader,
    )


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus

    client = fakeredis.FakeRedis(decode_responses=True)
    yield AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    await client.aclose()


async def _reader_from(payload: bytes) -> asyncio.StreamReader:
    r = asyncio.StreamReader()
    r.feed_data(payload)
    r.feed_eof()
    return r


async def _wait_event(bus, stream: str, etype: str, timeout: float = 3.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        for _id, ev in await bus.read(stream, last_id="0", count=50, block_ms=100):
            if ev.type == etype:
                return ev
        await asyncio.sleep(0.05)
    raise AssertionError(f"event {etype} never appeared on {stream}")


@pytest.mark.asyncio
async def test_frame_roundtrip():
    body = msgpack.packb({"kind": "chat", "message": "hi"}, use_bin_type=True)
    frame = await read_frame(await _reader_from(struct.pack(">I", len(body)) + body))
    assert frame == {"kind": "chat", "message": "hi"}


@pytest.mark.asyncio
async def test_disabled_is_noop(bus, monkeypatch):
    monkeypatch.delenv("KAINE_MUNDUS_OPERATOR_APPROVED", raising=False)
    # config on but env approval missing → still gated off; no adapter opened.
    m = _mundus(bus)
    await m.initialize()
    assert m._adapter._server is None
    await m.shutdown()


@pytest.mark.asyncio
async def test_perception_action_and_speech(bus, monkeypatch):
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    port = _free_port()
    m = _mundus(bus, port=port, mirror_speech=True,
                speech_stream="linguatest.out", locus_reader=lambda: "virtual")
    await m.initialize()
    assert m._adapter._server is not None
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await asyncio.sleep(0.1)  # let _on_client register the connection

    try:
        # --- perception: inbound chat → mundus.chat -----------------------
        await write_frame(writer, {"kind": "chat", "from_name": "Erik",
                                   "message": "hello kaine"})
        ev = await _wait_event(bus, "mundus.out", "mundus.chat")
        assert ev.payload["message"] == "hello kaine"
        assert ev.payload["from_name"] == "Erik"

        # --- vision frame: bytes must be stripped off the bus -------------
        await write_frame(writer, {"kind": "frame", "w": 224, "h": 224,
                                   "encoding": "rgb8", "seq": 1, "data": b"\x00" * 16})
        ev = await _wait_event(bus, "mundus.out", "mundus.visual.raw")
        assert ev.payload["w"] == 224 and "data" not in ev.payload

        # --- action: intent.avatar.say → action frame to the shim ---------
        await bus.publish(validate_event(
            source="volition", type="intent.avatar.say",
            payload={"message": "hi there", "channel": 0}, salience=0.5,
            timestamp=datetime.now(timezone.utc)))
        frame = await asyncio.wait_for(read_frame(reader), timeout=3.0)
        assert frame["kind"] == "action" and frame["action"] == "say"
        assert frame["message"] == "hi there"
        assert "reqid" in frame  # fresh per-action request id preserved

        # --- speech mirror: external speech → avatar say ------------------
        await bus.publish(validate_event(
            source="linguatest", type="lingua.external",
            payload={"text": "spoken aloud"}, salience=0.4,
            timestamp=datetime.now(timezone.utc)))
        frame = await asyncio.wait_for(read_frame(reader), timeout=3.0)
        assert frame["action"] == "say" and frame["message"] == "spoken aloud"
    finally:
        writer.close()
        await m.shutdown()


@pytest.mark.asyncio
async def test_physical_locus_blocks_avatar_actions(bus, monkeypatch):
    """perception_locus: in `physical` the entity isn't embodied in the grid, so
    no avatar action is forwarded even for an exposed family."""
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    port = _free_port()
    m = _mundus(bus, port=port, mirror_speech=False, locus_reader=lambda: "physical")
    await m.initialize()
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await asyncio.sleep(0.1)
    try:
        await bus.publish(validate_event(
            source="volition", type="intent.avatar.say",
            payload={"message": "should not reach the avatar"}, salience=0.5,
            timestamp=datetime.now(timezone.utc)))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(read_frame(reader), timeout=1.0)
    finally:
        writer.close()
        await m.shutdown()


@pytest.mark.asyncio
async def test_unexposed_action_is_dropped(bus, monkeypatch):
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    port = _free_port()
    m = _mundus(bus, port=port, mirror_speech=False, locus_reader=lambda: "virtual")
    await m.initialize()
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    await asyncio.sleep(0.1)
    try:
        # teleport defaults to NOT exposed → no frame should arrive
        await bus.publish(validate_event(
            source="volition", type="intent.avatar.teleport",
            payload={"region": "Welcome", "x": 128, "y": 128, "z": 25},
            salience=0.5, timestamp=datetime.now(timezone.utc)))
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(read_frame(reader), timeout=1.0)
    finally:
        writer.close()
        await m.shutdown()


# ---- descriptor drift guard (OpenSim behavior preservation) ---------------
def test_opensim_descriptor_equals_prior_constants():
    """The OpenSim adapter must declare EXACTLY the pre-refactor tables, so any
    future edit that drifts the OpenSim behavior fails CI."""
    caps = OpenSimAdapter("127.0.0.1", 7781).capabilities()
    assert caps.name == "opensim"
    assert caps.transitional is True
    assert caps.feed_events == FEED_EVENT
    assert caps.action_families == ACTION_DEFAULT_EXPOSED
    assert caps.continuous_channels == ()
    assert caps.raw_buffer_keys == ("data",)


def test_capabilities_descriptor_is_frozen_and_validated():
    caps = OpenSimAdapter("127.0.0.1", 7781).capabilities()
    with pytest.raises(Exception):
        caps.name = "other"  # frozen dataclass
    # salience must be in [0, 1]
    with pytest.raises(ValueError):
        EmbodimentCapabilities(
            name="bad", transitional=False,
            feed_events={"x": ("mundus.x", 1.5)}, action_families={})
    # family names must be non-empty
    with pytest.raises(ValueError):
        EmbodimentCapabilities(
            name="bad", transitional=False, feed_events={},
            action_families={"": True})
    # continuous channel names must be non-empty
    with pytest.raises(ValueError):
        EmbodimentCapabilities(
            name="bad", transitional=False, feed_events={},
            action_families={}, continuous_channels=("",))


# ---- continuous-setpoint path (stub body; OpenSim does not exercise it) ----
@pytest.mark.asyncio
async def test_continuous_setpoints_clamped_and_forwarded(bus):
    adapter = StubAdapter()
    m = Mundus(bus, adapter=adapter, enabled=True,
               continuous_expose={"drive": True, "yaw_rate": True},
               locus_reader=lambda: "virtual")
    # drive over range → clamps to +1.0; yaw_rate under range → clamps to -1.0.
    ok = await m.apply_setpoints({"drive": 2.0, "yaw_rate": -3.0})
    assert ok is True
    assert adapter.setpoints == [{"drive": 1.0, "yaw_rate": -1.0}]


@pytest.mark.asyncio
async def test_continuous_channel_default_unexposed_is_dropped(bus):
    adapter = StubAdapter()
    m = Mundus(bus, adapter=adapter, enabled=True, locus_reader=lambda: "virtual")
    # No continuous_expose → every channel defaults OFF → dropped.
    ok = await m.apply_setpoints({"drive": 0.5})
    assert ok is False
    assert adapter.setpoints == []


@pytest.mark.asyncio
async def test_continuous_setpoints_gated_by_locus(bus):
    adapter = StubAdapter()
    m = Mundus(bus, adapter=adapter, enabled=True,
               continuous_expose={"drive": True}, locus_reader=lambda: "physical")
    ok = await m.apply_setpoints({"drive": 0.5})
    assert ok is False
    assert adapter.setpoints == []


@pytest.mark.asyncio
async def test_symbolic_only_body_rejects_setpoints(bus):
    """A body that declares no continuous channels rejects setpoints as
    unsupported rather than silently dropping them (spec scenario)."""
    m = Mundus(bus, adapter=OpenSimAdapter("127.0.0.1", _free_port()),
               enabled=True, locus_reader=lambda: "virtual")
    ok = await m.apply_setpoints({"drive": 0.5})
    assert ok is False


@pytest.mark.asyncio
async def test_stub_feed_maps_through_descriptor(bus, monkeypatch):
    """The core pumps the adapter's feed and maps kinds via the descriptor,
    generically (no OpenSim knowledge)."""
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    adapter = StubAdapter()
    m = Mundus(bus, adapter=adapter, enabled=True, mirror_speech=False,
               locus_reader=lambda: "virtual")
    await m.initialize()
    try:
        adapter.push_frame(FeedFrame(kind="chat", payload={"message": "yo"}))
        ev = await _wait_event(bus, "mundus.out", "mundus.chat")
        assert ev.payload["message"] == "yo"
    finally:
        await m.shutdown()
