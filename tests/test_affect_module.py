# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.access_rate import max_report_salience
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.affect import Affect, CategoricalEmotion
from kaine.modules.affect.coupling import CouplingConfig
from kaine.modules.affect.drives import DriveCrossing
from kaine.modules.affect.state import DimensionalState


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _event(source="interoception", type_="t", salience=0.5, eid="e0", **payload) -> tuple:
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
        Affect(bus, baseline_salience=2.0)
    with pytest.raises(ValueError):
        Affect(bus, alert_salience=-0.1)
    with pytest.raises(ValueError):
        Affect(bus, drift_rate_per_s=-1.0)
    with pytest.raises(ValueError):
        Affect(bus, publish_interval_s=0)


@pytest.mark.asyncio
async def test_initialize_and_shutdown(bus: AsyncBus):
    affect = Affect(bus)
    await affect.initialize()
    await affect.shutdown()


@pytest.mark.asyncio
async def test_workspace_publishes_affect_state_after_interval(bus: AsyncBus):
    fake_now = [0.0]
    affect = Affect(bus, publish_interval_s=0.5, clock=lambda: fake_now[0])
    await affect.initialize()
    try:
        fake_now[0] = 0.0
        await affect.on_workspace(_snapshot([_event(salience=0.4)]))
        fake_now[0] = 1.0
        await affect.on_workspace(_snapshot([_event(salience=0.5)]))
        entries = await bus.read("affect.out", last_id="0", count=20)
        types = [e.type for _, e in entries]
        assert "affect.state" in types
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_workspace_publishes_emotion_when_changes(bus: AsyncBus):
    # Rewritten for research affect: appraisal novelty now comes from normalised
    # prediction-error ratios; a ratio of 3.0 yields maximal novelty and SURPRISE.
    fake_now = [0.0]
    affect = Affect(bus, publish_interval_s=5.0, clock=lambda: fake_now[0])
    # Burst state (habituation factor 1), so the alert's full step applies (paper A.4).
    affect._alert_fast = 0.2
    affect._alert_slow = 0.05
    await affect.initialize()
    try:
        fake_now[0] = 1.0
        await affect.on_workspace(
            _snapshot([_event(salience=0.5, type_="vision.report", normalised_error=3.0)])
        )
        entries = await bus.read("affect.out", last_id="0", count=20)
        emotion_events = [e for _, e in entries if e.type == "affect.emotion"]
        assert len(emotion_events) >= 1
        assert any(
            e.payload.get("emotion") == CategoricalEmotion.SURPRISE.value
            for e in emotion_events
        )
        assert all(
            e.payload["alert"] is True
            for e in emotion_events
            if e.payload.get("emotion") != CategoricalEmotion.NEUTRAL.value
        )
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_affective_reset_zeroes_state_and_drives(bus: AsyncBus):
    affect = Affect(bus)
    affect._state = DimensionalState(valence=0.7, arousal=0.8)
    affect.drives.curiosity.value = 0.9
    await affect.initialize()
    try:
        await affect.affective_reset()
        assert affect.state == affect.baseline
        for d in affect.drives.all():
            assert d.value == 0.0
        assert affect.last_emotion == CategoricalEmotion.NEUTRAL
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_add_goal_publishes_event(bus: AsyncBus):
    affect = Affect(bus)
    await affect.initialize()
    try:
        gid = await affect.add_goal("explore", priority=0.6)
        entries = await bus.read("affect.out", last_id="0", count=10)
        goal_events = [e for _, e in entries if e.type == "affect.goal"]
        assert len(goal_events) == 1
        assert goal_events[0].payload["action"] == "added"
        assert goal_events[0].payload["id"] == gid
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_complete_and_abandon_goal_publish_events(bus: AsyncBus):
    affect = Affect(bus)
    await affect.initialize()
    try:
        gid = await affect.add_goal("explore")
        await affect.complete_goal(gid)
        gid2 = await affect.add_goal("alt")
        await affect.abandon_goal(gid2)
        entries = await bus.read("affect.out", last_id="0", count=20)
        actions = [e.payload.get("action") for _, e in entries if e.type == "affect.goal"]
        assert "added" in actions
        assert "completed" in actions
        assert "abandoned" in actions
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_interoception_report_nudges_state(bus: AsyncBus):
    # Rewritten for research affect: wellness is stored as a valence target, and
    # only interoception *alerts* produce an immediate arousal nudge.
    affect = Affect(bus)
    await affect.initialize()
    try:
        prior_arousal = affect.state.arousal
        prior_valence = affect.state.valence
        await bus.publish(
            Event(
                source="interoception",
                type="interoception.report",
                payload={"wellness": 0.1, "alerts": ["cpu_percent"]},
                salience=0.7,
                timestamp=datetime.now(timezone.utc),
            )
        )
        # Wait for the peer consumer to drain.
        for _ in range(50):
            await asyncio.sleep(0.02)
            if affect._wellness < 1.0:
                break
        assert affect._wellness == pytest.approx(0.1)
        # Alert produces the hard-wired arousal nudge; valence is not nudged.
        assert affect.state.arousal > prior_arousal
        assert affect.state.valence == pytest.approx(prior_valence)
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_sequence_report_arms_social_drive(bus: AsyncBus):
    # Rewritten for research affect: the first sequence.report arms the social
    # drive; subsequent ticks build it with u=1, and a newly-reset TSLI relieves it.
    fake_now = [0.0]
    affect = Affect(bus, clock=lambda: fake_now[0], publish_interval_s=999.0)
    await affect.initialize()
    try:
        await bus.publish(
            Event(
                source="sequence",
                type="sequence.report",
                payload={"time_since_last_interaction_s": 8.0},
                salience=0.1,
                timestamp=datetime.now(timezone.utc),
            )
        )
        for _ in range(50):
            await asyncio.sleep(0.02)
            if affect._interaction_seen:
                break
        assert affect._interaction_seen
        fake_now[0] = 300.0
        await affect._tick()
        assert affect.drives.social_drive.value > 0.5
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_modulator_uses_current_state(bus: AsyncBus):
    affect = Affect(bus, baseline=DimensionalState(arousal=0.2))
    low = await affect.modulator.modulate(
        Event(source="x", type="t", payload={}, salience=0.5,
              timestamp=datetime.now(timezone.utc))
    )
    affect._state = DimensionalState(arousal=0.9)
    high = await affect.modulator.modulate(
        Event(source="x", type="t", payload={}, salience=0.5,
              timestamp=datetime.now(timezone.utc))
    )
    assert high > low


