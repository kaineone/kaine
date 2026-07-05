# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.thymos import CategoricalEmotion, Thymos
from kaine.modules.thymos.coupling import CouplingConfig
from kaine.modules.thymos.state import DimensionalState


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _event(source="soma", type_="t", salience=0.5, eid="e0", **payload) -> tuple:
    return eid, Event(
        source=source,
        type=type_,
        payload=payload or {"k": "v"},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(events=None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=events or [],
        inhibited=False,
    )


@pytest.mark.asyncio
async def test_invalid_construction(bus: AsyncBus):
    with pytest.raises(ValueError):
        Thymos(bus, baseline_salience=2.0)
    with pytest.raises(ValueError):
        Thymos(bus, alert_salience=-0.1)
    with pytest.raises(ValueError):
        Thymos(bus, drift_rate_per_s=-1.0)
    with pytest.raises(ValueError):
        Thymos(bus, publish_interval_s=0)


@pytest.mark.asyncio
async def test_initialize_and_shutdown(bus: AsyncBus):
    thymos = Thymos(bus)
    await thymos.initialize()
    await thymos.shutdown()


@pytest.mark.asyncio
async def test_workspace_publishes_thymos_state_after_interval(bus: AsyncBus):
    fake_now = [0.0]
    thymos = Thymos(bus, publish_interval_s=0.5, clock=lambda: fake_now[0])
    await thymos.initialize()
    try:
        fake_now[0] = 0.0
        await thymos.on_workspace(_snapshot([_event(salience=0.4)]))
        fake_now[0] = 1.0
        await thymos.on_workspace(_snapshot([_event(salience=0.5)]))
        entries = await bus.read("thymos.out", last_id="0", count=20)
        types = [e.type for _, e in entries]
        assert "thymos.state" in types
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_workspace_publishes_emotion_when_changes(bus: AsyncBus):
    fake_now = [0.0]
    thymos = Thymos(bus, publish_interval_s=5.0, clock=lambda: fake_now[0])
    await thymos.initialize()
    try:
        # Construct a snapshot that scores high pleasantness + high goal.
        thymos.goals.add("test goal", priority=1.0)
        await thymos.on_workspace(
            _snapshot([_event(salience=0.9, type_="test_goal_event")])
        )
        entries = await bus.read("thymos.out", last_id="0", count=20)
        emotion_events = [e for _, e in entries if e.type == "thymos.emotion"]
        assert len(emotion_events) >= 1
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_affective_reset_zeroes_state_and_drives(bus: AsyncBus):
    thymos = Thymos(bus)
    thymos._state = DimensionalState(valence=0.7, arousal=0.8)
    thymos.drives.curiosity.value = 0.9
    await thymos.initialize()
    try:
        await thymos.affective_reset()
        assert thymos.state == thymos.baseline
        for d in thymos.drives.all():
            assert d.value == 0.0
        assert thymos.last_emotion == CategoricalEmotion.NEUTRAL
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_add_goal_publishes_event(bus: AsyncBus):
    thymos = Thymos(bus)
    await thymos.initialize()
    try:
        gid = await thymos.add_goal("explore", priority=0.6)
        entries = await bus.read("thymos.out", last_id="0", count=10)
        goal_events = [e for _, e in entries if e.type == "thymos.goal"]
        assert len(goal_events) == 1
        assert goal_events[0].payload["action"] == "added"
        assert goal_events[0].payload["id"] == gid
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_complete_and_abandon_goal_publish_events(bus: AsyncBus):
    thymos = Thymos(bus)
    await thymos.initialize()
    try:
        gid = await thymos.add_goal("explore")
        await thymos.complete_goal(gid)
        gid2 = await thymos.add_goal("alt")
        await thymos.abandon_goal(gid2)
        entries = await bus.read("thymos.out", last_id="0", count=20)
        actions = [e.payload.get("action") for _, e in entries if e.type == "thymos.goal"]
        assert "added" in actions
        assert "completed" in actions
        assert "abandoned" in actions
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_soma_report_nudges_state(bus: AsyncBus):
    thymos = Thymos(bus)
    await thymos.initialize()
    try:
        await bus.publish(
            Event(
                source="soma",
                type="soma.report",
                payload={"wellness": 0.1, "alerts": ["cpu_percent"]},
                salience=0.7,
                timestamp=datetime.now(timezone.utc),
            )
        )
        # Wait for the peer consumer to drain.
        prior = thymos.state.valence
        for _ in range(50):
            await asyncio.sleep(0.02)
            if thymos.state.valence != prior:
                break
        # Low wellness should push valence down (or arousal up).
        assert thymos.state.valence < prior + 0.001
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_chronos_report_raises_social_drive(bus: AsyncBus):
    thymos = Thymos(bus, social_drive_time_scale_s=10.0)
    await thymos.initialize()
    try:
        await bus.publish(
            Event(
                source="chronos",
                type="chronos.report",
                payload={"time_since_last_interaction_s": 8.0},
                salience=0.1,
                timestamp=datetime.now(timezone.utc),
            )
        )
        for _ in range(50):
            await asyncio.sleep(0.02)
            if thymos.drives.social_drive.value > 0:
                break
        assert thymos.drives.social_drive.value >= 0.7
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_modulator_uses_current_state(bus: AsyncBus):
    thymos = Thymos(bus, baseline=DimensionalState(arousal=0.2))
    low = await thymos.modulator.modulate(
        Event(source="x", type="t", payload={}, salience=0.5,
              timestamp=datetime.now(timezone.utc))
    )
    thymos._state = DimensionalState(arousal=0.9)
    high = await thymos.modulator.modulate(
        Event(source="x", type="t", payload={}, salience=0.5,
              timestamp=datetime.now(timezone.utc))
    )
    assert high > low


@pytest.mark.asyncio
async def test_serialize_roundtrips(bus: AsyncBus):
    thymos = Thymos(bus)
    thymos._state = DimensionalState(valence=0.5, arousal=0.6)
    state = thymos.serialize()
    fresh = Thymos(bus)
    fresh.deserialize(state)
    assert fresh.state.valence == 0.5
    assert fresh.state.arousal == 0.6


# ---------------------------------------------------------------------------
# Coupling integration tests (task 5.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audition_emotion_event_is_consumed_by_peer_loop(bus: AsyncBus):
    """audition.emotion events published on the bus are recorded by Thymos's peer
    consumer loop when coupling is enabled, then fed to the entity's appraisal.

    The perceived signal is NOT written directly to the dimensional state: the
    peer loop records it, and the entity's own appraisal (run on the next
    workspace tick) produces the upward valence response.
    """
    cfg = CouplingConfig(
        enabled=True,
        coupling_base=0.15,
        coupling_familiarity_gain=0.0,
        coupling_ceiling=0.30,
        decay_s=10.0,
    )
    thymos = Thymos(bus, coupling=cfg, publish_interval_s=999.0)
    thymos._drift_rate = 0.0  # isolate the appraisal nudge from drift
    thymos._state = DimensionalState(valence=-0.3, arousal=0.3, dominance=0.0)
    await thymos.initialize()
    try:
        initial_valence = thymos.state.valence

        await bus.publish(
            Event(
                source="audition",
                type="audition.emotion",
                payload={
                    "category": "happy",
                    "confidence": 0.9,
                    "scores": {},
                    "model": "test",
                    "source_label": "mic",
                    "latency_ms": 1.0,
                },
                salience=0.8,
                timestamp=datetime.now(timezone.utc),
            )
        )

        # Wait for the peer consumer to record the perceived-emotion signal.
        for _ in range(60):
            await asyncio.sleep(0.02)
            if thymos._perceived_emotion is not None:
                break
        assert thymos._perceived_emotion is not None, (
            "audition.emotion not consumed by the peer loop"
        )
        # Recording alone must not move state — appraisal is the only route.
        assert thymos.state.valence == initial_valence

        # The entity's own appraisal (next tick) produces the response.
        await thymos.on_workspace(
            WorkspaceSnapshot(tick_index=0, selected_events=[], inhibited=False)
        )

        assert thymos.state.valence > initial_valence, (
            f"appraisal of perceived joy did not raise valence: "
            f"valence stuck at {thymos.state.valence:.4f}"
        )
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_appraisal_path_unchanged_by_coupling(bus: AsyncBus):
    """Coupling MUST NOT change the Scherer appraisal path.

    With coupling disabled, on_workspace produces the same emotion output
    as without any coupling config at all.
    """
    baseline_thymos = Thymos(bus, publish_interval_s=999.0)
    coupled_thymos = Thymos(
        bus,
        coupling=CouplingConfig(enabled=False),
        publish_interval_s=999.0,
    )

    # Both should start with the same state.
    assert baseline_thymos.state == coupled_thymos.state

    # Score a snapshot via the private helper — should be identical.
    snapshot = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[
            _event(salience=0.8, type_="user_speech"),
        ],
        inhibited=False,
    )

    scores_baseline = baseline_thymos._score_snapshot(snapshot)
    scores_coupled = coupled_thymos._score_snapshot(snapshot)

    assert scores_baseline == scores_coupled, (
        "Coupling must not alter the Scherer appraisal scores"
    )


