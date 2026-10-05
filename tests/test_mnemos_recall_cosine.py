# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.mnemos.embeddings import FakeEmbedder
from kaine.modules.mnemos.memory import MnemosCore
from kaine.modules.mnemos.storage import InMemoryStorage
from kaine.text_embedding_numpy import NumpyMiniLMEmbedder


@pytest.fixture
async def core():
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    c = MnemosCore(embedder=emb, storage=storage, short_term_capacity=8)
    await c.initialize()
    yield c
    await c.shutdown()


@pytest.mark.asyncio
async def test_second_recall_embeds_query_only(core: MnemosCore):
    await core.store("a sample memory text for testing recall caches")
    before = core.embedder.encode_count
    await core.recall("sample memory", k=2, collection="short_term")
    mid = core.embedder.encode_count
    await core.recall("another query", k=2, collection="short_term")
    after = core.embedder.encode_count

    # First recall: the query plus the one uncached entry.
    assert mid - before == 2
    # Second recall with no new entries: only the query is embedded.
    assert after - mid == 1


@pytest.mark.asyncio
async def test_store_short_term_never_embeds(core: MnemosCore):
    before = core.embedder.encode_count
    for i in range(5):
        await core.store(f"memory number {i}")
    assert core.embedder.encode_count == before
    assert core.short_term_size == 5


@pytest.mark.asyncio
async def test_empty_short_term_recall_embeds_nothing(core: MnemosCore):
    before = core.embedder.encode_count
    results, summary = await core.recall("anything", k=1, collection="short_term")
    assert results == []
    assert summary.count == 0
    assert core.embedder.encode_count == before


@pytest.mark.asyncio
async def test_export_state_short_term_entries_lack_embeddings(core: MnemosCore):
    await core.store("some text", payload={"x": 1}, affect={"intensity": 0.5})
    await core.recall("some", k=1, collection="short_term")
    state = await core.export_state()
    for entry in state["short_term"]:
        assert set(entry.keys()) == {"text", "payload", "affect", "timestamp"}


@pytest.mark.asyncio
async def test_embeddings_deque_length_bounded_by_capacity():
    cap = 2
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    c = MnemosCore(embedder=emb, storage=storage, short_term_capacity=cap)
    await c.initialize()
    try:
        for i in range(4):
            await c.store(f"memory {i}")
        assert c.short_term_size == cap
        assert len(c._short_term_embeddings) == cap
        assert len(c._short_term_embeddings) == len(c._short_term)
    finally:
        await c.shutdown()


@pytest.mark.asyncio
async def test_real_embedder_associative_recall():
    try:
        emb = NumpyMiniLMEmbedder()
        await emb.load()
    except FileNotFoundError as exc:
        pytest.skip(f"MiniLM weights not provisioned: {exc}")

    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    core = MnemosCore(embedder=emb, storage=storage, short_term_capacity=8)
    await core.initialize()
    try:
        await core.store("the kettle is boiling in the kitchen")
        await core.store("quarterly tax forms are due")
        results, _ = await core.recall(
            "water heating on the stove", k=1, collection="short_term"
        )
        assert len(results) == 1
        assert "kettle" in results[0].text
        assert results[0].score > 0.0
    finally:
        await core.shutdown()
