# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phantasia(BaseModule) — event-driven behavior with fakeredis.

Waking emits salience-only world_error; a mnemos.replay cue (during an open
Hypnos window) emits phantasia.scenario re-injected onto phantasia.out; the
trajectory buffer is bounded; no raw sense data lands on the bus.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.phantasia.module import Phantasia


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _event(source: str, type_: str, payload=None, salience: float = 0.5) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload or {},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(events, *, inhibited: bool = False, tick: int = 1) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=tick,
        selected_events=[(f"{i}-0", ev) for i, ev in enumerate(events)],
        inhibited=inhibited,
    )


async def _drain(bus: AsyncBus, stream: str = "phantasia.out") -> list[Event]:
    entries = await bus.read(stream, last_id="0")
    return [e for _, e in entries]


# ---------------------------------------------------------------------------
# Waking: world_error
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_waking_emits_world_error(bus: AsyncBus):
    ph = Phantasia(bus, backend="fake")
    await ph.initialize()
    try:
        await ph.on_workspace(_snapshot([_event("soma", "soma.report", salience=0.4)]))
        await ph.on_workspace(_snapshot([_event("topos", "topos.report", salience=0.9)]))
        events = await _drain(bus)
        world_errors = [e for e in events if e.type == "phantasia.world_error"]
        assert len(world_errors) == 2
        for e in world_errors:
            assert 0.0 <= e.salience <= 1.0
    finally:
        await ph.shutdown()


@pytest.mark.asyncio
async def test_world_error_carries_no_scenario_content(bus: AsyncBus):
    ph = Phantasia(bus, backend="fake")
    await ph.initialize()
    try:
        await ph.on_workspace(_snapshot([_event("nous", "nous.belief", salience=0.5)]))
        events = await _drain(bus)
        we = [e for e in events if e.type == "phantasia.world_error"]
        assert we
        for e in we:
            keys = set(e.payload.keys())
            # Salience-only signal: no imagined/scenario fields.
            for banned in ("scenario", "trajectory", "step_magnitudes", "rollout", "imagined"):
                assert banned not in keys
            assert keys <= {"world_error", "salience", "tick_index", "backend"}
    finally:
        await ph.shutdown()


@pytest.mark.asyncio
async def test_surprising_trajectory_raises_world_error(bus: AsyncBus):
    ph = Phantasia(bus, backend="fake")
    await ph.initialize()
    try:
        # Repeated identical snapshots → low error after the first.
        steady = _snapshot([_event("soma", "soma.report", salience=0.4)])
        for _ in range(4):
            await ph.on_workspace(steady)
        # A sharply different coalition → elevated error.
        surprising = _snapshot([
            _event("audition", "audition.transcription", salience=0.95),
            _event("topos", "topos.report", salience=0.95),
        ])
        await ph.on_workspace(surprising)

        events = await _drain(bus)
        we = [e.payload["world_error"] for e in events if e.type == "phantasia.world_error"]
        # Last (surprising) error should exceed the steady-state error.
        assert we[-1] >= we[-2]
    finally:
        await ph.shutdown()


# ---------------------------------------------------------------------------
# Offline: mnemos.replay cue -> scenario
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_cue_during_window_emits_scenario(bus: AsyncBus):
    ph = Phantasia(bus, backend="fake", rollout_horizon=5)
    await ph.initialize()
    try:
        # Accumulate some waking trajectory first.
        for i in range(6):
            await ph.on_workspace(_snapshot([_event("soma", "soma.report", salience=0.4)], tick=i))

        # Open the Hypnos window, then deliver a mnemos.replay cue.
        await ph._handle_peer_event("hypnos.out", _event("hypnos", "hypnos.sleep.started"))
        assert ph.window_active is True
        await ph._handle_peer_event(
            "mnemos.out",
            _event("mnemos", "mnemos.replay", {"memory_id": "m-1", "text": "secret"}),
        )

        events = await _drain(bus)
        scenarios = [e for e in events if e.type == "phantasia.scenario"]
        assert len(scenarios) >= 1
        payload = scenarios[-1].payload
        assert payload["horizon"] == 5
        assert payload["seed_memory_id"] == "m-1"
        assert "step_magnitudes" in payload
    finally:
        await ph.shutdown()


