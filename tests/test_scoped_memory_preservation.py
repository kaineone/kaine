# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Scoped memory preservation — bundle contains only the preserved being.

Verification suite for openspec change ``scoped-memory-preservation``.
Mnemos must export/import only its own prefixed memory kinds, replacing the
target collections, and Empatheia must preserve/restore its own profiles.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.empatheia.agent import AgentModel
from kaine.modules.empatheia.store import _AGENT_ID_NAMESPACE, QdrantAgentStore, _point_id
from kaine.modules.mnemos import MnemosCore
from kaine.modules.mnemos.storage import InMemoryStorage, QdrantStorage, StorageError
from kaine.text_embedding import FakeEmbedder


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    try:
        yield b
    finally:
        await b.close()


class _FakeQdrantPoint:
    def __init__(self, pid, vector, payload):
        self.id = pid
        self.vector = vector
        self.payload = payload


class _FakeAsyncQdrant:
    """Minimal in-process double of AsyncQdrantClient."""

    def __init__(self):
        self.store: dict[str, list[_FakeQdrantPoint]] = {}

    class _Colls:
        def __init__(self, names):
            self.collections = [type("C", (), {"name": n}) for n in names]

    async def get_collections(self):
        return self._Colls(list(self.store))

    async def create_collection(self, collection_name, vectors_config=None, **kwargs):
        self.store.setdefault(collection_name, [])

    async def delete_collection(self, collection_name, **kwargs):
        self.store.pop(collection_name, None)

    @staticmethod
    def _cosine_similarity(a, b):
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = (sum(x * x for x in a) ** 0.5) or 1.0
        norm_b = (sum(y * y for y in b) ** 0.5) or 1.0
        return dot / (norm_a * norm_b)

    async def scroll(
        self,
        collection_name,
        scroll_filter=None,
        offset=None,
        limit=10,
        with_payload=True,
        with_vectors=False,
        **kwargs,
    ):
        pts = list(self.store.get(collection_name, []))
        if with_vectors:
            out_pts = pts
        else:
            out_pts = [
                _FakeQdrantPoint(
                    p.id, None, p.payload if with_payload else {}
                )
                for p in pts
            ]

        def _matches_filter(p):
            if scroll_filter is None:
                return True
            must = getattr(scroll_filter, "must", None)
            if not must:
                return True
            payload = p.payload if p.payload is not None else {}
            for cond in must:
                key = getattr(cond, "key", None)
                match = getattr(cond, "match", None)
                if key is None or match is None:
                    continue
                value = getattr(match, "value", None)
                if payload.get(key) != value:
                    return False
            return True

        filtered = [p for p in out_pts if _matches_filter(p)]
        start = int(offset) if offset is not None else 0
        end = start + limit
        page = filtered[start:end]
        next_offset = end if end < len(filtered) else None
        return page, next_offset

    async def query_points(
        self,
        collection_name,
        query,
        limit=10,
        with_payload=True,
        with_vectors=False,
        **kwargs,
    ):
        pts = self.store.get(collection_name, [])
        q = list(query)
        scored = []
        for p in pts:
            hit = type(
                "ScoredPoint",
                (),
                {
                    "id": p.id,
                    "score": self._cosine_similarity(q, p.vector),
                    "payload": p.payload if with_payload else None,
                    "vector": p.vector if with_vectors else None,
                },
            )
            scored.append(hit)
        scored.sort(key=lambda h: h.score, reverse=True)
        return type("QueryResponse", (), {"points": scored[:limit]})()

    class _Count:
        def __init__(self, n: int) -> None:
            self.count = n

    async def count(self, collection_name, **kwargs):
        return self._Count(len(self.store.get(collection_name, [])))

    @staticmethod
    def _validate_point_id(pid):
        if isinstance(pid, int) and pid >= 0:
            return
        if isinstance(pid, uuid.UUID):
            return
        try:
            uuid.UUID(pid)
        except Exception as exc:
            raise ValueError(f"Unable to parse UUID: {pid}") from exc

    async def upsert(self, collection_name, points, **kwargs):
        coll = self.store.setdefault(collection_name, [])
        by_id = {p.id: i for i, p in enumerate(coll)}
        for p in points:
            self._validate_point_id(p.id)
            vec = list(p.vector) if p.vector is not None else []
            payload = dict(p.payload) if p.payload is not None else {}
            point = _FakeQdrantPoint(p.id, vec, payload)
            if p.id in by_id:
                coll[by_id[p.id]] = point
            else:
                coll.append(point)
                by_id[p.id] = len(coll) - 1

    async def delete(self, collection_name, points_selector=None, **kwargs):
        if points_selector is None:
            return
        ids = set()
        if hasattr(points_selector, "points"):
            ids = set(points_selector.points)
        elif isinstance(points_selector, (list, tuple)):
            ids = set(points_selector)
        pts = self.store.get(collection_name, [])
        self.store[collection_name] = [p for p in pts if p.id not in ids]

    async def close(self, **kwargs):
        pass


