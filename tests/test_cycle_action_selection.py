# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The cognitive cycle invokes the action selection module after the experiential broadcast and
publishes intents to action_selection.out, gated by inhibition."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle import CognitiveCycle
from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.action_selection import ACTION_SELECTION_STREAM, ActionSelection
from kaine.workspace.report_policy import SelfInitiatedReportPolicy
from tests._fakes import FakeClock, FakeRegistry


class _ScriptedWorkspace:
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
            workspace=_ScriptedWorkspace(
                selected=[_transcription_event()], inhibited=True
            ),
            registry=FakeRegistry([]),
            action_selection=ActionSelection(),
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        await cycle.tick()  # tick 0 is experiential at default equal rates
        entries = await bus.read(ACTION_SELECTION_STREAM, last_id="0")
        assert entries == []
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_non_inhibited_disposed_snapshot_publishes_speak_intent():
    bus = await _make_bus()
    try:
        cycle = CognitiveCycle(
            bus=bus,
            workspace=_ScriptedWorkspace(
                selected=[_transcription_event()], inhibited=False
            ),
            registry=FakeRegistry([]),
            action_selection=ActionSelection(),
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        await cycle.tick()
        entries = await bus.read(ACTION_SELECTION_STREAM, last_id="0")
        assert len(entries) == 1
        _, event = entries[0]
        assert event.source == "action_selection"
        assert event.type == "intent.speak"
        assert event.payload["kind"] == "speak"
        assert event.payload["about"] == "hello kaine"
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_action_selection_not_run_on_non_experiential_tick():
    bus = await _make_bus()
    try:
        # processing 10Hz, experiential 2Hz → most ticks are non-experiential.
        cycle = CognitiveCycle(
            bus=bus,
            workspace=_ScriptedWorkspace(
                selected=[_transcription_event()], inhibited=False
            ),
            registry=FakeRegistry([]),
            action_selection=ActionSelection(),
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
        entries = await bus.read(ACTION_SELECTION_STREAM, last_id="0")
        assert experiential >= 1
        assert 0 < len(entries) <= experiential
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_no_action_selection_means_no_intents():
    bus = await _make_bus()
    try:
        cycle = CognitiveCycle(
            bus=bus,
            workspace=_ScriptedWorkspace(
                selected=[_transcription_event()], inhibited=False
            ),
            registry=FakeRegistry([]),
            action_selection=None,
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        await cycle.tick()
        entries = await bus.read(ACTION_SELECTION_STREAM, last_id="0")
        assert entries == []
    finally:
        await bus.close()


class _ScoredWorkspace:
    """Returns a fixed snapshot each tick and records the candidate events it saw."""

    def __init__(self, *, selected) -> None:
        self._selected = list(selected)
        self.seen: list[list[tuple[str, Event]]] = []

    def set_selected(self, selected) -> None:
        self._selected = list(selected)

    async def select(self, events, context) -> WorkspaceSnapshot:
        self.seen.append(list(events))
        return WorkspaceSnapshot(
            tick_index=context.get("tick_index", 0),
            selected_events=list(self._selected),
            inhibited=False,
            is_experiential=bool(context.get("is_experiential")),
            salience_scores={entry_id: ev.salience for entry_id, ev in self._selected},
            metadata={},
        )


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def _drive_event(entry_id: str) -> tuple[str, Event]:
    return (entry_id, Event(
        source="affect",
        type="affect.drive",
        payload={"drive": "curiosity", "value": 0.8},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    ))


def _report_selection(sub: _Clock, wall: _Clock) -> ActionSelection:
    return ActionSelection(policy=SelfInitiatedReportPolicy(
        report_threshold=0.6,
        think_threshold=0.45,
        speak_refractory_s=8.0,
        think_refractory_s=3.0,
        clock=sub,
        guard_clock=wall,
    ))


@pytest.mark.asyncio
async def test_unaccessed_internal_speech_releases_think_guard():
    bus = await _make_bus()
    try:
        sub = _Clock()
        wall = _Clock()
        workspace = _ScoredWorkspace(selected=[_drive_event("d1")])
        cycle = CognitiveCycle(
            bus=bus,
            workspace=workspace,
            registry=FakeRegistry(["language.out"]),
            action_selection=_report_selection(sub, wall),
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        await cycle.tick()
        entries = await bus.read(ACTION_SELECTION_STREAM, last_id="0")
        assert len(entries) == 1
        assert entries[0][1].type == "intent.think"

        sub.advance(5.0)
        wall.advance(5.0)
        await bus.publish(Event(
            source="language",
            type="internal_speech",
            payload={"text": "a thought", "mode": "internal"},
            salience=0.4,
            timestamp=datetime.now(timezone.utc),
        ))
        await cycle.tick()
        entries = await bus.read(ACTION_SELECTION_STREAM, last_id="0")
        assert len(entries) == 2
        assert all(event.type == "intent.think" for _, event in entries)
        assert any(
            event.type == "internal_speech"
            for _, event in workspace.seen[1]
        )
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_think_guard_holds_without_own_output():
    bus = await _make_bus()
    try:
        sub = _Clock()
        wall = _Clock()
        workspace = _ScoredWorkspace(selected=[_drive_event("d1")])
        cycle = CognitiveCycle(
            bus=bus,
            workspace=workspace,
            registry=FakeRegistry(["language.out"]),
            action_selection=_report_selection(sub, wall),
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        await cycle.tick()
        sub.advance(5.0)
        wall.advance(5.0)
        await cycle.tick()
        entries = await bus.read(ACTION_SELECTION_STREAM, last_id="0")
        assert len(entries) == 1
        assert entries[0][1].type == "intent.think"
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_internal_speech_does_not_release_speak_guard():
    bus = await _make_bus()
    try:
        sub = _Clock()
        wall = _Clock()
        workspace = _ScoredWorkspace(selected=[("a1", Event(
            source="audition",
            type="audition.alert",
            payload={"level": 0.8},
            salience=0.7,
            timestamp=datetime.now(timezone.utc),
        ))])
        cycle = CognitiveCycle(
            bus=bus,
            workspace=workspace,
            registry=FakeRegistry(["language.out"]),
            action_selection=_report_selection(sub, wall),
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        await cycle.tick()
        entries = await bus.read(ACTION_SELECTION_STREAM, last_id="0")
        assert len(entries) == 1
        assert entries[0][1].type == "intent.speak"

        sub.advance(10.0)
        wall.advance(10.0)
        await bus.publish(Event(
            source="language",
            type="internal_speech",
            payload={"text": "a thought", "mode": "internal"},
            salience=0.4,
            timestamp=datetime.now(timezone.utc),
        ))
        workspace.set_selected([("v1", Event(
            source="vision",
            type="vision.alert",
            payload={"level": 0.8},
            salience=0.7,
            timestamp=datetime.now(timezone.utc),
        ))])
        await cycle.tick()
        entries = await bus.read(ACTION_SELECTION_STREAM, last_id="0")
        assert len(entries) == 2
        assert entries[1][1].type == "intent.think"
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_unaccessed_external_speech_releases_speak_guard():
    bus = await _make_bus()
    try:
        sub = _Clock()
        wall = _Clock()
        workspace = _ScoredWorkspace(selected=[("a1", Event(
            source="audition",
            type="audition.alert",
            payload={"level": 0.8},
            salience=0.7,
            timestamp=datetime.now(timezone.utc),
        ))])
        cycle = CognitiveCycle(
            bus=bus,
            workspace=workspace,
            registry=FakeRegistry(["language.out"]),
            action_selection=_report_selection(sub, wall),
            clock=FakeClock(),
            sleep=FakeClock().sleep,
        )
        await cycle.tick()
        entries = await bus.read(ACTION_SELECTION_STREAM, last_id="0")
        assert len(entries) == 1
        assert entries[0][1].type == "intent.speak"

        sub.advance(10.0)
        wall.advance(10.0)
        await bus.publish(Event(
            source="language",
            type="external_speech",
            payload={"text": "I said this", "mode": "external"},
            salience=0.4,
            timestamp=datetime.now(timezone.utc),
        ))
        workspace.set_selected([("v1", Event(
            source="vision",
            type="vision.alert",
            payload={"level": 0.8},
            salience=0.7,
            timestamp=datetime.now(timezone.utc),
        ))])
        await cycle.tick()
        entries = await bus.read(ACTION_SELECTION_STREAM, last_id="0")
        assert len(entries) == 2
        assert entries[1][1].type == "intent.speak"
    finally:
        await bus.close()
