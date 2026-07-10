# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Offline tests for the continuous embodiment control surface (the producer).

No entity is booted and no viewer/grid is needed: the continuous motor producer
(`ContinuousMotorSurface`) is exercised directly, and the closed producer ->
control-plane -> body path is exercised through the transport-free `StubAdapter`
over a fakeredis bus. These cover the surface shape, gaze decoupling, symbolic
exclusion, the mandatory closed loop, the freeze-then-free curriculum, the safety
gates, and that no new learner / scripted gait is introduced.
"""
from __future__ import annotations

import inspect
from dataclasses import fields

import pytest

from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.modules.mundus import (
    MOTOR_CHANNELS,
    MOTOR_STAGES,
    ContinuousMotorSurface,
    ControlCommand,
    EfferenceLoop,
    Mundus,
    MotorCurriculum,
    MotorFeedback,
    QuiescentMotorPolicy,
    StubAdapter,
    clamp_channel,
)
from kaine.modules.mundus import control_surface as cs
from kaine.modules.soma.forward import SubstrateForwardModel

from datetime import datetime, timezone


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus

    client = fakeredis.FakeRedis(decode_responses=True)
    yield AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    await client.aclose()


class _FakePolicy:
    """A stand-in learned policy returning fixed raw scalars (for tests)."""

    def __init__(self, **channels: float) -> None:
        self._channels = channels

    def __call__(self, observation):  # noqa: ANN001
        return dict(self._channels)


def _active(surface: ContinuousMotorSurface) -> ContinuousMotorSurface:
    surface.on_birth()
    return surface


# ---- W9.1 surface shape: continuous, clamped, single interact, no strafe -----

def test_surface_channels_are_exactly_the_canonical_five():
    assert MOTOR_CHANNELS == ("drive", "yaw_rate", "gaze_yaw", "gaze_pitch", "interact")
    # `strafe` is deferred: it is not a channel and not a command field.
    assert "strafe" not in MOTOR_CHANNELS
    field_names = {f.name for f in fields(ControlCommand)}
    assert field_names == set(MOTOR_CHANNELS)
    assert "strafe" not in field_names


def test_emitted_scalars_are_clamped_to_range():
    # Free every DOF so clamping (not masking) is what bounds the values.
    surface = _active(ContinuousMotorSurface(
        policy=_FakePolicy(drive=5.0, yaw_rate=-9.0, gaze_yaw=3.0,
                           gaze_pitch=-3.0, interact=7.0),
        curriculum=MotorCurriculum(),  # advance below
    ))
    # Force the curriculum to the final stage so all channels are free.
    while not surface.curriculum.at_final_stage():
        surface.curriculum._stage_index += 1  # test-only fast-forward
    cmd = surface.emit()
    ch = cmd.channels()
    assert ch["drive"] == 1.0 and ch["yaw_rate"] == -1.0
    assert ch["gaze_yaw"] == 1.0 and ch["gaze_pitch"] == -1.0
    # interact is a single non-negative trigger clamped to [0, 1].
    assert ch["interact"] == 1.0
    assert "strafe" not in ch


def test_interact_is_a_single_non_negative_trigger():
    lo_hi = clamp_channel("interact", -4.0), clamp_channel("interact", 4.0)
    assert lo_hi == (0.0, 1.0)


# ---- W9.1 gaze decoupled from the body --------------------------------------

def test_gaze_moves_without_body_motion():
    # A policy that only looks (no drive/yaw). Gaze must be free, so advance to M2.
    surface = _active(ContinuousMotorSurface(
        policy=_FakePolicy(gaze_yaw=0.5, gaze_pitch=-0.4),
    ))
    surface.curriculum._stage_index = 1  # M2: gaze freed
    cmd = surface.emit()
    ch = cmd.channels()
    # Gaze shifted...
    assert ch["gaze_yaw"] == 0.5 and ch["gaze_pitch"] == -0.4
    # ...while the body did not move.
    assert ch["drive"] == 0.0 and ch["yaw_rate"] == 0.0


# ---- W9.2 symbolic verbs are not the entity's surface -----------------------

def test_surface_cannot_emit_symbolic_verbs():
    """The producer's only output is the continuous command — there is no API by
    which the learned policy emits teleport/sit_on/autopilot/animate/gesture."""
    surface = ContinuousMotorSurface()
    payload = surface.intent_payload(surface.emit())
    # The intent payload carries ONLY continuous channels, nothing symbolic.
    assert set(payload) == {"channels"}
    assert set(payload["channels"]) == set(MOTOR_CHANNELS)
    for verb in ("teleport", "sit_on", "autopilot", "animate", "gesture", "stand"):
        assert verb not in payload["channels"]
    # And ControlCommand has no field/method that names a symbolic verb.
    for verb in ("teleport", "sit_on", "animate", "gesture"):
        assert not hasattr(ControlCommand(), verb)


@pytest.mark.asyncio
async def test_control_intent_routes_to_setpoints_not_symbolic_action(bus):
    """`intent.avatar.control` drives the continuous setpoint sink, never the
    symbolic `apply_action` path."""
    adapter = StubAdapter()
    m = Mundus(bus, adapter=adapter, enabled=True,
               continuous_expose={"drive": True, "yaw_rate": True},
               mirror_speech=False, locus_reader=lambda: "virtual")
    await m._drive_control({"drive": 0.5, "yaw_rate": -0.5})
    assert adapter.setpoints == [{"drive": 0.5, "yaw_rate": -0.5}]
    assert adapter.actions == []  # nothing went through the symbolic verb path


@pytest.mark.asyncio
async def test_operator_symbolic_verb_still_reaches_apply_action(bus):
    """The symbolic verbs remain available as operator tools (exposed → applied),
    distinct from the entity's continuous surface."""
    adapter = StubAdapter()  # exposes `say`, `gesture` by default
    m = Mundus(bus, adapter=adapter, enabled=True, mirror_speech=False,
               locus_reader=lambda: "virtual")
    ok = await m._send_action("gesture", name="wave")
    assert ok is True
    assert adapter.actions == [("gesture", {"name": "wave"})]