@pytest.mark.asyncio
async def test_qdrant_two_prefixes_scoped_export_import():
    pytest.importorskip("qdrant_client")
    client = _FakeAsyncQdrant()
    embedder = FakeEmbedder(latent_dim=4)

    store_a = QdrantStorage(latent_dim=4, api_key="k")
    store_a._client = client
    store_b = QdrantStorage(latent_dim=4, api_key="k")
    store_b._client = client

    core_a = MnemosCore(embedder, store_a, collection_prefix="a_")
    core_b = MnemosCore(embedder, store_b, collection_prefix="b_")
    await core_a.initialize()
    await core_b.initialize()

    await core_a.store("alpha episodic", collection="episodic")
    await core_b.store("beta episodic", collection="episodic")

    state_a = await core_a.export_state()
    assert "a_episodic" in state_a["persisted"]
    assert all(not k.startswith("b_") for k in state_a["persisted"])

    store_c = QdrantStorage(latent_dim=4, api_key="k")
    store_c._client = client
    core_c = MnemosCore(embedder, store_c, collection_prefix="c_")
    await core_c.initialize()
    n = await core_c.import_state(state_a)
    assert n == 1

    results, _ = await core_c.recall("alpha", collection="episodic")
    assert any("alpha episodic" in r.text for r in results)

    results_b, _ = await core_b.recall("beta", collection="episodic")
    assert any("beta episodic" in r.text for r in results_b)

    # a_* collections are untouched by importing into c_.
    results_a, _ = await core_a.recall("alpha", collection="episodic")
    assert any("alpha episodic" in r.text for r in results_a)
    assert "a_episodic" in client.store


@pytest.mark.asyncio
async def test_sqlite_vec_two_prefixes_scoped_export_import(tmp_path: Path):
    pytest.importorskip("sqlite_vec")
    from kaine.modules.mnemos.storage import SqliteVecStorage

    db_path = tmp_path / "mnemos.db"
    storage = SqliteVecStorage(latent_dim=4, db_path=str(db_path))
    await storage.initialize()

    embedder = FakeEmbedder(latent_dim=4)
    core_a = MnemosCore(embedder, storage, collection_prefix="a_")
    core_b = MnemosCore(embedder, storage, collection_prefix="b_")
    await core_a.initialize()
    await core_b.initialize()

    await core_a.store("alpha semantic", collection="semantic")
    await core_b.store("beta semantic", collection="semantic")

    state_a = await core_a.export_state()
    assert "a_semantic" in state_a["persisted"]
    assert all(not k.startswith("b_") for k in state_a["persisted"])

    core_c = MnemosCore(embedder, storage, collection_prefix="c_")
    await core_c.initialize()
    n = await core_c.import_state(state_a)
    assert n == 1

    results, _ = await core_c.recall("alpha", collection="semantic")
    assert any("alpha semantic" in r.text for r in results)

    results_b, _ = await core_b.recall("beta", collection="semantic")
    assert any("beta semantic" in r.text for r in results_b)


