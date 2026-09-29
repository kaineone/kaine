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

import asyncio
import json
import logging
import math
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Sequence, TypeVar, runtime_checkable

from kaine.memory_kinds import MNEMOS_STAMP_COLLECTION, stamp_point_id

log = logging.getLogger(__name__)

_T = TypeVar("_T")

_REQUIRED_STAMP_KEYS = frozenset({"model_id", "dim", "pooling", "normalized"})


def _validate_stamp(value: Any, backend: str, key: str) -> None:
    """Fail loudly on malformed embedding-space stamps.

    A stamp that is present but malformed must never be read as "no
    stamp"; otherwise Mnemos would silently re-stamp a store and
    pretend the existing vectors belong to the current embedder.

    The four canonical keys must be present with the right types; extra
    keys (from newer versions) are tolerated so a rollback does not refuse
    memory access.
    """
    if not isinstance(value, dict):
        raise StorageError(
            f"{backend} stamp for {key!r} is malformed: not a dict ({value!r})"
        )
    missing = _REQUIRED_STAMP_KEYS - value.keys()
    if missing:
        raise StorageError(
            f"{backend} stamp for {key!r} is malformed: "
            f"missing keys {sorted(missing)}"
        )
    if not isinstance(value.get("model_id"), str):
        raise StorageError(
            f"{backend} stamp for {key!r} is malformed: "
            f"model_id must be a string, got {value.get('model_id')!r}"
        )
    dim = value.get("dim")
    if not isinstance(dim, int) or isinstance(dim, bool):
        raise StorageError(
            f"{backend} stamp for {key!r} is malformed: "
            f"dim must be an int, got {dim!r}"
        )
    if not isinstance(value.get("pooling"), str):
        raise StorageError(
            f"{backend} stamp for {key!r} is malformed: "
            f"pooling must be a string, got {value.get('pooling')!r}"
        )
    normalized = value.get("normalized")
    if not isinstance(normalized, bool):
        raise StorageError(
            f"{backend} stamp for {key!r} is malformed: "
            f"normalized must be a bool, got {normalized!r}"
        )


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

    async def count(self, collection: str, strict: bool = False) -> int: ...

    async def vector_dim(self, collection: str) -> int | None: ...

    async def export(self, collections: Sequence[str]) -> dict[str, list[dict[str, Any]]]: ...

    async def replace_collection(self, name: str, points: Sequence[dict[str, Any]]) -> int: ...

    async def read_stamp(self, key: str) -> dict | None: ...

    async def write_stamp(self, key: str, stamp: dict) -> None: ...


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
        self._stamps: dict[str, dict] = {}

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

    async def count(self, collection: str, strict: bool = False) -> int:
        return len(self._collections.get(collection, []))

    async def vector_dim(self, collection: str) -> int | None:
        points = self._collections.get(collection, [])
        if not points:
            return None
        return len(points[0]["vector"])

    async def export(self, collections: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
        """Full-fidelity dump of the requested collections' points.

        Each point is ``{id, vector, text, payload, affect}`` — the same shape
        :meth:`upsert` stores. Used by Mnemos preservation so the persisted
        vector memory travels with the bundle, not just its sizes.
        Collections that do not exist are simply absent from the result.
        """
        out: dict[str, list[dict[str, Any]]] = {}
        for name in collections:
            if name not in self._collections:
                continue
            points = self._collections[name]
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

    async def replace_collection(self, name: str, points: Sequence[dict[str, Any]]) -> int:
        """Replace one collection with the given points. Returns point count.

        FAILS LOUDLY if any point has the wrong dimension or a non-finite
        vector — the target collection is left untouched on validation failure.
        """
        for p in points:
            vec = list(p.get("vector") or [])
            if len(vec) != self._latent_dim or not all(math.isfinite(v) for v in vec):
                raise StorageError(
                    f"point in {name!r} has invalid vector "
                    f"(dim {len(vec)} != {self._latent_dim} or non-finite)"
                )
        self._collections[name] = [
            {
                "id": str(p.get("id") or uuid.uuid4().hex),
                "vector": list(p.get("vector") or []),
                "text": str(p.get("text", "")),
                "payload": dict(p.get("payload") or {}),
                "affect": dict(p["affect"]) if p.get("affect") else None,
            }
            for p in points
        ]
        return len(points)

    async def read_stamp(self, key: str) -> dict | None:
        if key not in self._stamps:
            return None
        value = self._stamps[key]
        _validate_stamp(value, "in-memory", key)
        return dict(value)

    async def write_stamp(self, key: str, stamp: dict) -> None:
        self._stamps[key] = dict(stamp)


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

    Thread affinity: a ``sqlite3`` connection may only be used on the thread
    that created it, and one connection is not safe for concurrent use. The
    store therefore owns a dedicated single-worker executor for the life of
    the connection: it is opened, used and closed on that one thread, and
    every call is serialised through it (:meth:`_run`). The event loop's
    shared default executor (``asyncio.to_thread``) would instead hand each
    call to whichever worker is free, which need not be the opening thread.
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
        # The one thread that owns ``self._db``; set and cleared with it.
        self._executor: ThreadPoolExecutor | None = None

    @property
    def latent_dim(self) -> int:
        return self._latent_dim

    async def _run(self, fn: Callable[[Any], _T]) -> _T:
        """Run ``fn(db)`` on the connection's owning thread.

        ``fn`` receives the open connection. Before :meth:`initialize` or
        after :meth:`shutdown` it receives ``None`` and runs inline; each
        caller turns that into its own not-open outcome without touching
        SQLite. The connection is bound at submission, so a call queued before
        :meth:`shutdown` completes on the live connection ahead of the close.
        """
        executor, db = self._executor, self._db
        if executor is None or db is None:
            return fn(None)
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(executor, fn, db)

    async def initialize(self) -> None:
        if self._db is not None:
            return

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
            db.execute(
                "CREATE TABLE IF NOT EXISTS kaine_meta ("
                "key TEXT PRIMARY KEY, value TEXT)"
            )
            db.commit()
            return db

        executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mnemos-sqlite"
        )
        loop = asyncio.get_running_loop()
        try:
            db = await loop.run_in_executor(executor, _open)
        except BaseException:
            executor.shutdown(wait=False)
            raise
        if self._db is not None:
            # A concurrent initialize() won the race; keep its connection.
            await loop.run_in_executor(executor, db.close)
            executor.shutdown(wait=False)
            return
        self._db, self._executor = db, executor

    async def shutdown(self) -> None:
        db, executor = self._db, self._executor
        if db is None or executor is None:
            return
        # New calls see a closed store from here on; calls already queued on
        # the owning thread still run first (FIFO), then the close.
        self._db, self._executor = None, None
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(executor, db.close)
        except Exception:
            log.warning("sqlite-vec close failed", exc_info=True)
        finally:
            # The close was the last queued job, so this only retires the
            # now-idle worker thread.
            executor.shutdown(wait=True)

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
        import struct

        if len(vector) != self._latent_dim:
            raise ValueError(
                f"vector dim {len(vector)} != storage latent_dim {self._latent_dim}"
            )
        pid = point_id or uuid.uuid4().hex
        blob = struct.pack(f"{self._latent_dim}f", *[float(x) for x in vector])
        payload_json = json.dumps(payload or {})
        affect_json = json.dumps(affect) if affect else None

        def _write(db: Any) -> None:
            if db is None:
                raise StorageError("sqlite-vec store is not open")
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
                self._insert_point_sync(
                    db, collection, pid, vector, text, payload_json, affect_json
                )
            db.commit()

        await self._run(_write)
        return pid

    def _insert_point_sync(
        self,
        db: Any,
        collection: str,
        point_id: str,
        vector: list[float],
        text: str,
        payload_json: str,
        affect_json: str | None,
    ) -> None:
        import struct

        blob = struct.pack(
            f"{self._latent_dim}f", *[float(x) for x in vector]
        )
        cur = db.execute(
            "INSERT INTO memories (collection, point_id, text, payload, affect) "
            "VALUES (?, ?, ?, ?, ?)",
            (collection, point_id, text, payload_json, affect_json),
        )
        rowid = int(cur.lastrowid)
        db.execute(
            "INSERT INTO vec_memories (rowid, embedding) VALUES (?, ?)",
            (rowid, blob),
        )

    async def search(
        self,
        collection: str,
        *,
        query_vector: list[float],
        limit: int,
    ) -> list[RecalledMemory]:
        import struct

        blob = struct.pack(
            f"{self._latent_dim}f", *[float(x) for x in query_vector]
        )
        k = max(0, int(limit))
        if k == 0:
            return []

        def _query(db: Any) -> list[RecalledMemory]:
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

        return await self._run(_query)

    async def delete(self, collection: str, point_id: str) -> None:

        def _del(db: Any) -> None:
            if db is None:
                raise StorageError("sqlite-vec store is not open")
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

        await self._run(_del)

    async def count(self, collection: str, strict: bool = False) -> int:

        def _count(db: Any) -> int:
            if db is None:
                if strict:
                    raise StorageError("sqlite-vec count before initialize()")
                return 0
            try:
                cur = db.execute(
                    "SELECT COUNT(*) FROM memories WHERE collection = ?", (collection,)
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0
            except Exception as exc:
                if strict:
                    raise StorageError(
                        f"sqlite-vec count failed for {collection!r}: {exc}"
                    ) from exc
                return 0

        return await self._run(_count)

    async def vector_dim(self, collection: str) -> int | None:
        import re

        def _dim(db: Any) -> int | None:
            if db is None:
                raise StorageError("sqlite-vec vector_dim before initialize()")
            try:
                cur = db.execute(
                    "SELECT COUNT(*) FROM memories WHERE collection = ?", (collection,)
                )
                row = cur.fetchone()
                has_rows = bool(row and int(row[0]) > 0)
            except Exception as exc:
                raise StorageError(
                    f"sqlite-vec vector_dim failed counting {collection!r}: {exc}"
                ) from exc
            cur = db.execute(
                "SELECT sql FROM sqlite_master "
                "WHERE type='table' AND name='vec_memories'"
            )
            row = cur.fetchone()
            if row is None or row[0] is None:
                if has_rows:
                    raise StorageError(
                        f"sqlite-vec vector_dim: {collection!r} has rows "
                        "but vec_memories table is missing"
                    )
                return None
            sql = str(row[0])
            match = re.search(r"float\s*\[\s*(\d+)\s*\]", sql)
            if not match:
                raise StorageError(
                    f"sqlite-vec vector_dim: could not parse dimension from "
                    f"vec_memories SQL: {sql!r}"
                )
            return int(match.group(1))

        return await self._run(_dim)

    async def export(self, collections: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
        import struct

        if not collections:
            return {}

        def _export(db: Any) -> dict[str, list[dict[str, Any]]]:
            if db is None:
                raise StorageError("sqlite-vec export before initialize()")
            out: dict[str, list[dict[str, Any]]] = {}
            try:
                placeholders = ",".join("?" for _ in collections)
                cur = db.execute(
                    "SELECT m.collection, m.point_id, m.text, m.payload, m.affect, "
                    "v.embedding FROM memories m JOIN vec_memories v "
                    f"ON v.rowid = m.rowid WHERE m.collection IN ({placeholders})",
                    tuple(collections),
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

        return await self._run(_export)

    async def replace_collection(self, name: str, points: Sequence[dict[str, Any]]) -> int:

        for p in points:
            vec = list(p.get("vector") or [])
            if len(vec) != self._latent_dim or not all(math.isfinite(v) for v in vec):
                raise StorageError(
                    f"point in {name!r} has invalid vector "
                    f"(dim {len(vec)} != {self._latent_dim} or non-finite)"
                )

        def _replace(db: Any) -> int:
            if db is None:
                raise StorageError("sqlite-vec replace_collection before initialize()")
            try:
                db.execute("BEGIN")
                db.execute(
                    "DELETE FROM vec_memories WHERE rowid IN "
                    "(SELECT rowid FROM memories WHERE collection = ?)",
                    (name,),
                )
                db.execute("DELETE FROM memories WHERE collection = ?", (name,))
                for p in points:
                    pid = str(p.get("id") or uuid.uuid4().hex)
                    vec = list(p.get("vector") or [])
                    text = str(p.get("text", ""))
                    payload_json = json.dumps(p.get("payload") or {})
                    affect_json = json.dumps(p["affect"]) if p.get("affect") else None
                    self._insert_point_sync(
                        db, name, pid, vec, text, payload_json, affect_json
                    )
                db.commit()
                return len(points)
            except Exception as exc:
                db.rollback()
                raise StorageError(
                    f"sqlite-vec replace_collection failed for {name!r}: {exc}"
                ) from exc

        return await self._run(_replace)

    async def read_stamp(self, key: str) -> dict | None:

        def _read(db: Any) -> dict | None:
            if db is None:
                raise StorageError("sqlite-vec read_stamp before initialize()")
            try:
                cur = db.execute(
                    "SELECT value FROM kaine_meta WHERE key = ?", (key,)
                )
                row = cur.fetchone()
                if row is None:
                    return None
                try:
                    value = json.loads(row[0])
                except json.JSONDecodeError as exc:
                    raise StorageError(
                        f"sqlite-vec stamp for {key!r} is malformed: {exc}"
                    ) from exc
                _validate_stamp(value, "sqlite-vec", key)
                return value
            except StorageError:
                raise
            except Exception as exc:
                raise StorageError(
                    f"sqlite-vec read_stamp failed for {key!r}: {exc}"
                ) from exc

        return await self._run(_read)

    async def write_stamp(self, key: str, stamp: dict) -> None:

        def _write(db: Any) -> None:
            if db is None:
                raise StorageError("sqlite-vec write_stamp before initialize()")
            try:
                db.execute(
                    "INSERT INTO kaine_meta (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(stamp)),
                )
                db.commit()
            except Exception as exc:
                raise StorageError(
                    f"sqlite-vec write_stamp failed for {key!r}: {exc}"
                ) from exc

        await self._run(_write)


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

    async def count(self, collection: str, strict: bool = False) -> int:
        assert self._client is not None
        try:
            info = await self._client.count(collection_name=collection, exact=True)
        except Exception as exc:
            if strict:
                raise StorageError(
                    f"qdrant count failed for {collection!r}: {exc}"
                ) from exc
            return 0
        return int(info.count)

    async def vector_dim(self, collection: str) -> int | None:
        assert self._client is not None
        try:
            existing = await self._client.get_collections()
            existing_names = {c.name for c in existing.collections}
        except Exception as exc:
            raise StorageError(
                f"qdrant vector_dim failed listing collections: {exc}"
            ) from exc
        if collection not in existing_names:
            return None
        try:
            coll_info = await self._client.get_collection(collection_name=collection)
        except Exception as exc:
            raise StorageError(
                f"qdrant vector_dim failed reading collection {collection!r}: {exc}"
            ) from exc
        vectors = coll_info.config.params.vectors
        if isinstance(vectors, dict):
            raise StorageError(
                f"qdrant collection {collection!r} uses named vectors; "
                "Mnemos never creates named vectors"
            )
        try:
            return int(vectors.size)
        except Exception as exc:
            raise StorageError(
                f"qdrant collection {collection!r} has no vector size: {vectors!r}: {exc}"
            ) from exc

    async def export(self, collections: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
        """Scroll the requested collections into a full-fidelity point dump.

        FAILS LOUDLY (raises :class:`StorageError`) if the server is
        unreachable or a scroll fails — a preservation that cannot read the
        vector store MUST NOT silently emit an empty memory set that looks
        complete. Only requested collections that exist are returned.
        Returns ``{collection: [{id, vector, text, payload, affect}]}``.
        """
        assert self._client is not None
        try:
            existing = await self._client.get_collections()
            existing_names = {c.name for c in existing.collections}
        except Exception as exc:
            raise StorageError(
                f"qdrant export failed: could not list collections ({exc})"
            ) from exc
        out: dict[str, list[dict[str, Any]]] = {}
        for name in collections:
            if name not in existing_names:
                continue
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

    async def replace_collection(self, name: str, points: Sequence[dict[str, Any]]) -> int:
        """Replace one collection with the given validated points.

        FAILS LOUDLY on any server or validation error — a revive that
        cannot restore the vector store must raise.
        """
        from qdrant_client import models  # type: ignore[import-untyped]

        assert self._client is not None
        for p in points:
            vec = list(p.get("vector") or [])
            if len(vec) != self._latent_dim or not all(math.isfinite(v) for v in vec):
                raise StorageError(
                    f"qdrant replace_collection validation failed for {name!r}: "
                    f"point has dim {len(vec)} != {self._latent_dim} or non-finite vector"
                )
        try:
            existing = await self._client.get_collections()
            existing_names = {c.name for c in existing.collections}
        except Exception as exc:
            raise StorageError(
                f"qdrant replace_collection failed listing collections for {name!r}: {exc}"
            ) from exc
        if name in existing_names:
            try:
                await self._client.delete_collection(collection_name=name)
            except Exception as exc:
                raise StorageError(
                    f"qdrant replace_collection failed deleting {name!r}: {exc}"
                ) from exc
        try:
            await self.ensure_collection(name)
        except Exception as exc:
            raise StorageError(
                f"qdrant replace_collection failed recreating {name!r}: {exc}"
            ) from exc
        total = 0
        batch_size = 256
        for i in range(0, len(points), batch_size):
            batch = points[i : i + batch_size]
            structs = []
            for p in batch:
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
                        vector=list(p.get("vector") or []),
                        payload=merged_payload,
                    )
                )
            try:
                await self._client.upsert(collection_name=name, points=structs)
            except Exception as exc:
                raise StorageError(
                    f"qdrant replace_collection failed upserting into {name!r}: {exc}"
                ) from exc
            total += len(structs)
        return total

    async def write_stamp(self, key: str, stamp: dict) -> None:
        if self._client is None:
            raise StorageError("qdrant write_stamp before initialize()")
        from qdrant_client import models  # type: ignore[import-untyped]

        meta_name = MNEMOS_STAMP_COLLECTION
        try:
            existing = await self._client.get_collections()
            existing_names = {c.name for c in existing.collections}
        except Exception as exc:
            raise StorageError(
                f"qdrant write_stamp failed listing collections: {exc}"
            ) from exc
        if meta_name not in existing_names:
            try:
                await self._client.create_collection(
                    collection_name=meta_name,
                    vectors_config=models.VectorParams(
                        size=1,
                        distance=models.Distance.COSINE,
                    ),
                )
            except Exception as exc:
                # Another initializer may have won the race; tolerate it if the
                # collection now exists, otherwise fail closed.
                try:
                    existing = await self._client.get_collections()
                    existing_names = {c.name for c in existing.collections}
                except Exception as list_exc:
                    raise StorageError(
                        f"qdrant write_stamp failed creating {meta_name!r}: {exc}; "
                        f"re-list also failed: {list_exc}"
                    ) from exc
                if meta_name not in existing_names:
                    raise StorageError(
                        f"qdrant write_stamp failed creating {meta_name!r}: {exc}"
                    ) from exc
        pid = stamp_point_id(key)
        try:
            await self._client.upsert(
                collection_name=meta_name,
                points=[
                    models.PointStruct(
                        id=pid,
                        vector=[1.0],
                        payload={"key": key, "stamp": stamp},
                    )
                ],
            )
        except Exception as exc:
            raise StorageError(
                f"qdrant write_stamp failed upserting {key!r}: {exc}"
            ) from exc

    async def read_stamp(self, key: str) -> dict | None:
        if self._client is None:
            raise StorageError("qdrant read_stamp before initialize()")
        meta_name = MNEMOS_STAMP_COLLECTION
        pid = stamp_point_id(key)
        try:
            existing = await self._client.get_collections()
            existing_names = {c.name for c in existing.collections}
        except Exception as exc:
            raise StorageError(
                f"qdrant read_stamp failed listing collections: {exc}"
            ) from exc
        if meta_name not in existing_names:
            return None
        try:
            records = await self._client.retrieve(
                collection_name=meta_name,
                ids=[pid],
                with_payload=True,
            )
        except Exception as exc:
            raise StorageError(
                f"qdrant read_stamp failed for {key!r}: {exc}"
            ) from exc
        if not records:
            return None
        payload = getattr(records[0], "payload", None) or {}
        stamp = payload.get("stamp") if isinstance(payload, dict) else None
        _validate_stamp(stamp, "qdrant", key)
        return stamp