# ---- W9.3 closed loop: efference copy + proprioception, forward-model reuse ---

@pytest.mark.asyncio
async def test_control_tick_publishes_efference_copy(bus):
    """Every control tick emits a time-aligned efference copy on the bus."""
    adapter = StubAdapter()
    m = Mundus(bus, adapter=adapter, enabled=True,
               continuous_expose={"drive": True}, mirror_speech=False,
               locus_reader=lambda: "virtual")
    await m._drive_control({"drive": 2.0})  # over-range → clamped in efference
    seen = {ev.type: ev for _id, ev in await bus.read("mundus.out", last_id="0", count=50)}
    assert "mundus.efference" in seen
    eff = seen["mundus.efference"].payload
    assert eff["channels"]["drive"] == 1.0  # clamped efference copy
    assert eff["forwarded"] is True


def test_closed_loop_uses_existing_forward_model_no_new_learner():
    loop = EfferenceLoop()
    # The loop reuses Soma's SubstrateForwardModel — it adds no new learner.
    assert isinstance(loop.forward_model, SubstrateForwardModel)
    # No torch.nn.Module subclass is defined in the control-surface module.
    import torch.nn as nn

    defined_here = [
        obj for _n, obj in inspect.getmembers(cs, inspect.isclass)
        if obj.__module__ == cs.__name__
    ]
    assert not any(issubclass(c, nn.Module) for c in defined_here)


def test_efference_loop_requires_feedback_to_close():
    """A forward-model step needs the coupled feedback vector; the loop feeds the
    efference copy AND the proprioceptive feedback together."""
    loop = EfferenceLoop()
    dim = loop.forward_model.feature_dim
    # 5 command channels + 6 proprioception scalars.
    assert dim == len(MOTOR_CHANNELS) + 6
    err = loop.observe(ControlCommand(drive=0.5), MotorFeedback(forward_velocity=0.1))
    assert err >= 0.0


# ---- W9.4 curriculum: birth minimal, freed by competence not time ------------

def test_birth_starts_with_drive_and_yaw_only():
    cur = MotorCurriculum()
    assert cur.stage == 0
    assert cur.free_channels() == frozenset({"drive", "yaw_rate"})
    assert MOTOR_STAGES[0] == ("drive", "yaw_rate")


def test_dof_frees_only_on_demonstrated_competence():
    # Threshold trivially satisfied → advances after min_samples.
    cur = MotorCurriculum(competence_threshold=1e9, min_samples=4, window=8)
    surface = _active(ContinuousMotorSurface(curriculum=cur))
    for _ in range(4):
        surface.observe_feedback(ControlCommand(drive=0.3),
                                 MotorFeedback(forward_velocity=0.1))
    assert cur.stage == 1
    assert "gaze_yaw" in cur.free_channels()