@pytest.mark.asyncio
async def test_import_skips_foreign_collections_and_logs(caplog):
    pytest.importorskip("qdrant_client")
    client = _FakeAsyncQdrant()
    embedder = FakeEmbedder(latent_dim=4)
    store = QdrantStorage(latent_dim=4, api_key="k")
    store._client = client
    core = MnemosCore(embedder, store, collection_prefix="c_")
    await core.initialize()

    good_vec = list(await embedder.encode("good"))
    point = {
        "id": "11111111-1111-1111-1111-111111111111",
        "vector": good_vec,
        "text": "alpha",
        "payload": {"timestamp": 1.0},
        "affect": None,
    }
    state = {
        "collection_prefix": "a_",
        "short_term": [],
        "persisted": {
            "a_episodic": [point],
            "a_semantic": [],
            "a_procedural": [],
            "b_episodic": [point],
            "empatheia_agents": [
                {"id": "22222222-2222-2222-2222-222222222222", "vector": good_vec, "text": "agent", "payload": {}, "affect": None}
            ],
        },
    }

    caplog.set_level(logging.INFO, logger="kaine.modules.mnemos.memory")
    n = await core.import_state(state)
    assert n == 1

    results, _ = await core.recall("alpha", collection="episodic")
    assert any("alpha" in r.text for r in results)

    assert "b_episodic" in caplog.text
    assert "empatheia_agents" in caplog.text


@pytest.mark.asyncio
async def test_replace_semantics_and_validation_failure():
    embedder = FakeEmbedder(latent_dim=4)
    storage = InMemoryStorage(latent_dim=4)
    await storage.initialize()
    core = MnemosCore(embedder, storage, collection_prefix="x_")
    await core.initialize()

    await core.store("old extra point", collection="episodic")

    good_vec = list(await embedder.encode("good"))
    point = {
        "id": "p1",
        "vector": good_vec,
        "text": "new preserved",
        "payload": {},
        "affect": None,
    }
    state = {
        "collection_prefix": "x_",
        "short_term": [],
        "persisted": {"x_episodic": [point]},
    }
    n = await core.import_state(state)
    assert n == 1

    results, _ = await core.recall("new", collection="episodic")
    assert any("new preserved" in r.text for r in results)

    results_old, _ = await core.recall("old extra", collection="episodic")
    assert not any("old extra point" in r.text for r in results_old)

    bad_state = {
        "collection_prefix": "x_",
        "short_term": [],
        "persisted": {
            "x_episodic": [{"id": "bad", "vector": good_vec[:2], "text": "bad", "payload": {}, "affect": None}]
        },
    }
    with pytest.raises(StorageError):
        await core.import_state(bad_state)

    results2, _ = await core.recall("new", collection="episodic")
    assert any("new preserved" in r.text for r in results2)


@pytest.mark.asyncio
async def test_empatheia_qdrant_all_profiles_includes_collection():
    pytest.importorskip("qdrant_client")
    client = _FakeAsyncQdrant()
    model = AgentModel(id="remote", label="remote")
    profile_json = json.dumps(model.to_dict())
    point = _FakeQdrantPoint(
        pid=_point_id("remote"),
        vector=[0.1] * 4,
        payload={"agent_id": "remote", "profile_json": profile_json},
    )
    client.store["empatheia_agents"] = [point]

    embedder = FakeEmbedder(latent_dim=4)
    store = QdrantAgentStore(
        api_key="k",
        collection="empatheia_agents",
        latent_dim=4,
        embedder=embedder,
    )
    store._client = client
    store._initialized = True

    profiles = await store.all_profiles()
    assert "remote" in profiles
    assert profiles["remote"].label == "remote"


@pytest.mark.asyncio
async def test_empatheia_qdrant_replace_all_re_embeds():
    pytest.importorskip("qdrant_client")
    client = _FakeAsyncQdrant()

    class _NegatingEmbedder(FakeEmbedder):
        async def encode(self, text: str) -> list[float]:
            vec = await super().encode(text)
            return [-v for v in vec]

    src = QdrantAgentStore(
        api_key="k",
        collection="src_agents",
        latent_dim=4,
        embedder=FakeEmbedder(latent_dim=4),
    )
    src._client = client
    await src.initialize()

    model = AgentModel(id="operator", label="operator", interaction_count=5, reliability=0.9)
    await src.put(model)

    dst = QdrantAgentStore(
        api_key="k",
        collection="dst_agents",
        latent_dim=4,
        embedder=_NegatingEmbedder(latent_dim=4),
    )
    dst._client = client
    await dst.initialize()
    await dst.replace_all([model])

    pts, _ = await client.scroll(
        collection_name="dst_agents",
        limit=10,
        offset=None,
        with_payload=True,
        with_vectors=True,
    )
    assert len(pts) == 1
    assert pts[0].vector == await dst._build_embedding(model)
    assert pts[0].vector != await src._build_embedding(model)


