# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Embedding-space stamps: every memory store records its vector space."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
import math
import random
import types
from pathlib import Path
from typing import Any, Iterable

import pytest

from kaine.embedding_defaults import (
    DEFAULT_LATENT_DIM,
    DEFAULT_MODEL_ID,
    LEGACY_EMBEDDING_SPACE,
)
from kaine.lifecycle.strategies import MnemosMergeStrategy
from kaine.memory_kinds import MNEMOS_STAMP_COLLECTION
from kaine.modules.mnemos import MnemosCore
from kaine.modules.mnemos.storage import (
    InMemoryStorage,
    QdrantStorage,
    SqliteVecStorage,
    StorageError,
)
from kaine.text_embedding import (
    FakeEmbedder,
    SentenceTransformerTextEmbedder,
    SharedEmbedder,
    same_space,
)
from kaine.text_embedding_numpy import NumpyMiniLMEmbedder
from tests.test_scoped_memory_preservation import _FakeAsyncQdrant

HAS_QDRANT = importlib.util.find_spec("qdrant_client") is not None
HAS_SQLITE_VEC = importlib.util.find_spec("sqlite_vec") is not None


class _LegacySpaceEmbedder:
    """384-dim deterministic embedder whose space is the legacy MiniLM space."""

    latent_dim = DEFAULT_LATENT_DIM
    model_id = DEFAULT_MODEL_ID

    def __init__(self) -> None:
        self.loaded = False
        self.shutdown_called = False
        self.encode_count = 0

    @property
    def space(self) -> dict[str, Any]:
        return dict(LEGACY_EMBEDDING_SPACE)

    async def load(self) -> None:
        self.loaded = True

    async def encode(self, text: str) -> list[float]:
        if not self.loaded:
            await self.load()
        self.encode_count += 1
        seed = int.from_bytes(
            hashlib.blake2b(text.encode("utf-8"), digest_size=16).digest(),
            "big",
        )
        rng = random.Random(seed)
        vec = [(rng.random() * 2.0 - 1.0) for _ in range(self.latent_dim)]
        norm = math.sqrt(sum(v * v for v in vec))
        if norm == 0:
            norm = 1.0
        return [v / norm for v in vec]

    async def encode_batch(self, texts: Iterable[str]) -> list[list[float]]:
        return [await self.encode(t) for t in texts]

    async def shutdown(self) -> None:
        self.shutdown_called = True


class _OtherSpaceEmbedder(_LegacySpaceEmbedder):
    """384-dim embedder with a space that differs from the legacy space."""

    model_id = "other-384"

    @property
    def space(self) -> dict[str, Any]:
        return {
            "model_id": self.model_id,
            "dim": self.latent_dim,
            "pooling": "mean",
            "normalized": True,
        }


class _StampFakeQdrant(_FakeAsyncQdrant):
    """Qdrant double extended with the stamp retrieve method."""

    async def retrieve(
        self,
        collection_name,
        ids,
        with_payload=True,
        with_vectors=False,
        **kwargs,
    ):
        pts = self.store.get(collection_name, [])
        wanted = {str(i) for i in ids}
        out = []
        for p in pts:
            if str(p.id) not in wanted:
                continue
            vector = p.vector if with_vectors else None
            payload = p.payload if with_payload else {}
            out.append(
                type(
                    "RetrievedPoint",
                    (),
                    {"id": p.id, "payload": payload, "vector": vector},
                )()
            )
        return out

    async def count(self, collection_name, **kwargs):
        # The real AsyncQdrantClient returns a CountResult with ``.count``.
        return types.SimpleNamespace(count=len(self.store.get(collection_name, [])))

    async def create_collection(self, collection_name, **kwargs):
        self.store.setdefault(collection_name, [])

    async def get_collection(self, collection_name, **kwargs):
        pts = self.store.get(collection_name, [])
        if pts:
            size = len(pts[0].vector)
        else:
            size = int(getattr(self, "_default_dim", 1))
        return type(
            "CollectionInfo",
            (),
            {
                "config": type(
                    "Config",
                    (),
                    {
                        "params": type(
                            "Params",
                            (),
                            {
                                "vectors": type(
                                    "VectorParams", (), {"size": size}
                                )()
                            },
                        )()
                    },
                )()
            },
        )()


