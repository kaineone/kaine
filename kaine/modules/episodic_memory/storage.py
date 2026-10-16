# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Vector storage backends for the episodic memory module.

`MemoryStorage` is the protocol; `QdrantStorage` is the production
default (Tier 2); `InMemoryStorage` is the deterministic fallback for
tests; `SqliteVecStorage` is the in-process edge backend (Tier 0/1) —
an ``asg017/sqlite-vec`` vector index with near-zero idle footprint and
no server, selected by ``[episodic_memory].backend = "sqlite_vec"`` (openspec
runtime-backends). All three satisfy the SAME protocol and store the same
CLS collections, so selecting a backend never changes the episodic memory module's semantics.
"""
from __future__ import annotations

import asyncio
import heapq
import json
import logging
import math
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol, Sequence, TypeVar, runtime_checkable

from kaine.memory_kinds import EPISODIC_MEMORY_STAMP_COLLECTION, stamp_point_id
from kaine.storage import resolve

log = logging.getLogger(__name__)

_T = TypeVar("_T")

_REQUIRED_STAMP_KEYS = frozenset({"model_id", "dim", "pooling", "normalized"})


def _validate_stamp(value: Any, backend: str, key: str) -> None:
    """Fail loudly on malformed embedding-space stamps.

    A stamp that is present but malformed must never be read as "no
    stamp"; otherwise the episodic memory module would silently re-stamp a store and
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


_VEC_K_MAX = 4096  # sqlite-vec refuses a KNN query with k above 4096.


def _numeric_log_base(payload: Any) -> float | None:
    """Return the finite numeric log_base from a payload, or None."""
    if not isinstance(payload, dict):
        return None
    value = payload.get("log_base")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return float(value)


def _check_one_filter(born_sleep, has_log_base) -> None:
    """Raise unless exactly one count_filtered filter is given."""
    filters = [x is not None for x in (born_sleep, has_log_base)]
    if sum(filters) != 1:
        raise ValueError("count_filtered takes exactly one filter")


def record_size(latent_dim: int, text: str, payload: dict, affect: dict | None) -> int:
    """Bytes of one stored trace: its float32 embedding plus its serialized payload, text and affect."""
    body = {k: v for k, v in (payload or {}).items() if k != "size_bytes"}
    blob = json.dumps({"text": text, "payload": body, "affect": affect}, sort_keys=True, separators=(",", ":"), default=str)
    return 4 * int(latent_dim) + len(blob.encode("utf-8"))


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
    similarity: float | None = None
    strength: float | None = None


