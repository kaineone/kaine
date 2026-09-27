# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the shared text embedder machinery."""

from __future__ import annotations

import asyncio

import pytest

from kaine.boot import build_registry, construct_module
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.config import ConfigShapeError, validate_config_shape
from kaine.text_embedding import (
    EMBEDDING_ALLOWED_KEYS,
    EMBEDDING_BACKENDS,
    SharedEmbedder,
    make_text_embedder,
    resolve_embedding_config,
)
from kaine.text_embedding_numpy import NumpyMiniLMEmbedder


class _FakeInner:
    kind: str = "fake"

    def __init__(self, latent_dim: int = 8, model_id: str = "fake/inner") -> None:
        self.latent_dim = latent_dim
        self.model_id = model_id
        self.load_count = 0
        self.encode_count = 0
        self.shutdown_called = False

    async def load(self) -> None:
        self.load_count += 1

    async def encode(self, text: str) -> list[float]:
        self.encode_count += 1
        return [float(ord(c)) / 255.0 for c in text[: self.latent_dim]]

    async def encode_batch(self, texts: list[str]) -> list[list[float]]:
        return [await self.encode(t) for t in texts]

    async def shutdown(self) -> None:
        self.shutdown_called = True


@pytest.mark.asyncio
async def test_shared_embedder_loads_inner_once():
    inner = _FakeInner()
    shared = SharedEmbedder(inner)

    await asyncio.gather(shared.load(), shared.load(), shared.load())

    assert inner.load_count == 1
    assert shared._loaded is True


@pytest.mark.asyncio
async def test_shared_embedder_retries_after_failed_load():
    class _FailingInner(_FakeInner):
        def __init__(self) -> None:
            super().__init__()
            self.attempts = 0
            self._fail_next = True

        async def load(self) -> None:
            self.attempts += 1
            if self._fail_next:
                self._fail_next = False
                raise RuntimeError("load failed")
            await super().load()

    inner = _FailingInner()
    shared = SharedEmbedder(inner)

    with pytest.raises(RuntimeError):
        await shared.load()

    await shared.load()

    assert inner.attempts == 2
    assert inner.load_count == 1  # only the successful load counted
    assert shared._loaded is True

    # Once loaded, subsequent calls must be cached and not re-invoke inner.load().
    await shared.load()
    assert inner.attempts == 2
    assert inner.load_count == 1


@pytest.mark.asyncio
async def test_shared_embedder_shutdown_is_no_op():
    inner = _FakeInner()
    shared = SharedEmbedder(inner)
    await shared.shutdown()
    assert inner.shutdown_called is False


@pytest.mark.asyncio
async def test_shared_embedder_forwards_methods_and_properties():
    inner = _FakeInner(latent_dim=4, model_id="fake/model")
    shared = SharedEmbedder(inner)

    assert shared.latent_dim == 4
    assert shared.model_id == "fake/model"
    assert shared.kind == "fake"

    vec = await shared.encode("hi")
    assert vec == await inner.encode("hi")
    assert inner.encode_count == 2

    batch = await shared.encode_batch(["a", "b"])
    assert batch == [await inner.encode("a"), await inner.encode("b")]


@pytest.mark.asyncio
async def test_shared_embedder_embed_falls_back_to_encode():
    class _NoEmbedInner(_FakeInner):
        async def encode(self, text: str) -> list[float]:
            return [1.0, 2.0, 3.0]

    inner = _NoEmbedInner()
    shared = SharedEmbedder(inner)

    assert await shared.embed("x") == [1.0, 2.0, 3.0]


def test_resolve_embedding_config_defaults():
    cfg = resolve_embedding_config({})
    assert cfg == {
        "backend": "numpy",
        "model_id": "sentence-transformers/all-MiniLM-L6-v2",
        "device": "cpu",
        "model_path": None,
    }


def test_resolve_embedding_config_rejects_unknown_keys():
    with pytest.raises(ValueError) as exc:
        resolve_embedding_config({"embedding": {"backend": "numpy", "secret": "x"}})
    assert "unknown [embedding] config keys" in str(exc.value)
    assert "secret" in str(exc.value)
    assert str(sorted(EMBEDDING_ALLOWED_KEYS)) in str(exc.value)


def test_resolve_embedding_config_rejects_unknown_backend():
    with pytest.raises(ValueError) as exc:
        resolve_embedding_config({"embedding": {"backend": "magic"}})
    assert "magic" in str(exc.value)
    assert str(EMBEDDING_BACKENDS) in str(exc.value)


def test_make_text_embedder_defaults_to_numpy_backend():
    embedder = make_text_embedder({})
    assert isinstance(embedder, NumpyMiniLMEmbedder)
    assert embedder.model_id == "sentence-transformers/all-MiniLM-L6-v2"


def test_make_text_embedder_can_build_sentence_transformers_backend():
    from kaine.text_embedding import SentenceTransformerTextEmbedder

    embedder = make_text_embedder(
        {"embedding": {"backend": "sentence_transformers", "device": "cpu"}}
    )
    assert isinstance(embedder, SentenceTransformerTextEmbedder)
    assert embedder.model_id == "sentence-transformers/all-MiniLM-L6-v2"
    assert embedder._device_preference == "cpu"


def test_boot_wires_same_shared_embedder_for_modules_and_spot_rebuild():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)

    config = {
        "modules": {"mnemos": True, "empatheia": True},
        "mnemos": {"backend": "inmemory"},
        "empatheia": {"backend": "inmemory"},
    }

    registry = build_registry(bus, config)

    shared = registry.shared_embedder
    assert isinstance(shared, SharedEmbedder)

    mnemos = registry.get("mnemos")
    assert mnemos._core._embedder is shared

    # Spot rebuild of the same module must receive the existing instance.
    mnemos2 = construct_module("mnemos", bus, config, registry=registry)
    assert mnemos2._core._embedder is shared


@pytest.mark.asyncio
async def test_shared_methods_load_inner_once():
    inner = _FakeInner()
    shared = SharedEmbedder(inner)

    await asyncio.gather(
        shared.encode("a"),
        shared.encode_batch(["b", "c"]),
        shared.embed("d"),
    )

    assert inner.load_count == 1
    assert inner.encode_count == 4


@pytest.mark.asyncio
async def test_shared_encode_batch_empty_skips_load():
    inner = _FakeInner()
    shared = SharedEmbedder(inner)

    result = await shared.encode_batch([])
    assert result == []
    assert inner.load_count == 0
    assert inner.encode_count == 0


@pytest.mark.asyncio
async def test_shared_encode_raises_when_inner_load_fails():
    class _FailingInner(_FakeInner):
        async def load(self) -> None:
            raise RuntimeError("load failed")

    inner = _FailingInner()
    shared = SharedEmbedder(inner)

    with pytest.raises(RuntimeError, match="load failed"):
        await shared.encode("hi")

    assert inner.encode_count == 0


def test_shared_getattr_forwards_inner_attribute():
    class _DeviceInner(_FakeInner):
        device = "cpu"

    inner = _DeviceInner()
    shared = SharedEmbedder(inner)
    assert shared.device == "cpu"
    assert shared._inner is inner
    with pytest.raises(AttributeError):
        shared.no_such_attribute


def test_validate_config_shape_rejects_bad_embedding_model_id_type():
    with pytest.raises(ConfigShapeError) as exc:
        validate_config_shape({"embedding": {"model_id": 3}})
    assert "embedding.model_id" in str(exc.value)
    assert "expected string" in str(exc.value)
