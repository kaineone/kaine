# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Vector storage backends for Mnemos.

`MemoryStorage` is the protocol; `QdrantStorage` is the production
default (Tier 2); `InMemoryStorage` is the deterministic fallback for
tests; `SqliteVecStorage` is the in-process edge backend (Tier 0/1) —
an ``asg017/sqlite-vec`` vector index with near-zero idle footprint and
no server, selected by ``[mnemos].backend = "sqlite_vec"`` (openspec
runtime-backends). All three satisfy the SAME protocol and store the same
CLS collections, so selecting a backend never changes Mnemos's semantics.
"""
from __future__ import annotations

import json
import logging
import math
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

log = logging.getLogger(__name__)


class StorageError(Exception):
    """Raised when a storage backend operation fails.

    Callers MUST handle or propagate this; swallowing it as an empty
    result would fabricate a "no relevant memories" outcome on an
    actual failure (pretend-process violation).
    """


@dataclass(frozen=True)
class RecalledMemory:
    point_id: str
    score: float
    text: str
    payload: dict[str, Any] = field(default_factory=dict)
    affect: dict[str, Any] | None = None


@runtime_checkable
class MemoryStorage(Protocol):
    @property
    def latent_dim(self) -> int: ...

    async def initialize(self) -> None: ...

    async def shutdown(self) -> None: ...

    async def ensure_collection(self, name: str) -> None: ...

    async def upsert(
        self,
        collection: str,
        *,
        vector: list[float],
        text: str,
        payload: dict[str, Any],
        affect: dict[str, Any] | None,
        point_id: str | None = None,
    ) -> str: ...

    async def search(
        self,
        collection: str,
        *,
        query_vector: list[float],
        limit: int,
    ) -> list[RecalledMemory]: ...

    async def delete(self, collection: str, point_id: str) -> None: ...

    async def count(self, collection: str) -> int: ...

    async def export(self) -> dict[str, list[dict[str, Any]]]: ...

    async def import_(self, collections: dict[str, list[dict[str, Any]]]) -> int: ...


def _cosine(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


class InMemoryStorage:
    """Pure-Python backend. Useful for tests and minimal deployments.

    Collections live in a dict mapping name → list of points. Each
    point keeps its vector, text, payload, and affect. Search is
    linear (O(N) per query) — acceptable for short-term tests and
    documented as the test backend.
    """

    def __init__(self, latent_dim: int) -> None:
        if latent_dim <= 0:
            raise ValueError("latent_dim must be positive")
        self._latent_dim = int(latent_dim)
        self._collections: dict[str, list[dict[str, Any]]] = {}

    @property
    def latent_dim(self) -> int:
        return self._latent_dim

    async def initialize(self) -> None:
        return

    async def shutdown(self) -> None:
        return

    async def ensure_collection(self, name: str) -> None:
        self._collections.setdefault(name, [])

    async def upsert(
        self,
        collection: str,
        *,
        vector: list[float],
        text: str,
        payload: dict[str, Any],
        affect: dict[str, Any] | None,
        point_id: str | None = None,
    ) -> str:
        if len(vector) != self._latent_dim:
            raise ValueError(
                f"vector dim {len(vector)} != storage latent_dim {self._latent_dim}"
            )
        pid = point_id or uuid.uuid4().hex
        self._collections.setdefault(collection, [])
        self._collections[collection].append(
            {
                "id": pid,
                "vector": list(vector),
                "text": text,
                "payload": dict(payload),
                "affect": dict(affect) if affect else None,
            }
        )
        return pid

    async def search(
        self,
        collection: str,
        *,
        query_vector: list[float],
        limit: int,
    ) -> list[RecalledMemory]:
        if collection not in self._collections:
            return []
        scored: list[tuple[float, dict[str, Any]]] = []
        for point in self._collections[collection]:
            scored.append((_cosine(query_vector, point["vector"]), point))
        scored.sort(key=lambda t: t[0], reverse=True)
        out: list[RecalledMemory] = []
        for score, point in scored[: max(0, int(limit))]:
            out.append(
                RecalledMemory(
                    point_id=point["id"],
                    score=score,
                    text=point["text"],
                    payload=dict(point["payload"]),
                    affect=dict(point["affect"]) if point["affect"] else None,
                )
            )
        return out

    async def delete(self, collection: str, point_id: str) -> None:
        if collection not in self._collections:
            return
        self._collections[collection] = [
            p for p in self._collections[collection] if p["id"] != point_id
        ]

    async def count(self, collection: str) -> int:
        return len(self._collections.get(collection, []))

    async def export(self) -> dict[str, list[dict[str, Any]]]:
        """Full-fidelity dump of every collection's points.

        Each point is ``{id, vector, text, payload, affect}`` — the same shape
        :meth:`upsert` stores. Used by Mnemos preservation so the persisted
        vector memory travels with the bundle, not just its sizes.
        """
        out: dict[str, list[dict[str, Any]]] = {}
        for name, points in self._collections.items():
            out[name] = [
                {
                    "id": p["id"],
                    "vector": list(p["vector"]),
                    "text": p["text"],
                    "payload": dict(p["payload"]),
                    "affect": dict(p["affect"]) if p["affect"] else None,
                }
                for p in points
            ]
        return out

    async def import_(self, collections: dict[str, list[dict[str, Any]]]) -> int:
        """Rebuild collections from an :meth:`export` dump. Returns point count.

        Replaces the in-memory store wholesale (revive runs against a fresh,
        empty backend), preserving point ids/vectors/text/payload/affect so a
        revived entity recalls exactly what was preserved.
        """
        total = 0
        for name, points in (collections or {}).items():
            self._collections.setdefault(name, [])
            for p in points:
                vec = list(p.get("vector") or [])
                if len(vec) != self._latent_dim:
                    raise StorageError(
                        f"imported point in {name!r} has vector dim {len(vec)} "
                        f"!= storage latent_dim {self._latent_dim}"
                    )
                affect = p.get("affect")
                self._collections[name].append(
                    {
                        "id": str(p.get("id") or uuid.uuid4().hex),
                        "vector": vec,
                        "text": str(p.get("text", "")),
                        "payload": dict(p.get("payload") or {}),
                        "affect": dict(affect) if affect else None,
                    }
                )
                total += 1
        return total


class SqliteVecStorage:
    """In-process vector store on ``sqlite-vec`` (edge backend, Tier 0/1).

    A single SQLite file holds a ``vec0`` virtual table for the vectors plus a
    companion metadata table for text/payload/affect; cosine KNN runs inside the
    process with no Qdrant server and near-zero idle footprint — the single-user
    edge counterpart of :class:`QdrantStorage`. It stores the same CLS
    collections and exposes the same ``search`` (``query_points``-equivalent)
    API, so Mnemos's memory semantics are unchanged (openspec runtime-backends).

    ``sqlite_vec`` is imported lazily inside :meth:`initialize` (mirroring
    :class:`QdrantStorage`'s lazy ``qdrant_client`` import), so a Tier-2 install
    that never selects this backend does not need the dependency.
    """

    def __init__(
        self,
        latent_dim: int,
        *,
        db_path: str = "state/mnemos/mnemos.db",
        distance: str = "cosine",
    ) -> None:
        if latent_dim <= 0:
            raise ValueError("latent_dim must be positive")
        self._latent_dim = int(latent_dim)
        self._db_path = str(db_path)
        self._distance = distance
        self._db: Any = None

    @property
    def latent_dim(self) -> int:
        return self._latent_dim

    async def initialize(self) -> None:
        if self._db is not None:
            return
        import asyncio

        def _open() -> Any:
            import os
            import sqlite3

            import sqlite_vec  # type: ignore[import-untyped]

            parent = os.path.dirname(self._db_path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            db = sqlite3.connect(self._db_path)
            db.enable_load_extension(True)
            sqlite_vec.load(db)
            db.enable_load_extension(False)
            db.execute(
                "CREATE TABLE IF NOT EXISTS memories ("
                "rowid INTEGER PRIMARY KEY AUTOINCREMENT, collection TEXT, "
                "point_id TEXT, text TEXT, payload TEXT, affect TEXT)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS memories_collection "
                "ON memories(collection)"
            )
            db.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS memories_pid "
                "ON memories(collection, point_id)"
            )
            db.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories USING vec0("
                f"embedding float[{self._latent_dim}] distance_metric=cosine)"
            )
            db.commit()
            return db

        self._db = await asyncio.to_thread(_open)

    async def shutdown(self) -> None:
        if self._db is not None:
            db, self._db = self._db, None
            try:
                db.close()
            except Exception:
                log.warning("sqlite-vec close failed", exc_info=True)

    async def ensure_collection(self, name: str) -> None:
        # Collections are a metadata column, not a separate table — nothing to
        # create up-front. Kept for protocol parity with Qdrant.
        return

    async def upsert(
        self,
        collection: str,
        *,
        vector: list[float],
        text: str,
        payload: dict[str, Any],
        affect: dict[str, Any] | None,
        point_id: str | None = None,
    ) -> str:
        import asyncio
        import struct

        if len(vector) != self._latent_dim:
            raise ValueError(
                f"vector dim {len(vector)} != storage latent_dim {self._latent_dim}"
            )
        pid = point_id or uuid.uuid4().hex
        blob = struct.pack(f"{self._latent_dim}f", *[float(x) for x in vector])
        payload_json = json.dumps(payload or {})
        affect_json = json.dumps(affect) if affect else None

        def _write() -> None:
            db = self._db
            assert db is not None
            cur = db.execute(
                "SELECT rowid FROM memories WHERE collection = ? AND point_id = ?",
                (collection, pid),
            )
            row = cur.fetchone()
            if row is not None:
                rowid = int(row[0])
                db.execute(
                    "UPDATE memories SET text = ?, payload = ?, affect = ? "
                    "WHERE rowid = ?",
                    (text, payload_json, affect_json, rowid),
                )
                db.execute(
                    "UPDATE vec_memories SET embedding = ? WHERE rowid = ?",
                    (blob, rowid),
                )
            else:
                cur = db.execute(
                    "INSERT INTO memories (collection, point_id, text, payload, "
                    "affect) VALUES (?, ?, ?, ?, ?)",
                    (collection, pid, text, payload_json, affect_json),
                )
                rowid = int(cur.lastrowid)
                db.execute(
                    "INSERT INTO vec_memories (rowid, embedding) VALUES (?, ?)",
                    (rowid, blob),
                )
            db.commit()

        await asyncio.to_thread(_write)
        return pid

    async def search(
        self,
        collection: str,
        *,
        query_vector: list[float],
        limit: int,
    ) -> list[RecalledMemory]:
        import asyncio
        import struct

        blob = struct.pack(
            f"{self._latent_dim}f", *[float(x) for x in query_vector]
        )
        k = max(0, int(limit))
        if k == 0:
            return []

        def _query() -> list[RecalledMemory]:
            db = self._db
            if db is None:
                raise StorageError("sqlite-vec search before initialize()")
            try:
                cur = db.execute(
                    "SELECT m.point_id, v.distance, m.text, m.payload, m.affect "
                    "FROM vec_memories v JOIN memories m ON m.rowid = v.rowid "
                    "WHERE v.embedding MATCH ? AND m.collection = ? AND k = ? "
                    "ORDER BY v.distance",
                    (blob, collection, k),
                )
                rows = cur.fetchall()
            except Exception as exc:
                raise StorageError(
                    f"sqlite-vec search failed for collection {collection!r}: {exc}"
                ) from exc
            out: list[RecalledMemory] = []
            for point_id, distance, text, payload_json, affect_json in rows:
                # vec0 cosine distance → similarity score on the same [-1, 1]
                # scale Qdrant/InMemory report.
                score = 1.0 - float(distance)
                affect = json.loads(affect_json) if affect_json else None
                out.append(
                    RecalledMemory(
                        point_id=str(point_id),
                        score=score,
                        text=str(text or ""),
                        payload=json.loads(payload_json) if payload_json else {},
                        affect=affect,
                    )
                )
            return out

        return await asyncio.to_thread(_query)

    async def delete(self, collection: str, point_id: str) -> None:
        import asyncio

        def _del() -> None:
            db = self._db
            assert db is not None
            cur = db.execute(
                "SELECT rowid FROM memories WHERE collection = ? AND point_id = ?",
                (collection, point_id),
            )
            row = cur.fetchone()
            if row is None:
                return
            rowid = int(row[0])
            db.execute("DELETE FROM vec_memories WHERE rowid = ?", (rowid,))
            db.execute("DELETE FROM memories WHERE rowid = ?", (rowid,))
            db.commit()

        await asyncio.to_thread(_del)

    async def count(self, collection: str) -> int:
        import asyncio

        def _count() -> int:
            db = self._db
            if db is None:
                return 0
            cur = db.execute(
                "SELECT COUNT(*) FROM memories WHERE collection = ?", (collection,)
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0

        return await asyncio.to_thread(_count)

    async def export(self) -> dict[str, list[dict[str, Any]]]:
        import asyncio
        import struct

        def _export() -> dict[str, list[dict[str, Any]]]:
            db = self._db
            if db is None:
                raise StorageError("sqlite-vec export before initialize()")
            out: dict[str, list[dict[str, Any]]] = {}
            try:
                cur = db.execute(
                    "SELECT m.collection, m.point_id, m.text, m.payload, m.affect, "
                    "v.embedding FROM memories m JOIN vec_memories v "
                    "ON v.rowid = m.rowid"
                )
                for coll, pid, text, payload_json, affect_json, emb in cur.fetchall():
                    vec = list(struct.unpack(f"{self._latent_dim}f", emb))
                    affect = json.loads(affect_json) if affect_json else None
                    out.setdefault(str(coll), []).append(
                        {
                            "id": str(pid),
                            "vector": vec,
                            "text": str(text or ""),
                            "payload": json.loads(payload_json) if payload_json else {},
                            "affect": affect,
                        }
                    )
            except Exception as exc:
                raise StorageError(f"sqlite-vec export failed: {exc}") from exc
            return out

        return await asyncio.to_thread(_export)

    async def import_(self, collections: dict[str, list[dict[str, Any]]]) -> int:
        total = 0
        for name, points in (collections or {}).items():
            for p in points:
                vec = list(p.get("vector") or [])
                if len(vec) != self._latent_dim:
                    raise StorageError(
                        f"imported point in {name!r} has vector dim {len(vec)} "
                        f"!= storage latent_dim {self._latent_dim}"
                    )
                await self.upsert(
                    name,
                    vector=vec,
                    text=str(p.get("text", "")),
                    payload=dict(p.get("payload") or {}),
                    affect=(dict(p["affect"]) if p.get("affect") else None),
                    point_id=str(p.get("id") or uuid.uuid4().hex),
                )
                total += 1
        return total


class QdrantStorage:
    """Production storage backed by a KAINE-owned Qdrant container.

    API key is mandatory: the bootstrap script generates it, the compose
    file requires it, KAINE's loader pulls it from secrets/env.
    """

    def __init__(
        self,
        latent_dim: int,
        *,
        host: str = "127.0.0.1",
        port: int = 6533,
        api_key: str | None = None,
        distance: str = "Cosine",
    ) -> None:
        if latent_dim <= 0:
            raise ValueError("latent_dim must be positive")
        if not api_key:
            raise ValueError(
                "QdrantStorage requires api_key (mandatory on every host)"
            )
        self._latent_dim = int(latent_dim)
        self._host = host
        self._port = int(port)
        self._api_key = api_key
        self._distance = distance
        self._client: Any = None

    @property
    def latent_dim(self) -> int:
        return self._latent_dim

    async def initialize(self) -> None:
        if self._client is not None:
            return
        import asyncio

        def _open():
            from qdrant_client import AsyncQdrantClient  # type: ignore[import-untyped]

            return AsyncQdrantClient(
                host=self._host,
                port=self._port,
                api_key=self._api_key,
                https=False,
            )

        self._client = await asyncio.to_thread(_open)

    async def shutdown(self) -> None:
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                log.warning("qdrant client close failed", exc_info=True)
            self._client = None

    async def ensure_collection(self, name: str) -> None:
        from qdrant_client import models  # type: ignore[import-untyped]

        assert self._client is not None
        existing = await self._client.get_collections()
        existing_names = {c.name for c in existing.collections}
        if name in existing_names:
            return
        await self._client.create_collection(
            collection_name=name,
            vectors_config=models.VectorParams(
                size=self._latent_dim,
                distance=models.Distance.COSINE if self._distance == "Cosine" else models.Distance.DOT,
            ),
        )

    async def upsert(
        self,
        collection: str,
        *,
        vector: list[float],
        text: str,
        payload: dict[str, Any],
        affect: dict[str, Any] | None,
        point_id: str | None = None,
    ) -> str:
        from qdrant_client import models  # type: ignore[import-untyped]

        assert self._client is not None
        if len(vector) != self._latent_dim:
            raise ValueError(
                f"vector dim {len(vector)} != storage latent_dim {self._latent_dim}"
            )
        pid = point_id or uuid.uuid4().hex
        merged_payload: dict[str, Any] = {"text": text, **payload}
        if affect:
            merged_payload["affect"] = affect
        await self._client.upsert(
            collection_name=collection,
            points=[
                models.PointStruct(id=pid, vector=list(vector), payload=merged_payload)
            ],
        )
        return pid

    async def search(
        self,
        collection: str,
        *,
        query_vector: list[float],
        limit: int,
    ) -> list[RecalledMemory]:
        assert self._client is not None
        try:
            # qdrant-client >=1.12 removed AsyncQdrantClient.search; query_points
            # is the replacement. The bare vector is passed as `query` and the
            # scored points come back under `.points`.
            response = await self._client.query_points(
                collection_name=collection,
                query=list(query_vector),
                limit=int(limit),
                with_payload=True,
            )
            hits = response.points
        except Exception as exc:
            raise StorageError(
                f"qdrant search failed for collection {collection!r}: {exc}"
            ) from exc
        out: list[RecalledMemory] = []
        for h in hits:
            payload = dict(h.payload or {})
            text = str(payload.pop("text", ""))
            affect = payload.pop("affect", None)
            out.append(
                RecalledMemory(
                    point_id=str(h.id),
                    score=float(h.score),
                    text=text,
                    payload=payload,
                    affect=dict(affect) if affect else None,
                )
            )
        return out

    async def delete(self, collection: str, point_id: str) -> None:
        from qdrant_client import models  # type: ignore[import-untyped]

        assert self._client is not None
        await self._client.delete(
            collection_name=collection,
            points_selector=models.PointIdsList(points=[point_id]),
        )

    async def count(self, collection: str) -> int:
        assert self._client is not None
        try:
            info = await self._client.count(collection_name=collection, exact=True)
        except Exception:
            return 0
        return int(info.count)

    async def export(self) -> dict[str, list[dict[str, Any]]]:
        """Scroll every Mnemos collection into a full-fidelity point dump.

        FAILS LOUDLY (raises :class:`StorageError`) if the server is
        unreachable or a scroll fails — a preservation that cannot read the
        vector store MUST NOT silently emit an empty memory set that looks
        complete. Returns ``{collection: [{id, vector, text, payload, affect}]}``.
        """
        assert self._client is not None
        try:
            existing = await self._client.get_collections()
            names = [c.name for c in existing.collections]
        except Exception as exc:
            raise StorageError(
                f"qdrant export failed: could not list collections ({exc})"
            ) from exc
        out: dict[str, list[dict[str, Any]]] = {}
        for name in names:
            points: list[dict[str, Any]] = []
            offset = None
            try:
                while True:
                    batch, offset = await self._client.scroll(
                        collection_name=name,
                        limit=256,
                        offset=offset,
                        with_payload=True,
                        with_vectors=True,
                    )
                    for p in batch:
                        payload = dict(getattr(p, "payload", None) or {})
                        text = str(payload.pop("text", ""))
                        affect = payload.pop("affect", None)
                        points.append(
                            {
                                "id": getattr(p, "id", None),
                                "vector": getattr(p, "vector", None),
                                "text": text,
                                "payload": payload,
                                "affect": dict(affect) if affect else None,
                            }
                        )
                    if offset is None:
                        break
            except Exception as exc:
                raise StorageError(
                    f"qdrant export failed scrolling collection {name!r}: {exc}"
                ) from exc
            out[name] = points
        return out

    async def import_(self, collections: dict[str, list[dict[str, Any]]]) -> int:
        """Recreate collections and re-upsert every exported point.

        FAILS LOUDLY on any error — a revive that cannot restore the vector
        store must raise, not produce a memory-poor lesser individual.
        """
        from qdrant_client import models  # type: ignore[import-untyped]

        assert self._client is not None
        total = 0
        for name, points in (collections or {}).items():
            try:
                await self.ensure_collection(name)
            except Exception as exc:
                raise StorageError(
                    f"qdrant import failed creating collection {name!r}: {exc}"
                ) from exc
            structs = []
            for p in points:
                vec = list(p.get("vector") or [])
                if len(vec) != self._latent_dim:
                    raise StorageError(
                        f"imported point in {name!r} has vector dim {len(vec)} "
                        f"!= storage latent_dim {self._latent_dim}"
                    )
                merged_payload: dict[str, Any] = {
                    "text": str(p.get("text", "")),
                    **dict(p.get("payload") or {}),
                }
                affect = p.get("affect")
                if affect:
                    merged_payload["affect"] = dict(affect)
                structs.append(
                    models.PointStruct(
                        id=p.get("id") or uuid.uuid4().hex,
                        vector=vec,
                        payload=merged_payload,
                    )
                )
            if structs:
                try:
                    await self._client.upsert(collection_name=name, points=structs)
                except Exception as exc:
                    raise StorageError(
                        f"qdrant import failed upserting into {name!r}: {exc}"
                    ) from exc
                total += len(structs)
        return total
