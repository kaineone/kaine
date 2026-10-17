# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the episodic memory get_points storage method."""
import uuid
from pathlib import Path
from typing import Any

import pytest

from kaine.modules.episodic_memory.storage import (
    InMemoryStorage,
    QdrantStorage,
    SqliteVecStorage,
)

pytestmark = pytest.mark.filterwarnings("ignore:Payload indexes have no effect")

DIM = 4
VEC = [0.5, 1.0, -2.0, 0.25]


async def _open_storage(kind: str, path: Path) -> Any:
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
        raise ValueError(kind)
    await s.initialize()
    return s


@pytest.fixture(params=["inmemory", "sqlite_vec", "qdrant"])
async def storage(request, tmp_path):
    s = await _open_storage(request.param, tmp_path)
    yield s
    await s.shutdown()


def _canonical_id(point: dict[str, Any]) -> str:
    return uuid.UUID(point["id"]).hex


async def _insert_three(storage):
    ids = [uuid.uuid4().hex for _ in range(3)]
    # Unit vectors: Qdrant normalizes cosine vectors on storage.
    vectors = [
        [0.0, 1.0, 0.0, 0.0],
        [0.6, 0.0, 0.8, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
    payloads = [{"t": 1.0, "x": "a"}, {"t": 2.0, "x": "b"}, {"t": 3.0, "x": "c"}]
    affects = [{"mood": "ok"}, {"mood": "good"}, None]
    await storage.ensure_collection("c")
    for i in range(3):
        await storage.upsert(
            "c",
            vector=vectors[i],
            text=f"text{i}",
            payload=payloads[i],
            affect=affects[i],
            point_id=ids[i],
        )
    return ids, vectors, payloads, affects


async def test_get_points_returns_requested_points(storage):
    ids, _vectors, payloads, affects = await _insert_three(storage)
    result = await storage.get_points("c", [ids[0], ids[2]])
    by_id = {_canonical_id(p): p for p in result}
    assert set(by_id) == {ids[0], ids[2]}
    assert len(result) == 2
    for i in (0, 2):
        p = by_id[ids[i]]
        assert "vector" not in p
        assert p["text"] == f"text{i}"
        assert p["payload"] == payloads[i]
        assert p["affect"] == affects[i]


async def test_get_points_with_vectors(storage):
    ids, vectors, _payloads, _affects = await _insert_three(storage)
    result = await storage.get_points("c", ids, with_vectors=True)
    by_id = {_canonical_id(p): p for p in result}
    assert set(by_id) == set(ids)
    assert len(result) == 3
    for i, pid in enumerate(ids):
        p = by_id[pid]
        assert p["vector"] == pytest.approx(vectors[i])


async def test_get_points_hyphenated_id(storage):
    ids, _vectors, _payloads, _affects = await _insert_three(storage)
    result = await storage.get_points("c", [str(uuid.UUID(ids[0]))])
    assert len(result) == 1
    assert _canonical_id(result[0]) == ids[0]
    assert "vector" not in result[0]


async def test_get_points_skips_unknown_ids(storage):
    ids, _vectors, _payloads, _affects = await _insert_three(storage)
    result = await storage.get_points("c", ["not-a-real-id", ids[1]])
    assert len(result) == 1
    assert _canonical_id(result[0]) == ids[1]


async def test_get_points_missing_collection(storage):
    await storage.ensure_collection("c")
    pid = uuid.uuid4().hex
    await storage.upsert("c", vector=VEC, text="x", payload={}, affect=None, point_id=pid)
    result = await storage.get_points("no_such_collection", [pid])
    assert result == []


async def test_get_points_empty_ids(storage):
    await storage.ensure_collection("c")
    pid = uuid.uuid4().hex
    await storage.upsert("c", vector=VEC, text="x", payload={}, affect=None, point_id=pid)
    result = await storage.get_points("c", [])
    assert result == []


async def test_get_points_affect_none(storage):
    await storage.ensure_collection("c")
    pid = uuid.uuid4().hex
    await storage.upsert(
        "c",
        vector=VEC,
        text="no-affect",
        payload={"k": "v"},
        affect=None,
        point_id=pid,
    )
    result = await storage.get_points("c", [pid])
    assert len(result) == 1
    assert result[0]["affect"] is None
    assert result[0]["text"] == "no-affect"