@runtime_checkable
class MemoryStorage(Protocol):
    @property
    def latent_dim(self) -> int:
        """Protocol member: latent dim."""

    async def initialize(self) -> None:
        """Protocol member: initialize."""

    async def shutdown(self) -> None:
        """Protocol member: shutdown."""

    async def ensure_collection(self, name: str) -> None:
        """Protocol member: ensure collection."""

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
        """Protocol member: upsert."""

    async def search(
        self,
        collection: str,
        *,
        query_vector: list[float],
        limit: int,
    ) -> list[RecalledMemory]:
        """Protocol member: search."""

    async def delete(self, collection: str, point_id: str) -> None:
        """Protocol member: delete."""

    async def count(self, collection: str, strict: bool = False) -> int:
        """Protocol member: count."""

    async def vector_dim(self, collection: str) -> int | None:
        """Protocol member: vector dim."""

    async def export(self, collections: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
        """Protocol member: export."""

    async def recent_points(self, collection: str, *, limit: int) -> list[dict[str, Any]]:
        """Protocol member: recent points.

        Returns at most ``limit`` points of ``collection``, the newest by
        ``payload["timestamp"]`` (a missing or non-numeric timestamp counts as
        0.0), newest first. Each point dict has keys ``id`` (str), ``text``
        (str), ``payload`` (dict), ``affect`` (dict or None) and NO vector. A
        collection that does not exist gives ``[]``. ``limit <= 0`` gives ``[]``.
        Used to load the associative-replay links and schema nodes, which
        must not pull every vector.
        """

    async def get_points(
        self,
        collection: str,
        ids: Sequence[str],
        *,
        with_vectors: bool = False,
    ) -> list[dict[str, Any]]:
        """Protocol member: get points by id.

        Returns the points of ``collection`` whose id matches one of ``ids``,
        in no particular order, each point at most once. Each point dict has
        keys ``id`` (str), ``text`` (str), ``payload`` (dict), ``affect`` (dict
        or None) and, ONLY when ``with_vectors`` is true, ``vector`` (list of
        float). An id matches a stored point when the two are equal strings or
        when both parse as the same UUID. Ids that match nothing are skipped
        silently. A collection that does not exist gives ``[]``. Empty ``ids``
        gives ``[]`` without touching the backend. A backend failure raises
        ``StorageError``.
        """

    async def replace_collection(self, name: str, points: Sequence[dict[str, Any]]) -> int:
        """Protocol member: replace collection."""

    async def read_stamp(self, key: str) -> dict | None:
        """Protocol member: read stamp."""

    async def write_stamp(self, key: str, stamp: dict) -> None:
        """Protocol member: write stamp."""

    async def read_meta(self, key: str) -> dict | None:
        """Protocol member: read meta."""

    async def write_meta(self, key: str, value: dict) -> None:
        """Protocol member: write meta."""

    async def wake_points(self, collections: Sequence[str], born_sleep: int) -> list[dict[str, Any]]:
        """Protocol member: wake points."""

    async def count_filtered(
        self,
        collection: str,
        *,
        born_sleep: int | None = None,
        has_log_base: bool | None = None,
    ) -> int:
        """Protocol member: count filtered."""

    async def total_size(self, collections: Sequence[str]) -> int:
        """Protocol member: total persisted bytes."""

    async def scan_store(self, collections: Sequence[str]) -> dict[str, Any]:
        """Protocol member: scan persisted store.

        Returns ``bytes`` (total persisted record size), ``log_base_counts``
        (map from numeric log_base to count), and ``unstrengthed`` (points
        without a numeric log_base).
        """

    async def weakest(self, collections: Sequence[str], *, limit: int) -> list[dict[str, Any]]:
        """Protocol member: weakest points."""

    async def delete_points(self, collection: str, point_ids: Sequence[str]) -> None:
        """Protocol member: delete many points."""

    async def set_log_base(self, collection: str, updates: Sequence[tuple[str, float]]) -> None:
        """Protocol member: set log base."""

    async def backfill_strength(self, collections: Sequence[str], *, log_base: float) -> int:
        """Protocol member: backfill strength."""


def _cosine(a: list[float], b: list[float]) -> float:
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return sum(x * y for x, y in zip(a, b)) / (na * nb)


def _payload_timestamp(payload: Any) -> float:
    """Return the payload's timestamp as a float.

    Returns 0.0 when missing, unparseable, NaN or infinite so every backend
    ranks such a point as the oldest.
    """
    if not isinstance(payload, dict):
        return 0.0
    try:
        ts = float(payload.get("timestamp", 0.0))
    except (TypeError, ValueError):
        return 0.0
    return ts if math.isfinite(ts) else 0.0


def _id_forms(point_id: Any) -> set[str]:
    s = str(point_id)
    forms: set[str] = {s}
    try:
        u = uuid.UUID(s)
        forms.add(u.hex)
        forms.add(str(u))
    except ValueError:
        pass
    return forms

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
        self._meta: dict[str, dict] = {}

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
                    similarity=score,
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
        :meth:`upsert` stores. Used by the episodic memory module's preservation so the persisted
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

    async def recent_points(self, collection: str, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        points = self._collections.get(collection, [])
        newest = heapq.nlargest(limit, points, key=lambda p: _payload_timestamp(p["payload"]))
        return [
            {
                "id": str(p["id"]),
                "text": p["text"],
                "payload": dict(p["payload"]),
                "affect": dict(p["affect"]) if p["affect"] else None,
            }
            for p in newest
        ]

    async def get_points(
        self,
        collection: str,
        ids: Sequence[str],
        *,
        with_vectors: bool = False,
    ) -> list[dict[str, Any]]:
        if not ids:
            return []
        points = self._collections.get(collection, [])
        forms: set[str] = set()
        for pid in ids:
            forms.update(_id_forms(pid))
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        for p in points:
            key = str(p["id"])
            if key in forms and key not in seen:
                seen.add(key)
                point: dict[str, Any] = {
                    "id": key,
                    "text": p["text"],
                    "payload": dict(p["payload"]),
                    "affect": dict(p["affect"]) if p["affect"] else None,
                }
                if with_vectors:
                    point["vector"] = list(p["vector"])
                out.append(point)
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

    async def read_meta(self, key: str) -> dict | None:
        if key not in self._meta:
            return None
        value = self._meta[key]
        if not isinstance(value, dict):
            raise StorageError(
                f"in-memory meta for {key!r} is malformed: not a dict ({value!r})"
            )
        return dict(value)

    async def write_meta(self, key: str, value: dict) -> None:
        self._meta[key] = dict(value)

    async def wake_points(self, collections: Sequence[str], born_sleep: int) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for name in collections:
            for p in self._collections.get(name, []):
                bs = p["payload"].get("born_sleep")
                if isinstance(bs, int) and not isinstance(bs, bool) and bs == born_sleep:
                    out.append(
                        {
                            "id": str(p["id"]),
                            "collection": name,
                            "text": p["text"],
                            "payload": dict(p["payload"]),
                            "affect": dict(p["affect"]) if p["affect"] else None,
                        }
                    )
        return out

    async def count_filtered(
        self,
        collection: str,
        *,
        born_sleep: int | None = None,
        has_log_base: bool | None = None,
    ) -> int:
        _check_one_filter(born_sleep, has_log_base)
        points = self._collections.get(collection, [])
        if born_sleep is not None:
            return sum(
                1
                for p in points
                if isinstance(p["payload"].get("born_sleep"), int)
                and not isinstance(p["payload"].get("born_sleep"), bool)
                and p["payload"]["born_sleep"] == born_sleep
            )
        has = has_log_base is True
        return sum(1 for p in points if ("log_base" in p["payload"]) == has)

    async def scan_store(self, collections: Sequence[str]) -> dict[str, Any]:
        total = 0
        log_base_counts: dict[float, int] = {}
        unstrengthed = 0
        for name in collections:
            for p in self._collections.get(name, []):
                sb = p["payload"].get("size_bytes")
                if isinstance(sb, int) and not isinstance(sb, bool):
                    total += int(sb)
                else:
                    total += record_size(
                        self._latent_dim, p["text"], p["payload"], p["affect"]
                    )
                lb = _numeric_log_base(p["payload"])
                if lb is None:
                    unstrengthed += 1
                else:
                    log_base_counts[lb] = log_base_counts.get(lb, 0) + 1
        return {"bytes": total, "log_base_counts": log_base_counts, "unstrengthed": unstrengthed}

    async def total_size(self, collections: Sequence[str]) -> int:
        return (await self.scan_store(collections))["bytes"]

    async def weakest(self, collections: Sequence[str], *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0 or not collections:
            return []

        def _entity_time(payload: Any) -> float:
            v = payload.get("entity_time", 0.0)
            try:
                v = float(v)
                return v if math.isfinite(v) else 0.0
            except (TypeError, ValueError):
                return 0.0

        def _key(p: dict[str, Any]) -> tuple[float, float, str]:
            payload = p["payload"]
            return (
                float(payload.get("log_base", 0.0)),
                _entity_time(payload),
                str(p["id"]),
            )

        items: list[tuple[tuple[float, float, str], str, dict[str, Any]]] = []
        for name in collections:
            for p in self._collections.get(name, []):
                if _numeric_log_base(p["payload"]) is None:
                    continue
                items.append((_key(p), name, p))
        items.sort(key=lambda t: t[0])
        if not items:
            return []
        n = min(limit, len(items))
        result = items[:n]
        last_lb = result[-1][0][0]
        idx = n
        while idx < len(items) and items[idx][0][0] == last_lb:
            result.append(items[idx])
            idx += 1
        result.sort(key=lambda t: t[0])
        out: list[dict[str, Any]] = []
        for _, name, p in result:
            payload = p["payload"]
            sb = payload.get("size_bytes")
            size = (
                int(sb)
                if isinstance(sb, int) and not isinstance(sb, bool)
                else record_size(
                    self._latent_dim, p["text"], payload, p["affect"]
                )
            )
            out.append(
                {
                    "id": str(p["id"]),
                    "collection": name,
                    "log_base": float(payload.get("log_base", 0.0)),
                    "entity_time": _entity_time(payload),
                    "size_bytes": size,
                }
            )
        return out

    async def delete_points(self, collection: str, point_ids: Sequence[str]) -> None:
        if collection not in self._collections:
            return
        ids = set(point_ids)
        self._collections[collection] = [
            p for p in self._collections[collection] if p["id"] not in ids
        ]

    async def set_log_base(self, collection: str, updates: Sequence[tuple[str, float]]) -> None:
        points = self._collections.get(collection, [])
        for point_id, value in updates:
            for p in points:
                if p["id"] == point_id:
                    p["payload"]["log_base"] = float(value)
                    break

    async def backfill_strength(self, collections: Sequence[str], *, log_base: float) -> int:
        changed = 0
        for name in collections:
            for p in self._collections.get(name, []):
                if "log_base" not in p["payload"]:
                    # Keep an existing integer size if it was already counted.
                    existing_size = p["payload"].get("size_bytes")
                    if not isinstance(existing_size, int) or isinstance(existing_size, bool):
                        p["payload"]["size_bytes"] = record_size(
                            self._latent_dim, p["text"], p["payload"], p["affect"]
                        )
                    p["payload"]["log_base"] = float(log_base)
                    p["payload"]["born_sleep"] = -1
                    changed += 1
        return changed


class SqliteVecStorage:
    """In-process vector store on ``sqlite-vec`` (edge backend, Tier 0/1).

    A single SQLite file holds a ``vec0`` virtual table for the vectors plus a
    companion metadata table for text/payload/affect; cosine KNN runs inside the
    process with no Qdrant server and near-zero idle footprint — the single-user
    edge counterpart of :class:`QdrantStorage`. It stores the same CLS
    collections and exposes the same ``search`` (``query_points``-equivalent)
    API, so the episodic memory module's semantics are unchanged (openspec runtime-backends).

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
        db_path: str = "state/episodic_memory/episodic_memory.db",
        distance: str = "cosine",
    ) -> None:
        if latent_dim <= 0:
            raise ValueError("latent_dim must be positive")
        self._latent_dim = int(latent_dim)
        self._db_path = str(resolve(db_path))
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
                "CREATE TABLE IF NOT EXISTS kaine_meta ("
                "key TEXT PRIMARY KEY, value TEXT)"
            )
            db.commit()

            cur = db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='vec_memories'"
            )
            row = cur.fetchone()
            rebuild = (
                row is not None
                and row[0] is not None
                and "partition key" not in str(row[0]).lower()
            )
            if rebuild:
                try:
                    db.execute("BEGIN")
                    db.execute(
                        "CREATE TEMP TABLE vec_rebuild AS "
                        "SELECT v.rowid AS rid, m.collection AS collection, v.embedding AS embedding "
                        "FROM vec_memories v JOIN memories m ON m.rowid = v.rowid"
                    )
                    db.execute("DROP TABLE vec_memories")
                    db.execute(
                        "CREATE VIRTUAL TABLE vec_memories USING vec0("
                        f"collection text partition key, embedding float[{self._latent_dim}] distance_metric=cosine)"
                    )
                    db.execute(
                        "INSERT INTO vec_memories(rowid, collection, embedding) "
                        "SELECT rid, collection, embedding FROM temp.vec_rebuild"
                    )
                    db.execute("DROP TABLE temp.vec_rebuild")
                    db.commit()
                    n = int(db.execute("SELECT COUNT(*) FROM vec_memories").fetchone()[0])
                    log.info("sqlite-vec: rebuilt vec_memories with a collection partition key (%d rows)", n)
                except Exception:
                    db.rollback()
                    raise
            else:
                db.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS vec_memories USING vec0("
                    f"collection text partition key, embedding float[{self._latent_dim}] distance_metric=cosine)"
                )

            db.execute(
                "CREATE INDEX IF NOT EXISTS memories_born "
                "ON memories(collection, json_extract(payload, '$.born_sleep'))"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS memories_weakest "
                "ON memories(json_extract(payload, '$.log_base'), json_extract(payload, '$.entity_time'))"
            )
            db.execute("DROP INDEX IF EXISTS memories_log_base")
            db.commit()
            return db

        executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="episodic-memory-sqlite"
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
            "INSERT INTO vec_memories (rowid, collection, embedding) VALUES (?, ?, ?)",
            (rowid, collection, blob),
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
                out: list[RecalledMemory] = []
                seen: set[str] = set()
                first_page = True
                last_distance: float | None = None
                op = ">="
                while len(out) < k:
                    # Start with k rows; later pages expand to amortize paging round-trips.
                    page_k = min(_VEC_K_MAX, k) if first_page else _VEC_K_MAX
                    if last_distance is None:
                        cur = db.execute(
                            "SELECT m.point_id, v.distance, m.text, m.payload, m.affect "
                            "FROM vec_memories v JOIN memories m ON m.rowid = v.rowid "
                            "WHERE v.embedding MATCH ? AND v.collection = ? AND k = ? "
                            "ORDER BY v.distance",
                            (blob, collection, page_k),
                        )
                    else:
                        cur = db.execute(
                            "SELECT m.point_id, v.distance, m.text, m.payload, m.affect "
                            "FROM vec_memories v JOIN memories m ON m.rowid = v.rowid "
                            "WHERE v.embedding MATCH ? AND v.collection = ? AND k = ? "
                            f"AND v.distance {op} ? "
                            "ORDER BY v.distance",
                            (blob, collection, page_k, last_distance),
                        )
                    rows = list(cur.fetchall())
                    if not rows:
                        break
                    d_last = float(rows[-1][1])
                    # Record fullness before we mutate rows for tie handling.
                    full = len(rows) == page_k
                    # Inclusive boundary paging: drop point_ids already returned.
                    # A full page that yields no new row needs one exact fallback scan
                    # at the boundary distance, then we can advance past that distance.
                    new_rows = [r for r in rows if str(r[0]) not in seen]
                    if full and not new_rows:
                        tie_cur = db.execute(
                            "SELECT m.point_id, vec_distance_cosine(v.embedding, ?) AS d, "
                            "m.text, m.payload, m.affect "
                            "FROM vec_memories v JOIN memories m ON m.rowid = v.rowid "
                            "WHERE v.collection = ? AND vec_distance_cosine(v.embedding, ?) = ?",
                            (blob, collection, blob, d_last),
                        )
                        tie_rows = list(tie_cur.fetchall())
                        if not tie_rows:
                            tie_cur = db.execute(
                                "SELECT m.point_id, vec_distance_cosine(v.embedding, ?) AS d, "
                                "m.text, m.payload, m.affect "
                                "FROM vec_memories v JOIN memories m ON m.rowid = v.rowid "
                                "WHERE v.collection = ? AND ABS(vec_distance_cosine(v.embedding, ?) - ?) < 1e-7",
                                (blob, collection, blob, d_last),
                            )
                            tie_rows = list(tie_cur.fetchall())
                        if tie_rows:
                            new_rows = [r for r in tie_rows if str(r[0]) not in seen]
                        else:
                            # Floating-point mismatch must not drop the boundary rows.
                            new_rows = rows
                        op = ">"
                    elif full:
                        op = ">="
                    for row in new_rows:
                        point_id, distance, text, payload_json, affect_json = row
                        if str(point_id) in seen:
                            continue
                        seen.add(str(point_id))
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
                                similarity=score,
                            )
                        )
                        if len(out) >= k:
                            break
                    if not full:
                        break
                    last_distance = d_last
                    first_page = False
                return out
            except StorageError:
                raise
            except Exception as exc:
                raise StorageError(
                    f"sqlite-vec search failed for collection {collection!r}: {exc}"
                ) from exc

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

    async def recent_points(self, collection: str, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            return []

        def _recent(db: Any) -> list[dict[str, Any]]:
            if db is None:
                raise StorageError("sqlite-vec recent_points before initialize()")
            out: list[dict[str, Any]] = []
            try:
                # SQLite reads a JSON NaN as NULL and Infinity as an infinite REAL;
                # both rank as 0.0, as `_payload_timestamp` ranks them on the other backends.
                cur = db.execute(
                    "SELECT point_id, text, payload, affect FROM ("
                    "SELECT point_id, text, payload, affect, "
                    "CAST(json_extract(payload, '$.timestamp') AS REAL) AS ts "
                    "FROM memories WHERE collection = ?"
                    ") ORDER BY CASE WHEN abs(ts) <= 1.7976931348623157e308 "
                    "THEN ts ELSE 0.0 END DESC "
                    "LIMIT ?",
                    (collection, int(limit)),
                )
                for pid, text, payload_json, affect_json in cur.fetchall():
                    out.append(
                        {
                            "id": str(pid),
                            "text": str(text or ""),
                            "payload": json.loads(payload_json) if payload_json else {},
                            "affect": json.loads(affect_json) if affect_json else None,
                        }
                    )
            except Exception as exc:
                raise StorageError(f"sqlite-vec recent_points failed: {exc}") from exc
            return out

        return await self._run(_recent)

    async def get_points(
        self,
        collection: str,
        ids: Sequence[str],
        *,
        with_vectors: bool = False,
    ) -> list[dict[str, Any]]:
        if not ids:
            return []

        import struct

        forms: set[str] = set()
        for pid in ids:
            forms.update(_id_forms(pid))

        def _get(db: Any) -> list[dict[str, Any]]:
            if db is None:
                raise StorageError("sqlite-vec get_points before initialize()")
            out: list[dict[str, Any]] = []
            seen: set[str] = set()
            try:
                all_forms = list(forms)
                for start in range(0, len(all_forms), 500):
                    chunk = all_forms[start : start + 500]
                    placeholders = ",".join("?" * len(chunk))
                    if with_vectors:
                        sql = (
                            "SELECT m.point_id, m.text, m.payload, m.affect, v.embedding "
                            "FROM memories m JOIN vec_memories v ON v.rowid = m.rowid "
                            f"WHERE m.collection = ? AND m.point_id IN ({placeholders})"
                        )
                    else:
                        sql = (
                            "SELECT m.point_id, m.text, m.payload, m.affect "
                            "FROM memories m "
                            f"WHERE m.collection = ? AND m.point_id IN ({placeholders})"
                        )
                    cur = db.execute(sql, [collection] + chunk)
                    for row in cur.fetchall():
                        if with_vectors:
                            pid, text, payload_json, affect_json, emb = row
                            vector = list(struct.unpack(f"{self._latent_dim}f", emb))
                        else:
                            pid, text, payload_json, affect_json = row
                            vector = None
                        key = str(pid)
                        if key in seen:
                            continue
                        seen.add(key)
                        point: dict[str, Any] = {
                            "id": key,
                            "text": str(text or ""),
                            "payload": json.loads(payload_json) if payload_json else {},
                            "affect": json.loads(affect_json) if affect_json else None,
                        }
                        if with_vectors and vector is not None:
                            point["vector"] = vector
                        out.append(point)
            except Exception as exc:
                raise StorageError(f"sqlite-vec get_points failed: {exc}") from exc
            return out

        return await self._run(_get)

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

    async def read_meta(self, key: str) -> dict | None:

        def _read(db: Any) -> dict | None:
            if db is None:
                raise StorageError("sqlite-vec read_meta before initialize()")
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
                        f"sqlite-vec meta for {key!r} is malformed: {exc}"
                    ) from exc
                if not isinstance(value, dict):
                    raise StorageError(
                        f"sqlite-vec meta for {key!r} is malformed: not a dict ({value!r})"
                    )
                return value
            except StorageError:
                raise
            except Exception as exc:
                raise StorageError(
                    f"sqlite-vec read_meta failed for {key!r}: {exc}"
                ) from exc

        return await self._run(_read)

    async def write_meta(self, key: str, value: dict) -> None:

        def _write(db: Any) -> None:
            if db is None:
                raise StorageError("sqlite-vec write_meta before initialize()")
            try:
                db.execute(
                    "INSERT INTO kaine_meta (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                    (key, json.dumps(value)),
                )
                db.commit()
            except Exception as exc:
                raise StorageError(
                    f"sqlite-vec write_meta failed for {key!r}: {exc}"
                ) from exc

        await self._run(_write)

    async def wake_points(self, collections: Sequence[str], born_sleep: int) -> list[dict[str, Any]]:
        if not collections:
            return []

        def _query(db: Any) -> list[dict[str, Any]]:
            if db is None:
                raise StorageError("sqlite-vec wake_points before initialize()")
            try:
                placeholders = ",".join("?" for _ in collections)
                cur = db.execute(
                    "SELECT collection, point_id, text, payload, affect FROM memories "
                    f"WHERE collection IN ({placeholders}) "
                    "AND json_extract(payload, '$.born_sleep') = ?",
                    (*collections, int(born_sleep)),
                )
                out: list[dict[str, Any]] = []
                for coll, pid, text, payload_json, affect_json in cur.fetchall():
                    out.append(
                        {
                            "id": str(pid),
                            "collection": str(coll),
                            "text": str(text or ""),
                            "payload": json.loads(payload_json) if payload_json else {},
                            "affect": json.loads(affect_json) if affect_json else None,
                        }
                    )
                return out
            except Exception as exc:
                raise StorageError(f"sqlite-vec wake_points failed: {exc}") from exc

        return await self._run(_query)

    async def count_filtered(
        self,
        collection: str,
        *,
        born_sleep: int | None = None,
        has_log_base: bool | None = None,
    ) -> int:
        _check_one_filter(born_sleep, has_log_base)

        def _count(db: Any) -> int:
            if db is None:
                raise StorageError("sqlite-vec count_filtered before initialize()")
            try:
                if born_sleep is not None:
                    cond = "json_extract(payload, '$.born_sleep') = ?"
                    args = (collection, int(born_sleep))
                elif has_log_base is True:
                    cond = "json_type(payload, '$.log_base') IS NOT NULL"
                    args = (collection,)
                else:
                    cond = "json_type(payload, '$.log_base') IS NULL"
                    args = (collection,)
                cur = db.execute(
                    f"SELECT COUNT(*) FROM memories WHERE collection = ? AND {cond}",
                    args,
                )
                row = cur.fetchone()
                return int(row[0]) if row else 0
            except Exception as exc:
                raise StorageError(
                    f"sqlite-vec count_filtered failed for {collection!r}: {exc}"
                ) from exc

        return await self._run(_count)

    async def set_log_base(self, collection: str, updates: Sequence[tuple[str, float]]) -> None:

        def _update(db: Any) -> None:
            if db is None:
                raise StorageError("sqlite-vec set_log_base before initialize()")
            try:
                for point_id, value in updates:
                    cur = db.execute(
                        "SELECT rowid, payload FROM memories WHERE collection = ? AND point_id = ?",
                        (collection, point_id),
                    )
                    row = cur.fetchone()
                    if row is None:
                        continue
                    rowid, payload_json = int(row[0]), row[1]
                    payload = json.loads(payload_json) if payload_json else {}
                    payload["log_base"] = float(value)
                    db.execute(
                        "UPDATE memories SET payload = ? WHERE rowid = ?",
                        (json.dumps(payload), rowid),
                    )
                db.commit()
            except Exception as exc:
                raise StorageError(
                    f"sqlite-vec set_log_base failed for {collection!r}: {exc}"
                ) from exc

        await self._run(_update)

    async def backfill_strength(self, collections: Sequence[str], *, log_base: float) -> int:
        if not collections:
            return 0

        def _backfill(db: Any) -> int:
            if db is None:
                raise StorageError("sqlite-vec backfill_strength before initialize()")
            try:
                placeholders = ",".join("?" for _ in collections)
                cur = db.execute(
                    "SELECT rowid, text, payload, affect FROM memories "
                    f"WHERE collection IN ({placeholders}) "
                    "AND json_type(COALESCE(payload, '{}'), '$.log_base') IS NULL",
                    tuple(collections),
                )
                rows = cur.fetchall()
                if not rows:
                    db.commit()
                    return 0
                for rowid, text, payload_json, affect_json in rows:
                    payload = json.loads(payload_json) if payload_json else {}
                    affect = json.loads(affect_json) if affect_json else None
                    # Keep an existing integer size if it was already counted.
                    existing_size = payload.get("size_bytes")
                    if not isinstance(existing_size, int) or isinstance(existing_size, bool):
                        payload["size_bytes"] = record_size(
                            self._latent_dim, str(text or ""), payload, affect
                        )
                    payload["log_base"] = float(log_base)
                    payload["born_sleep"] = -1
                    db.execute(
                        "UPDATE memories SET payload = ? WHERE rowid = ?",
                        (json.dumps(payload), int(rowid)),
                    )
                db.commit()
                return len(rows)
            except Exception as exc:
                db.rollback()
                raise StorageError(f"sqlite-vec backfill_strength failed: {exc}") from exc

        return await self._run(_backfill)

    def _total_size_sync(self, db: Any, collections: Sequence[str]) -> int:
        if db is None:
            raise StorageError("sqlite-vec total_size before initialize()")
        if not collections:
            return 0
        try:
            placeholders = ",".join("?" for _ in collections)
            cur = db.execute(
                f"SELECT SUM(json_extract(payload, '$.size_bytes')) FROM memories "
                f"WHERE collection IN ({placeholders}) "
                "AND json_type(payload, '$.size_bytes') = 'integer'",
                tuple(collections),
            )
            row = cur.fetchone()
            total = int(row[0]) if row and row[0] is not None else 0
            cur = db.execute(
                f"SELECT text, payload, affect FROM memories "
                f"WHERE collection IN ({placeholders}) "
                "AND (json_type(payload, '$.size_bytes') IS NULL "
                "OR json_type(payload, '$.size_bytes') != 'integer')",
                tuple(collections),
            )
            for text, payload_json, affect_json in cur.fetchall():
                payload = json.loads(payload_json) if payload_json else {}
                affect = json.loads(affect_json) if affect_json else None
                total += record_size(
                    self._latent_dim, str(text or ""), payload, affect
                )
            return total
        except Exception as exc:
            raise StorageError(f"sqlite-vec total_size failed: {exc}") from exc

    async def total_size(self, collections: Sequence[str]) -> int:
        return await self._run(lambda db: self._total_size_sync(db, collections))

    async def scan_store(self, collections: Sequence[str]) -> dict[str, Any]:
        if not collections:
            return {"bytes": 0, "log_base_counts": {}, "unstrengthed": 0}

        def _scan(db: Any) -> dict[str, Any]:
            if db is None:
                raise StorageError("sqlite-vec scan_store before initialize()")
            total = self._total_size_sync(db, collections)
            placeholders = ",".join("?" for _ in collections)
            cur = db.execute(
                f"SELECT json_extract(payload, '$.log_base') AS lb, COUNT(*) "
                f"FROM memories WHERE collection IN ({placeholders}) "
                "AND json_type(payload, '$.log_base') IN ('real', 'integer') "
                "GROUP BY lb",
                tuple(collections),
            )
            log_base_counts: dict[float, int] = {}
            unstrengthed = 0
            for lb, cnt in cur.fetchall():
                val = _numeric_log_base({"log_base": lb})
                if val is None:
                    unstrengthed += int(cnt)
                else:
                    log_base_counts[val] = log_base_counts.get(val, 0) + int(cnt)
            cur2 = db.execute(
                f"SELECT COUNT(*) FROM memories WHERE collection IN ({placeholders}) "
                "AND (json_type(payload, '$.log_base') IS NULL "
                "OR json_type(payload, '$.log_base') NOT IN ('real', 'integer'))",
                tuple(collections),
            )
            row = cur2.fetchone()
            unstrengthed += int(row[0]) if row else 0
            return {"bytes": total, "log_base_counts": log_base_counts, "unstrengthed": unstrengthed}

        return await self._run(_scan)

    async def weakest(self, collections: Sequence[str], *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0 or not collections:
            return []

        def _entity_time(payload: Any) -> float:
            v = payload.get("entity_time", 0.0)
            try:
                v = float(v)
                return v if math.isfinite(v) else 0.0
            except (TypeError, ValueError):
                return 0.0

        def _size(text: str, payload: dict[str, Any], affect: Any) -> int:
            sb = payload.get("size_bytes")
            if isinstance(sb, int) and not isinstance(sb, bool):
                return int(sb)
            affect_dict = json.loads(affect) if affect else None
            return record_size(
                self._latent_dim, str(text or ""), payload, affect_dict
            )

        placeholders = ",".join("?" for _ in collections)

        def _weakest(db: Any) -> list[dict[str, Any]]:
            if db is None:
                raise StorageError("sqlite-vec weakest before initialize()")
            try:
                cur = db.execute(
                    f"SELECT collection, point_id, text, payload, affect FROM memories "
                    f"WHERE collection IN ({placeholders}) "
                    "AND json_type(payload, '$.log_base') IN ('real', 'integer') "
                    "ORDER BY json_extract(payload, '$.log_base') ASC, "
                    "json_extract(payload, '$.entity_time') ASC, point_id ASC "
                    "LIMIT ?",
                    (*collections, int(limit)),
                )
                rows = list(cur.fetchall())
                if not rows:
                    return []
                seen: set[tuple[str, str]] = set()
                out: list[tuple[tuple[float, float, str], dict[str, Any]]] = []
                for row in rows:
                    coll, pid, text, payload_json, affect_json = row
                    seen.add((str(coll), str(pid)))
                    payload = json.loads(payload_json) if payload_json else {}
                    lb = float(payload.get("log_base", 0.0))
                    et = _entity_time(payload)
                    out.append(
                        (
                            (lb, et, str(pid)),
                            {
                                "id": str(pid),
                                "collection": str(coll),
                                "log_base": lb,
                                "entity_time": et,
                                "size_bytes": _size(str(text or ""), payload, affect_json),
                            },
                        )
                    )
                if len(rows) == limit:
                    last_payload = json.loads(rows[-1][3]) if rows[-1][3] else {}
                    last_lb = float(last_payload.get("log_base", 0.0))
                    cur2 = db.execute(
                        f"SELECT collection, point_id, text, payload, affect FROM memories "
                        f"WHERE collection IN ({placeholders}) "
                        "AND json_type(payload, '$.log_base') IN ('real', 'integer') "
                        "AND json_extract(payload, '$.log_base') = ?",
                        (*collections, last_lb),
                    )
                    for row in cur2.fetchall():
                        coll, pid, text, payload_json, affect_json = row
                        key = (str(coll), str(pid))
                        if key in seen:
                            continue
                        seen.add(key)
                        payload = json.loads(payload_json) if payload_json else {}
                        lb = float(payload.get("log_base", 0.0))
                        et = _entity_time(payload)
                        out.append(
                            (
                                (lb, et, str(pid)),
                                {
                                    "id": str(pid),
                                    "collection": str(coll),
                                    "log_base": lb,
                                    "entity_time": et,
                                    "size_bytes": _size(str(text or ""), payload, affect_json),
                                },
                            )
                        )
                out.sort(key=lambda t: t[0])
                return [d for _, d in out]
            except Exception as exc:
                raise StorageError(f"sqlite-vec weakest failed: {exc}") from exc

        return await self._run(_weakest)

    async def delete_points(self, collection: str, point_ids: Sequence[str]) -> None:
        if not point_ids:
            return

        def _delete(db: Any) -> None:
            if db is None:
                raise StorageError("sqlite-vec delete_points before initialize()")
            try:
                db.execute("BEGIN")
                ids = list(point_ids)
                chunk = 500
                for i in range(0, len(ids), chunk):
                    batch = ids[i : i + chunk]
                    ph = ",".join("?" for _ in batch)
                    cur = db.execute(
                        f"SELECT rowid FROM memories WHERE collection = ? AND point_id IN ({ph})",
                        (collection, *batch),
                    )
                    rowids = tuple(int(r[0]) for r in cur.fetchall())
                    if not rowids:
                        continue
                    db.execute(
                        f"DELETE FROM vec_memories WHERE rowid IN ({','.join('?' for _ in rowids)})",
                        rowids,
                    )
                    db.execute(
                        f"DELETE FROM memories WHERE rowid IN ({','.join('?' for _ in rowids)})",
                        rowids,
                    )
                db.commit()
            except Exception as exc:
                db.rollback()
                raise StorageError(
                    f"sqlite-vec delete_points failed for {collection!r}: {exc}"
                ) from exc

        await self._run(_delete)


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

    async def _collection_names(self) -> set[str]:
        """Names that reach a collection: the collections and their aliases.

        A store renamed by ``kaine.lifecycle.rename_state`` keeps its collections
        under their old names and reaches them through aliases named like the new
        ones, so an alias counts as an existing collection and is never created
        again as a second, empty collection.
        """
        assert self._client is not None
        existing = await self._client.get_collections()
        names = {c.name for c in existing.collections}
        aliases = await self._client.get_aliases()
        names.update(a.alias_name for a in aliases.aliases)
        return names

    async def ensure_collection(self, name: str) -> None:
        from qdrant_client import models  # type: ignore[import-untyped]

        assert self._client is not None
        existing_names = await self._collection_names()
        if name not in existing_names:
            await self._client.create_collection(
                collection_name=name,
                vectors_config=models.VectorParams(
                    size=self._latent_dim,
                    distance=models.Distance.COSINE if self._distance == "Cosine" else models.Distance.DOT,
                ),
            )
        for field_name, field_schema in (
            ("log_base", models.PayloadSchemaType.FLOAT),
            ("born_sleep", models.PayloadSchemaType.INTEGER),
        ):
            try:
                await self._client.create_payload_index(
                    collection_name=name,
                    field_name=field_name,
                    field_schema=field_schema,
                )
            except Exception:
                log.warning(
                    "qdrant create_payload_index failed for %s.%s",
                    name,
                    field_name,
                    exc_info=True,
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
            score = float(h.score)
            out.append(
                RecalledMemory(
                    point_id=str(h.id),
                    score=score,
                    text=text,
                    payload=payload,
                    affect=dict(affect) if affect else None,
                    similarity=score,
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
            existing_names = await self._collection_names()
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
                "Episodic memory never creates named vectors"
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
            existing_names = await self._collection_names()
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

    async def recent_points(self, collection: str, *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        assert self._client is not None
        try:
            existing_names = await self._collection_names()
        except Exception as exc:
            raise StorageError(
                f"qdrant recent_points failed: could not list collections ({exc})"
            ) from exc
        if collection not in existing_names:
            return []

        heap: list[tuple[float, int, dict[str, Any]]] = []
        seq = 0
        offset = None
        try:
            while True:
                batch, offset = await self._client.scroll(
                    collection_name=collection,
                    limit=256,
                    offset=offset,
                    with_payload=True,
                    with_vectors=False,
                )
                for p in batch:
                    payload = dict(getattr(p, "payload", None) or {})
                    text = str(payload.pop("text", ""))
                    affect = payload.pop("affect", None)
                    ts = _payload_timestamp(payload)
                    point = {
                        "id": str(getattr(p, "id", "")),
                        "text": text,
                        "payload": payload,
                        "affect": dict(affect) if affect else None,
                    }
                    if len(heap) < limit:
                        heapq.heappush(heap, (ts, seq, point))
                    elif heap and ts > heap[0][0]:
                        heapq.heappushpop(heap, (ts, seq, point))
                    seq += 1
                if offset is None:
                    break
        except Exception as exc:
            raise StorageError(
                f"qdrant recent_points failed scrolling collection {collection!r}: {exc}"
            ) from exc
        return [point for _, _, point in sorted(heap, reverse=True)]

    async def get_points(
        self,
        collection: str,
        ids: Sequence[str],
        *,
        with_vectors: bool = False,
    ) -> list[dict[str, Any]]:
        if not ids:
            return []
        assert self._client is not None
        try:
            existing_names = await self._collection_names()
        except Exception as exc:
            raise StorageError(
                f"qdrant get_points failed: could not list collections ({exc})"
            ) from exc
        if collection not in existing_names:
            return []

        # A Qdrant server reports UUIDs hyphenated while the local mode keeps the
        # form it was given, so every form of each id is asked for.
        unique_ids = list(dict.fromkeys(f for i in ids for f in sorted(_id_forms(i))))
        out: list[dict[str, Any]] = []
        seen: set[str] = set()
        try:
            for start in range(0, len(unique_ids), 256):
                chunk = unique_ids[start : start + 256]
                points = await self._client.retrieve(
                    collection_name=collection,
                    ids=chunk,
                    with_payload=True,
                    with_vectors=with_vectors,
                )
                for p in points:
                    key = str(p.id)
                    if key in seen:
                        continue
                    seen.add(key)
                    payload = dict(p.payload or {})
                    text = str(payload.pop("text", ""))
                    affect = payload.pop("affect", None)
                    point: dict[str, Any] = {
                        "id": key,
                        "text": text,
                        "payload": payload,
                        "affect": dict(affect) if affect else None,
                    }
                    if with_vectors:
                        point["vector"] = list(p.vector)
                    out.append(point)
        except Exception as exc:
            raise StorageError(
                f"qdrant get_points failed retrieving collection {collection!r}: {exc}"
            ) from exc
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
            existing_names = await self._collection_names()
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

    async def _ensure_meta_collection(self, label: str) -> None:
        from qdrant_client import models  # type: ignore[import-untyped]

        assert self._client is not None
        meta_name = EPISODIC_MEMORY_STAMP_COLLECTION
        try:
            existing_names = await self._collection_names()
        except Exception as exc:
            raise StorageError(
                f"qdrant {label} failed listing collections: {exc}"
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
                    existing_names = await self._collection_names()
                except Exception as list_exc:
                    raise StorageError(
                        f"qdrant {label} failed creating {meta_name!r}: {exc}; "
                        f"re-list also failed: {list_exc}"
                    ) from exc
                if meta_name not in existing_names:
                    raise StorageError(
                        f"qdrant {label} failed creating {meta_name!r}: {exc}"
                    ) from exc

    async def write_stamp(self, key: str, stamp: dict) -> None:
        if self._client is None:
            raise StorageError("qdrant write_stamp before initialize()")
        from qdrant_client import models  # type: ignore[import-untyped]

        await self._ensure_meta_collection("write_stamp")
        pid = stamp_point_id(key)
        try:
            await self._client.upsert(
                collection_name=EPISODIC_MEMORY_STAMP_COLLECTION,
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

    async def write_meta(self, key: str, value: dict) -> None:
        if self._client is None:
            raise StorageError("qdrant write_meta before initialize()")
        from qdrant_client import models  # type: ignore[import-untyped]

        await self._ensure_meta_collection("write_meta")
        pid = stamp_point_id(key)
        try:
            await self._client.upsert(
                collection_name=EPISODIC_MEMORY_STAMP_COLLECTION,
                points=[
                    models.PointStruct(
                        id=pid,
                        vector=[1.0],
                        payload={"key": key, "meta": value},
                    )
                ],
            )
        except Exception as exc:
            raise StorageError(
                f"qdrant write_meta failed upserting {key!r}: {exc}"
            ) from exc

    async def read_meta(self, key: str) -> dict | None:
        if self._client is None:
            raise StorageError("qdrant read_meta before initialize()")
        meta_name = EPISODIC_MEMORY_STAMP_COLLECTION
        pid = stamp_point_id(key)
        try:
            existing_names = await self._collection_names()
        except Exception as exc:
            raise StorageError(
                f"qdrant read_meta failed listing collections: {exc}"
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
                f"qdrant read_meta failed for {key!r}: {exc}"
            ) from exc
        if not records:
            return None
        payload = getattr(records[0], "payload", None) or {}
        meta = payload.get("meta") if isinstance(payload, dict) else None
        if meta is not None and not isinstance(meta, dict):
            raise StorageError(
                f"qdrant meta for {key!r} is malformed: not a dict ({meta!r})"
            )
        return meta

    async def read_stamp(self, key: str) -> dict | None:
        if self._client is None:
            raise StorageError("qdrant read_stamp before initialize()")
        meta_name = EPISODIC_MEMORY_STAMP_COLLECTION
        pid = stamp_point_id(key)
        try:
            existing_names = await self._collection_names()
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

    async def wake_points(self, collections: Sequence[str], born_sleep: int) -> list[dict[str, Any]]:
        if not collections:
            return []
        if self._client is None:
            raise StorageError("qdrant wake_points before initialize()")
        from qdrant_client import models  # type: ignore[import-untyped]

        try:
            existing_names = await self._collection_names()
        except Exception as exc:
            raise StorageError(
                f"qdrant wake_points failed listing collections: {exc}"
            ) from exc
        out: list[dict[str, Any]] = []
        scroll_filter = models.Filter(
            must=[
                models.FieldCondition(
                    key="born_sleep",
                    match=models.MatchValue(value=int(born_sleep)),
                )
            ]
        )
        for name in collections:
            if name not in existing_names:
                continue
            offset = None
            try:
                while True:
                    batch, offset = await self._client.scroll(
                        collection_name=name,
                        limit=1024,
                        offset=offset,
                        with_payload=True,
                        with_vectors=False,
                        scroll_filter=scroll_filter,
                    )
                    for p in batch:
                        payload = dict(getattr(p, "payload", None) or {})
                        text = str(payload.pop("text", ""))
                        affect = payload.pop("affect", None)
                        out.append(
                            {
                                "id": str(p.id),
                                "collection": name,
                                "text": text,
                                "payload": payload,
                                "affect": dict(affect) if affect else None,
                            }
                        )
                    if offset is None:
                        break
            except Exception as exc:
                raise StorageError(
                    f"qdrant wake_points failed scrolling collection {name!r}: {exc}"
                ) from exc
        return out

    async def count_filtered(
        self,
        collection: str,
        *,
        born_sleep: int | None = None,
        has_log_base: bool | None = None,
    ) -> int:
        _check_one_filter(born_sleep, has_log_base)
        if self._client is None:
            raise StorageError("qdrant count_filtered before initialize()")
        from qdrant_client import models  # type: ignore[import-untyped]

        try:
            existing_names = await self._collection_names()
        except Exception as exc:
            raise StorageError(
                f"qdrant count_filtered failed listing collections: {exc}"
            ) from exc
        if collection not in existing_names:
            return 0
        if born_sleep is not None:
            count_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="born_sleep",
                        match=models.MatchValue(value=int(born_sleep)),
                    )
                ]
            )
        elif has_log_base is True:
            count_filter = models.Filter(
                must_not=[
                    models.IsEmptyCondition(
                        is_empty=models.PayloadField(key="log_base")
                    )
                ]
            )
        else:
            count_filter = models.Filter(
                must=[
                    models.IsEmptyCondition(
                        is_empty=models.PayloadField(key="log_base")
                    )
                ]
            )
        try:
            info = await self._client.count(
                collection_name=collection,
                count_filter=count_filter,
                exact=True,
            )
            return int(info.count)
        except Exception as exc:
            raise StorageError(
                f"qdrant count_filtered failed for {collection!r}: {exc}"
            ) from exc

    async def set_log_base(self, collection: str, updates: Sequence[tuple[str, float]]) -> None:
        if not updates:
            return
        if self._client is None:
            raise StorageError("qdrant set_log_base before initialize()")
        from qdrant_client import models  # type: ignore[import-untyped]

        try:
            await self._client.batch_update_points(
                collection_name=collection,
                update_operations=[
                    models.SetPayloadOperation(
                        set_payload=models.SetPayload(
                            payload={"log_base": float(v)},
                            points=[pid],
                        )
                    )
                    for pid, v in updates
                ],
            )
        except Exception as exc:
            raise StorageError(
                f"qdrant set_log_base failed for {collection!r}: {exc}"
            ) from exc

    async def backfill_strength(self, collections: Sequence[str], *, log_base: float) -> int:
        if not collections:
            return 0
        if self._client is None:
            raise StorageError("qdrant backfill_strength before initialize()")
        from qdrant_client import models  # type: ignore[import-untyped]

        try:
            existing_names = await self._collection_names()
        except Exception as exc:
            raise StorageError(
                f"qdrant backfill_strength failed listing collections: {exc}"
            ) from exc
        total = 0
        chunk_size = 256
        empty_filter = models.Filter(
            must=[
                models.IsEmptyCondition(
                    is_empty=models.PayloadField(key="log_base")
                )
            ]
        )
        for name in collections:
            if name not in existing_names:
                continue
            operations: list[Any] = []
            try:
                offset = None
                while True:
                    batch, offset = await self._client.scroll(
                        collection_name=name,
                        limit=chunk_size,
                        offset=offset,
                        with_payload=True,
                        with_vectors=False,
                        scroll_filter=empty_filter,
                    )
                    for p in batch:
                        payload = dict(getattr(p, "payload", None) or {})
                        text = str(payload.pop("text", ""))
                        affect = payload.pop("affect", None)
                        # Keep an existing integer size if it was already counted.
                        existing_size = payload.get("size_bytes")
                        if isinstance(existing_size, int) and not isinstance(existing_size, bool):
                            size = existing_size
                        else:
                            size = record_size(
                                self._latent_dim, text, payload, affect
                            )
                        operations.append(
                            models.SetPayloadOperation(
                                set_payload=models.SetPayload(
                                    payload={
                                        "log_base": float(log_base),
                                        "born_sleep": -1,
                                        "size_bytes": size,
                                    },
                                    points=[str(p.id)],
                                )
                            )
                        )
                    if offset is None:
                        break
            except Exception as exc:
                raise StorageError(
                    f"qdrant backfill_strength failed scrolling collection {name!r}: {exc}"
                ) from exc
            total += len(operations)
            for i in range(0, len(operations), chunk_size):
                try:
                    await self._client.batch_update_points(
                        collection_name=name,
                        update_operations=operations[i : i + chunk_size],
                    )
                except Exception as exc:
                    raise StorageError(
                        f"qdrant backfill_strength failed updating collection {name!r}: {exc}"
                    ) from exc
        return total

    async def scan_store(self, collections: Sequence[str]) -> dict[str, Any]:
        if not collections:
            return {"bytes": 0, "log_base_counts": {}, "unstrengthed": 0}
        if self._client is None:
            raise StorageError("qdrant scan_store before initialize()")
        from qdrant_client import models
        try:
            existing_names = await self._collection_names()
        except Exception as exc:
            raise StorageError(
                f"qdrant scan_store failed listing collections: {exc}"
            ) from exc
        total = 0
        log_base_counts: dict[float, int] = {}
        unstrengthed = 0
        for name in collections:
            if name not in existing_names:
                continue
            offset = None
            missing_ids: list[str] = []
            try:
                while True:
                    batch, offset = await self._client.scroll(
                        collection_name=name,
                        limit=1024,
                        offset=offset,
                        with_payload=models.PayloadSelectorInclude(include=["size_bytes", "log_base"]),
                        with_vectors=False,
                    )
                    for p in batch:
                        payload = dict(getattr(p, "payload", None) or {})
                        sb = payload.get("size_bytes")
                        if isinstance(sb, int) and not isinstance(sb, bool):
                            total += int(sb)
                        else:
                            missing_ids.append(str(p.id))
                        lb = _numeric_log_base(payload)
                        if lb is None:
                            unstrengthed += 1
                        else:
                            log_base_counts[lb] = log_base_counts.get(lb, 0) + 1
                    if offset is None:
                        break
                for i in range(0, len(missing_ids), 256):
                    chunk = missing_ids[i : i + 256]
                    retrieved = await self._client.retrieve(
                        collection_name=name,
                        ids=chunk,
                        with_payload=True,
                        with_vectors=False,
                    )
                    for p in retrieved:
                        payload = dict(getattr(p, "payload", None) or {})
                        text = str(payload.pop("text", ""))
                        affect = payload.pop("affect", None)
                        total += record_size(
                            self._latent_dim, text, payload, affect
                        )
            except Exception as exc:
                raise StorageError(
                    f"qdrant scan_store failed scrolling collection {name!r}: {exc}"
                ) from exc
        return {"bytes": total, "log_base_counts": log_base_counts, "unstrengthed": unstrengthed}

    async def total_size(self, collections: Sequence[str]) -> int:
        if not collections:
            return 0
        if self._client is None:
            raise StorageError("qdrant total_size before initialize()")
        return (await self.scan_store(collections))["bytes"]

    async def weakest(self, collections: Sequence[str], *, limit: int) -> list[dict[str, Any]]:
        if limit <= 0 or not collections:
            return []
        if self._client is None:
            raise StorageError("qdrant weakest before initialize()")
        from qdrant_client import models  # type: ignore[import-untyped]

        def _entity_time(payload: dict[str, Any]) -> float:
            v = payload.get("entity_time", 0.0)
            try:
                v = float(v)
                return v if math.isfinite(v) else 0.0
            except (TypeError, ValueError):
                return 0.0

        try:
            existing_names = await self._collection_names()
        except Exception as exc:
            raise StorageError(
                f"qdrant weakest failed listing collections: {exc}"
            ) from exc

        per_collection: list[tuple[str, list[tuple[str, float, dict[str, Any], str, Any]], bool, float | None]] = []
        for name in collections:
            if name not in existing_names:
                continue
            try:
                batch, _ = await self._client.scroll(
                    collection_name=name,
                    limit=limit,
                    order_by=models.OrderBy(
                        key="log_base", direction=models.Direction.ASC
                    ),
                    with_payload=True,
                    with_vectors=False,
                )
            except Exception as exc:
                raise StorageError(
                    f"qdrant weakest failed scrolling collection {name!r}: {exc}"
                ) from exc
            if not batch:
                continue
            points: list[tuple[str, float, dict[str, Any], str, Any]] = []
            last_lb: float | None = None
            seen: set[str] = set()
            for p in batch:
                payload = dict(getattr(p, "payload", None) or {})
                text = str(payload.pop("text", ""))
                affect = payload.pop("affect", None)
                lb = _numeric_log_base(payload)
                if lb is None:
                    continue
                last_lb = lb
                points.append((str(p.id), lb, payload, text, affect))
                seen.add(str(p.id))
            if len(batch) == limit and last_lb is not None:
                tie_filter = models.Filter(
                    must=[
                        models.FieldCondition(
                            key="log_base",
                            range=models.Range(gte=last_lb, lte=last_lb),
                        )
                    ]
                )
                offset = None
                while True:
                    try:
                        tie_batch, offset = await self._client.scroll(
                            collection_name=name,
                            limit=1024,
                            offset=offset,
                            with_payload=True,
                            with_vectors=False,
                            scroll_filter=tie_filter,
                        )
                    except Exception as exc:
                        raise StorageError(
                            f"qdrant weakest failed scrolling tie in collection {name!r}: {exc}"
                        ) from exc
                    for p in tie_batch:
                        pid = str(p.id)
                        if pid in seen:
                            continue
                        payload = dict(getattr(p, "payload", None) or {})
                        text = str(payload.pop("text", ""))
                        affect = payload.pop("affect", None)
                        lb = _numeric_log_base(payload)
                        if lb is None:
                            continue
                        points.append((pid, lb, payload, text, affect))
                        seen.add(pid)
                    if offset is None:
                        break
            per_collection.append((name, points, len(batch) == limit, last_lb))

        any_frontier = any(has_frontier for _, _, has_frontier, _ in per_collection)
        frontier: float | None = None
        if any_frontier:
            frontier = min(
                last_lb
                for _, _, has_frontier, last_lb in per_collection
                if has_frontier and last_lb is not None
            )

        all_points: list[tuple[float, float, str, str, dict[str, Any], str, Any]] = []
        for name, points, _, _ in per_collection:
            for pid, lb, payload, text, affect in points:
                if frontier is not None and lb > frontier:
                    continue
                all_points.append(
                    (lb, _entity_time(payload), pid, name, payload, text, affect)
                )
        all_points.sort(key=lambda t: (t[0], t[1], t[2]))
        return [
            {
                "id": pid,
                "collection": name,
                "log_base": lb,
                "entity_time": et,
                "size_bytes": (
                    int(payload["size_bytes"])
                    if isinstance(payload.get("size_bytes"), int)
                    and not isinstance(payload.get("size_bytes"), bool)
                    else record_size(
                        self._latent_dim, text, payload, affect
                    )
                ),
            }
            for lb, et, pid, name, payload, text, affect in all_points
        ]

    async def delete_points(self, collection: str, point_ids: Sequence[str]) -> None:
        if not point_ids:
            return
        if self._client is None:
            raise StorageError("qdrant delete_points before initialize()")
        from qdrant_client import models  # type: ignore[import-untyped]

        chunk_size = 1000
        ids = list(point_ids)
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            try:
                await self._client.delete(
                    collection_name=collection,
                    points_selector=models.PointIdsList(points=chunk),
                )
            except Exception as exc:
                raise StorageError(
                    f"qdrant delete_points failed for {collection!r}: {exc}"
                ) from exc