@pytest.mark.asyncio
async def test_serialize_roundtrips(bus: AsyncBus):
    affect = Affect(bus)
    affect._state = DimensionalState(valence=0.5, arousal=0.6)
    state = affect.serialize()
    fresh = Affect(bus)
    fresh.deserialize(state)
    assert fresh.state.valence == 0.5
    assert fresh.state.arousal == 0.6


# ---------------------------------------------------------------------------
# Coupling integration tests (task 5.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audition_emotion_event_is_consumed_by_peer_loop(bus: AsyncBus):
    """audition.emotion events published on the bus are recorded by the affect module's peer
    consumer loop when coupling is enabled, then fed to the entity's appraisal.

    Rewritten for research affect: the perceived signal is NOT written directly to
    the dimensional state and the per-broadcast appraisal nudges are removed.
    Instead it changes the appraisal scores (intrinsic_pleasantness / novelty),
    and valence follows learning progress through its own relaxation.
    """
    cfg = CouplingConfig(
        enabled=True,
        coupling_base=0.15,
        coupling_familiarity_gain=0.0,
        coupling_ceiling=0.30,
        decay_s=10.0,
    )
    fake_now = [0.0]
    affect = Affect(bus, coupling=cfg, clock=lambda: fake_now[0], publish_interval_s=999.0)
    affect._drift_rate = 0.0
    affect._state = DimensionalState(valence=-0.3, arousal=0.3, dominance=0.0)
    await affect.initialize()
    try:
        baseline_scores = affect._score_snapshot(
            WorkspaceSnapshot(tick_index=0, selected_events=[], inhibited=False)
        )
        initial_valence = affect.state.valence

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
            if affect._perceived_emotion is not None:
                break
        assert affect._perceived_emotion is not None, (
            "audition.emotion not consumed by the peer loop"
        )
        # Recording alone must not move state; valence relaxation only runs in _tick.
        assert affect.state.valence == initial_valence

        # The entity's own appraisal reflects the perceived emotion.
        coupled_scores = affect._score_snapshot(
            WorkspaceSnapshot(tick_index=0, selected_events=[], inhibited=False)
        )
        assert coupled_scores.intrinsic_pleasantness > baseline_scores.intrinsic_pleasantness
        assert coupled_scores.novelty > baseline_scores.novelty
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_appraisal_path_unchanged_by_coupling(bus: AsyncBus):
    """Coupling MUST NOT change the Scherer appraisal path.

    With coupling disabled, on_workspace produces the same emotion output
    as without any coupling config at all.
    """
    baseline_affect = Affect(bus, publish_interval_s=999.0)
    coupled_affect = Affect(
        bus,
        coupling=CouplingConfig(enabled=False),
        publish_interval_s=999.0,
    )

    # Both should start with the same state.
    assert baseline_affect.state == coupled_affect.state

    # Score a snapshot via the private helper — should be identical.
    snapshot = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[
            _event(salience=0.8, type_="user_speech"),
        ],
        inhibited=False,
    )

    scores_baseline = baseline_affect._score_snapshot(snapshot)
    scores_coupled = coupled_affect._score_snapshot(snapshot)

    assert scores_baseline == scores_coupled, (
        "Coupling must not alter the Scherer appraisal scores"
    )