@pytest.mark.asyncio
async def test_replay_cue_while_awake_emits_nothing(bus: AsyncBus):
    """Scenario generation is offline-only — a replay cue while awake is ignored."""
    ph = Phantasia(bus, backend="fake")
    await ph.initialize()
    try:
        assert ph.window_active is False
        await ph._handle_peer_event(
            "mnemos.out",
            _event("mnemos", "mnemos.replay", {"memory_id": "m-2"}),
        )
        events = await _drain(bus)
        assert [e for e in events if e.type == "phantasia.scenario"] == []
    finally:
        await ph.shutdown()


@pytest.mark.asyncio
async def test_scenario_reinjected_onto_phantasia_out(bus: AsyncBus):
    """phantasia.scenario must be published on phantasia.out so the workspace
    selection re-injects it into the broadcast for downstream on_workspace
    consumers (Nous/Thymos/Eidolon)."""
    ph = Phantasia(bus, backend="fake", rollout_horizon=4)
    await ph.initialize()
    try:
        for i in range(4):
            await ph.on_workspace(_snapshot([_event("soma", "soma.report", salience=0.4)], tick=i))
        await ph._handle_peer_event("hypnos.out", _event("hypnos", "hypnos.sleep.started"))
        await ph.generate_scenario(seed_memory_id="seed-x")

        # The event is readable on the module's output stream — that IS the
        # re-injection path (syneidesis selects from module .out streams).
        events = await _drain(bus, "phantasia.out")
        scenarios = [e for e in events if e.type == "phantasia.scenario"]
        assert scenarios
        assert scenarios[-1].source == "phantasia"
    finally:
        await ph.shutdown()


@pytest.mark.asyncio
async def test_window_close_stops_scenarios(bus: AsyncBus):
    ph = Phantasia(bus, backend="fake")
    await ph.initialize()
    try:
        await ph._handle_peer_event("hypnos.out", _event("hypnos", "hypnos.sleep.started"))
        assert ph.window_active is True
        await ph._handle_peer_event("hypnos.out", _event("hypnos", "hypnos.sleep.completed"))
        assert ph.window_active is False
        await ph._handle_peer_event(
            "mnemos.out", _event("mnemos", "mnemos.replay", {"memory_id": "m"})
        )
        events = await _drain(bus)
        assert [e for e in events if e.type == "phantasia.scenario"] == []
    finally:
        await ph.shutdown()


# ---------------------------------------------------------------------------
# Trajectory buffer is bounded
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trajectory_buffer_is_bounded(bus: AsyncBus):
    ph = Phantasia(bus, backend="fake", trajectory_buffer_size=10)
    await ph.initialize()
    try:
        for i in range(50):
            await ph.on_workspace(_snapshot([_event("soma", "soma.report", salience=0.4)], tick=i))
        assert ph.buffer_size == 10
    finally:
        await ph.shutdown()


# ---------------------------------------------------------------------------
# No raw sense data on the bus
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_raw_sense_data_on_bus(bus: AsyncBus):
    ph = Phantasia(bus, backend="fake", rollout_horizon=4)
    await ph.initialize()
    try:
        # Drive waking with a snapshot that carries transcript + frame data.
        snap = _snapshot([
            _event("audition", "audition.transcription",
                   {"text": "private words", "pcm": "rawaudio"}, 0.7),
        ])
        for i in range(5):
            await ph.on_workspace(snap)
        await ph._handle_peer_event("hypnos.out", _event("hypnos", "hypnos.sleep.started"))
        await ph._handle_peer_event(
            "mnemos.out",
            _event("mnemos", "mnemos.replay",
                   {"memory_id": "m", "text": "memory transcript text"}),
        )

        events = await _drain(bus)
        assert events
        for e in events:
            blob = str(e.payload).lower()
            for forbidden in ("private words", "rawaudio", "memory transcript text", "pcm"):
                assert forbidden not in blob, (
                    f"raw sense data leaked onto bus in {e.type}: {e.payload}"
                )
    finally:
        await ph.shutdown()


