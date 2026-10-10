# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for broadcast-context conditioning of the perceptual forward models."""

from __future__ import annotations

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