@pytest.mark.asyncio
async def test_disabled_coupling_no_emotion_stream_consumption(bus: AsyncBus):
    """When emotion coupling is disabled the social cognition stream is not subscribed.

    (Perception→arousal reads vision.out / audition.out unconditionally — arousal
    is pre-attentive — so those ARE subscribed; the emotion and social cognition module coupling
    stays gated by CouplingConfig.enabled.)
    """
    cfg = CouplingConfig(enabled=False)
    affect = Affect(bus, coupling=cfg, publish_interval_s=999.0)
    await affect.initialize()
    try:
        assert "social_cognition.out" not in affect._cursors  # emotion coupling stays gated
        # perception→arousal streams are always read
        assert "vision.out" in affect._cursors
        assert "audition.out" in affect._cursors
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_perceptual_surprise_arouses_scaled_by_normalised_error(bus: AsyncBus):
    """Perception→arousal coupling: a perceptual ALERT raises arousal, scaled by the
    normalised prediction error (surprise above the expected level); a well-predicted
    event does not arouse. Mirrors the interoception module's alert→arousal path.
    The burst state makes the habituation factor 1."""
    affect = Affect(bus, publish_interval_s=999.0)
    # Burst state (habituation factor 1), so the alert's full step applies (paper A.4).
    affect._alert_fast = 0.2
    affect._alert_slow = 0.05
    for stream, typ in (("vision.out", "vision.report"),
                        ("audition.out", "audition.perception")):
        base = affect._state.arousal
        # A strong surprise (normalised error 5 → surprise 4, capped) arouses.
        strong = Event(
            source=typ.split(".")[0], type=typ,
            payload={"alert": True, "normalised_error": 5.0}, salience=0.8,
            timestamp=datetime.now(timezone.utc),
        )
        await affect._handle_peer_event(stream, strong)
        aroused = affect._state.arousal
        assert aroused > base, f"{typ} alert must raise arousal"
        # A larger surprise arouses more (scaling), until the per-event cap.
        # A well-predicted (non-alert) event does NOT arouse.
        calm = Event(
            source=typ.split(".")[0], type=typ,
            payload={"alert": False, "normalised_error": 1.0}, salience=0.2,
            timestamp=datetime.now(timezone.utc),
        )
        await affect._handle_peer_event(stream, calm)
        assert affect._state.arousal == aroused, "well-predicted input must not arouse"


@pytest.mark.asyncio
async def test_social_cognition_agent_model_updates_familiarity_cache(bus: AsyncBus):
    """social_cognition.agent_model events update the per-agent familiarity cache."""
    cfg = CouplingConfig(enabled=True)
    affect = Affect(bus, coupling=cfg, publish_interval_s=999.0)
    await affect.initialize()
    try:
        await bus.publish(
            Event(
                source="social_cognition",
                type="social_cognition.agent_model",
                payload={"agent_id": "alice", "familiarity": 0.65},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        )
        for _ in range(60):
            await asyncio.sleep(0.02)
            if "alice" in affect._familiarity_cache:
                break

        assert "alice" in affect._familiarity_cache
        assert affect._familiarity_cache["alice"] == pytest.approx(0.65)
    finally:
        await affect.shutdown()

@pytest.mark.asyncio
async def test_familiarity_cached_under_source_label(bus: AsyncBus):
    """social_cognition.agent_model events cache familiarity under source_label too."""
    cfg = CouplingConfig(enabled=True)
    affect = Affect(bus, coupling=cfg, publish_interval_s=999.0)
    await affect.initialize()
    try:
        await bus.publish(
            Event(
                source="social_cognition",
                type="social_cognition.agent_model",
                payload={
                    "agent_id": "media:live_mic",
                    "source_label": "live_mic",
                    "familiarity": 0.65,
                },
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        )
        for _ in range(60):
            await asyncio.sleep(0.02)
            if "live_mic" in affect._familiarity_cache:
                break

        assert "live_mic" in affect._familiarity_cache
        assert affect._familiarity_cache["live_mic"] == pytest.approx(0.65)
        assert "media:live_mic" in affect._familiarity_cache
        assert affect._familiarity_cache["media:live_mic"] == pytest.approx(0.65)
    finally:
        await affect.shutdown()


@pytest.mark.asyncio
async def test_drive_crossing_is_a_categorical_alert(bus):
    fake_now = [0.0]
    affect = Affect(bus, publish_interval_s=999.0, clock=lambda: fake_now[0])
    await affect.initialize()
    try:
        affect._drives.tick = lambda dt, **kwargs: [DriveCrossing(name="boredom", value=0.9)]
        fake_now[0] = 1.0
        await affect._tick()
        entries = await bus.read("affect.out", last_id="0", count=50)
        drive_events = [entry for entry in entries if entry[1].type == "affect.drive"]
        assert len(drive_events) == 1
        payload = drive_events[0][1].payload
        assert payload["alert"] is True
        assert drive_events[0][1].salience == pytest.approx(affect._alert_salience)
        assert max_report_salience(entries) == pytest.approx(affect._alert_salience)
    finally:
        await affect.shutdown()