class _CountFailFakeQdrant(_StampFakeQdrant):
    async def count(self, collection_name, **kwargs):
        raise RuntimeError("count boom")


class _WrongDimFakeQdrant(_StampFakeQdrant):
    def __init__(self):
        super().__init__()
        self._default_dim = 768

    async def count(self, collection_name, **kwargs):
        if collection_name.startswith("mnemos_"):
            return types.SimpleNamespace(count=1)
        return await super().count(collection_name, **kwargs)


class _RaceCreateFakeQdrant(_StampFakeQdrant):
    def __init__(self):
        super().__init__()
        self._create_attempts = 0

    async def create_collection(self, collection_name, **kwargs):
        self._create_attempts += 1
        if (
            collection_name == MNEMOS_STAMP_COLLECTION
            and self._create_attempts == 1
        ):
            self.store.setdefault(collection_name, [])
            raise RuntimeError("concurrent kaine_meta creation")
        await super().create_collection(collection_name, **kwargs)


@pytest.mark.asyncio
async def test_empty_store_initializes_stamp():
    embedder = FakeEmbedder(latent_dim=32)
    storage = InMemoryStorage(latent_dim=32)
    core = MnemosCore(embedder, storage)
    await core.initialize()
    stamp = await storage.read_stamp(core.stamp_key)
    assert same_space(stamp, embedder.space)


@pytest.mark.asyncio
async def test_matching_stamp_allows_initialize():
    embedder = FakeEmbedder(latent_dim=32)
    storage = InMemoryStorage(latent_dim=32)
    await storage.write_stamp("mnemos_embedding_space", embedder.space)
    core = MnemosCore(embedder, storage)
    await core.initialize()
    await storage.upsert(
        core.collection_name("episodic"),
        vector=[0.0] * 32,
        text="x",
        payload={},
        affect=None,
    )
    await core.initialize()
    assert await storage.count(core.collection_name("episodic")) == 1


@pytest.mark.asyncio
async def test_mismatched_stamp_refuses_initialize():
    embedder = FakeEmbedder(latent_dim=32)
    storage = InMemoryStorage(latent_dim=32)
    bad_stamp = {
        "model_id": "other-model",
        "dim": 32,
        "pooling": "mean",
        "normalized": True,
    }
    await storage.write_stamp("mnemos_embedding_space", bad_stamp)
    await storage.upsert(
        "mnemos_episodic",
        vector=[0.0] * 32,
        text="x",
        payload={},
        affect=None,
    )
    core = MnemosCore(embedder, storage)
    with pytest.raises(StorageError, match="re-embedded"):
        await core.initialize()
    assert await storage.count("mnemos_episodic") == 1


@pytest.mark.asyncio
async def test_legacy_store_stamped_with_warning(caplog):
    caplog.set_level(logging.WARNING)
    embedder = _LegacySpaceEmbedder()
    storage = InMemoryStorage(latent_dim=DEFAULT_LATENT_DIM)
    await storage.upsert(
        "mnemos_episodic",
        vector=[0.0] * DEFAULT_LATENT_DIM,
        text="legacy",
        payload={},
        affect=None,
    )
    core = MnemosCore(embedder, storage)
    await core.initialize()
    stamp = await storage.read_stamp(core.stamp_key)
    assert same_space(stamp, LEGACY_EMBEDDING_SPACE)
    assert any(
        "predates embedding-space stamps" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_legacy_store_refused_for_non_legacy_embedder():
    embedder = FakeEmbedder(latent_dim=32)
    storage = InMemoryStorage(latent_dim=32)
    await storage.upsert(
        "mnemos_episodic",
        vector=[0.0] * 32,
        text="legacy",
        payload={},
        affect=None,
    )
    core = MnemosCore(embedder, storage)
    with pytest.raises(StorageError, match="re-embedded"):
        await core.initialize()


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_QDRANT, reason="qdrant_client not installed")
async def test_qdrant_prefixes_keep_separate_stamps():
    fake = _StampFakeQdrant()
    storage_a = QdrantStorage(latent_dim=DEFAULT_LATENT_DIM, api_key="test")
    storage_a._client = fake
    storage_b = QdrantStorage(latent_dim=DEFAULT_LATENT_DIM, api_key="test")
    storage_b._client = fake

    embedder_a = _LegacySpaceEmbedder()
    embedder_b = _OtherSpaceEmbedder()

    core_a = MnemosCore(embedder_a, storage_a, collection_prefix="alpha_")
    core_b = MnemosCore(embedder_b, storage_b, collection_prefix="beta_")

    await core_a.initialize()
    await core_b.initialize()

    stamp_a = await storage_a.read_stamp(core_a.stamp_key)
    stamp_b = await storage_b.read_stamp(core_b.stamp_key)

    assert same_space(stamp_a, embedder_a.space)
    assert same_space(stamp_b, embedder_b.space)
    assert not same_space(stamp_a, stamp_b)