@pytest.mark.asyncio
async def test_empatheia_qdrant_all_profiles_fails_loud_on_scroll_error():
    pytest.importorskip("qdrant_client")

    class _Broken:
        async def scroll(self, *args, **kwargs):
            raise RuntimeError("scroll down")

    store = QdrantAgentStore(
        api_key="k",
        collection="empatheia_agents",
        latent_dim=4,
    )
    store._client = _Broken()
    store._initialized = True

    with pytest.raises(RuntimeError, match="scroll down|all_profiles failed"):
        await store.all_profiles()


@pytest.mark.asyncio
async def test_empatheia_put_stores_profile_when_embedder_fails():
    pytest.importorskip("qdrant_client")
    client = _FakeAsyncQdrant()

    class _FailingEmbedder(FakeEmbedder):
        async def encode(self, text: str) -> list[float]:
            raise RuntimeError("embedder broken")

    store = QdrantAgentStore(
        api_key="k",
        collection="empatheia_agents",
        latent_dim=4,
        embedder=_FailingEmbedder(latent_dim=4),
    )
    store._client = client
    await store.initialize()

    model = AgentModel(id="operator", label="operator", interaction_count=3, reliability=0.8)
    await store.put(model)

    pts, _ = await client.scroll(
        collection_name="empatheia_agents",
        limit=10,
        offset=None,
        with_payload=True,
        with_vectors=True,
    )
    assert len(pts) == 1
    assert pts[0].vector == [0.0] * 4
    assert json.loads(pts[0].payload["profile_json"]) == model.to_dict()

    profiles = await store.all_profiles()
    assert "operator" in profiles
    assert profiles["operator"].to_dict() == model.to_dict()


@pytest.mark.asyncio
async def test_empatheia_all_profiles_raises_without_client():
    pytest.importorskip("qdrant_client")
    store = QdrantAgentStore(
        api_key="k",
        collection="empatheia_agents",
        latent_dim=4,
    )
    with pytest.raises(RuntimeError, match="not initialized"):
        await store.all_profiles()


@pytest.mark.asyncio
async def test_inmemory_export_ignores_uncreated_collections():
    storage = InMemoryStorage(latent_dim=4)
    point = {
        "id": "p1",
        "vector": [0.1, 0.2, 0.3, 0.4],
        "text": "hello",
        "payload": {"k": "v"},
        "affect": None,
    }
    await storage.replace_collection("x_episodic", [point])
    result = await storage.export(["x_episodic", "never_created"])
    assert list(result) == ["x_episodic"]
    assert [p["text"] for p in result["x_episodic"]] == ["hello"]


@pytest.mark.asyncio
async def test_qdrant_replace_collection_drops_stale_points():
    pytest.importorskip("qdrant_client")
    store = QdrantStorage(latent_dim=4, api_key="k")
    store._client = _FakeAsyncQdrant()

    p1 = {
        "id": "00000000-0000-0000-0000-00000000000a",
        "vector": [0.1, 0.2, 0.3, 0.4],
        "text": "a",
        "payload": {},
        "affect": None,
    }
    p2 = {
        "id": "00000000-0000-0000-0000-00000000000b",
        "vector": [0.4, 0.3, 0.2, 0.1],
        "text": "b",
        "payload": {},
        "affect": None,
    }
    p3 = {
        "id": "00000000-0000-0000-0000-00000000000c",
        "vector": [0.5, 0.6, 0.7, 0.8],
        "text": "c",
        "payload": {},
        "affect": None,
    }

    await store.replace_collection("c_episodic", [p1, p2])
    await store.replace_collection("c_episodic", [p3])

    result = await store.export(["c_episodic"])
    assert list(result) == ["c_episodic"]
    assert len(result["c_episodic"]) == 1
    assert result["c_episodic"][0]["id"] == "00000000-0000-0000-0000-00000000000c"

    bad = {
        "id": "00000000-0000-0000-0000-00000000000d",
        "vector": [0.1, 0.2, 0.3],
        "text": "bad",
        "payload": {},
        "affect": None,
    }
    with pytest.raises(StorageError):
        await store.replace_collection("c_episodic", [bad])

    result_after = await store.export(["c_episodic"])
    assert [p["id"] for p in result_after["c_episodic"]] == ["00000000-0000-0000-0000-00000000000c"]


