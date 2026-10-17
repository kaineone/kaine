# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import types

import pytest

from kaine.modules.episodic_memory import InMemoryStorage
from kaine.modules.episodic_memory.storage import (
    QdrantStorage,
    SqliteVecStorage,
    _payload_timestamp,
)


@pytest.mark.asyncio
async def test_inmemory_recent_points_newest_first_without_vectors():
    s = InMemoryStorage(latent_dim=4)
    await s.ensure_collection("c")
    for text, ts in [("a", 10.0), ("b", 30.0), ("c", 20.0)]:
        await s.upsert(
            "c",
            vector=[1.0, 0.0, 0.0, 0.0],
            text=text,
            payload={"timestamp": ts},
            affect=None,
        )
    got = await s.recent_points("c", limit=2)
    assert [p["text"] for p in got] == ["b", "c"]
    for p in got:
        assert set(p.keys()) == {"id", "text", "payload", "affect"}
        assert "vector" not in p
    assert await s.recent_points("missing", limit=5) == []
    assert await s.recent_points("c", limit=0) == []


@pytest.mark.asyncio
async def test_sqlite_vec_recent_points(tmp_path):
    pytest.importorskip("sqlite_vec")
    s = SqliteVecStorage(latent_dim=4, db_path=str(tmp_path / "m.db"))
    await s.initialize()
    try:
        await s.ensure_collection("c")
        for text, ts in [("a", 10.0), ("b", 30.0), ("c", 20.0)]:
            await s.upsert(
                "c",
                vector=[1.0, 0.0, 0.0, 0.0],
                text=text,
                payload={"timestamp": ts},
                affect=None,
            )
        got = await s.recent_points("c", limit=2)
        assert [p["text"] for p in got] == ["b", "c"]
        for p in got:
            assert set(p.keys()) == {"id", "text", "payload", "affect"}
            assert "vector" not in p
        assert await s.recent_points("missing", limit=5) == []
        assert await s.recent_points("c", limit=0) == []
    finally:
        await s.shutdown()


@pytest.mark.asyncio
async def test_qdrant_recent_points_scrolls_without_vectors():
    pytest.importorskip("qdrant_client")

    points_data = [
        {"text": "p0", "affect": None, "timestamp": 5.0},
        {"text": "p1", "affect": None, "timestamp": 1.0},
        {"text": "p2", "affect": None, "timestamp": 4.0},
        {"text": "p3", "affect": None, "timestamp": 2.0},
        {"text": "p4", "affect": None, "timestamp": 3.0},
    ]
    stored_points = [
        types.SimpleNamespace(id=i, payload=dict(d))
        for i, d in enumerate(points_data)
    ]

    class FakeClient:
        def __init__(self, points):
            self.points = points
            self.calls = []

        async def get_aliases(self):
            """No collection aliases (a store that was never renamed)."""
            from types import SimpleNamespace

            return SimpleNamespace(aliases=[])

        async def get_collections(self):
            return types.SimpleNamespace(
                collections=[types.SimpleNamespace(name="c")]
            )

        async def scroll(
            self,
            collection_name,
            limit,
            offset=None,
            with_payload=True,
            with_vectors=False,
            **kwargs,
        ):
            self.calls.append({"with_vectors": with_vectors, "offset": offset})
            page_size = 3
            start = 0 if offset is None else offset
            batch = self.points[start : start + page_size]
            next_offset = start + page_size if start + page_size < len(self.points) else None
            return batch, next_offset

        async def close(self):
            pass

    fake = FakeClient(stored_points)
    store = QdrantStorage(latent_dim=4, api_key="k")
    store._client = fake
    got = await store.recent_points("c", limit=3)
    assert [p["text"] for p in got] == ["p0", "p2", "p4"]
    for call in fake.calls:
        assert call["with_vectors"] is False
    assert len(fake.calls) == 2
    for p in got:
        assert "vector" not in p
        assert "text" not in p["payload"]
    assert await store.recent_points("other", limit=3) == []


_NON_FINITE_CASES = [
    ("new", 30.0),
    ("nan", float("nan")),
    ("old", 10.0),
    ("inf", float("inf")),
    ("ninf", float("-inf")),
]


