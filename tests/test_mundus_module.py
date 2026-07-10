# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline tests for the Mundus embodiment control plane — no body/transport.

Mundus is body-agnostic: the core owns feed→bus mapping (raw-buffer stripping +
salience policy), symbolic-action gating (locus + exposure), the continuous-
setpoint path, and cursor serialization, and knows nothing of any wire protocol.
No transport-backed body ships today, so these tests drive the core through the
transport-free ``StubAdapter`` and a small in-file ``FakeAdapter`` whose
descriptor declares a raw-buffer key, a default-unexposed family, and the
salience-policy feed kinds — enough to exercise every core behavior locally.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import pytest

from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.modules.mundus import (
    EmbodimentCapabilities,
    FeedFrame,
    Mundus,
    StubAdapter,
)


class FakeAdapter:
    """A transport-free EmbodimentAdapter for exercising the core generically.

    Richer than the stub: it declares a raw-buffer key (``data``) so the core's
    raw-strip is covered, the salience-policy feed kinds (``proprio``/``entity``),
    and a default-unexposed family (``teleport``) so exposure gating is covered.
    It records applied actions/setpoints and takes scripted feed frames.
    """

    def __init__(self, *, continuous: tuple[str, ...] = ()) -> None:
        self._frames: asyncio.Queue[FeedFrame] = asyncio.Queue()
        self.opened = False
        self.closed = False
        self.actions: list[tuple[str, dict[str, Any]]] = []
        self.setpoints: list[dict[str, float]] = []
        self._continuous = tuple(continuous)

    def capabilities(self) -> EmbodimentCapabilities:
        return EmbodimentCapabilities(
            name="fake",
            transitional=False,
            feed_events={
                "chat": ("mundus.chat", 0.6),
                "proprio": ("mundus.proprio", 0.3),
                "entity": ("mundus.entity", 0.2),
                "frame": ("mundus.visual.raw", 0.1),
            },
            action_families={"say": True, "gesture": True, "teleport": False},
            continuous_channels=self._continuous,
            raw_buffer_keys=("data",),
        )

    def push_frame(self, frame: FeedFrame) -> None:
        self._frames.put_nowait(frame)

    async def open(self) -> None:
        self.opened = True

    async def close(self) -> None:
        self.closed = True

    async def feed(self) -> AsyncIterator[FeedFrame]:
        while True:
            yield await self._frames.get()

    async def apply_action(self, family: str, params: dict[str, Any]) -> bool:
        self.actions.append((family, dict(params)))
        return True

    async def apply_setpoints(self, channels: dict[str, float]) -> bool:
        if not self._continuous:
            return False  # symbolic-only body: no continuous sink
        self.setpoints.append(dict(channels))
        return True


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus

    client = fakeredis.FakeRedis(decode_responses=True)
    yield AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    await client.aclose()