@pytest.mark.asyncio
async def test_qdrant_export_paginates_large_collection():
    pytest.importorskip("qdrant_client")
    client = _FakeAsyncQdrant()
    embedder = FakeEmbedder(latent_dim=4)
    storage = QdrantStorage(latent_dim=4, api_key="k")
    storage._client = client
    await storage.initialize()

    vec = list(await embedder.encode("x"))
    point_ids = {f"{i:032x}" for i in range(300)}
    points = [
        {
            "id": f"{i:032x}",
            "vector": vec,
            "text": f"text {i}",
            "payload": {"i": i},
            "affect": None,
        }
        for i in range(300)
    ]
    await storage.replace_collection("big_episodic", points)
    exported = await storage.export(["big_episodic"])
    assert "big_episodic" in exported
    assert len(exported["big_episodic"]) == 300
    assert {p["id"] for p in exported["big_episodic"]} == point_ids


@pytest.mark.asyncio
async def test_import_absent_kind_empties_target():
    embedder = FakeEmbedder(latent_dim=4)
    storage = InMemoryStorage(latent_dim=4)
    await storage.initialize()
    core = MnemosCore(embedder, storage, collection_prefix="x_")
    await core.initialize()

    await core.store("old semantic point", collection="semantic")
    state = {
        "collection_prefix": "x_",
        "short_term": [],
        "persisted": {"x_episodic": []},
    }
    n = await core.import_state(state)
    assert n == 0

    results, _ = await core.recall("old semantic", collection="semantic")
    assert not any("old semantic point" in r.text for r in results)


@pytest.mark.asyncio
async def test_import_only_foreign_collections_raises():
    embedder = FakeEmbedder(latent_dim=4)
    storage = InMemoryStorage(latent_dim=4)
    await storage.initialize()
    core = MnemosCore(embedder, storage, collection_prefix="c_")
    await core.initialize()

    good_vec = list(await embedder.encode("good"))
    state = {
        "collection_prefix": "z_",
        "short_term": [],
        "persisted": {
            "a_episodic": [
                {"id": "p1", "vector": good_vec, "text": "alpha", "payload": {}, "affect": None}
            ],
        },
    }
    with pytest.raises(StorageError, match="none belongs to this bundle's prefix"):
        await core.import_state(state)


@pytest.mark.asyncio
async def test_import_empty_collection_prefix_maps_kind_directly():
    embedder = FakeEmbedder(latent_dim=4)
    storage = InMemoryStorage(latent_dim=4)
    await storage.initialize()
    core = MnemosCore(embedder, storage, collection_prefix="")
    await core.initialize()

    vec = list(await embedder.encode("good"))
    state = {
        "collection_prefix": "",
        "short_term": [],
        "persisted": {
            "episodic": [
                {"id": "p1", "vector": vec, "text": "alpha", "payload": {}, "affect": None}
            ],
        },
    }
    n = await core.import_state(state)
    assert n == 1

    results, _ = await core.recall("alpha", collection="episodic")
    assert any("alpha" in r.text for r in results)