@pytest.mark.asyncio
async def test_import_refuses_mismatched_bundle_space():
    embedder = FakeEmbedder(latent_dim=32)
    storage = InMemoryStorage(latent_dim=32)
    core = MnemosCore(embedder, storage)
    await core.initialize()
    bundle = {
        "collection_prefix": "mnemos_",
        "embedding_space": {
            "model_id": "other",
            "dim": 32,
            "pooling": "mean",
            "normalized": True,
        },
        "persisted": {
            "mnemos_episodic": [
                {"id": "1", "vector": [0.0] * 32, "text": "x", "payload": {}}
            ],
        },
        "short_term": [],
    }
    with pytest.raises(StorageError, match="bundle embedding space"):
        await core.import_state(bundle)
    assert await storage.count(core.collection_name("episodic")) == 0


@pytest.mark.asyncio
async def test_import_legacy_bundle_without_space_stamps_running_space():
    embedder = _LegacySpaceEmbedder()
    storage = InMemoryStorage(latent_dim=DEFAULT_LATENT_DIM)
    core = MnemosCore(embedder, storage)
    await core.initialize()
    bundle = {
        "collection_prefix": "mnemos_",
        "persisted": {
            "mnemos_episodic": [
                {
                    "id": "1",
                    "vector": [0.0] * DEFAULT_LATENT_DIM,
                    "text": "x",
                    "payload": {},
                }
            ],
        },
        "short_term": [],
    }
    total = await core.import_state(bundle)
    assert total == 1
    stamp = await storage.read_stamp(core.stamp_key)
    assert same_space(stamp, embedder.space)


@pytest.mark.asyncio
async def test_export_includes_embedding_space():
    embedder = FakeEmbedder(latent_dim=32)
    storage = InMemoryStorage(latent_dim=32)
    core = MnemosCore(embedder, storage)
    await core.initialize()
    state = await core.export_state()
    assert "embedding_space" in state
    assert same_space(state["embedding_space"], embedder.space)


def test_same_space_compares_four_keys():
    base = {
        "model_id": "m",
        "dim": 10,
        "pooling": "mean",
        "normalized": True,
    }
    assert same_space(base, dict(base))
    assert not same_space(base, {**base, "dim": 11})
    assert not same_space(base, {**base, "model_id": "x"})
    assert not same_space(base, {**base, "pooling": "cls"})
    assert not same_space(base, {**base, "normalized": False})


def test_fake_embedder_space_shape():
    e = FakeEmbedder(latent_dim=48)
    assert e.space == {
        "model_id": "fake",
        "dim": 48,
        "pooling": "mean",
        "normalized": True,
    }


def test_shared_embedder_forwards_space():
    inner = FakeEmbedder(latent_dim=16)
    shared = SharedEmbedder(inner)
    assert shared.space == inner.space
    assert shared.space is not inner.space


def test_numpy_embedder_space_reads_dim_from_config(tmp_path: Path):
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({"hidden_size": 8}))
    e = NumpyMiniLMEmbedder(model_id="test", model_path=str(tmp_path))
    assert e.space["model_id"] == "sentence-transformers/test"
    assert e.space["dim"] == 8
    assert e.space["pooling"] == "mean"
    assert e.space["normalized"] is True


