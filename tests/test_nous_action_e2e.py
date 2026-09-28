# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""End-to-end test for Nous-driven action through Volition and Lingua."""

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
from kaine.modules.lingua import (
    EXTERNAL_STREAM,
    INTERNAL_STREAM,
    FakeChatClient,
    IntentExpressionLog,
    Lingua,
)
from kaine.workspace.nous_proposals import NousProposalSource
from kaine.workspace.volition import Volition


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


def _soma_report(value: float = 0.5) -> tuple[str, Event]:
    return ("s1", _event("soma", "soma.report", {"wellness": value}))


def _proposal(
    proposal_id: str, kind: str, *, action: str = "noop", preference: float = 0.5
) -> tuple[str, Event]:
    return (
        "p-" + proposal_id,
        _event(
            "nous",
            "nous.proposal",
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


def _make_lingua(bus: AsyncBus, tmp_path: Path, responses=None) -> Lingua:
    return Lingua(
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

    def __init__(self, bus: AsyncBus, volition: Volition) -> None:
        self._volition = volition
        self._bus = bus

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_nous_proposal_drives_intent_and_internal_speech(
    bus: AsyncBus, tmp_path: Path
):
    volition = Volition(policy=NousProposalSource(lambda s: []))
    snap = _snapshot([_proposal("p1", "think"), _soma_report()], inhibited=False)
    cycle = _Cycle(bus, volition)

    await CognitiveCycle._run_volition(cycle, snap)

    volition_events = [e for _, e in await bus.read("volition.out", last_id="0")]
    think_events = [e for e in volition_events if e.type == "intent.think"]
    assert len(think_events) == 1
    think_event = think_events[0]
    assert think_event.source == "volition"
    assert think_event.payload.get("origin") == "nous"

    feedback_events = [
        e
        for _, e in await bus.read("volition_feedback.out", last_id="0")
        if e.type == "volition.proposal_outcome"
    ]
    assert len(feedback_events) == 1
    assert feedback_events[0].payload.get("realized") is True

    lingua = _make_lingua(bus, tmp_path, responses=["internal thought"])
    await lingua._dispatch_intent(think_event)

    internal = await _wait_for_events(bus, INTERNAL_STREAM)
    external = await _wait_for_events(bus, EXTERNAL_STREAM)
    assert len(internal) == 1
    assert internal[0].type == "internal_speech"
    assert internal[0].source == "lingua"
    assert len(external) == 0


@pytest.mark.asyncio
async def test_inhibited_nous_proposal_publishes_no_intent_and_inhibited_outcome(
    bus: AsyncBus,
):
    volition = Volition(policy=NousProposalSource(lambda s: []))
    snap = _snapshot([_proposal("p1", "think"), _soma_report()], inhibited=True)
    cycle = _Cycle(bus, volition)

    await CognitiveCycle._run_volition(cycle, snap)

    volition_events = [e for _, e in await bus.read("volition.out", last_id="0")]
    assert volition_events == []

    feedback_events = [
        e
        for _, e in await bus.read("volition_feedback.out", last_id="0")
        if e.type == "volition.proposal_outcome"
    ]
    assert len(feedback_events) == 1
    assert feedback_events[0].source == "volition_feedback"
    assert feedback_events[0].payload.get("proposal_id") == "p1"
    assert feedback_events[0].payload.get("realized") is False
    assert feedback_events[0].payload.get("reason") == "inhibited"