@pytest.mark.asyncio
async def test_import_validation_failure_leaves_short_term_and_persisted_unchanged():
    embedder = FakeEmbedder(latent_dim=4)
    storage = InMemoryStorage(latent_dim=4)
    await storage.initialize()
    core = MnemosCore(embedder, storage, collection_prefix="x_")
    await core.initialize()

    await core.store("old episodic point", collection="episodic")
    await core.store("old semantic point", collection="semantic")
    await core.store("stm entry")

    good_vec = list(await embedder.encode("good"))
    bad_state = {
        "collection_prefix": "x_",
        "short_term": [
            {"text": "new stm", "payload": {}, "affect": None, "timestamp": 1.0}
        ],
        "persisted": {
            "x_episodic": [
                {"id": "p1", "vector": good_vec, "text": "new preserved", "payload": {}, "affect": None}
            ],
            "x_semantic": [
                {"id": "bad", "vector": good_vec[:2], "text": "bad", "payload": {}, "affect": None}
            ],
        },
    }
    with pytest.raises(StorageError):
        await core.import_state(bad_state)

    results_e, _ = await core.recall("old episodic", collection="episodic")
    assert any("old episodic point" in r.text for r in results_e)
    results_s, _ = await core.recall("old semantic", collection="semantic")
    assert any("old semantic point" in r.text for r in results_s)

    assert len(core._short_term) == 1
    assert core._short_term[0].text == "stm entry"


@pytest.mark.asyncio
async def test_sqlite_vec_import_absent_kind_empties_target(tmp_path: Path):
    pytest.importorskip("sqlite_vec")
    from kaine.modules.mnemos.storage import SqliteVecStorage

    db_path = tmp_path / "mnemos.db"
    storage = SqliteVecStorage(latent_dim=4, db_path=str(db_path))
    await storage.initialize()

    embedder = FakeEmbedder(latent_dim=4)
    core = MnemosCore(embedder, storage, collection_prefix="x_")
    await core.initialize()
    await core.store("old semantic point", collection="semantic")

    state = {
        "collection_prefix": "x_",
        "short_term": [],
        "persisted": {"x_episodic": []},
    }
    await core.import_state(state)
    assert await storage.count("x_semantic") == 0


@pytest.mark.asyncio
async def test_sqlite_vec_replace_collection_only_named_rows(tmp_path: Path):
    pytest.importorskip("sqlite_vec")
    from kaine.modules.mnemos.storage import SqliteVecStorage

    db_path = tmp_path / "mnemos.db"
    storage = SqliteVecStorage(latent_dim=4, db_path=str(db_path))
    await storage.initialize()

    vec = [0.1, 0.2, 0.3, 0.4]
    await storage.replace_collection(
        "x_episodic",
        [{"id": "a", "vector": vec, "text": "a", "payload": {}, "affect": None}],
    )
    await storage.replace_collection(
        "x_semantic",
        [{"id": "b", "vector": vec, "text": "b", "payload": {}, "affect": None}],
    )
    await storage.replace_collection("x_episodic", [])

    assert await storage.count("x_episodic") == 0
    assert await storage.count("x_semantic") == 1


@pytest.mark.asyncio
async def test_empatheia_put_generates_stable_valid_point_id():
    pytest.importorskip("qdrant_client")
    client = _FakeAsyncQdrant()
    store = QdrantAgentStore(
        api_key="k",
        collection="empatheia_agents",
        latent_dim=4,
        embedder=FakeEmbedder(latent_dim=4),
    )
    store._client = client
    await store.initialize()

    model = AgentModel(
        id="operator", label="operator", interaction_count=1, reliability=0.5
    )
    expected_pid = str(uuid.uuid5(_AGENT_ID_NAMESPACE, "operator"))

    await store.put(model)
    pts, _ = await client.scroll(
        collection_name="empatheia_agents",
        limit=10,
        offset=None,
        with_payload=True,
        with_vectors=True,
    )
    assert len(pts) == 1
    assert pts[0].id == expected_pid

    model2 = AgentModel(
        id="operator", label="operator", interaction_count=2, reliability=0.6
    )
    await store.put(model2)
    pts2, _ = await client.scroll(
        collection_name="empatheia_agents",
        limit=10,
        offset=None,
        with_payload=True,
        with_vectors=True,
    )
    assert len(pts2) == 1
    assert pts2[0].id == expected_pid
    assert json.loads(pts2[0].payload["profile_json"]) == model2.to_dict()