def test_sentence_transformer_space_before_load():
    pytest.importorskip("sentence_transformers")
    default = SentenceTransformerTextEmbedder(model_id=DEFAULT_MODEL_ID)
    assert default.space == {
        "model_id": DEFAULT_MODEL_ID,
        "dim": DEFAULT_LATENT_DIM,
        "pooling": "mean",
        "normalized": True,
    }
    other = SentenceTransformerTextEmbedder(
        model_id="sentence-transformers/all-MiniLM-L12-v2"
    )
    with pytest.raises(RuntimeError, match="embedding space unknown before load"):
        other.space


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_SQLITE_VEC, reason="sqlite_vec not installed")
async def test_sqlite_stamp_round_trip(tmp_path: Path):
    db = tmp_path / "mnemos.db"
    storage = SqliteVecStorage(latent_dim=32, db_path=str(db))
    await storage.initialize()
    stamp = {
        "model_id": "test",
        "dim": 32,
        "pooling": "mean",
        "normalized": True,
    }
    await storage.write_stamp("mnemos_embedding_space", stamp)
    read = await storage.read_stamp("mnemos_embedding_space")
    assert same_space(read, stamp)
    updated = {**stamp, "model_id": "updated"}
    await storage.write_stamp("mnemos_embedding_space", updated)
    read = await storage.read_stamp("mnemos_embedding_space")
    assert same_space(read, updated)
    assert await storage.read_stamp("missing_key") is None


@pytest.mark.asyncio
async def test_malformed_stamp_fails_loudly():
    embedder = FakeEmbedder(latent_dim=32)
    storage = InMemoryStorage(latent_dim=32)
    await storage.write_stamp(
        "mnemos_embedding_space",
        {"model_id": "x", "dim": 32, "normalized": True},
    )
    core = MnemosCore(embedder, storage)
    with pytest.raises(StorageError, match="malformed"):
        await core.initialize()


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_QDRANT, reason="qdrant_client not installed")
async def test_qdrant_read_stamp_missing_meta_returns_none_without_retrieve():
    class _NoRetrieveFake(_FakeAsyncQdrant):
        async def retrieve(self, *args, **kwargs):
            raise AssertionError("retrieve called unexpectedly")

    client = _NoRetrieveFake()
    storage = QdrantStorage(latent_dim=32, api_key="test")
    storage._client = client
    assert await storage.read_stamp("mnemos_embedding_space") is None


def test_space_uses_the_canonical_model_id(tmp_path: Path) -> None:
    from kaine.text_embedding import SentenceTransformerTextEmbedder
    from kaine.text_embedding_numpy import NumpyMiniLMEmbedder

    (tmp_path / "config.json").write_text(json.dumps({"hidden_size": 384}))
    short = NumpyMiniLMEmbedder("all-MiniLM-L6-v2", model_path=str(tmp_path))
    assert same_space(short.space, LEGACY_EMBEDDING_SPACE)
    st_short = SentenceTransformerTextEmbedder("all-MiniLM-L6-v2")
    assert same_space(st_short.space, LEGACY_EMBEDDING_SPACE)


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_QDRANT, reason="qdrant_client not installed")
async def test_strict_count_failure_raises_storage_error():
    fake = _CountFailFakeQdrant()
    storage = QdrantStorage(latent_dim=32, api_key="test")
    storage._client = fake
    embedder = FakeEmbedder(latent_dim=32)
    core = MnemosCore(embedder, storage)
    with pytest.raises(StorageError, match="count boom"):
        await core.initialize()
    assert await storage.read_stamp(core.stamp_key) is None


@pytest.mark.asyncio
async def test_legacy_store_with_wrong_dimension_refuses_in_memory():
    embedder = _LegacySpaceEmbedder()
    storage = InMemoryStorage(latent_dim=768)
    await storage.upsert(
        "mnemos_episodic",
        vector=[0.0] * 768,
        text="legacy-wrong-dim",
        payload={},
        affect=None,
    )
    core = MnemosCore(embedder, storage)
    with pytest.raises(StorageError, match="re-embedded"):
        await core.initialize()
    assert await storage.read_stamp(core.stamp_key) is None


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_QDRANT, reason="qdrant_client not installed")
async def test_legacy_store_with_wrong_dimension_refuses_qdrant():
    fake = _WrongDimFakeQdrant()
    storage = QdrantStorage(latent_dim=DEFAULT_LATENT_DIM, api_key="test")
    storage._client = fake
    embedder = _LegacySpaceEmbedder()
    core = MnemosCore(embedder, storage)
    with pytest.raises(StorageError, match="re-embedded"):
        await core.initialize()
    assert await storage.read_stamp(core.stamp_key) is None


