# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Cross-period selection of sleep phase 3 reads the newest persisted episodic
traces through a bounded, vector-free storage call, so it works on backends that
keep their points out of process.
"""

import uuid
from pathlib import Path
from typing import Any, Sequence

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.episodic_memory import (
    EpisodicMemory,
    EpisodicMemoryCore,
    FakeEmbedder,
    InMemoryStorage,
)
from kaine.modules.episodic_memory.storage import StorageError
from kaine.modules.sleep.phases import associative_replay


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

    async def read_meta(self, key: str) -> dict | None:
        return await self._inner.read_meta(key)

    async def write_meta(self, key: str, value: dict) -> None:
        return await self._inner.write_meta(key, value)

    async def wake_points(
        self, collections: Sequence[str], born_sleep: int
    ) -> list[dict[str, Any]]:
        result = await self._inner.wake_points(collections, born_sleep)
        out: list[dict] = []
        for point in result:
            new_point = dict(point)
            new_point["id"] = str(uuid.UUID(point["id"]))
            out.append(new_point)
        return out

    async def count_filtered(
        self,
        collection: str,
        *,
        born_sleep: int | None = None,
        has_log_base: bool | None = None,
    ) -> int:
        return await self._inner.count_filtered(
            collection,
            born_sleep=born_sleep,
            has_log_base=has_log_base,
        )

    async def total_size(self, collections: Sequence[str]) -> int:
        return await self._inner.total_size(collections)

    async def scan_store(self, collections: Sequence[str]) -> dict[str, Any]:
        return await self._inner.scan_store(collections)

    async def weakest(self, collections: Sequence[str], *, limit: int) -> list[dict[str, Any]]:
        return await self._inner.weakest(collections, limit=limit)

    async def delete_points(self, collection: str, point_ids: Sequence[str]) -> None:
        return await self._inner.delete_points(collection, point_ids)

    async def set_log_base(
        self, collection: str, updates: Sequence[tuple[str, float]]
    ) -> None:
        return await self._inner.set_log_base(collection, updates)

    async def backfill_strength(
        self, collections: Sequence[str], *, log_base: float
    ) -> int:
        return await self._inner.backfill_strength(collections, log_base=log_base)

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

    async def read_meta(self, key: str) -> dict | None:
        return None

    async def write_meta(self, key: str, value: dict) -> None:
        return None

    async def wake_points(
        self, collections: Sequence[str], born_sleep: int
    ) -> list[dict[str, Any]]:
        return []

    async def count_filtered(
        self,
        collection: str,
        *,
        born_sleep: int | None = None,
        has_log_base: bool | None = None,
    ) -> int:
        return 0

    async def total_size(self, collections: Sequence[str]) -> int:
        return 0

    async def scan_store(self, collections: Sequence[str]) -> dict[str, Any]:
        return {"bytes": 0, "log_base_counts": {}, "unstrengthed": 0}

    async def weakest(self, collections: Sequence[str], *, limit: int) -> list[dict[str, Any]]:
        return []

    async def delete_points(self, collection: str, point_ids: Sequence[str]) -> None:
        return None

    async def set_log_base(
        self, collection: str, updates: Sequence[tuple[str, float]]
    ) -> None:
        return None

    async def backfill_strength(
        self, collections: Sequence[str], *, log_base: float
    ) -> int:
        return 0


async def _seeded(bus: AsyncBus, storage, **episodic_memory_kwargs) -> tuple[EpisodicMemory, EpisodicMemoryCore]:
    emb = FakeEmbedder(latent_dim=8)
    await emb.load()

    # Controllable clock so timestamps are pinned exactly.
    clock_val: dict[str, float] = {"t": 0.0}
    core = EpisodicMemoryCore(
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

    return EpisodicMemory(bus, core=core, **episodic_memory_kwargs), core


@pytest.mark.asyncio
async def test_cross_period_reads_episodic_memory_without_in_process_collections(bus):
    storage = _OutOfProcessStorage(InMemoryStorage(latent_dim=8))
    assert not hasattr(storage, "_collections")

    episodic_memory, core = await _seeded(bus, storage)

    by_period = await episodic_memory.select_cross_period_traces(periods=2, per_period=5)

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
    episodic_memory, _ = await _seeded(bus, storage)

    r = await associative_replay(enabled=True, episodic_memory=episodic_memory)

    assert r.success is True
    assert r.metadata["distinct_periods"] >= 2
    assert r.metadata["cross_period_traces"] == 4


@pytest.mark.asyncio
async def test_cross_period_storage_error_propagates(bus):
    storage = _FailingStorage(InMemoryStorage(latent_dim=8))
    episodic_memory, _ = await _seeded(bus, storage)

    with pytest.raises(StorageError):
        await episodic_memory.select_cross_period_traces(periods=2, per_period=5)


@pytest.mark.asyncio
async def test_cross_period_on_sqlite_vec(tmp_path: Path, bus):
    pytest.importorskip("sqlite_vec")
    from kaine.modules.episodic_memory.storage import SqliteVecStorage

    storage = SqliteVecStorage(latent_dim=8, db_path=str(tmp_path / "mnemos.db"))
    try:
        episodic_memory, _ = await _seeded(bus, storage)

        by_period = await episodic_memory.select_cross_period_traces(periods=2, per_period=5)

        traces = [t for bucket in by_period.values() for t in bucket]
        texts = sorted(t["text"] for t in traces)

        assert texts == ["new one", "new two", "old one", "old two"]
        assert len(by_period) >= 2
    finally:
        await storage.shutdown()


@pytest.mark.asyncio
async def test_cross_period_reads_only_the_newest_candidates(bus):
    storage = _OutOfProcessStorage(InMemoryStorage(latent_dim=8))
    episodic_memory, core = await _seeded(bus, storage, cross_period_candidates=1)

    by_period = await episodic_memory.select_cross_period_traces(periods=2, per_period=5)

    traces = [t for bucket in by_period.values() for t in bucket]
    texts = sorted(t["text"] for t in traces)

    assert texts == ["new one", "new two"]
