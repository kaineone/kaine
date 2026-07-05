# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.mnemos.storage import (
    InMemoryStorage,
    MemoryStorage,
    RecalledMemory,
)


@pytest.mark.asyncio
async def test_inmemory_protocol_satisfied():
    assert isinstance(InMemoryStorage(latent_dim=4), MemoryStorage)


@pytest.mark.asyncio
async def test_ensure_collection_idempotent():
    s = InMemoryStorage(latent_dim=4)
    await s.initialize()
    await s.ensure_collection("a")
    await s.ensure_collection("a")
    assert await s.count("a") == 0


@pytest.mark.asyncio
async def test_upsert_then_count():
    s = InMemoryStorage(latent_dim=4)
    await s.initialize()
    await s.ensure_collection("e")
    await s.upsert(
        "e",
        vector=[1.0, 0.0, 0.0, 0.0],
        text="hello",
        payload={"k": "v"},
        affect=None,
    )
    assert await s.count("e") == 1


@pytest.mark.asyncio
async def test_search_returns_top_k_by_cosine():
    s = InMemoryStorage(latent_dim=2)
    await s.ensure_collection("e")
    await s.upsert("e", vector=[1.0, 0.0], text="east", payload={}, affect=None)
    await s.upsert("e", vector=[0.0, 1.0], text="north", payload={}, affect=None)
    await s.upsert("e", vector=[-1.0, 0.0], text="west", payload={}, affect=None)
    results = await s.search("e", query_vector=[1.0, 0.0], limit=2)
    assert len(results) == 2
    texts = [r.text for r in results]
    assert texts[0] == "east"
    assert "west" not in texts


@pytest.mark.asyncio
async def test_search_missing_collection_returns_empty():
    s = InMemoryStorage(latent_dim=2)
    results = await s.search("nope", query_vector=[1.0, 0.0], limit=5)
    assert results == []


@pytest.mark.asyncio
async def test_vector_dim_mismatch_rejected():
    s = InMemoryStorage(latent_dim=4)
    await s.ensure_collection("e")
    with pytest.raises(ValueError):
        await s.upsert(
            "e",
            vector=[1.0, 0.0],
            text="bad",
            payload={},
            affect=None,
        )


@pytest.mark.asyncio
async def test_affect_roundtrips():
    s = InMemoryStorage(latent_dim=2)
    await s.ensure_collection("e")
    await s.upsert(
        "e",
        vector=[1.0, 0.0],
        text="x",
        payload={},
        affect={"valence": -0.7, "intensity": 0.8},
    )
    results = await s.search("e", query_vector=[1.0, 0.0], limit=1)
    assert results[0].affect == {"valence": -0.7, "intensity": 0.8}


@pytest.mark.asyncio
async def test_delete_removes_point():
    s = InMemoryStorage(latent_dim=2)
    await s.ensure_collection("e")
    pid = await s.upsert("e", vector=[1.0, 0.0], text="x", payload={}, affect=None)
    assert await s.count("e") == 1
    await s.delete("e", pid)
    assert await s.count("e") == 0


def test_qdrant_storage_requires_api_key():
    from kaine.modules.mnemos.storage import QdrantStorage
    with pytest.raises(ValueError):
        QdrantStorage(latent_dim=4, api_key="")


def test_recalled_memory_dataclass_frozen():
    r = RecalledMemory(point_id="x", score=0.5, text="t", payload={})
    with pytest.raises(Exception):
        r.score = 0.9  # type: ignore[misc]