async def _wait_event(bus, stream: str, etype: str, timeout: float = 3.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        for _id, ev in await bus.read(stream, last_id="0", count=50, block_ms=100):
            if ev.type == etype:
                return ev
        await asyncio.sleep(0.05)
    raise AssertionError(f"event {etype} never appeared on {stream}")


# ---- gating: config + operator approval -----------------------------------
@pytest.mark.asyncio
async def test_disabled_is_noop(bus, monkeypatch):
    monkeypatch.delenv("KAINE_MUNDUS_OPERATOR_APPROVED", raising=False)
    # config on but env approval missing → still gated off; adapter never opened.
    adapter = FakeAdapter()
    m = Mundus(bus, adapter=adapter, enabled=True)
    await m.initialize()
    assert adapter.opened is False
    await m.shutdown()


# ---- perception: body → bus (mapping, raw-strip, salience policy) ----------
@pytest.mark.asyncio
async def test_feed_maps_through_descriptor(bus, monkeypatch):
    """The core pumps the adapter's feed and maps kinds via the descriptor,
    generically (no body-specific knowledge)."""
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    adapter = FakeAdapter()
    m = Mundus(bus, adapter=adapter, enabled=True, mirror_speech=False,
               locus_reader=lambda: "virtual")
    await m.initialize()
    try:
        adapter.push_frame(FeedFrame(kind="chat", payload={"message": "yo"}))
        ev = await _wait_event(bus, "mundus.out", "mundus.chat")
        assert ev.payload["message"] == "yo"
    finally:
        await m.shutdown()


@pytest.mark.asyncio
async def test_raw_buffer_stripped_before_bus(bus, monkeypatch):
    """Raw-sense buffers named by the descriptor never reach the bus/disk."""
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    adapter = FakeAdapter()
    m = Mundus(bus, adapter=adapter, enabled=True, mirror_speech=False,
               locus_reader=lambda: "virtual")
    await m.initialize()
    try:
        adapter.push_frame(FeedFrame(
            kind="frame",
            payload={"w": 224, "h": 224, "encoding": "rgb8", "seq": 1,
                     "data": b"\x00" * 16}))
        ev = await _wait_event(bus, "mundus.out", "mundus.visual.raw")
        assert ev.payload["w"] == 224
        assert "data" not in ev.payload
    finally:
        await m.shutdown()


@pytest.mark.asyncio
async def test_salience_policy_bumps_notable_events(bus, monkeypatch):
    """Core-owned salience policy raises the baseline for notable feed content."""
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    adapter = FakeAdapter()
    m = Mundus(bus, adapter=adapter, enabled=True, mirror_speech=False,
               locus_reader=lambda: "virtual")
    await m.initialize()
    try:
        adapter.push_frame(FeedFrame(kind="proprio", payload={"dying": True}))
        ev = await _wait_event(bus, "mundus.out", "mundus.proprio")
        assert ev.salience == pytest.approx(0.8)  # bumped from baseline 0.3

        adapter.push_frame(FeedFrame(kind="entity", payload={"arrived": ["a"]}))
        ev = await _wait_event(bus, "mundus.out", "mundus.entity")
        assert ev.salience == pytest.approx(0.5)  # bumped from baseline 0.2
    finally:
        await m.shutdown()


# ---- action: bus → body (gated by locus + exposure) ------------------------
@pytest.mark.asyncio
async def test_intent_and_speech_reach_the_body(bus, monkeypatch):
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    adapter = FakeAdapter()
    m = Mundus(bus, adapter=adapter, enabled=True, mirror_speech=True,
               speech_stream="linguatest.out", locus_reader=lambda: "virtual")
    await m.initialize()
    try:
        # intent.avatar.say → symbolic action on the body
        await bus.publish(validate_event(
            source="volition", type="intent.avatar.say",
            payload={"message": "hi there", "channel": 0}, salience=0.5,
            timestamp=datetime.now(timezone.utc)))
        # mirrored external speech → avatar say
        await bus.publish(validate_event(
            source="linguatest", type="lingua.external",
            payload={"text": "spoken aloud"}, salience=0.4,
            timestamp=datetime.now(timezone.utc)))

        deadline = asyncio.get_event_loop().time() + 3.0
        while len(adapter.actions) < 2 and asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(0.05)
        assert ("say", {"message": "hi there", "channel": 0}) in adapter.actions
        assert ("say", {"message": "spoken aloud", "channel": 0}) in adapter.actions
    finally:
        await m.shutdown()


@pytest.mark.asyncio
async def test_physical_locus_blocks_avatar_actions(bus, monkeypatch):
    """perception_locus: in `physical` the entity isn't embodied in the world, so
    no avatar action is forwarded even for an exposed family."""
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    adapter = FakeAdapter()
    m = Mundus(bus, adapter=adapter, enabled=True, mirror_speech=False,
               locus_reader=lambda: "physical")
    await m.initialize()
    try:
        await bus.publish(validate_event(
            source="volition", type="intent.avatar.say",
            payload={"message": "should not reach the body"}, salience=0.5,
            timestamp=datetime.now(timezone.utc)))
        await asyncio.sleep(0.5)
        assert adapter.actions == []
    finally:
        await m.shutdown()


@pytest.mark.asyncio
async def test_unexposed_action_is_dropped(bus, monkeypatch):
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    adapter = FakeAdapter()  # teleport defaults NOT exposed
    m = Mundus(bus, adapter=adapter, enabled=True, mirror_speech=False,
               locus_reader=lambda: "virtual")
    await m.initialize()
    try:
        await bus.publish(validate_event(
            source="volition", type="intent.avatar.teleport",
            payload={"region": "Welcome", "x": 128, "y": 128, "z": 25},
            salience=0.5, timestamp=datetime.now(timezone.utc)))
        await asyncio.sleep(0.5)
        assert adapter.actions == []
    finally:
        await m.shutdown()


# ---- capability descriptor validation --------------------------------------
def test_capabilities_descriptor_is_frozen_and_validated():
    caps = StubAdapter().capabilities()
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


# ---- continuous-setpoint path (stub body exercises it) ---------------------
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
    m = Mundus(bus, adapter=FakeAdapter(continuous=()),
               enabled=True, locus_reader=lambda: "virtual")
    ok = await m.apply_setpoints({"drive": 0.5})
    assert ok is False


# ---- state serialization ---------------------------------------------------
@pytest.mark.asyncio
async def test_serialize_deserialize_roundtrips_cursors(bus):
    m = Mundus(bus, adapter=StubAdapter(), enabled=True)
    m._intent_cursor = "10-0"
    m._speech_cursor = "20-3"
    state = m.serialize()
    assert state == {"intent_cursor": "10-0", "speech_cursor": "20-3"}

    m2 = Mundus(bus, adapter=StubAdapter(), enabled=True)
    m2.deserialize(state)
    assert m2._intent_cursor == "10-0"
    assert m2._speech_cursor == "20-3"
