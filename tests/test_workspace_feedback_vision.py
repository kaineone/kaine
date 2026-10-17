# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for workspace feedback wiring in the vision module."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from kaine.boot.errors import ConfigurationError
from kaine.boot.factories.vision import make_vision
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.feedback import TopDownBlend
from kaine.modules.intensity import graded_intensity
from kaine.modules.positive_control import PositiveControlSettings
from kaine.modules.vision import Vision
from kaine.modules.vision.forward import LatentForwardModel
from kaine.workspace.feedback import FEEDBACK_KEY, WorkspaceFeedbackSettings


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class FakeCounterSmall:
    model_id = "fake/counter"
    latent_dim = 4
    clip_len = 1

    def __init__(self):
        self._n = 0

    async def load(self):
        return None

    async def shutdown(self):
        return None

    async def encode(self, image):  # noqa: ARG002
        self._n += 1
        # Keep every component finite and changing so prediction error is non-zero.
        return [
            0.1 + self._n * 0.01,
            0.2 - self._n * 0.005,
            0.3 + math.sin(self._n) * 0.01,
            0.4,
        ]

    async def encode_clip(self, frames):
        return await self.encode(frames[-1])


def _payloads(entries):
    return [event.payload for _, event in entries]


def _scrub(payload):
    """Remove clock-dependent keys before comparing payloads across runs."""
    copy = dict(payload)
    for key in ("entity_time_s", "context_age_s", "prediction_context_age_s"):
        copy.pop(key, None)
    return copy


def _feedback_snapshot(tick, *, gain=1.2, inhibited=False, seq=None):
    if seq is None:
        seq = [0.05] * 24
    return WorkspaceSnapshot(
        tick_index=tick,
        selected_events=[
            (
                "1-0",
                Event(
                    source="interoception",
                    type="interoception.report",
                    payload={"k": 1},
                    salience=0.6,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        ],
        inhibited=inhibited,
        salience_scores={"1-0": 0.5},
        metadata={
            "access_threshold": 0.35,
            "workspace_feedback": {
                "gains": {"vision": gain},
                "sequence_prediction": seq,
            },
        },
    )


class _FixedClock:
    """Entity-clock stand-in that never advances, so context ages are equal across runs."""

    def now(self) -> float:
        return 100.0

    def wall(self) -> float:
        return 100.0


async def _vision(bus, *, feedback=None, encoder=None):
    vision = Vision(
        bus,
        encoder=encoder or FakeCounterSmall(),
        forward_prediction=True,
        workspace_feedback=feedback,
        entity_clock=_FixedClock(),
    )
    await vision.initialize()
    vision._forward_model = LatentForwardModel(
        latent_dim=4,
        units=8,
        context_dim=24,
        seed=4,
    )
    return vision


@pytest.mark.asyncio
async def test_feedback_off_is_bit_for_bit(bus):
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    bus2 = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=fakeredis.FakeRedis(decode_responses=True),
    )
    try:
        vision_off = await _vision(bus)
        vision_none = await _vision(bus2, feedback=None)

        snapshot = _feedback_snapshot(1)
        for _ in range(5):
            await vision_off.on_workspace(snapshot)
            await vision_none.on_workspace(snapshot)
            await vision_off.process_frame(None)
            await vision_none.process_frame(None)

        entries1 = await bus.read("vision.out", last_id="0")
        entries2 = await bus2.read("vision.out", last_id="0")
        payloads1 = [_scrub(p) for p in _payloads(entries1)]
        payloads2 = [_scrub(p) for p in _payloads(entries2)]

        assert payloads1 == payloads2
        assert all(FEEDBACK_KEY not in p for p in payloads1)
        assert all(FEEDBACK_KEY not in p for p in payloads2)
    finally:
        await bus2.close()


@pytest.mark.asyncio
async def test_feedback_on_wraps_and_channel_adopts(bus):
    settings = WorkspaceFeedbackSettings.from_section({"enabled": True, "arm": "full"})
    vision = await _vision(bus, feedback=settings)

    assert not isinstance(vision._forward_model, TopDownBlend)
    await vision.process_frame(None)
    assert isinstance(vision._forward_model, TopDownBlend)

    entries = await bus.read("vision.out", last_id="0")
    payloads = _payloads(entries)
    assert len(payloads) == 1
    payload = payloads[0]
    assert FEEDBACK_KEY in payload
    feedback = payload[FEEDBACK_KEY]
    assert set(feedback.keys()) == {
        "disagreement",
        "error_ratio",
        "gain",
        "top_down_weight",
        "own_error",
        "top_down_error",
    }

    await vision.on_workspace(_feedback_snapshot(1, gain=1.2))
    assert vision._feedback_channel.gain == pytest.approx(1.2)
    assert vision._feedback_channel.sequence_prediction == tuple([0.05] * 24)

    # Inhibited broadcasts are ignored by the feedback channel.
    await vision.on_workspace(_feedback_snapshot(2, gain=0.9, inhibited=True))
    assert vision._feedback_channel.gain == pytest.approx(1.2)


@pytest.mark.asyncio
async def test_feedback_gain_on_intensity(bus):
    # arm "full" applies the adopted gain to the graded intensity.
    full_settings = WorkspaceFeedbackSettings.from_section({"enabled": True, "arm": "full"})
    vision_full = await _vision(bus, feedback=full_settings)
    await vision_full.on_workspace(_feedback_snapshot(1, gain=1.2))
    for _ in range(2):
        await vision_full.process_frame(None)

    entries = await bus.read("vision.out", last_id="0")
    for _, event in entries:
        payload = event.payload
        if not payload["alert"]:
            expected = graded_intensity(
                vision_full._baseline_salience,
                vision_full._alert_salience,
                1.2 * payload["normalised_error"],
            )
            assert event.salience == pytest.approx(expected)
            assert payload[FEEDBACK_KEY]["gain"] == pytest.approx(1.2)

    # arm "head_only" uses the ratio directly for intensity and reports gain 1.0.
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    bus2 = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=fakeredis.FakeRedis(decode_responses=True),
    )
    try:
        head_settings = WorkspaceFeedbackSettings.from_section(
            {"enabled": True, "arm": "head_only"}
        )
        vision_head = await _vision(bus2, feedback=head_settings)
        await vision_head.on_workspace(_feedback_snapshot(1, gain=1.2))
        await vision_head.process_frame(None)

        entries2 = await bus2.read("vision.out", last_id="0")
        event = entries2[0][1]
        payload = event.payload
        if not payload["alert"]:
            expected = graded_intensity(
                vision_head._baseline_salience,
                vision_head._alert_salience,
                payload["normalised_error"],
            )
            assert event.salience == pytest.approx(expected)
        assert payload[FEEDBACK_KEY]["gain"] == 1.0
    finally:
        await bus2.close()


