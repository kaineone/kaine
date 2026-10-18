# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.affect import Affect
from kaine.workspace.action_selection import THINK
from kaine.workspace.drive_policy import DriveBiasedActionSelectionPolicy
from kaine.workspace.report_policy import SelfInitiatedReportPolicy


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _event(source, type_, payload):
    return Event(source=source, type=type_, payload=payload, salience=0.5, timestamp=datetime.now(timezone.utc))


def _as_bus_event(intent):
    # What the action selection module publishes on action_selection.out.
    return _event("action_selection", f"intent.{intent.kind}", intent.to_event_payload())


def _report_policy():
    clock = lambda: 0.0  # noqa: E731
    return SelfInitiatedReportPolicy(report_threshold=0.6, think_threshold=0.45, speak_refractory_s=8.0, think_refractory_s=3.0, clock=clock, guard_clock=clock, about_style="felt")


async def _bored(affect, t):
    # Fire a boredom crossing so the drive has an open crossing to end.
    affect.drives.boredom.value = 0.75
    await affect._tick()
    assert affect.drives.boredom._has_fired
    t[0] += 0.1


async def test_felt_event_led_think_relieves_boredom_as_own(bus):
    t = [0.0]
    policy = _report_policy()
    snapshot = WorkspaceSnapshot(
        tick_index=1,
        selected_events=[
            ("vision.out:5-0", _event("vision", "vision.report", {"change_score": 0.0004}))
        ],
        salience_scores={"vision.out:5-0": 0.5},
    )
    intents = policy(snapshot)
    assert len(intents) == 1
    intent = intents[0]
    assert intent.kind == THINK
    assert intent.about == "Something in what I see stands out noticeably."
    assert intent.about_kind == "event"
    assert not any(ch.isdigit() for ch in intent.about)

    affect = Affect(bus, clock=lambda: t[0])
    await _bored(affect, t)
    before = affect.drives.boredom.value
    await affect._handle_peer_event("action_selection.out", _as_bus_event(intent))
    assert affect.drives.boredom.value == pytest.approx(before * 0.5)
    assert affect.drives.boredom.own_ends == 1
    assert affect.drives.boredom.other_ends == 0


async def test_drive_phrase_intent_does_not_relieve_boredom(bus):
    t = [0.0]
    policy = DriveBiasedActionSelectionPolicy()
    snapshot = WorkspaceSnapshot(
        tick_index=1,
        selected_events=[
            ("affect.out:7-0", _event("affect", "affect.drive", {"drive": "curiosity", "value": 0.7}))
        ],
        salience_scores={"affect.out:7-0": 0.6},
    )
    intents = policy(snapshot)
    assert len(intents) == 1
    intent = intents[0]
    assert intent.kind == THINK
    assert intent.about_kind == "felt"
    assert intent.about == "I feel curious."

    affect = Affect(bus, clock=lambda: t[0])
    affect.drives.boredom.value = 0.5
    await affect._handle_peer_event("action_selection.out", _as_bus_event(intent))
    assert affect.drives.boredom.value == 0.5


async def test_event_led_intent_about_a_drive_crossing_does_not_relieve_boredom(bus):
    t = [0.0]
    affect = Affect(bus, clock=lambda: t[0])
    await _bored(affect, t)

    entries = await bus.read("affect.out", last_id="0", count=200)
    eid = [e_id for e_id, e in entries if e.type == "affect.drive"][-1]

    policy = _report_policy()
    snapshot = WorkspaceSnapshot(
        tick_index=1,
        selected_events=[
            (f"affect.out:{eid}", _event("affect", "affect.drive", {"drive": "boredom", "value": 0.75}))
        ],
        salience_scores={f"affect.out:{eid}": 0.5},
    )
    intents = policy(snapshot)
    assert len(intents) == 1
    intent = intents[0]
    assert intent.kind == THINK
    assert intent.about_kind == "event"
    assert intent.entry_id == f"affect.out:{eid}"

    before = affect.drives.boredom.value
    await affect._handle_peer_event("action_selection.out", _as_bus_event(intent))
    assert affect.drives.boredom.value == pytest.approx(before)
    assert affect.drives.boredom.own_ends == 0
