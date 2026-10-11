# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Cross-period selection of sleep phase 3 reads the newest persisted episodic
traces through a bounded, vector-free storage call, so it works on backends that
keep their points out of process.
"""

import uuid
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.hypnos.phases import associative_replay
from kaine.modules.mnemos import FakeEmbedder, InMemoryStorage, Mnemos, MnemosCore
from kaine.modules.mnemos.storage import StorageError


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class _OutOfProcessStorage:
    """A backend that keeps its points out of process, like Qdrant, including
    its hyphenated ids.
    """

    def __init__(self, inner: InMemoryStorage) -> None:
        self._inner = inner
        self.recent_calls: list[tuple[str, int]] = []

    @property
    def latent_dim(self) -> int:
        return self._inner.latent_dim

    async def initialize(self) -> None:
        return await self._inner.initialize()

    async def shutdown(self) -> None:
        return await self._inner.shutdown()

    async def ensure_collection(self, name: str) -> None:
        return await self._inner.ensure_collection(name)

    async def upsert(
        self,
        collection: str,
        *,
        vector: list[float],
        text: str,
        payload: dict,
        affect: dict | None,
        point_id: str | None = None,
    ) -> str:
        return await self._inner.upsert(
            collection,
            vector=vector,
            text=text,
            payload=payload,
            affect=affect,
            point_id=point_id,
        )

    async def search(
        self,
        collection: str,
        *,
        query_vector: list[float],
        limit: int,
    ) -> list:
        return await self._inner.search(collection, query_vector=query_vector, limit=limit)

    async def delete(self, collection: str, point_id: str) -> None:
        return await self._inner.delete(collection, point_id)

    async def count(self, collection: str, strict: bool = False) -> int:
        return await self._inner.count(collection, strict=strict)

    async def vector_dim(self, collection: str) -> int | None:
        return await self._inner.vector_dim(collection)

    async def replace_collection(self, name: str, points: list[dict]) -> int:
        return await self._inner.replace_collection(name, points)

    async def read_stamp(self, key: str) -> dict | None:
        return await self._inner.read_stamp(key)

    async def write_stamp(self, key: str, stamp: dict) -> None:
        return await self._inner.write_stamp(key, stamp)

    async def recent_points(self, collection: str, *, limit: int) -> list[dict]:
        self.recent_calls.append((collection, limit))
        result = await self._inner.recent_points(collection, limit=limit)
        out: list[dict] = []
        for point in result:
            new_point = dict(point)
            new_point["id"] = str(uuid.UUID(point["id"]))
            out.append(new_point)
        return out

    async def export(self, collections: list[str]) -> dict[str, list[dict]]:
        raise AssertionError("selection must not export every vector")


class _FailingStorage(_OutOfProcessStorage):
    async def recent_points(self, collection: str, *, limit: int) -> list[dict]:
        raise StorageError("store down")


async def _seeded(bus: AsyncBus, storage, **mnemos_kwargs) -> tuple[Mnemos, MnemosCore]:
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()

    # Controllable clock so timestamps are pinned exactly.
    clock_val: dict[str, float] = {"t": 0.0}
    core = MnemosCore(
        embedder=emb,
        storage=storage,
        short_term_capacity=32,
        clock=lambda: clock_val["t"],
    )
    await core.initialize()

    # Two older traces already in episodic memory.
    for text, ts in [("old one", 1000.0), ("old two", 1010.0)]:
        clock_val["t"] = ts
        await core.store(text, payload={"timestamp": ts}, collection="episodic")

    # Two newer traces in short-term memory.
    for text, ts in [("new one", 5000.0), ("new two", 5010.0)]:
        clock_val["t"] = ts
        await core.store(text, collection="short_term")

    # Phase 1 consolidation moves short-term traces into episodic memory.
    assert await core.consolidate_now() == 2

    return Mnemos(bus, core=core, **mnemos_kwargs), core


@pytest.mark.asyncio
async def test_cross_period_reads_episodic_memory_without_in_process_collections(bus):
    storage = _OutOfProcessStorage(InMemoryStorage(latent_dim=8))
    assert not hasattr(storage, "_collections")

    mnemos, core = await _seeded(bus, storage)

    by_period = await mnemos.select_cross_period_traces(periods=2, per_period=5)

    traces = [t for bucket in by_period.values() for t in bucket]
    texts = sorted(t["text"] for t in traces)

    assert texts == ["new one", "new two", "old one", "old two"]
    assert len(by_period) >= 2
    assert storage.recent_calls == [(core.collection_name("episodic"), 128)]

    returned_ids = {t["point_id"] for t in traces}
    consolidated_ids = {str(pid) for pid, _ in core.last_consolidated}
    assert consolidated_ids.issubset(returned_ids)


@pytest.mark.asyncio
async def test_phase_three_spans_periods_on_a_remote_style_backend(bus):
    storage = _OutOfProcessStorage(InMemoryStorage(latent_dim=8))
    mnemos, _ = await _seeded(bus, storage)

    r = await associative_replay(enabled=True, mnemos=mnemos)

    assert r.success is True
    assert r.metadata["distinct_periods"] >= 2
    assert r.metadata["cross_period_traces"] == 4


@pytest.mark.asyncio
async def test_cross_period_storage_error_propagates(bus):
    storage = _FailingStorage(InMemoryStorage(latent_dim=8))
    mnemos, _ = await _seeded(bus, storage)

    with pytest.raises(StorageError):
        await mnemos.select_cross_period_traces(periods=2, per_period=5)


@pytest.mark.asyncio
async def test_cross_period_on_sqlite_vec(tmp_path: Path, bus):
    pytest.importorskip("sqlite_vec")
    from kaine.modules.mnemos.storage import SqliteVecStorage

    storage = SqliteVecStorage(latent_dim=8, db_path=str(tmp_path / "mnemos.db"))
    try:
        mnemos, _ = await _seeded(bus, storage)

        by_period = await mnemos.select_cross_period_traces(periods=2, per_period=5)

        traces = [t for bucket in by_period.values() for t in bucket]
        texts = sorted(t["text"] for t in traces)

        assert texts == ["new one", "new two", "old one", "old two"]
        assert len(by_period) >= 2
    finally:
        await storage.shutdown()


@pytest.mark.asyncio
async def test_cross_period_reads_only_the_newest_candidates(bus):
    storage = _OutOfProcessStorage(InMemoryStorage(latent_dim=8))
    mnemos, core = await _seeded(bus, storage, cross_period_candidates=1)

    by_period = await mnemos.select_cross_period_traces(periods=2, per_period=5)

    traces = [t for bucket in by_period.values() for t in bucket]
    texts = sorted(t["text"] for t in traces)

    assert texts == ["new one", "new two"]