def test_dof_does_not_free_on_elapsed_time_without_competence():
    # Impossible threshold → never advances no matter how many ticks elapse.
    cur = MotorCurriculum(competence_threshold=1e-12, min_samples=4, window=8)
    surface = _active(ContinuousMotorSurface(curriculum=cur))
    for _ in range(200):
        surface.observe_feedback(ControlCommand(drive=0.9),
                                 MotorFeedback(forward_velocity=0.5))
    assert cur.stage == 0  # elapsed time alone never frees a DOF
    assert cur.free_channels() == frozenset({"drive", "yaw_rate"})


def test_competence_readout_needs_min_samples():
    cur = MotorCurriculum(min_samples=5, window=10)
    for _ in range(4):
        cur.record(0.001)
    assert cur.competence() is None  # too few samples to judge
    cur.record(0.001)
    assert cur.competence() is not None


# ---- W9.5 safety: inert without gates, inhibition zeroes, clamped ------------

def test_surface_is_inert_before_birth_handoff():
    surface = ContinuousMotorSurface(policy=_FakePolicy(drive=1.0, yaw_rate=1.0))
    assert surface.active is False
    assert surface.emit().is_zero()  # inert before birth
    surface.on_birth()
    assert surface.active is True
    assert not surface.emit().is_zero()  # active after birth


def test_inhibition_zeroes_the_action():
    surface = _active(ContinuousMotorSurface(
        policy=_FakePolicy(drive=1.0, yaw_rate=-1.0)))
    assert not surface.emit(inhibited=False).is_zero()
    assert surface.emit(inhibited=True).is_zero()  # inhibition → null command


@pytest.mark.asyncio
async def test_forwarding_inert_when_locus_not_virtual(bus):
    adapter = StubAdapter()
    m = Mundus(bus, adapter=adapter, enabled=True,
               continuous_expose={"drive": True}, mirror_speech=False,
               locus_reader=lambda: "physical")
    forwarded = await m._drive_control({"drive": 0.5})
    assert forwarded is False
    assert adapter.setpoints == []  # nothing reaches the body off-locus


@pytest.mark.asyncio
async def test_forwarding_inert_when_channel_unexposed(bus):
    adapter = StubAdapter()
    m = Mundus(bus, adapter=adapter, enabled=True, mirror_speech=False,
               locus_reader=lambda: "virtual")  # no continuous_expose → all off
    forwarded = await m._drive_control({"drive": 0.5})
    assert forwarded is False
    assert adapter.setpoints == []


# ---- W9.6 emergent: no scripted gait / intent->effect mapping ----------------

def test_default_policy_is_quiescent_no_scripted_gait():
    """The built-in default policy scripts NO gait — it emits nothing, so any
    motion must come from an injected (learned) policy."""
    surface = _active(ContinuousMotorSurface())
    assert isinstance(surface.policy, QuiescentMotorPolicy)
    # Even fully active and un-inhibited, the default surface produces no motion.
    assert surface.emit().is_zero()
    for _ in range(50):
        assert surface.emit().is_zero()


def test_provided_scaffold_is_cited_in_source():
    """The provided action-space structure + freeze-then-free progression cite
    the developmental-motor-learning basis at the code site (design §9)."""
    src = inspect.getsource(cs)
    assert "Bernstein" in src
    assert "O'Regan" in src or "O'Regan & No" in src
    assert "Wolpert" in src


# ---- end-to-end: producer -> control plane -> body, closed with efference ----

@pytest.mark.asyncio
async def test_producer_to_body_via_intent_bus(bus, monkeypatch):
    """The producer emits `intent.avatar.control`; the control plane drives the
    body's setpoint sink and mirrors the efference copy — the producer gap
    closed end-to-end, no entity booted."""
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    adapter = StubAdapter()
    surface = _active(ContinuousMotorSurface(
        policy=_FakePolicy(drive=0.7, yaw_rate=-0.2)))
    m = Mundus(bus, adapter=adapter, enabled=True,
               continuous_expose={"drive": True, "yaw_rate": True},
               mirror_speech=False, locus_reader=lambda: "virtual")
    await m.initialize()
    try:
        cmd = surface.emit()
        await bus.publish(validate_event(
            source="volition", type="intent.avatar.control",
            payload=surface.intent_payload(cmd), salience=0.4,
            timestamp=datetime.now(timezone.utc)))
        # Wait for the setpoint to reach the stub body.
        import asyncio
        for _ in range(60):
            if adapter.setpoints:
                break
            await asyncio.sleep(0.05)
        assert adapter.setpoints == [{"drive": 0.7, "yaw_rate": -0.2}]
    finally:
        await m.shutdown()
