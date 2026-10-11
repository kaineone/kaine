# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for broadcast-context conditioning of the perceptual forward models."""

from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.audition.forward import AuditoryForwardModel
from kaine.modules.topos import Topos
from kaine.modules.topos.forward import LatentForwardModel


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class FakeSmall:
    model_id = "fake/small"
    latent_dim = 4
    clip_len = 1

    async def load(self):
        return None

    async def shutdown(self):
        return None

    async def encode(self, image):  # noqa: ARG002
        return [0.1, 0.2, 0.3, 0.4]

    async def encode_clip(self, frames):
        return await self.encode(frames[-1])


def test_legacy_checkpoint_restores_with_zero_context_weights():
    old = LatentForwardModel(latent_dim=4, units=8, seed=1)
    new = LatentForwardModel(latent_dim=4, units=8, context_dim=24, seed=2)
    assert new.matches_state_shape(old.state_dict())
    new.load_state_dict(old.state_dict())

    x = [0.1, 0.2, 0.3, 0.4]
    assert new.predict(x, [0.5] * 24) == pytest.approx(old.predict(x))

    old_audio = AuditoryForwardModel(feature_dim=8, units=4, seed=1)
    new_audio = AuditoryForwardModel(feature_dim=8, units=4, context_dim=24, seed=2)
    assert new_audio.matches_state_shape(old_audio.state_dict())
    new_audio.load_state_dict(old_audio.state_dict())

    x_audio = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]
    assert new_audio.predict(x_audio, [0.5] * 24) == pytest.approx(
        old_audio.predict(x_audio)
    )


def test_null_prediction_error_is_recorded():
    m = LatentForwardModel(latent_dim=4, units=8, context_dim=24, seed=3)
    ctx = [0.2] * 24
    x1 = [0.1, 0.2, 0.3, 0.4]
    x2 = [0.2, 0.3, 0.4, 0.5]
    m.step(x1, ctx, ctx)
    err = m.step(x2, ctx, ctx)
    assert m.last_scored_had_context is True
    assert m.last_null_error == pytest.approx(err)


def test_step_without_context_marks_no_context():
    m = LatentForwardModel(latent_dim=4, units=8, context_dim=24, seed=5)
    x1 = [0.1, 0.2, 0.3, 0.4]
    x2 = [0.2, 0.3, 0.4, 0.5]
    m.step(x1)
    m.step(x2)
    assert m.last_scored_had_context is False
    assert m.last_null_error is None


def test_context_dim_validation():
    with pytest.raises(ValueError):
        LatentForwardModel(latent_dim=4, units=8, context_dim=-1)


def _last_payload(entries):
    """Return the payload of the last entry from AsyncBus.read()."""
    if isinstance(entries, dict):
        item = list(entries.values())[-1]
    else:
        item = entries[-1]
    if isinstance(item, tuple):
        item = item[-1]
    return item.payload if hasattr(item, "payload") else item