@pytest.mark.asyncio
async def test_feedback_sequence_prediction_reaches_step(bus):
    settings = WorkspaceFeedbackSettings.from_section({"enabled": True, "arm": "full"})
    vision = await _vision(bus, feedback=settings)
    await vision.process_frame(None)  # triggers the TopDownBlend wrap
    assert isinstance(vision._forward_model, TopDownBlend)

    original_step = vision._forward_model.step
    seen_predictions = []

    def recording_step(*args, sequence_prediction=None, **kwargs):
        seen_predictions.append(sequence_prediction)
        return original_step(*args, sequence_prediction=sequence_prediction, **kwargs)

    vision._forward_model.step = recording_step

    await vision.process_frame(None)
    assert seen_predictions[-1] is None

    await vision.on_workspace(_feedback_snapshot(1, gain=1.0))
    seen_predictions.clear()
    await vision.process_frame(None)
    assert seen_predictions[-1] == tuple([0.05] * 24)


@pytest.mark.asyncio
async def test_feedback_positive_control_refusal_and_factory(bus):
    feedback_settings = WorkspaceFeedbackSettings.from_section(
        {"enabled": True, "arm": "full"}
    )
    pc_settings = PositiveControlSettings.from_config({"enabled": True, "mode": "estimate_pc"})

    with pytest.raises(ValueError, match="workspace feedback runs with the positive control off"):
        Vision(
            bus,
            encoder=FakeCounterSmall(),
            forward_prediction=True,
            workspace_feedback=feedback_settings,
            positive_control=pc_settings,
        )

    # Factory path: workspace_feedback on.
    vision = make_vision(
        bus,
        {"forward_prediction": True, "workspace_feedback": {"enabled": True, "arm": "full"}},
    )
    assert isinstance(vision, Vision)
    assert vision._feedback_settings is not None
    assert vision._feedback_settings.arm == "full"

    # Factory path: workspace_feedback off.
    vision_off = make_vision(
        bus,
        {"forward_prediction": True, "workspace_feedback": {"enabled": True, "arm": "off"}},
    )
    assert vision_off._feedback_settings is None

    # Factory path: invalid arm raises ConfigurationError.
    with pytest.raises(ConfigurationError):
        make_vision(
            bus,
            {
                "forward_prediction": True,
                "workspace_feedback": {"enabled": True, "arm": "invalid"},
            },
        )
