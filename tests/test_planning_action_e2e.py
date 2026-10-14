# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""End-to-end test for planning-driven action through the action selection and language modules."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.engine import CognitiveCycle
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.language import (
    EXTERNAL_STREAM,
    INTERNAL_STREAM,
    FakeChatClient,
    IntentExpressionLog,
    Language,
)
from kaine.workspace.action_selection import ActionSelection
from kaine.workspace.planning_proposals import PlanningProposalSource


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _event(
    source: str, type_: str, payload: dict | None = None, salience: float = 0.5
) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload or {},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _interoception_report(value: float = 0.5) -> tuple[str, Event]:
    return ("s1", _event("interoception", "interoception.report", {"wellness": value}))


def _proposal(
    proposal_id: str, kind: str, *, action: str = "noop", preference: float = 0.5
) -> tuple[str, Event]:
    return (
        "p-" + proposal_id,
        _event(
            "planning",
            "planning.proposal",
            {
                "proposal_id": proposal_id,
                "action": action,
                "kind": kind,
                "step": 1,
                "preference": preference,
            },
        ),
    )


def _snapshot(events, *, inhibited: bool = False) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=list(events),
        inhibited=inhibited,
        is_experiential=True,
    )


def _make_language(bus: AsyncBus, tmp_path: Path, responses=None) -> Language:
    return Language(
        bus,
        chat_client=FakeChatClient(responses=responses),
        intent_log=IntentExpressionLog(tmp_path / "intent.jsonl"),
        model_id="fake-model",
    )


async def _wait_for_events(
    bus: AsyncBus, stream: str, *, timeout_s: float = 2.0
) -> list[Event]:
    deadline = asyncio.get_event_loop().time() + timeout_s
    while asyncio.get_event_loop().time() < deadline:
        events = [e for _, e in await bus.read(stream, last_id="0")]
        if events:
            return events
        await asyncio.sleep(0.02)
    return [e for _, e in await bus.read(stream, last_id="0")]


class _Cycle:
    _tick_index = 1

    def __init__(self, bus: AsyncBus, action_selection: ActionSelection) -> None:
        self._action_selection = action_selection
        self._bus = bus

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_planning_proposal_drives_intent_and_internal_speech(
    bus: AsyncBus, tmp_path: Path
):
    action_selection = ActionSelection(policy=PlanningProposalSource(lambda s: []))
    snap = _snapshot([_proposal("p1", "think"), _interoception_report()], inhibited=False)
    cycle = _Cycle(bus, action_selection)

    await CognitiveCycle._run_action_selection(cycle, snap)

    action_selection_events = [e for _, e in await bus.read("action_selection.out", last_id="0")]
    think_events = [e for e in action_selection_events if e.type == "intent.think"]
    assert len(think_events) == 1
    think_event = think_events[0]
    assert think_event.source == "action_selection"
    assert think_event.payload.get("origin") == "planning"

    feedback_events = [
        e
        for _, e in await bus.read("action_selection_feedback.out", last_id="0")
        if e.type == "action_selection.proposal_outcome"
    ]
    assert len(feedback_events) == 1
    assert feedback_events[0].payload.get("realized") is True

    language = _make_language(bus, tmp_path, responses=["internal thought"])
    await language._dispatch_intent(think_event)

    internal = await _wait_for_events(bus, INTERNAL_STREAM)
    external = await _wait_for_events(bus, EXTERNAL_STREAM)
    assert len(internal) == 1
    assert internal[0].type == "internal_speech"
    assert internal[0].source == "language"
    assert len(external) == 0


@pytest.mark.asyncio
async def test_inhibited_planning_proposal_publishes_no_intent_and_inhibited_outcome(
    bus: AsyncBus,
):
    action_selection = ActionSelection(policy=PlanningProposalSource(lambda s: []))
    snap = _snapshot([_proposal("p1", "think"), _interoception_report()], inhibited=True)
    cycle = _Cycle(bus, action_selection)

    await CognitiveCycle._run_action_selection(cycle, snap)

    action_selection_events = [e for _, e in await bus.read("action_selection.out", last_id="0")]
    assert action_selection_events == []

    feedback_events = [
        e
        for _, e in await bus.read("action_selection_feedback.out", last_id="0")
        if e.type == "action_selection.proposal_outcome"
    ]
    assert len(feedback_events) == 1
    assert feedback_events[0].source == "action_selection_feedback"
    assert feedback_events[0].payload.get("proposal_id") == "p1"
    assert feedback_events[0].payload.get("realized") is False
    assert feedback_events[0].payload.get("reason") == "inhibited"
