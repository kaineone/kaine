# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.mnemos.embeddings import Embedder, FakeEmbedder


def test_fake_satisfies_protocol():
    assert isinstance(FakeEmbedder(), Embedder)


def test_invalid_dim_rejected():
    with pytest.raises(ValueError):
        FakeEmbedder(latent_dim=0)
    with pytest.raises(ValueError):
        FakeEmbedder(latent_dim=128)


@pytest.mark.asyncio
async def test_fake_encode_is_deterministic():
    e = FakeEmbedder()
    a = await e.encode("hello")
    b = await e.encode("hello")
    assert a == b


@pytest.mark.asyncio
async def test_fake_encode_distinguishes_strings():
    e = FakeEmbedder()
    a = await e.encode("hello")
    b = await e.encode("goodbye")
    assert a != b


@pytest.mark.asyncio
async def test_fake_encode_dim_matches_latent_dim():
    e = FakeEmbedder(latent_dim=32)
    vec = await e.encode("text")
    assert len(vec) == 32


@pytest.mark.asyncio
async def test_fake_batch_path():
    e = FakeEmbedder()
    out = await e.encode_batch(["a", "b", "a"])
    assert len(out) == 3
    assert out[0] == out[2]
    assert out[0] != out[1]


@pytest.mark.asyncio
async def test_fake_lifecycle():
    e = FakeEmbedder()
    assert e.loaded is False
    await e.load()
    assert e.loaded is True
    await e.shutdown()
    assert e.shutdown_called is True


def test_fake_model_id_default():
    assert FakeEmbedder().model_id == "fake/embedder"