# ---------------------------------------------------------------------------
# Training gating + serialize metadata-only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_training_disabled_does_not_train(bus: AsyncBus):
    ph = Phantasia(bus, backend="fake", training_enabled=False)
    await ph.initialize()
    try:
        for i in range(5):
            await ph.on_workspace(_snapshot([_event("soma", "soma.report", salience=0.4)], tick=i))
        # Opening the window triggers _maybe_train, which is a no-op when disabled.
        outcome = await ph._maybe_train()
        assert outcome is None
    finally:
        await ph.shutdown()


@pytest.mark.asyncio
async def test_training_enabled_runs_in_memory(bus: AsyncBus):
    ph = Phantasia(bus, backend="fake", training_enabled=True)
    await ph.initialize()
    try:
        for i in range(5):
            await ph.on_workspace(_snapshot([_event("soma", "soma.report", salience=0.4)], tick=i))
        outcome = ph.train_now()
        assert outcome is not None
        assert outcome.steps == 5
        assert not outcome.aborted
    finally:
        await ph.shutdown()


@pytest.mark.asyncio
async def test_serialize_emits_metadata_only(bus: AsyncBus):
    ph = Phantasia(bus, backend="fake")
    await ph.initialize()
    try:
        for i in range(3):
            await ph.on_workspace(_snapshot([_event("soma", "soma.report", salience=0.4)], tick=i))
        state = ph.serialize()
        # Metadata only — never the buffer or raw weights.
        assert "encoder_version" in state
        assert "backend" in state
        assert "buffer" not in state
        assert "trajectory" not in state
        assert "weights" not in state
        assert "params" not in state
        blob = str(state).lower()
        assert "soma.report" not in blob
    finally:
        await ph.shutdown()


@pytest.mark.asyncio
async def test_no_inference_during_window(bus: AsyncBus):
    """During an open Hypnos window the waking inference path is suspended."""
    ph = Phantasia(bus, backend="fake")
    await ph.initialize()
    try:
        await ph._handle_peer_event("hypnos.out", _event("hypnos", "hypnos.sleep.started"))
        await ph.on_workspace(_snapshot([_event("soma", "soma.report", salience=0.4)]))
        events = await _drain(bus)
        assert [e for e in events if e.type == "phantasia.world_error"] == []
    finally:
        await ph.shutdown()


# ---------------------------------------------------------------------------
# H7: backend disclosure — every phantasia.* event must carry 'backend'
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_world_error_discloses_backend(bus: AsyncBus):
    """phantasia.world_error must carry 'backend' in every payload."""
    ph = Phantasia(bus, backend="fake")
    await ph.initialize()
    try:
        await ph.on_workspace(_snapshot([_event("soma", "soma.report", salience=0.5)]))
        events = await _drain(bus)
        world_errors = [e for e in events if e.type == "phantasia.world_error"]
        assert world_errors, "expected at least one world_error event"
        for e in world_errors:
            assert "backend" in e.payload, "world_error payload missing 'backend'"
            assert e.payload["backend"] == "fake"
    finally:
        await ph.shutdown()


@pytest.mark.asyncio
async def test_scenario_discloses_backend(bus: AsyncBus):
    """phantasia.scenario must carry 'backend' in every payload."""
    ph = Phantasia(bus, backend="fake", rollout_horizon=4)
    await ph.initialize()
    try:
        for i in range(4):
            await ph.on_workspace(_snapshot([_event("soma", "soma.report", salience=0.4)], tick=i))
        await ph._handle_peer_event("hypnos.out", _event("hypnos", "hypnos.sleep.started"))
        payloads = await ph.generate_scenario(seed_memory_id="test-h7")
        assert payloads, "expected at least one scenario payload"
        for p in payloads:
            assert "backend" in p, "scenario payload missing 'backend'"
            assert p["backend"] == "fake"
    finally:
        await ph.shutdown()


@pytest.mark.asyncio
async def test_backend_value_matches_constructor_arg(bus: AsyncBus):
    """The 'backend' field in published events reflects the constructor arg."""
    ph = Phantasia(bus, backend="fake")
    await ph.initialize()
    try:
        await ph.on_workspace(_snapshot([_event("soma", "soma.report", salience=0.5)]))
        events = await _drain(bus)
        for e in events:
            if "backend" in e.payload:
                assert e.payload["backend"] == ph._backend
    finally:
        await ph.shutdown()
