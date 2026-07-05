# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Opt-in real DINOv2 encoder test.

Loads facebook/dinov2-small from HuggingFace on first run (~85 MB
download). Skipped unless `KAINE_TOPOS_RUN_REAL_ENCODER=1` is set.
"""
import os

import pytest

from kaine.modules.topos.encoder import DINOv2Encoder

REAL_ENCODER_ENV = "KAINE_TOPOS_RUN_REAL_ENCODER"


@pytest.mark.skipif(
    os.environ.get(REAL_ENCODER_ENV) != "1",
    reason=f"set {REAL_ENCODER_ENV}=1 to run real-encoder tests",
)
@pytest.mark.asyncio
async def test_dinov2_loads_and_produces_384_dim_cls():
    enc = DINOv2Encoder(device_preference="cpu")
    await enc.load()
    try:
        assert enc.latent_dim == 384
        # All parameters frozen.
        for p in enc._model.parameters():
            assert p.requires_grad is False
        # Encode a small solid image and confirm the output shape.
        from PIL import Image

        img = Image.new("RGB", (32, 32), color=(128, 128, 128))
        vec = await enc.encode(img)
        assert len(vec) == 384
        assert all(isinstance(v, float) for v in vec)
    finally:
        await enc.shutdown()
