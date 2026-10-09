# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for precision-weighted spatial saliency and foveated clip encoding."""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.topos import Topos
from kaine.modules.topos.foveation import FoveaTarget, SpatialSaliency, select_fovea, tile_change

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("cv2") is None,
    reason="requires cv2",
)


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _make_frame(t00, t33, base=100):
    frame = np.full((64, 64, 3), base, dtype=np.uint8)
    frame[0:16, 0:16] = t00
    frame[48:64, 48:64] = t33
    return frame


def test_precision_weighting_upweights_rare_change():
    sal = SpatialSaliency((4, 4))
    frames = [_make_frame(0, 100)]
    # Frames 2-31: (0,0) alternates grey, (3,3) stays constant.
    for i in range(2, 32):
        t00 = 200 if i % 2 == 0 else 0
        frames.append(_make_frame(t00, 100))
    # Frame 32: rare change at (3,3).
    frames.append(_make_frame(200, 140))

    out = None
    for f in frames:
        out = sal.observe(f)
    assert out is not None
    assert np.unravel_index(int(np.argmax(out)), out.shape) == (3, 3)

    prev_tiles = tile_change(frames[-2], None, grid=(4, 4))[1]
    raw, _ = tile_change(frames[-1], prev_tiles, grid=(4, 4))
    assert np.unravel_index(int(np.argmax(raw)), raw.shape) == (0, 0)


def test_warmup_returns_raw_change():
    sal = SpatialSaliency((4, 4), warmup=5)
    frames = [np.full((64, 64, 3), i * 20, dtype=np.uint8) for i in range(7)]
    prev_tiles = None
    for i, f in enumerate(frames):
        out = sal.observe(f)
        if i == 0:
            prev_tiles = sal._prev
            continue
        if i <= 5:
            raw, prev_tiles = tile_change(f, prev_tiles, grid=(4, 4))
            assert np.allclose(out, raw, rtol=1e-5, atol=1e-6)


def test_output_is_nonnegative_and_finite():
    sal = SpatialSaliency((4, 4))
    rng = np.random.default_rng(0)
    for _ in range(20):
        f = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
        out = sal.observe(f)
        assert np.all(out >= 0.0)
        assert np.all(np.isfinite(out))


def test_invalid_constructor_args_raise():
    with pytest.raises(ValueError):
        SpatialSaliency((4, 4), alpha=0.0)
    with pytest.raises(ValueError):
        SpatialSaliency((4, 4), alpha=1.5)
    with pytest.raises(ValueError):
        SpatialSaliency((4, 4), warmup=-1)
    with pytest.raises(ValueError):
        SpatialSaliency((4, 4), floor_fraction=0.0)
    with pytest.raises(ValueError):
        SpatialSaliency((4, 4), floor_fraction=-0.1)


class FakeClipEncoder:
    model_id = "fake/clip-encoder"
    latent_dim = 4
    clip_len = 4

    def __init__(self) -> None:
        self.calls = []
        self.loaded = False

    async def load(self) -> None:
        self.loaded = True

    async def shutdown(self) -> None:
        pass

    async def encode(self, image):
        raise NotImplementedError("clip encoder uses encode_clip")

    async def encode_clip(self, frames):
        self.calls.append([f.copy() for f in frames])
        return [1.0, 0.0, 0.0, 0.0]


@pytest.mark.asyncio
async def test_module_foveates_every_buffered_frame(bus):
    enc = FakeClipEncoder()
    topos = Topos(bus, encoder=enc, foveation_enabled=True, clip_stride=1)
    for i in range(4):
        frame = np.full((64, 64, 3), i * 50, dtype=np.uint8)
        await topos.process_frame(frame)
    assert len(enc.calls) == 2
    assert len(enc.calls[0]) == 4
    assert any(not np.array_equal(enc.calls[0][0], enc.calls[0][i]) for i in range(1, 4))


def test_select_fovea_holds_on_flat_map():
    flat = np.zeros((4, 4))
    prev = FoveaTarget(0.2, 0.7, 0.3)
    target = select_fovea(flat, prev=prev)
    assert target.x == 0.2
    assert target.y == 0.7

    centre = select_fovea(flat, prev=None)
    assert centre.x == 0.5
    assert centre.y == 0.5
