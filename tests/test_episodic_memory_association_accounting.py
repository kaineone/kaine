# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for association accounting defects."""

from __future__ import annotations

import math
import uuid
from pathlib import Path
from typing import Any

import pytest

from kaine.modules.episodic_memory import (
    EpisodicMemoryCore,
    FakeEmbedder,
    InMemoryStorage,
)
from kaine.modules.episodic_memory.associations import (
    AssociationParams,
    link_id,
    trace_ref,
)
from kaine.modules.episodic_memory.storage import (
    QdrantStorage,
    SqliteVecStorage,
)

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect")

DIM = 8


class _Clock:
    """Settable entity clock for tests."""

    def __init__(self, t: float = 0.0) -> None:
        self.t = float(t)

    def __call__(self) -> float:
        return self.t


class _TableEmbedder(FakeEmbedder):
    """Fake embedder that looks up vectors from a table."""

    def __init__(self, table: dict[str, list[float]] | None = None) -> None:
        super().__init__(latent_dim=DIM)
        self.table: dict[str, list[float]] = dict(table or {})

    async def encode(self, text: str) -> list[float]:
        if text in self.table:
            return list(self.table[text])
        return await super().encode(text)


BACKENDS = ["inmemory", "sqlite_vec", "qdrant"]


async def _open_storage(kind: str, path: Path) -> Any:
    """Build and initialize one storage backend."""
    if kind == "inmemory":
        s = InMemoryStorage(latent_dim=DIM)
    elif kind == "sqlite_vec":
        pytest.importorskip("sqlite_vec")
        s = SqliteVecStorage(latent_dim=DIM, db_path=str(path / "m.db"))
    elif kind == "qdrant":
        qc = pytest.importorskip("qdrant_client")
        s = QdrantStorage(latent_dim=DIM, api_key="test")
        s._client = qc.AsyncQdrantClient(location=":memory:")
    else:
        raise ValueError(f"unknown backend {kind!r}")
    await s.initialize()
    return s


@pytest.fixture(params=BACKENDS)
async def storage(request, tmp_path):
    """Parametrized storage backend."""
    s = await _open_storage(request.param, tmp_path)
    yield s
    await s.shutdown()


async def _core(storage, *, embedder=None, clock=None, **kw) -> EpisodicMemoryCore:
    """Create and initialize a EpisodicMemoryCore over the given storage."""
    core = EpisodicMemoryCore(
        embedder or _TableEmbedder(),
        storage,
        entity_clock=clock or _Clock(),
        **kw,
    )
    await core.initialize()
    return core


def _flat(exported: dict) -> list:
    """Every exported point of every collection, in one list."""
    out = []
    for collection, points in exported.items():
        for p in points:
            p2 = dict(p)
            p2["collection"] = collection
            out.append(p2)
    return out


def _key(pid: Any) -> str:
    """Normalize a point id for comparison across backends."""
    try:
        return uuid.UUID(str(pid)).hex
    except ValueError:
        return str(pid)


async def _protect(core: EpisodicMemoryCore, texts: list[str]) -> list[tuple[str, str, float]]:
    """Build protect triples for the current wake matching the given texts."""
    pool = await core.wake_pool()
    return [
        (p["collection"], _key(p["id"]), float(p["payload"]["log_base"]))
        for p in pool
        if p["text"] in texts
    ]


def _unit(first: float, axis: int) -> list[float]:
    """Return a unit vector whose cosine with e0 is ``first``."""
    v = [0.0] * DIM
    v[0] = float(first)
    if axis != 0:
        v[axis] = math.sqrt(max(0.0, 1.0 - first * first))
    return v


def _mean(vectors: list[list[float]]) -> list[float]:
    """Elementwise mean of equal-length vectors."""
    if not vectors:
        return []
    dim = len(vectors[0])
    n = len(vectors)
    return [sum(v[i] for v in vectors) / n for i in range(dim)]


def _normalize(v: list[float]) -> list[float]:
    """Scale a vector to unit length."""
    norm = math.sqrt(sum(x * x for x in v))
    if norm == 0.0:
        return list(v)
    return [x / norm for x in v]


async def _protect_point(core: EpisodicMemoryCore, point_id: Any) -> tuple[str, str, float]:
    """Build a protect triple for one existing episodic point."""
    coll = core.collection_name("episodic")
    pts = await core.storage.get_points(coll, [point_id])
    assert len(pts) == 1
    return (coll, str(pts[0]["id"]), float(pts[0]["payload"]["log_base"]))


async def _point_payload(core: EpisodicMemoryCore, point_id: Any) -> dict[str, Any]:
    """Return the payload of one existing episodic point."""
    coll = core.collection_name("episodic")
    pts = await core.storage.get_points(coll, [point_id])
    assert len(pts) == 1
    return pts[0]["payload"]


async def test_store_size_includes_links_after_a_later_sleep(storage):
    """Association bytes must be counted after a plain later sleep."""
    table = {
        "o": _unit(0.95, 1),
        "q": _unit(0.9, 2),
        "r": _unit(0.0, 3),
    }
    core = await _core(storage, embedder=_TableEmbedder(table))

    await core.store("o", collection="episodic")
    await core.downscale(await _protect(core, ["o"]))

    await core.store("q", collection="episodic")
    await core.downscale(await _protect(core, ["q"]), prune=False)
    await core.associate()
    await core.prune()

    await core.store("r", collection="episodic")
    await core.downscale(await _protect(core, ["r"]))

    full = await core.storage.scan_store(
        core.persisted_collection_names() + core.association_collection_names()
    )
    assert core.store_bytes == full["bytes"]
    assert len(core.association_index.links) == 1


async def test_budget_counts_links_in_a_later_sleep(storage):
    """A later plain sleep must treat links as store budget bytes."""
    table = {
        "o": _unit(0.95, 1),
        "q": _unit(0.9, 2),
    }
    core = await _core(storage, embedder=_TableEmbedder(table))

    await core.store("o", collection="episodic")
    await core.downscale(await _protect(core, ["o"]))

    await core.store("q", collection="episodic")
    await core.downscale(await _protect(core, ["q"]), prune=False)
    await core.associate()
    await core.prune()

    full = await core.storage.scan_store(
        core.persisted_collection_names() + core.association_collection_names()
    )
    core._budget_bytes = full["bytes"] - 1

    summary = await core.downscale([])
    assert summary["links_pruned"] == 1
    assert core.store_bytes <= core._budget_bytes


async def test_capped_pairs_are_not_reported(storage):
    """Pairs whose link is dropped by n_link must not be reported."""
    table = {
        "o1": _unit(0.95, 1),
        "o2": _unit(0.9, 2),
        "q": _unit(0.92, 3),
    }
    core = await _core(
        storage,
        embedder=_TableEmbedder(table),
        association=AssociationParams(n_link=1, n_pair=2),
    )

    await core.store("o1", collection="episodic")
    await core.store("o2", collection="episodic")
    await core.downscale(await _protect(core, ["o1", "o2"]))

    await core.store("q", collection="episodic")
    await core.downscale(await _protect(core, ["q"]), prune=False)
    summary = await core.associate()

    assert summary["links_dropped"] == 1
    assert len(summary["pairs"]) == 1

    pair = summary["pairs"][0]
    lid = link_id(
        trace_ref("episodic", pair["a"]),
        trace_ref("episodic", pair["b"]),
    )
    assert lid in core.association_index.links