@pytest.mark.asyncio
async def test_stale_stamp_on_empty_store_is_replaced(caplog):
    caplog.set_level(logging.WARNING)
    embedder = FakeEmbedder(latent_dim=32)
    storage = InMemoryStorage(latent_dim=32)
    stale_stamp = {
        "model_id": "other-model",
        "dim": 32,
        "pooling": "mean",
        "normalized": True,
    }
    await storage.write_stamp("mnemos_embedding_space", stale_stamp)
    core = MnemosCore(embedder, storage)
    await core.initialize()
    stamp = await storage.read_stamp(core.stamp_key)
    assert same_space(stamp, embedder.space)
    assert any(
        "stale embedding-space stamp" in record.message
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_stale_stamp_on_non_empty_store_refuses():
    embedder = FakeEmbedder(latent_dim=32)
    storage = InMemoryStorage(latent_dim=32)
    stale_stamp = {
        "model_id": "other-model",
        "dim": 32,
        "pooling": "mean",
        "normalized": True,
    }
    await storage.write_stamp("mnemos_embedding_space", stale_stamp)
    await storage.upsert(
        "mnemos_episodic",
        vector=[0.0] * 32,
        text="x",
        payload={},
        affect=None,
    )
    core = MnemosCore(embedder, storage)
    with pytest.raises(StorageError, match="re-embedded"):
        await core.initialize()


def test_merge_defaults_missing_space_to_legacy():
    strategy = MnemosMergeStrategy()
    a = {
        "short_term_size": 1,
        "collection_prefix": "mnemos_",
        "embedding_space": LEGACY_EMBEDDING_SPACE,
    }
    b = {"short_term_size": 2, "collection_prefix": "mnemos_"}
    out = strategy.merge(a, b)
    assert "embedding_space_mismatch" not in out.get("metadata", {})
    assert same_space(out["embedding_space"], LEGACY_EMBEDDING_SPACE)


def test_merge_flags_different_space_when_one_missing():
    strategy = MnemosMergeStrategy()
    a = {"short_term_size": 1, "collection_prefix": "mnemos_"}
    b = {
        "short_term_size": 2,
        "collection_prefix": "mnemos_",
        "embedding_space": {
            "model_id": "other-384",
            "dim": DEFAULT_LATENT_DIM,
            "pooling": "mean",
            "normalized": True,
        },
    }
    out = strategy.merge(a, b)
    assert out["metadata"]["embedding_space_mismatch"] is True
    assert same_space(out["embedding_space"], LEGACY_EMBEDDING_SPACE)


@pytest.mark.asyncio
async def test_stamp_tolerates_extra_keys_and_rejects_malformed():
    storage = InMemoryStorage(latent_dim=32)
    extra = {
        "model_id": "x",
        "dim": 32,
        "pooling": "mean",
        "normalized": True,
        "extra": 1,
    }
    await storage.write_stamp("mnemos_embedding_space", extra)
    read = await storage.read_stamp("mnemos_embedding_space")
    assert read == extra
    assert "extra" in read

    missing = {"model_id": "x", "dim": 32, "normalized": True}
    await storage.write_stamp("missing_key", missing)
    with pytest.raises(StorageError, match="malformed"):
        await storage.read_stamp("missing_key")

    bool_dim = {
        "model_id": "x",
        "dim": True,
        "pooling": "mean",
        "normalized": True,
    }
    await storage.write_stamp("bool_key", bool_dim)
    with pytest.raises(StorageError, match="malformed"):
        await storage.read_stamp("bool_key")


@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_QDRANT, reason="qdrant_client not installed")
async def test_qdrant_write_stamp_race_creating_meta_collection():
    fake = _RaceCreateFakeQdrant()
    storage = QdrantStorage(latent_dim=DEFAULT_LATENT_DIM, api_key="test")
    storage._client = fake
    stamp = {
        "model_id": "legacy",
        "dim": DEFAULT_LATENT_DIM,
        "pooling": "mean",
        "normalized": True,
    }
    await storage.write_stamp("mnemos_embedding_space", stamp)
    read = await storage.read_stamp("mnemos_embedding_space")
    assert same_space(read, stamp)