def test_payload_timestamp_clamps_non_finite():
    assert _payload_timestamp({"timestamp": float("nan")}) == 0.0
    assert _payload_timestamp({"timestamp": float("inf")}) == 0.0
    assert _payload_timestamp({"timestamp": float("-inf")}) == 0.0
    assert _payload_timestamp({"timestamp": "nan"}) == 0.0
    assert _payload_timestamp({"timestamp": "inf"}) == 0.0
    assert _payload_timestamp({"timestamp": "abc"}) == 0.0
    assert _payload_timestamp({"timestamp": None}) == 0.0
    assert _payload_timestamp({}) == 0.0
    assert _payload_timestamp("not a dict") == 0.0
    assert _payload_timestamp({"timestamp": 5.0}) == 5.0
    assert _payload_timestamp({"timestamp": "5"}) == 5.0


@pytest.mark.asyncio
async def test_inmemory_recent_points_ranks_non_finite_as_oldest():
    s = InMemoryStorage(latent_dim=4)
    await s.ensure_collection("c")
    for text, ts in _NON_FINITE_CASES:
        await s.upsert(
            "c",
            vector=[1.0, 0.0, 0.0, 0.0],
            text=text,
            payload={"timestamp": ts},
            affect=None,
        )
    got = await s.recent_points("c", limit=2)
    assert [p["text"] for p in got] == ["new", "old"]
    got_all = await s.recent_points("c", limit=5)
    assert [p["text"] for p in got_all[:2]] == ["new", "old"]
    assert {p["text"] for p in got_all[2:]} == {"nan", "inf", "ninf"}


@pytest.mark.asyncio
async def test_sqlite_vec_recent_points_ranks_non_finite_as_oldest(tmp_path):
    pytest.importorskip("sqlite_vec")
    s = SqliteVecStorage(latent_dim=4, db_path=str(tmp_path / "m.db"))
    await s.initialize()
    try:
        await s.ensure_collection("c")
        for text, ts in _NON_FINITE_CASES:
            await s.upsert(
                "c",
                vector=[1.0, 0.0, 0.0, 0.0],
                text=text,
                payload={"timestamp": ts},
                affect=None,
            )
        got = await s.recent_points("c", limit=2)
        assert [p["text"] for p in got] == ["new", "old"]
        got_all = await s.recent_points("c", limit=5)
        assert [p["text"] for p in got_all[:2]] == ["new", "old"]
        assert {p["text"] for p in got_all[2:]} == {"nan", "inf", "ninf"}
    finally:
        await s.shutdown()


@pytest.mark.asyncio
async def test_qdrant_recent_points_ranks_non_finite_as_oldest():
    pytest.importorskip("qdrant_client")

    points_data = [
        {"text": text, "affect": None, "timestamp": ts}
        for text, ts in _NON_FINITE_CASES
    ]
    stored_points = [
        types.SimpleNamespace(id=i, payload=dict(d))
        for i, d in enumerate(points_data)
    ]

    class FakeClient:
        def __init__(self, points):
            self.points = points
            self.calls = []

        async def get_aliases(self):
            """No collection aliases (a store that was never renamed)."""
            from types import SimpleNamespace

            return SimpleNamespace(aliases=[])

        async def get_collections(self):
            return types.SimpleNamespace(
                collections=[types.SimpleNamespace(name="c")]
            )

        async def scroll(
            self,
            collection_name,
            limit,
            offset=None,
            with_payload=True,
            with_vectors=False,
            **kwargs,
        ):
            self.calls.append({"with_vectors": with_vectors, "offset": offset})
            page_size = 3
            start = 0 if offset is None else offset
            batch = self.points[start : start + page_size]
            next_offset = start + page_size if start + page_size < len(self.points) else None
            return batch, next_offset

        async def close(self):
            pass

    fake = FakeClient(stored_points)
    store = QdrantStorage(latent_dim=4, api_key="k")
    store._client = fake
    got = await store.recent_points("c", limit=2)
    assert [p["text"] for p in got] == ["new", "old"]
    got_all = await store.recent_points("c", limit=5)
    assert [p["text"] for p in got_all[:2]] == ["new", "old"]
    assert {p["text"] for p in got_all[2:]} == {"nan", "inf", "ninf"}
