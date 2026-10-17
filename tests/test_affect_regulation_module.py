# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.boot.errors import ConfigurationError
from kaine.boot.factories.affect import make_affect
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.affect import Affect
from kaine.modules.affect.appraisal import CategoricalEmotion
from kaine.modules.affect.regulation import (
    PassiveDecay,
    RegulationConfig,
    ThreeTierRegulation,
)
from kaine.modules.affect.state import DimensionalState
from kaine.workspace.strategies import dominant_drive


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _snapshot(events=None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=0, selected_events=events or [], inhibited=False)


def _ev(source="interoception", type_="t", salience=0.5, eid="e0", **payload):
    return eid, Event(
        source=source,
        type=type_,
        payload=payload or {"k": "v"},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _pleasantness_value(negative: bool) -> float:
    return -0.4 if negative else 0.2


async def _drive(affect, t, seconds, *, valence=-0.8, negative=True):
    affect._pleasantness = lambda g: _pleasantness_value(negative)
    for _ in range(seconds):
        t[0] += 1.0
        affect._state = DimensionalState(
            valence=valence,
            arousal=affect.state.arousal,
            dominance=affect.state.dominance,
        )
        await affect.on_workspace(
            _snapshot(
                [
                    _ev("vision", salience=0.7, eid="v"),
                    _ev("audition", salience=0.3, eid="a"),
                ]
            )
        )


async def _reg_events(bus):
    entries = await bus.read("affect.out", last_id="0", count=500)
    events = []
    for e in entries:
        if isinstance(e, tuple):
            e = e[1]
        if getattr(e, "type", None) == "affect.regulation":
            events.append(e)
    return events


async def _emotion_events(bus):
    entries = await bus.read("affect.out", last_id="0", count=500)
    events = []
    for e in entries:
        if isinstance(e, tuple):
            e = e[1]
        if getattr(e, "type", None) == "affect.emotion":
            events.append(e)
    return events


@pytest.mark.asyncio
async def test_below_set_point_no_regulation():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    cfg = RegulationConfig()
    buses = []
    affects = []
    t = [0.0]
    for _ in range(2):
        client = fakeredis.FakeRedis(decode_responses=True)
        b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
        buses.append(b)
        regulation = ThreeTierRegulation(cfg) if len(affects) == 0 else PassiveDecay()
        affects.append(
            Affect(
                b,
                clock=lambda: t[0],
                regulation=regulation,
                publish_interval_s=1000.0,
            )
        )

    for _ in range(120):
        t[0] += 1.0
        for affect in affects:
            affect._pleasantness = lambda g: -0.4
            affect._state = DimensionalState(
                valence=-0.3,
                arousal=affect.state.arousal,
                dominance=affect.state.dominance,
            )
            await affect.on_workspace(
                _snapshot(
                    [
                        _ev("vision", salience=0.7, eid="v"),
                        _ev("audition", salience=0.3, eid="a"),
                    ]
                )
            )

    for b in buses:
        assert len(await _reg_events(b)) == 0
    assert affects[0].state.to_dict() == affects[1].state.to_dict()
    for b in buses:
        await b.close()


@pytest.mark.asyncio
async def test_not_negative_no_regulation(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        regulation=ThreeTierRegulation(RegulationConfig()),
        publish_interval_s=1000.0,
    )
    await _drive(affect, t, 120, valence=-0.8, negative=False)
    assert len(await _reg_events(bus)) == 0


@pytest.mark.asyncio
async def test_escalation_tiers_one_two_three(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        regulation=ThreeTierRegulation(RegulationConfig()),
        publish_interval_s=1000.0,
    )
    await _drive(affect, t, 95, valence=-0.8, negative=True)
    events = await _reg_events(bus)
    assert len(events) == 3
    tiers = [e.payload["tier"] for e in events]
    assert tiers == [1, 2, 3]

    p1 = events[0].payload
    assert p1["action"] == "attentional_deployment"
    assert p1["source"] == "vision"
    assert p1["bias"] == pytest.approx(0.2)
    assert p1["decay_s"] == pytest.approx(20.0)
    assert p1["size"] == pytest.approx(0.2)

    p2 = events[1].payload
    assert p2["action"] == "reappraisal"
    assert "valence_before" not in p2
    assert isinstance(p2["emotion_before"], str)
    assert isinstance(p2["emotion_after"], str)
    assert p2["size"] == pytest.approx(
        1.0 if p2["emotion_before"] != p2["emotion_after"] else 0.0
    )

    p3 = events[2].payload
    assert p3["action"] == "request_maintenance"
    assert p3["size"] == pytest.approx(p3["intensity"])


@pytest.mark.asyncio
async def test_tier2_leaves_dimensions_unchanged(monkeypatch):
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    affect = Affect(
        bus,
        clock=lambda: 0.0,
        regulation=ThreeTierRegulation(RegulationConfig()),
        publish_interval_s=1000.0,
    )
    monkeypatch.setattr(affect, "_pleasantness", lambda g: -0.4)
    affect._last_pleasantness = -0.4
    affect._last_goal_score = 0.0
    affect._last_snapshot = _snapshot([_ev("vision", salience=0.7, eid="v")])
    affect._state = DimensionalState(valence=-0.8, arousal=0.55, dominance=0.0)

    affect._regulation.update(now=0.0, intensity=0.8, negative=True)
    before_state = affect.state.to_dict()
    await affect._run_regulation(60.0)
    assert affect.state.to_dict() == before_state
    events = await _reg_events(bus)
    assert len(events) == 1
    assert events[0].payload["tier"] == 2
    await bus.close()


@pytest.mark.asyncio
async def test_reappraisal_turns_fear_into_non_fear_when_coping_improves(monkeypatch):
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    affect = Affect(
        bus,
        clock=lambda: 0.0,
        regulation=ThreeTierRegulation(RegulationConfig()),
        publish_interval_s=1000.0,
    )
    affect.set_drive_relevance(
        {
            "social_drive": frozenset({"audition"}),
            "curiosity": frozenset({"vision"}),
            "boredom": frozenset(),
            "restlessness": frozenset(),
        },
        dominant_drive,
    )
    monkeypatch.setattr(affect, "_pleasantness", lambda g: -0.4)
    affect.drives.social_drive.value = 0.8
    affect.drives.social_drive._has_fired = True
    affect.drives.social_drive.own_ends = 0
    affect.drives.social_drive.other_ends = 8
    affect._state = DimensionalState(valence=-0.6, arousal=0.6, dominance=0.0)

    snap = _snapshot([_ev("audition", salience=0.9, eid="a")])
    await affect._appraise_snapshot(snap)
    assert affect.last_emotion == CategoricalEmotion.FEAR

    affect.drives.social_drive.own_ends = 8
    affect.drives.social_drive.other_ends = 0

    affect._regulation.update(now=0.0, intensity=0.8, negative=True)
    before_valence = affect.state.valence
    await affect._run_regulation(60.0)
    assert affect.state.valence == before_valence
    assert affect.last_emotion is not CategoricalEmotion.FEAR

    emotion_events = await _emotion_events(bus)
    reappraised = [e for e in emotion_events if e.payload.get("reappraised")]
    assert reappraised
    last_reappraised = reappraised[-1]
    assert last_reappraised.payload["emotion"] == affect.last_emotion.value
    assert last_reappraised.payload["reappraised"] is True

    reg_events = await _reg_events(bus)
    p2 = [e.payload for e in reg_events if e.payload.get("tier") == 2][-1]
    assert p2["emotion_before"] == "fear"
    assert p2["emotion_after"] == affect.last_emotion.value
    assert p2["size"] == pytest.approx(1.0)
    await bus.close()


@pytest.mark.asyncio
async def test_reappraisal_without_change_publishes_no_emotion(monkeypatch):
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    affect = Affect(
        bus,
        clock=lambda: 0.0,
        regulation=ThreeTierRegulation(RegulationConfig()),
        publish_interval_s=1000.0,
    )
    affect.set_drive_relevance(
        {
            "social_drive": frozenset({"audition"}),
            "curiosity": frozenset({"vision"}),
            "boredom": frozenset(),
            "restlessness": frozenset(),
        },
        dominant_drive,
    )
    monkeypatch.setattr(affect, "_pleasantness", lambda g: -0.4)
    affect.drives.social_drive.value = 0.8
    affect.drives.social_drive._has_fired = True
    affect.drives.social_drive.own_ends = 0
    affect.drives.social_drive.other_ends = 8
    affect._state = DimensionalState(valence=-0.6, arousal=0.6, dominance=0.0)

    snap = _snapshot([_ev("audition", salience=0.9, eid="a")])
    await affect._appraise_snapshot(snap)
    assert affect.last_emotion == CategoricalEmotion.FEAR

    affect._regulation.update(now=0.0, intensity=0.8, negative=True)
    await affect._run_regulation(60.0)
    assert affect.last_emotion == CategoricalEmotion.FEAR

    reg_events = await _reg_events(bus)
    p2 = [e.payload for e in reg_events if e.payload.get("tier") == 2][-1]
    assert p2["emotion_before"] == "fear"
    assert p2["emotion_after"] == "fear"
    assert p2["size"] == pytest.approx(0.0)

    emotion_events = await _emotion_events(bus)
    assert not any(e.payload.get("reappraised") for e in emotion_events)
    await bus.close()


@pytest.mark.asyncio
async def test_reappraisal_once_per_episode(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        regulation=ThreeTierRegulation(RegulationConfig()),
        publish_interval_s=1000.0,
    )
    await _drive(affect, t, 95, valence=-0.8, negative=True)
    events = await _reg_events(bus)
    tier2 = [e for e in events if e.payload["tier"] == 2]
    assert len(tier2) == 1


@pytest.mark.asyncio
async def test_developmental_phase_suppresses_regulation(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        regulation=ThreeTierRegulation(RegulationConfig()),
        publish_interval_s=1000.0,
    )
    affect.set_development_probe(lambda: True)
    await _drive(affect, t, 120, valence=-0.8, negative=True)
    assert len(await _reg_events(bus)) == 0

    affect.set_development_probe(lambda: False)
    await _drive(affect, t, 31, valence=-0.8, negative=True)
    events = await _reg_events(bus)
    assert len(events) == 1
    assert events[0].payload["tier"] == 1


@pytest.mark.asyncio
async def test_passive_default_publishes_no_regulation(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        publish_interval_s=1000.0,
    )
    assert isinstance(affect.regulation, PassiveDecay)
    await _drive(affect, t, 95, valence=-0.8, negative=True)
    assert len(await _reg_events(bus)) == 0


@pytest.mark.asyncio
async def test_affective_reset_restarts_episode(bus):
    t = [0.0]
    affect = Affect(
        bus,
        clock=lambda: t[0],
        regulation=ThreeTierRegulation(RegulationConfig()),
        publish_interval_s=1000.0,
    )
    await _drive(affect, t, 40, valence=-0.8, negative=True)
    events = await _reg_events(bus)
    assert len(events) == 1
    assert events[0].payload["tier"] == 1

    await affect.affective_reset()
    await _drive(affect, t, 25, valence=-0.8, negative=True)
    events = await _reg_events(bus)
    assert len(events) == 1


@pytest.mark.asyncio
async def test_factory_default_is_three_tier(bus):
    affect = make_affect(bus, {})
    assert isinstance(affect.regulation, ThreeTierRegulation)
    assert affect.regulation.config == RegulationConfig()


@pytest.mark.asyncio
async def test_factory_passive_policy(bus):
    affect = make_affect(bus, {"regulation": {"policy": "passive"}})
    assert isinstance(affect.regulation, PassiveDecay)


@pytest.mark.asyncio
async def test_factory_set_point(bus):
    affect = make_affect(bus, {"regulation": {"set_point": 0.6}})
    assert isinstance(affect.regulation, ThreeTierRegulation)
    assert affect.regulation.config.set_point == pytest.approx(0.6)
    assert affect.regulation.config.selection_bias == RegulationConfig().selection_bias


@pytest.mark.asyncio
async def test_factory_rejects_bogus_key(bus):
    # Unknown keys fail boot with the shared guard's ValueError, as for
    # [affect.coupling].
    with pytest.raises(ValueError, match="bogus"):
        make_affect(bus, {"regulation": {"bogus": 1}})


@pytest.mark.asyncio
async def test_factory_rejects_retired_reappraisal_fraction(bus):
    with pytest.raises(ValueError, match="reappraisal_fraction"):
        make_affect(bus, {"regulation": {"reappraisal_fraction": 0.5}})


@pytest.mark.asyncio
async def test_factory_rejects_bad_policy(bus):
    with pytest.raises(ConfigurationError):
        make_affect(bus, {"regulation": {"policy": "x"}})


@pytest.mark.asyncio
async def test_factory_rejects_invalid_selection_bias(bus):
    with pytest.raises(ConfigurationError):
        make_affect(bus, {"regulation": {"selection_bias": 2.0}})
