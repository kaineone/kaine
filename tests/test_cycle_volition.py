# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The cognitive cycle invokes Volition after the experiential broadcast and
publishes intents to volition.out, gated by inhibition."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle import CognitiveCycle
from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.volition import VOLITION_STREAM, Volition
from tests._fakes import FakeClock, FakeRegistry


class _ScriptedSyneidesis:
    """Returns a fixed snapshot each tick (selected events + inhibition flag)."""

    def __init__(self, *, selected, inhibited: bool) -> None:
        self._selected = list(selected)
        self._inhibited = inhibited

    async def select(self, events, context) -> WorkspaceSnapshot:
        return WorkspaceSnapshot(
            tick_index=context.get("tick_index", 0),
            selected_events=list(self._selected),
            inhibited=self._inhibited,
            is_experiential=bool(context.get("is_experiential")),
        )


def _transcription_event() -> tuple[str, Event]:
    return ("e1", Event(
        source="audition",
        type="audition.transcription",
        payload={"text": "hello kaine"},
        salience=0.6,
        timestamp=datetime.now(timezone.utc),
    ))


async def _make_bus() -> AsyncBus:
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client)


@pytest.mark.asyncio
async def test_inhibited_snapshot_publishes_no_intent():
    bus = await _make_bus()
    try:
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=_ScriptedSyneidesis(
                selected=[_transcription_event()], inhibited=True
            ),
            registry=FakeRegistry([]),
            volition=Volition(),
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        await cycle.tick()  # tick 0 is experiential at default equal rates
        entries = await bus.read(VOLITION_STREAM, last_id="0")
        assert entries == []
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_non_inhibited_disposed_snapshot_publishes_speak_intent():
    bus = await _make_bus()
    try:
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=_ScriptedSyneidesis(
                selected=[_transcription_event()], inhibited=False
            ),
            registry=FakeRegistry([]),
            volition=Volition(),
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        await cycle.tick()
        entries = await bus.read(VOLITION_STREAM, last_id="0")
        assert len(entries) == 1
        _, event = entries[0]
        assert event.source == "volition"
        assert event.type == "intent.speak"
        assert event.payload["kind"] == "speak"
        assert event.payload["about"] == "hello kaine"
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_volition_not_run_on_non_experiential_tick():
    bus = await _make_bus()
    try:
        # processing 10Hz, experiential 2Hz → most ticks are non-experiential.
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=_ScriptedSyneidesis(
                selected=[_transcription_event()], inhibited=False
            ),
            registry=FakeRegistry([]),
            volition=Volition(),
            processing_rate_hz=10.0,
            experiential_rate_hz=2.0,
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        experiential = 0
        for _ in range(10):
            if (await cycle.tick()).is_experiential:
                experiential += 1
        # Default policy's one-in-flight guard means at most one intent even
        # across multiple experiential ticks (no realization observed). Key
        # assertion: intents only ever come from experiential ticks, never more
        # than the number of experiential broadcasts.
        entries = await bus.read(VOLITION_STREAM, last_id="0")
        assert experiential >= 1
        assert 0 < len(entries) <= experiential
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_no_volition_means_no_intents():
    bus = await _make_bus()
    try:
        cycle = CognitiveCycle(
            bus=bus,
            syneidesis=_ScriptedSyneidesis(
                selected=[_transcription_event()], inhibited=False
            ),
            registry=FakeRegistry([]),
            volition=None,
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        await cycle.tick()
        entries = await bus.read(VOLITION_STREAM, last_id="0")
        assert entries == []
    finally:
        await bus.close()