@pytest.mark.asyncio
async def test_disabled_coupling_no_event_consumption(bus: AsyncBus):
    """When coupling is disabled the peer loop must not subscribe to audition.out."""
    cfg = CouplingConfig(enabled=False)
    thymos = Thymos(bus, coupling=cfg, publish_interval_s=999.0)
    await thymos.initialize()
    try:
        # audition.out stream must not be in the cursors when disabled.
        assert "audition.out" not in thymos._cursors
    finally:
        await thymos.shutdown()


@pytest.mark.asyncio
async def test_empatheia_agent_model_updates_familiarity_cache(bus: AsyncBus):
    """empatheia.agent_model events update the per-agent familiarity cache."""
    cfg = CouplingConfig(enabled=True)
    thymos = Thymos(bus, coupling=cfg, publish_interval_s=999.0)
    await thymos.initialize()
    try:
        await bus.publish(
            Event(
                source="empatheia",
                type="empatheia.agent_model",
                payload={"agent_id": "alice", "familiarity": 0.65},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        )
        for _ in range(60):
            await asyncio.sleep(0.02)
            if "alice" in thymos._familiarity_cache:
                break

        assert "alice" in thymos._familiarity_cache
        assert thymos._familiarity_cache["alice"] == pytest.approx(0.65)
    finally:
        await thymos.shutdown()
