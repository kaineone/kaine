# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import json
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.chronos.module import Chronos


class FakeNetwork:
    """Returns a constant hidden state of the requested size."""

    def __init__(self, units: int = 8, value: float = 0.5) -> None:
        self.units = units
        self.value = value
        self.calls: list[list[float]] = []

    def tick(self, feature_vec: list[float]) -> list[float]:
        self.calls.append(list(feature_vec))
        return [self.value] * self.units


def _empty_snapshot(tick: int = 0) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=tick, selected_events=[], inhibited=False)


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _xadd_fields(
    etype: str,
    source_label: str | None = None,
    text: str | None = None,
) -> dict:
    payload: dict = {}
    if source_label is not None:
        payload["source_label"] = source_label
    if text is not None:
        payload["text"] = text
    return {
        "source": "audition",
        "type": etype,
        "salience": "0.5",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "causal_parent": "",
        "payload": json.dumps(payload),
    }


async def _wait_for_cursor(
    chronos: Chronos, stream: str, target_id: str, timeout: float = 2.0
) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while chronos._user_input_cursors.get(stream) != target_id:
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(f"cursor did not reach {target_id}")
        await asyncio.sleep(0.05)


async def _wait_for_condition(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("condition did not become true")
        await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_audition_perception_from_live_mic_does_not_reset(bus: AsyncBus):
    now = {"v": 1000.0}
    chronos = Chronos(
        bus,
        network=FakeNetwork(),
        user_input_streams=("audition.out",),
        clock=lambda: now["v"],
    )
    await chronos.initialize()
    try:
        await bus.client.xadd(
            "audition.out",
            _xadd_fields("audition.perception", source_label="live_mic"),
        )
        id2 = await bus.client.xadd(
            "audition.out",
            _xadd_fields("audition.perception", source_label="live_mic"),
        )
        await _wait_for_cursor(chronos, "audition.out", id2)
        assert chronos._last_interaction_at is None
        assert chronos._user_input_cursors["audition.out"] == id2
    finally:
        await chronos.shutdown()


@pytest.mark.asyncio
async def test_audition_emotion_from_playlist_does_not_reset(bus: AsyncBus):
    now = {"v": 1000.0}
    chronos = Chronos(
        bus,
        network=FakeNetwork(),
        user_input_streams=("audition.out",),
        clock=lambda: now["v"],
    )
    await chronos.initialize()
    try:
        await bus.client.xadd(
            "audition.out",
            _xadd_fields("audition.emotion", source_label="playlist"),
        )
        id2 = await bus.client.xadd(
            "audition.out",
            _xadd_fields("audition.perception", source_label="playlist"),
        )
        await _wait_for_cursor(chronos, "audition.out", id2)
        assert chronos._last_interaction_at is None
        assert chronos._user_input_cursors["audition.out"] == id2
    finally:
        await chronos.shutdown()


@pytest.mark.asyncio
async def test_audition_emotion_from_live_mic_with_error_resets(bus: AsyncBus):
    now = {"v": 1000.0}
    chronos = Chronos(
        bus,
        network=FakeNetwork(),
        user_input_streams=("audition.out",),
        clock=lambda: now["v"],
    )
    await chronos.initialize()
    try:
        fields = _xadd_fields("audition.emotion", source_label="live_mic")
        fields["payload"] = json.dumps(
            {"source_label": "live_mic", "error": "transient"}
        )
        id1 = await bus.client.xadd("audition.out", fields)
        await _wait_for_condition(lambda: chronos._last_interaction_at is not None)
        assert chronos._last_interaction_at == pytest.approx(1000.0)
        assert chronos._user_input_cursors["audition.out"] == id1
    finally:
        await chronos.shutdown()


@pytest.mark.asyncio
async def test_empty_transcription_from_live_mic_does_not_reset(bus: AsyncBus):
    now = {"v": 1000.0}
    chronos = Chronos(
        bus,
        network=FakeNetwork(),
        user_input_streams=("audition.out",),
        clock=lambda: now["v"],
    )
    await chronos.initialize()
    try:
        await bus.client.xadd(
            "audition.out",
            _xadd_fields("audition.transcription", source_label="live_mic", text="   "),
        )
        id2 = await bus.client.xadd(
            "audition.out",
            _xadd_fields("audition.perception", source_label="live_mic"),
        )
        await _wait_for_cursor(chronos, "audition.out", id2)
        assert chronos._last_interaction_at is None
        assert chronos._user_input_cursors["audition.out"] == id2
    finally:
        await chronos.shutdown()


@pytest.mark.asyncio
async def test_transcription_from_remote_resets(bus: AsyncBus):
    now = {"v": 1000.0}
    chronos = Chronos(
        bus,
        network=FakeNetwork(),
        user_input_streams=("audition.out",),
        clock=lambda: now["v"],
    )
    await chronos.initialize()
    try:
        id1 = await bus.client.xadd(
            "audition.out",
            _xadd_fields(
                "audition.transcription", source_label="remote", text="hello"
            ),
        )
        await _wait_for_condition(lambda: chronos._last_interaction_at is not None)
        assert chronos._last_interaction_at == pytest.approx(1000.0)
        assert chronos._user_input_cursors["audition.out"] == id1
        now["v"] = 1002.0
        await chronos.on_workspace(_empty_snapshot())
        entries = await bus.read("chronos.out", last_id="0")
        _, event = entries[0]
        assert event.payload["time_since_last_interaction_s"] == pytest.approx(2.0)
    finally:
        await chronos.shutdown()