@pytest.mark.asyncio
async def test_topos_reports_context_gain(bus):
    topos = Topos(bus, encoder=FakeSmall(), forward_prediction=True)
    topos._forward_model = LatentForwardModel(
        latent_dim=4, units=8, context_dim=24, seed=4
    )

    snapshot = WorkspaceSnapshot(
        tick_index=1,
        selected_events=[
            (
                "1-0",
                Event(
                    source="soma",
                    type="soma.report",
                    payload={"k": 1},
                    salience=0.6,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        ],
        inhibited=False,
        salience_scores={"1-0": 0.5},
        metadata={"access_threshold": 0.35},
    )
    await topos.on_workspace(snapshot)

    for _ in range(3):
        await topos.process_frame(None)

    entries = await bus.read("topos.out", last_id="0")
    payload = _last_payload(entries)
    assert "context_gain" in payload
    assert "context_age_s" in payload
    assert isinstance(payload["context_age_s"], float)
    assert payload["context_age_s"] >= 0


@pytest.mark.asyncio
async def test_topos_gain_is_zero_when_the_context_carries_nothing(bus):
    topos = Topos(bus, encoder=FakeSmall(), forward_prediction=True)
    topos._forward_model = LatentForwardModel(
        latent_dim=4, units=8, context_dim=24, seed=4
    )

    for i in range(4):
        snapshot = WorkspaceSnapshot(
            tick_index=i,
            selected_events=[
                (
                    f"{i}-0",
                    Event(
                        source="soma",
                        type="soma.report",
                        payload={"k": 1},
                        salience=0.5,
                        timestamp=datetime.now(timezone.utc),
                    ),
                )
            ],
            inhibited=False,
            salience_scores={f"{i}-0": 0.5},
            metadata={"access_threshold": 0.35},
        )
        await topos.on_workspace(snapshot)
        await topos.process_frame(None)

    entries = await bus.read("topos.out", last_id="0")
    payload = _last_payload(entries)
    assert payload["context_gain"] == 0.0
    assert payload["null_prediction_error"] == payload["prediction_error"]
    assert payload["mean_prediction_error"] > 0.0


@pytest.mark.asyncio
async def test_topos_report_carries_the_paired_evaluations(bus):
    topos = Topos(bus, encoder=FakeSmall(), forward_prediction=True)
    topos._forward_model = LatentForwardModel(
        latent_dim=4, units=8, context_dim=24, seed=4
    )

    first = WorkspaceSnapshot(
        tick_index=1,
        selected_events=[
            (
                "1-0",
                Event(
                    source="soma",
                    type="soma.report",
                    payload={"k": 1},
                    salience=0.5,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        ],
        inhibited=False,
        salience_scores={"1-0": 0.5},
        metadata={"access_threshold": 0.35},
    )
    await topos.on_workspace(first)
    await topos.process_frame(None)

    second = WorkspaceSnapshot(
        tick_index=2,
        selected_events=[
            (
                "2-0",
                Event(
                    source="thymos",
                    type="thymos.report",
                    payload={"k": 1},
                    salience=0.75,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        ],
        inhibited=False,
        salience_scores={"2-0": 0.75},
        metadata={"access_threshold": 0.35},
    )
    await topos.on_workspace(second)
    await topos.process_frame(None)

    for _ in range(2):
        await topos.process_frame(None)

    entries = await bus.read("topos.out", last_id="0")
    payload = _last_payload(entries)
    assert isinstance(payload["null_prediction_error"], float)
    assert isinstance(payload["mean_prediction_error"], float)
    assert payload["context_gain"] == pytest.approx(
        (payload["null_prediction_error"] - payload["prediction_error"])
        / payload["mean_prediction_error"]
    )


def _non_finite_numbers(value):
    """Every non-finite number anywhere inside *value*."""
    if isinstance(value, bool):
        return []
    if isinstance(value, (int, float)):
        return [] if math.isfinite(value) else [value]
    if isinstance(value, dict):
        return [n for v in value.values() for n in _non_finite_numbers(v)]
    if isinstance(value, (list, tuple)):
        return [n for v in value for n in _non_finite_numbers(v)]
    return []


class _ScriptedEncoder(FakeSmall):
    """Returns the queued embeddings in order."""

    def __init__(self, embeddings):
        self._embeddings = list(embeddings)

    async def encode(self, image):  # noqa: ARG002
        return self._embeddings.pop(0)


@pytest.mark.asyncio
async def test_topos_skips_a_non_finite_latent(bus):
    torch = pytest.importorskip("torch")
    nan = float("nan")
    embeddings = [
        [0.1, 0.2, 0.3, 0.4],
        [0.2, 0.1, 0.4, 0.3],
        [0.3, 0.3, 0.1, 0.2],
        [nan, 0.2, 0.3, 0.4],
        [0.4, 0.1, 0.2, 0.3],
        [0.1, 0.4, 0.3, 0.2],
    ]

    topos = Topos(
        bus, encoder=_ScriptedEncoder(embeddings), forward_prediction=True
    )
    topos._forward_model = LatentForwardModel(
        latent_dim=4, units=8, context_dim=24, seed=4
    )

    snapshot = WorkspaceSnapshot(
        tick_index=1,
        selected_events=[
            (
                "1-0",
                Event(
                    source="soma",
                    type="soma.report",
                    payload={"k": 1},
                    salience=0.6,
                    timestamp=datetime.now(timezone.utc),
                ),
            )
        ],
        inhibited=False,
        salience_scores={"1-0": 0.5},
        metadata={"access_threshold": 0.35},
    )
    await topos.on_workspace(snapshot)

    for _ in range(3):
        await topos.process_frame(None)

    model = topos._forward_model
    buffer_before = [list(v) for v in model._buffer]
    weights_before = [p.detach().clone() for p in model._net.parameters()]
    errors_before = list(topos._pred_errors)
    changes_before = list(topos._change_history)
    frames_before = [list(f) for f in topos._habituator._frames]

    await topos.process_frame(None)

    assert [list(v) for v in model._buffer] == buffer_before
    assert [list(f) for f in topos._habituator._frames] == frames_before
    for saved, current in zip(weights_before, model._net.parameters()):
        assert torch.equal(saved, current)
    assert list(topos._pred_errors) == errors_before
    assert list(topos._change_history) == changes_before

    for _ in range(2):
        await topos.process_frame(None)

    entries = await bus.read("topos.out", last_id="0", count=50)
    events = [e for _, e in entries if e.type == "topos.report"]
    assert len(events) == 6
    assert isinstance(events[2].payload["context_gain"], float)
    assert events[3].payload["context_gain"] is None
    assert events[3].payload["null_prediction_error"] is None
    assert events[3].payload["mean_prediction_error"] is None
    assert events[3].payload["prediction_error"] == 0.0
    assert events[3].payload["change_score"] == 0.0
    assert events[3].payload["alert"] is False
    assert events[3].salience == pytest.approx(topos._baseline_salience)
    assert events[4].payload["context_gain"] is None
    assert isinstance(events[5].payload["context_gain"], float)
    assert events[3].payload["latent"] is None
    assert events[3].payload["habituation_score"] == events[2].payload["habituation_score"]
    for event in events:
        assert _non_finite_numbers(event.payload) == []
