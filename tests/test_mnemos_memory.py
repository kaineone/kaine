# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import pytest

from kaine.modules.mnemos.embeddings import FakeEmbedder
from kaine.modules.mnemos.memory import MnemosCore, RecallSummary
from kaine.modules.mnemos.storage import InMemoryStorage


@pytest.fixture
async def core():
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()
    storage = InMemoryStorage(latent_dim=emb.latent_dim)
    c = MnemosCore(embedder=emb, storage=storage, short_term_capacity=4)
    await c.initialize()
    yield c
    await c.shutdown()


@pytest.mark.asyncio
async def test_invalid_capacity_rejected():
    emb = FakeEmbedder(latent_dim=8)
    storage = InMemoryStorage(latent_dim=8)
    with pytest.raises(ValueError):
        MnemosCore(embedder=emb, storage=storage, short_term_capacity=0)


@pytest.mark.asyncio
async def test_short_term_store_and_size(core: MnemosCore):
    await core.store("first memory")
    await core.store("second memory")
    assert core.short_term_size == 2


@pytest.mark.asyncio
async def test_capacity_eviction_to_episodic(core: MnemosCore):
    for i in range(4):
        await core.store(f"memory {i}")
    assert core.short_term_size == 4
    # 5th store should evict the oldest into episodic.
    await core.store("memory 4")
    assert core.short_term_size == 4
    episodic_name = core.collection_name("episodic")
    assert await core.storage.count(episodic_name) == 1


@pytest.mark.asyncio
async def test_episodic_store_then_recall(core: MnemosCore):
    pid = await core.store("the cat sat on the mat", collection="episodic")
    assert pid is not None
    results, summary = await core.recall("the cat sat on the mat", k=1, collection="episodic")
    assert summary.count == 1
    assert len(results) == 1
    assert results[0].text == "the cat sat on the mat"


@pytest.mark.asyncio
async def test_recall_triggers_hook(core: MnemosCore):
    captured: list[RecallSummary] = []

    async def hook(summary: RecallSummary):
        captured.append(summary)

    core._hook = hook
    await core.store(
        "a fearful memory",
        affect={"valence": -0.8, "intensity": 0.9, "label": "fear"},
        collection="episodic",
    )
    _, summary = await core.recall("fearful", k=1, collection="episodic")
    assert len(captured) == 1
    assert captured[0].max_affect_intensity == 0.9
    assert captured[0].count == 1


@pytest.mark.asyncio
async def test_consolidate_now_empties_short_term(core: MnemosCore):
    for i in range(3):
        await core.store(f"memory {i}")
    assert core.short_term_size == 3
    moved = await core.consolidate_now()
    assert moved == 3
    assert core.short_term_size == 0
    assert await core.storage.count(core.collection_name("episodic")) == 3


@pytest.mark.asyncio
async def test_short_term_recall_uses_substring(core: MnemosCore):
    await core.store("the cat is on the mat")
    await core.store("the dog is at the door")
    results, summary = await core.recall("cat", k=2, collection="short_term")
    assert summary.count == 2
    # The first result is the one containing "cat".
    assert "cat" in results[0].text


@pytest.mark.asyncio
async def test_recall_summary_excludes_text_contents(core: MnemosCore):
    await core.store("secret content", collection="episodic")
    _, summary = await core.recall("secret", k=1, collection="episodic")
    # RecallSummary itself carries no text — that's the privacy boundary.
    assert "secret" not in str(summary)


@pytest.mark.asyncio
async def test_unknown_collection_rejected(core: MnemosCore):
    with pytest.raises(ValueError):
        await core.store("x", collection="nope")
    with pytest.raises(ValueError):
        await core.recall("x", collection="nope")


@pytest.mark.asyncio
async def test_collections_initialized_after_initialize(core: MnemosCore):
    # The fixture already initialized; the three persisted collections
    # should be present in the storage.
    for kind in ("episodic", "semantic", "procedural"):
        name = core.collection_name(kind)
        assert await core.storage.count(name) == 0
