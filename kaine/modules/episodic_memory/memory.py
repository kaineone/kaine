# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""EpisodicMemoryCore — orchestrates embedder + storage + short-term buffer.

This is the thing the episodic memory module `BaseModule` wraps. It also exists
independently so callers (tests, the sleep module, future language module introspection)
can drive memory operations without spinning up a bus.
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import time
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Iterable, Optional

from kaine import legacy_aliases, legacy_names
from kaine.embedding_defaults import LEGACY_EMBEDDING_SPACE
from kaine.entity_clock import EntityClock
from kaine.memory_kinds import (
    EPISODIC_MEMORY_ASSOCIATION_KINDS,
    EPISODIC_MEMORY_COLLECTION_KINDS,
    stamp_key,
    strength_key,
)
from kaine.modules.episodic_memory.associations import (
    AssociationIndex,
    AssociationParams,
    Link,
    Node,
    cap_links,
    co_replayed_weight,
    link_id,
    log_base_for,
    mean_vector,
    node_id,
    node_log_base,
    point_key,
    select_pairs,
    split_ref,
    trace_ref,
    weight,
)
from kaine.modules.episodic_memory.embeddings import Embedder
from kaine.modules.episodic_memory.storage import (
    MemoryStorage,
    RecalledMemory,
    StorageError,
    record_size,
)
from kaine.text_embedding import same_space

log = logging.getLogger(__name__)

# The collection prefix every release used before bundles stored their prefix.
_PREFIX_BEFORE_STORED = next(
    entry["old"] for entry in legacy_names.COLLECTIONS if entry["old"].endswith("_")
)


# Canonical memory-collection kinds. Sourced from the boundary-neutral
# kaine.memory_kinds so kaine.lifecycle.decommission (which must not import
# kaine.modules) can share the single source of truth.
DEFAULT_COLLECTIONS: tuple[str, str, str, str] = EPISODIC_MEMORY_COLLECTION_KINDS

# Search cap for exact recall ranking (paper A.10).
_RECALL_SEARCH_CAP: int = 4096

#: Limit that reads an entire persisted collection (associative replay load).
_ALL_POINTS: int = 2**62


@dataclass(frozen=True)
class _PendingPrune:
    """Traces protected by a downscaling that deferred pruning to associative replay."""
    protected: tuple[tuple[str, str, float], ...]
    protected_keys: frozenset[tuple[str, str]]
    wake_sleep: int


def _write_health_file(path: Path, data: dict[str, Any]) -> None:
    """Write the episodic memory module's health JSON atomically; failures are logged, not raised."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, sort_keys=True, separators=(",", ":"))
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except OSError:
        log.warning("episodic memory: failed to write health file %s", path, exc_info=True)


# The episodic memory module owns these payload keys (paper A.10); a caller's payload cannot set them.
_RESERVED_PAYLOAD_KEYS: frozenset[str] = frozenset({"log_base", "born_sleep", "entity_time", "size_bytes"})


@dataclass(frozen=True)
class StoredMemory:
    text: str
    payload: dict[str, Any]
    affect: dict[str, Any] | None
    timestamp: float
    entity_time: float = 0.0


@dataclass(frozen=True)
class RecallSummary:
    count: int
    collection: str
    max_affect_intensity: float
    affects: tuple[dict[str, Any], ...] = field(default_factory=tuple)


EmotionalRetriggerHook = Callable[[RecallSummary], Awaitable[None]]


async def _noop_hook(_: RecallSummary) -> None:
    return


def _strength(log_base: float, log_gain: float) -> float:
    """h = exp(log_base + L), clamped to at most 1; a non-finite value is a corrupt store."""
    x = log_base + log_gain
    if not math.isfinite(x):
        raise StorageError(f"episodic memory: non-finite trace strength (log_base {log_base!r}, log gain {log_gain!r})")
    return math.exp(min(0.0, x))


class EpisodicMemoryCore:
    def __init__(
        self,
        embedder: Embedder,
        storage: MemoryStorage,
        *,
        collection_prefix: str = "episodic_memory_",
        short_term_capacity: int = 128,
        retrigger_hook: EmotionalRetriggerHook | None = None,
        clock: Callable[[], float] = time.time,
        retention_per_day: float = 0.82,
        prune_floor: float = 0.01,
        budget_bytes: int = 10 * 1024**3,
        traces_per_day: float = 288000.0,
        health_path: Path | None = None,
        entity_clock: Callable[[], float] | None = None,
        association: AssociationParams | None = None,
    ) -> None:
        if short_term_capacity <= 0:
            raise ValueError("short_term_capacity must be positive")
        if not (0.0 < retention_per_day < 1.0):
            raise ValueError("retention_per_day must be in (0, 1)")
        if not (0.0 < prune_floor < 1.0):
            raise ValueError("prune_floor must be in (0, 1)")
        if isinstance(budget_bytes, bool) or not isinstance(budget_bytes, int) or budget_bytes <= 0:
            raise ValueError("budget_bytes must be a positive integer")
        if not (math.isfinite(traces_per_day) and traces_per_day > 0.0):
            raise ValueError("traces_per_day must be a positive finite number")
        self._embedder = embedder
        self._storage = storage
        self._prefix = collection_prefix
        self._short_term_capacity = int(short_term_capacity)
        self._short_term: deque[StoredMemory] = deque()
        self._short_term_embeddings: deque[tuple[dict[str, Any], list[float]] | None] = deque()
        # Traces the latest consolidation pass moved, with their episodic point ids, kept for that sleep's replay.
        self._last_consolidated: list[tuple[str, StoredMemory]] = []
        self._hook = retrigger_hook or _noop_hook
        self._clock = clock
        self._retention_per_day = float(retention_per_day)
        self._prune_floor = float(prune_floor)
        self._budget_bytes = int(budget_bytes)
        self._traces_per_day = float(traces_per_day)
        self._health_path = health_path
        self._entity_clock = entity_clock or EntityClock().now
        # Trace-strength state (paper A.10). Values loaded from storage meta.
        self._log_gain = 0.0
        self._sleeps = 0
        self._total = 0.0
        self._bytes = 0
        self._last_sleep_entity_time = 0.0
        self._import_pending = False
        self._blocked_sleeps = 0
        self._persist_refusals = 0
        # Bytes persisted since the last sleep; added to the meta's bytes for S while awake.
        self._wake_bytes = 0
        # Number of persisted traces written in the current wake.
        self._wake_count = 0
        # entity_time stamps are offset + entity_clock(), so they continue across restarts.
        self._entity_offset = 0.0
        # Associative replay state (paper A.10).
        self._association = association or AssociationParams()
        self._assoc = AssociationIndex()
        self._assoc_ready = False
        self._pending_prune: _PendingPrune | None = None
        # Held by persist, downscale, export and import so a downscaling never interleaves with a write.
        self._strength_lock = asyncio.Lock()

    def collection_name(self, kind: str) -> str:
        if kind not in DEFAULT_COLLECTIONS:
            raise ValueError(f"unknown collection kind {kind!r}")
        return f"{self._prefix}{kind}"

    def persisted_collection_names(self) -> list[str]:
        return [self.collection_name(k) for k in DEFAULT_COLLECTIONS if k != "short_term"]

    def association_collection_names(self) -> list[str]:
        """Return the persisted collection names for links and schema nodes."""
        return [f"{self._prefix}{k}" for k in EPISODIC_MEMORY_ASSOCIATION_KINDS]

    @property
    def short_term_size(self) -> int:
        return len(self._short_term)

    @property
    def short_term_capacity(self) -> int:
        return self._short_term_capacity

    @property
    def embedder(self) -> Embedder:
        return self._embedder

    @property
    def storage(self) -> MemoryStorage:
        return self._storage

    @property
    def stamp_key(self) -> str:
        return stamp_key(self._prefix)

    @property
    def strength_key(self) -> str:
        return strength_key(self._prefix)

    @property
    def association_index(self) -> AssociationIndex:
        """In-process index of links and schema nodes (read-only for tests)."""
        return self._assoc

    @property
    def association_params(self) -> AssociationParams:
        """Hyper-parameters for associative replay."""
        return self._association

    def link_weight(self, link: Link) -> float:
        """Current weight of an associative link."""
        return weight(link.log_base, self._log_gain)

    def node_strength(self, node: Node) -> float:
        """Current strength of a schema node."""
        return weight(node.log_base, self._log_gain)

    def _kind_of(self, collection: str) -> str | None:
        """Collection kind for a persisted trace collection name, if any."""
        names = self.persisted_collection_names()
        if collection not in names:
            return None
        return collection[len(self._prefix) :]

    async def _ensure_association_collections(self) -> None:
        """Create the links and schemas collections on first co-replay."""
        if self._assoc_ready:
            return
        for name in self.association_collection_names():
            await self._storage.ensure_collection(name)
        self._assoc_ready = True

    async def _load_associations(self) -> None:
        """Load links and schema nodes from persisted storage into memory."""
        links_name, schemas_name = self.association_collection_names()
        link_points = await self._storage.recent_points(links_name, limit=_ALL_POINTS)
        node_points = await self._storage.recent_points(schemas_name, limit=_ALL_POINTS)
        try:
            self._assoc = AssociationIndex.from_points(link_points, node_points)
        except ValueError as exc:
            raise StorageError(f"episodic memory: malformed association record: {exc}") from exc
        self._assoc_ready = False

    async def _vectors(self, refs: Iterable[str]) -> dict[str, list[float]]:
        """Fetch vectors for trace refs, grouped by collection kind."""
        by_kind: dict[str, list[str]] = {}
        for ref in refs:
            kind, key = split_ref(ref)
            by_kind.setdefault(kind, []).append(key)
        out: dict[str, list[float]] = {}
        for kind, keys in by_kind.items():
            points = await self._storage.get_points(
                self.collection_name(kind), keys, with_vectors=True
            )
            for p in points:
                out[trace_ref(kind, p["id"])] = list(p["vector"])
        return out

    def _legacy_meta_keys(self, key: str) -> list[str]:
        """Return legacy meta/stamp keys that may still hold this entity's records."""
        keys: list[str] = []
        if not key.startswith(self._prefix):
            return keys
        for entry in legacy_aliases.active(legacy_names.COLLECTIONS):
            if entry.get("new") != self._prefix:
                continue
            old = entry.get("old", "")
            if old == self._prefix:
                continue
            keys.append(old + key[len(self._prefix) :])
        return keys

    async def _read_meta_carried(self, key: str) -> dict | None:
        value = await self._storage.read_meta(key)
        if value is not None:
            return value
        for legacy_key in self._legacy_meta_keys(key):
            value = await self._storage.read_meta(legacy_key)
            if value is not None:
                await self._storage.write_meta(key, value)
                log.info(
                    "episodic memory: carried the %s record over from %s",
                    key,
                    legacy_key,
                )
                return value
        return None

    async def _read_stamp_carried(self, key: str) -> dict | None:
        value = await self._storage.read_stamp(key)
        if value is not None:
            return value
        for legacy_key in self._legacy_meta_keys(key):
            value = await self._storage.read_stamp(legacy_key)
            if value is not None:
                await self._storage.write_stamp(key, value)
                log.info(
                    "episodic memory: carried the %s record over from %s",
                    key,
                    legacy_key,
                )
                return value
        return None

    @property
    def log_gain(self) -> float:
        return self._log_gain

    @property
    def sleeps(self) -> int:
        return self._sleeps

    @property
    def total_strength(self) -> float:
        return self._total

    @property
    def store_bytes(self) -> int:
        """Current persisted-store byte count S (meta bytes + writes since last sleep)."""
        return self._bytes + self._wake_bytes

    def _write_health(self) -> None:
        if self._health_path is None:
            return
        _write_health_file(
            self._health_path,
            {
                "import_pending": self._import_pending,
                "blocked_sleeps": self._blocked_sleeps,
                "persist_refusals": self._persist_refusals,
                "store_bytes": self.store_bytes,
                "budget_bytes": self._budget_bytes,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    def _total_from_scan(self, scan: dict[str, Any]) -> float:
        """Sum of trace strengths from a scan_store result."""
        total = 0.0
        for lb, count in scan.get("log_base_counts", {}).items():
            total += count * _strength(float(lb), self._log_gain)
        total += scan.get("unstrengthed", 0)
        return total

    @property
    def _prune_threshold(self) -> float:
        # A trace whose log_base is below this value is below the floor.
        return math.log(self._prune_floor) - self._log_gain

    def entity_now(self) -> float:
        return self._entity_offset + float(self._entity_clock())

    def strength_of(self, payload: Any) -> float:
        lb = _log_base(payload)
        if lb is None:
            return 1.0
        return _strength(lb, self._log_gain)

    async def initialize(self) -> None:
        await self._embedder.load()
        await self._storage.initialize()
        # Persisted collections only. Short-term lives in process.
        for kind in ("episodic", "semantic", "procedural"):
            await self._storage.ensure_collection(self.collection_name(kind))
        await self._check_embedding_space_stamp()
        await self._init_strength()
        if self._import_pending:
            log.error(
                "episodic memory: a preservation import was interrupted; "
                "re-run the revive from its bundle before the next sleep"
            )
        await self._resume_entity_time()
        await self._load_associations()
        names = self.persisted_collection_names()
        scan = await self._storage.scan_store(names)
        assoc_bytes = (await self._storage.scan_store(self.association_collection_names()))["bytes"]
        new_bytes = scan["bytes"] + assoc_bytes - self._wake_bytes
        new_total = self._total_from_scan(scan) - self._wake_count
        if new_bytes != self._bytes or not math.isclose(new_total, self._total, rel_tol=1e-12):
            self._bytes = new_bytes
            self._total = new_total
            await self._storage.write_meta(self.strength_key, self._strength_meta())
        self._write_health()

    async def _check_embedding_space_stamp(self) -> None:
        space = self._embedder.space
        stamp = await self._read_stamp_carried(self.stamp_key)
        own_collections = self.persisted_collection_names()

        if stamp is not None:
            if same_space(stamp, space):
                return
            # The stamp is stale. If the entity's own persisted collections are
            # empty there is nothing to mix, so replace the stamp.
            total = 0
            for name in own_collections:
                total += await self._storage.count(name, strict=True)
            if total == 0:
                await self._storage.write_stamp(self.stamp_key, space)
                log.warning(
                    "episodic memory: memory store is empty; its stale embedding-space stamp %s is replaced with %s",
                    stamp,
                    space,
                )
                return
            raise StorageError(
                f"episodic memory: the memory store is stamped with embedding space {stamp} "
                f"but the embedder is {space}; its memories must be re-embedded "
                f"before this embedder can use them"
            )

        # No stamp yet. Count strictly; a storage failure must not read as empty.
        total = 0
        for name in own_collections:
            total += await self._storage.count(name, strict=True)
        if total == 0:
            await self._storage.write_stamp(self.stamp_key, space)
            return

        # Store predates embedding-space stamps; assume it holds the legacy space.
        # Verify the *actual* stored dimension first; a collection whose vectors
        # are not the legacy dimension must not be stamped as legacy.
        for name in own_collections:
            if await self._storage.count(name, strict=True) == 0:
                continue
            dim = await self._storage.vector_dim(name)
            if dim != LEGACY_EMBEDDING_SPACE["dim"]:
                raise StorageError(
                    f"episodic memory: memory store collection {name!r} has vector "
                    f"dimension {dim} but the legacy KAINE space requires "
                    f"{LEGACY_EMBEDDING_SPACE['dim']}; its memories must be "
                    f"re-embedded before this embedder can use them"
                )

        if same_space(space, LEGACY_EMBEDDING_SPACE):
            await self._storage.write_stamp(self.stamp_key, LEGACY_EMBEDDING_SPACE)
            log.warning(
                "episodic memory: memory store predates embedding-space stamps; stamped as %s",
                LEGACY_EMBEDDING_SPACE,
            )
        else:
            raise StorageError(
                f"episodic memory: the memory store is stamped with embedding space {LEGACY_EMBEDDING_SPACE} "
                f"but the embedder is {space}; its memories must be re-embedded "
                f"before this embedder can use them"
            )

    async def _init_strength(self) -> None:
        """Load strength meta and backfill old traces."""
        names = self.persisted_collection_names()
        meta = await self._read_meta_carried(self.strength_key)
        fresh = False
        if meta is None:
            carried = 0
            for name in names:
                carried += await self._storage.count_filtered(name, has_log_base=True)
            if carried > 0:
                raise StorageError(
                    f"episodic memory: the memory store has no trace-strength record but {carried} "
                    "traces carry log_base; their strengths cannot be recovered"
                )
            total = 0
            for name in names:
                total += await self._storage.count(name, strict=True)
            meta = {
                "log_gain": 0.0,
                "sleeps": 0,
                "total": float(total),
                "entity_time": 0.0,
                "bytes": await self._storage.total_size(names),
            }
            await self._storage.write_meta(self.strength_key, meta)
            fresh = True
        self._load_strength(meta)
        changed = 0
        for name in names:
            changed += await self._storage.backfill_strength(
                [name], log_base=-self._log_gain
            )
        if changed and not fresh:
            self._total += changed
            await self._storage.write_meta(self.strength_key, self._strength_meta())
        if changed:
            log.info(
                "episodic memory: gave %d traces from before trace strengths a strength of 1",
                changed,
            )

    def _load_strength(self, meta: dict[str, Any]) -> None:
        meta = _validate_strength(meta)
        self._log_gain = meta["log_gain"]
        self._sleeps = meta["sleeps"]
        self._total = meta["total"]
        self._bytes = meta["bytes"]
        self._last_sleep_entity_time = meta["entity_time"]
        self._import_pending = meta["import_pending"]
        self._blocked_sleeps = meta.get("blocked_sleeps", 0)
        self._persist_refusals = meta.get("persist_refusals", 0)

    def _strength_meta(self) -> dict[str, Any]:
        meta: dict[str, Any] = {
            "log_gain": self._log_gain,
            "sleeps": self._sleeps,
            "total": self._total,
            "bytes": self._bytes,
            "entity_time": self._last_sleep_entity_time,
        }
        if self._import_pending:
            meta["import_pending"] = True
        if self._blocked_sleeps:
            meta["blocked_sleeps"] = self._blocked_sleeps
        if self._persist_refusals:
            meta["persist_refusals"] = self._persist_refusals
        return meta

    async def _resume_entity_time(self) -> None:
        newest = self._last_sleep_entity_time
        wake_bytes = 0
        wake_count = 0
        for point in await self._storage.wake_points(
            self.persisted_collection_names(), self._sleeps
        ):
            wake_count += 1
            payload = point.get("payload") or {}
            et = _entity_time(payload)
            if et > newest:
                newest = et
            size = payload.get("size_bytes")
            if isinstance(size, bool) or not isinstance(size, int):
                size = record_size(
                    self._storage.latent_dim,
                    point.get("text") or "",
                    payload,
                    point.get("affect"),
                )
            wake_bytes += int(size)
        for memory in self._short_term:
            if memory.entity_time > newest:
                newest = memory.entity_time
        self._wake_bytes = wake_bytes
        self._wake_count = wake_count
        # The entity clock restarts at 0 on each boot, so stamps are shifted
        # forward only when the clock reads behind the newest stamp of the
        # current wake.
        self._entity_offset = max(0.0, newest - float(self._entity_clock()))

    async def wake_pool(self) -> list[dict[str, Any]]:
        """Persisted traces stored since the last downscaling."""
        return await self._storage.wake_points(
            self.persisted_collection_names(), self._sleeps
        )

    async def downscale(
        self, protect: Iterable[tuple[str, str, float]] = (), *, prune: bool = True
    ) -> dict[str, Any]:
        """Downscale trace strengths for one sleep (paper A.10).

        When ``prune`` is true, pruning follows immediately. When it is false,
        pruning is deferred so associative replay can run first; call
        :meth:`associate` and then :meth:`prune`. A trace replayed in this
        sleep is never pruned in it.
        """
        async with self._strength_lock:
            if self._import_pending:
                self._blocked_sleeps += 1
                await self._storage.write_meta(self.strength_key, self._strength_meta())
                self._write_health()
                log.error(
                    "episodic memory: a preservation import was interrupted; "
                    "re-run the revive from its bundle before the next sleep "
                    "(blocked sleeps: %d)",
                    self._blocked_sleeps,
                )
                return {
                    "blocked": "import_pending",
                    "blocked_sleeps": self._blocked_sleeps,
                    "persist_refusals": self._persist_refusals,
                    "store_bytes": self.store_bytes,
                }

            names = self.persisted_collection_names()
            scan = await self._storage.scan_store(names)
            s_now = scan["bytes"]
            n_new = 0
            for name in names:
                n_new += await self._storage.count_filtered(
                    name, born_sleep=self._sleeps
                )
            log_f = (n_new / self._traces_per_day) * math.log(self._retention_per_day)
            factor = math.exp(log_f)

            seen: set[tuple[str, str]] = set()
            protected: list[tuple[str, str, float]] = []
            h_q = 0.0
            for coll, point_id, lb in protect:
                key = (str(coll), str(point_id))
                if key in seen or coll not in names:
                    continue
                nlb = _log_base({"log_base": lb})
                if nlb is None:
                    continue
                seen.add(key)
                protected.append((coll, str(point_id), nlb))
                h_q += _strength(nlb, self._log_gain)

            total_before = self._total_from_scan(scan)
            total_after = factor * (total_before - h_q) + h_q

            # Write meta before touching points. A crash after this leaves the
            # protected traces downscaled with the rest; strength is lost, never created.
            meta = {
                "log_gain": self._log_gain + log_f,
                "sleeps": self._sleeps + 1,
                "total": total_after,
                "entity_time": self.entity_now(),
                "bytes": s_now,
            }
            await self._storage.write_meta(self.strength_key, meta)
            self._write_health()
            self._log_gain = meta["log_gain"]
            self._sleeps = meta["sleeps"]
            self._total = meta["total"]
            self._last_sleep_entity_time = meta["entity_time"]
            self._bytes = meta["bytes"]
            self._wake_bytes = 0

            by_coll: dict[str, list[tuple[str, float]]] = {}
            for coll, point_id, lb in protected:
                by_coll.setdefault(coll, []).append((point_id, lb - log_f))
            for coll, updates in by_coll.items():
                await self._storage.set_log_base(coll, updates)

            protected_keys = {(coll, str(pid)) for coll, pid, _ in protected}
            if not prune:
                self._pending_prune = _PendingPrune(
                    protected=tuple(protected),
                    protected_keys=frozenset(protected_keys),
                    wake_sleep=self._sleeps - 1,
                )
                await self._storage.write_meta(self.strength_key, self._strength_meta())
                self._write_health()
                return {
                    "n_new": n_new,
                    "factor": factor,
                    "protected": len(protected),
                    "total_before": total_before,
                    "total_after": total_after,
                    "pruned_floor": 0,
                    "pruned_budget": 0,
                    "prune_deferred": True,
                    "store_bytes": self._bytes,
                    "blocked": None,
                    "blocked_sleeps": 0,
                    "persist_refusals": self._persist_refusals,
                }

            self._pending_prune = None
            has_assoc = bool(self._assoc)
            counts = await self._prune_locked(protected_keys)
            pruned_floor = counts["pruned_floor"]
            pruned_budget = counts["pruned_budget"]

        log.info(
            "episodic memory: sleep pruned %d traces at the floor and %d for the budget; store is %d bytes",
            pruned_floor,
            pruned_budget,
            self._bytes,
        )
        result: dict[str, Any] = {
            "n_new": n_new,
            "factor": factor,
            "protected": len(protected),
            "total_before": total_before,
            "total_after": total_after,
            "pruned_floor": pruned_floor,
            "pruned_budget": pruned_budget,
            "store_bytes": self._bytes,
            "blocked": None,
            "blocked_sleeps": 0,
            "persist_refusals": self._persist_refusals,
        }
        if has_assoc:
            result["links_pruned"] = counts["links_pruned"]
            result["nodes_pruned"] = counts["nodes_pruned"]
        return result

    async def _prune_locked(self, protected_keys) -> dict[str, int]:
        """Prune records below the floor and then to the budget (paper A.10).

        Association links and nodes are included in the weakest-first pruning.
        Deleting a trace cascades to its links; schema nodes are rebuilt or
        removed afterwards so the store stays consistent.
        """
        names = self.persisted_collection_names()
        has_assoc = bool(self._assoc)
        links_name, schemas_name = self.association_collection_names()
        scan_names = names + ([links_name, schemas_name] if has_assoc else [])
        trace_set = set(names)

        protected = {(c, point_key(i)) for c, i in protected_keys}
        deleted: set[tuple[str, str]] = set()
        cascaded: set[tuple[str, str]] = set()
        touched: set[str] = set()
        gone: set[str] = set()

        thr = self._prune_threshold
        pruned_floor = pruned_budget = links_pruned = nodes_pruned = 0

        while True:
            done = False
            pass_deleted = 0
            while not done:
                batch = await self._storage.weakest(scan_names, limit=1024)
                if not batch:
                    break
                projected = self._bytes
                by_coll_doomed: dict[str, list[tuple[str, float, int, str]]] = {}
                for p in batch:
                    coll = str(p["collection"])
                    pid = str(p["id"])
                    key = (coll, point_key(pid))
                    if key in protected:
                        continue
                    if key in deleted:
                        if key in cascaded:
                            continue
                        raise StorageError(
                            f"episodic memory: pruning found point {p['id']!r} of {p['collection']!r} again after deleting it"
                        )
                    if p["log_base"] < thr:
                        reason = "floor"
                    elif projected > self._budget_bytes:
                        reason = "budget"
                    else:
                        done = True
                        break
                    deleted.add(key)
                    size = int(p["size_bytes"])
                    projected -= size
                    by_coll_doomed.setdefault(coll, []).append(
                        (pid, float(p["log_base"]), size, reason)
                    )
                    pass_deleted += 1

                    if has_assoc and coll in trace_set:
                        ref = trace_ref(self._kind_of(coll), pid)
                        gone.add(ref)
                        for link in self._assoc.links_of(ref):
                            lk = (links_name, link.id)
                            if lk in deleted:
                                continue
                            deleted.add(lk)
                            cascaded.add(lk)
                            projected -= link.size_bytes
                            by_coll_doomed.setdefault(links_name, []).append(
                                (link.raw_id, 0.0, link.size_bytes, "cascade")
                            )
                            touched.add(link.other(ref))
                    elif has_assoc and coll == links_name:
                        link = self._assoc.links.get(point_key(pid))
                        if link is not None:
                            touched.add(link.a)
                            touched.add(link.b)

                if not by_coll_doomed:
                    break
                for coll, items in by_coll_doomed.items():
                    ids = [i[0] for i in items]
                    await self._storage.delete_points(coll, ids)
                    if coll in trace_set:
                        for _, lb, size, reason in items:
                            self._bytes -= size
                            self._total -= _strength(lb, self._log_gain)
                            if reason == "floor":
                                pruned_floor += 1
                            else:
                                pruned_budget += 1
                    elif coll == links_name:
                        for item_id, _, size, _ in items:
                            self._bytes -= size
                            self._assoc.remove_link(point_key(item_id))
                            links_pruned += 1
                    elif coll == schemas_name:
                        for item_id, _, size, _ in items:
                            self._bytes -= size
                            nodes_pruned += 1
                            node = self._assoc.node_by_id(item_id)
                            if node is not None:
                                self._assoc.remove_node(node.center)
                    await self._storage.write_meta(self.strength_key, self._strength_meta())
                    self._write_health()

            if not has_assoc:
                break

            _, removed = await self._sync_nodes(touched | gone, gone)
            nodes_pruned += removed
            if self._bytes > self._budget_bytes and pass_deleted > 0:
                touched = set()
                gone = set()
                continue
            break

        self._bytes = max(0, self._bytes)
        self._total = max(0.0, self._total)
        await self._storage.write_meta(self.strength_key, self._strength_meta())
        self._write_health()

        return {
            "pruned_floor": pruned_floor,
            "pruned_budget": pruned_budget,
            "links_pruned": links_pruned,
            "nodes_pruned": nodes_pruned,
        }

    async def _sync_nodes(self, refs: Iterable[str], gone: set[str]) -> tuple[int, int]:
        """Rebuild or remove schema nodes for the given trace references.

        A node is removed when its center is gone or has too few links.
        Otherwise it is rebuilt from the current links and partner vectors.
        """
        schemas_name = self.association_collection_names()[1]
        formed = 0
        removed = 0
        for ref in sorted(set(refs)):
            node = self._assoc.node_of(ref)
            if ref in gone or self._assoc.degree(ref) < self._association.n_sch:
                if node is not None:
                    await self._storage.delete_points(schemas_name, [node.raw_id])
                    self._bytes -= node.size_bytes
                    self._assoc.remove_node(ref)
                    removed += 1
                continue

            links = self._assoc.links_of(ref)
            members = [ref] + self._assoc.partners(ref)
            vecs = await self._vectors(members)
            missing = [m for m in members if m not in vecs]
            if missing:
                log.warning(
                    "episodic memory: schema member(s) %s missing during sync; removing node %s",
                    missing,
                    node.raw_id if node else node_id(ref),
                )
                if node is not None:
                    await self._storage.delete_points(schemas_name, [node.raw_id])
                    self._bytes -= node.size_bytes
                    self._assoc.remove_node(ref)
                    removed += 1
                continue

            centroid = mean_vector([vecs[m] for m in members])
            lb = node_log_base([link.log_base for link in links], self._log_gain)
            payload = {
                "center": ref,
                "log_base": lb,
                "entity_time": self.entity_now(),
            }
            payload["size_bytes"] = record_size(
                self._storage.latent_dim,
                "",
                payload,
                None,
            )
            nid = node_id(ref)
            await self._ensure_association_collections()
            if node is not None:
                await self._storage.delete_points(schemas_name, [node.raw_id])
                self._bytes -= node.size_bytes
            await self._storage.upsert(
                schemas_name,
                vector=centroid,
                text="",
                payload=payload,
                affect=None,
                point_id=nid,
            )
            self._bytes += payload["size_bytes"]
            self._assoc.set_node(
                Node(
                    id=nid,
                    raw_id=nid,
                    center=ref,
                    log_base=lb,
                    entity_time=payload["entity_time"],
                    size_bytes=payload["size_bytes"],
                )
            )
            formed += 1
        return formed, removed

    async def associate(self) -> dict[str, Any]:
        """Run associative replay for a deferred downscaling (paper A.10).

        Co-replays at most ``n_pair`` pairs between the protected wake traces
        and older traces, creates or strengthens links, caps per-trace link
        counts, and rebuilds schema nodes. Returns a summary dict.
        """
        async with self._strength_lock:
            if self._pending_prune is None:
                return {"skipped": "no downscaling awaits pruning"}

            params = self._association
            pending = self._pending_prune
            names = self.persisted_collection_names()

            # 1. Fetch the protected (Q) traces that were replayed.
            q_map: dict[str, list[float]] = {}
            q_ids_by_coll: dict[str, list[str]] = {}
            for coll, pid, _ in pending.protected:
                if coll not in names:
                    continue
                q_ids_by_coll.setdefault(coll, []).append(pid)
            for coll, ids in q_ids_by_coll.items():
                for p in await self._storage.get_points(coll, ids, with_vectors=True):
                    q_map[trace_ref(self._kind_of(coll), p["id"])] = list(p["vector"])

            # 2. Find candidate neighbours in every trace collection.
            candidates: list[tuple[str, str, float]] = []
            for q_ref in sorted(q_map):
                q_vector = q_map[q_ref]
                for name in names:
                    for old_ref, sim in await self._band_neighbours(
                        name, q_vector, pending.wake_sleep, params
                    ):
                        candidates.append((q_ref, old_ref, sim))

            # 3. Select the best pairs.
            pairs = select_pairs(candidates, params.n_pair)
            if not pairs:
                return {
                    "pairs": [],
                    "links_dropped": 0,
                    "nodes_formed": 0,
                    "nodes_removed": 0,
                    "links": len(self._assoc.links),
                    "nodes": len(self._assoc.nodes),
                    "store_bytes": self._bytes,
                }

            # 4. Upsert the chosen links.
            await self._ensure_association_collections()
            links_name = self.association_collection_names()[0]
            old_refs = [old_ref for (_, old_ref, _) in pairs]
            old_vectors = await self._vectors(old_refs)
            touched: set[str] = set()
            reported: list[dict[str, Any]] = []
            for q_ref, old_ref, sim in pairs:
                if old_ref not in old_vectors:
                    continue
                q_vec = q_map[q_ref]
                old_vec = old_vectors[old_ref]
                lid = link_id(q_ref, old_ref)
                existing = self._assoc.links.get(lid)
                w_old = self.link_weight(existing) if existing else 0.0
                w_new = co_replayed_weight(w_old)
                a, b = sorted((q_ref, old_ref))
                lb = log_base_for(w_new, self._log_gain)
                et = self.entity_now()
                payload = {
                    "a": a,
                    "b": b,
                    "log_base": lb,
                    "entity_time": et,
                }
                payload["size_bytes"] = record_size(
                    self._storage.latent_dim,
                    "",
                    payload,
                    None,
                )
                if existing is not None:
                    await self._storage.delete_points(links_name, [existing.raw_id])
                    self._bytes -= existing.size_bytes
                await self._storage.upsert(
                    links_name,
                    vector=mean_vector([q_vec, old_vec]),
                    text="",
                    payload=payload,
                    affect=None,
                    point_id=lid,
                )
                self._bytes += payload["size_bytes"]
                self._assoc.add_link(
                    Link(
                        id=lid,
                        raw_id=lid,
                        a=a,
                        b=b,
                        log_base=lb,
                        entity_time=et,
                        size_bytes=payload["size_bytes"],
                    )
                )
                touched.add(a)
                touched.add(b)
                reported.append(
                    {
                        "a": split_ref(q_ref)[1],
                        "b": split_ref(old_ref)[1],
                        "weight": w_new,
                    }
                )

            # 5. Cap per-trace link counts.
            dropped = cap_links(self._assoc, touched, params.n_link)
            for link in dropped:
                await self._storage.delete_points(links_name, [link.raw_id])
                self._bytes -= link.size_bytes
                touched.add(link.a)
                touched.add(link.b)

            # 6. Rebuild schema nodes.
            formed, removed = await self._sync_nodes(touched, set())

            # 7. Persist state.
            await self._storage.write_meta(self.strength_key, self._strength_meta())
            self._write_health()

            return {
                "pairs": reported,
                "links_dropped": len(dropped),
                "nodes_formed": formed,
                "nodes_removed": removed,
                "links": len(self._assoc.links),
                "nodes": len(self._assoc.nodes),
                "store_bytes": self._bytes,
            }

    async def _band_neighbours(
        self,
        name: str,
        vector: list[float],
        wake_sleep: int,
        params: AssociationParams,
    ) -> list[tuple[str, float]]:
        """Return up to ``n_pair`` older trace neighbours in a band of similarity.

        Candidates must satisfy ``sim_min <= sim < sim_dup`` and have been
        born before the current wake window.
        """
        kind = self._kind_of(name)
        if kind is None:
            return []
        n_all = await self._storage.count(name, strict=True)
        if n_all == 0:
            return []
        m = min(max(4 * params.n_pair, 32), n_all, _RECALL_SEARCH_CAP)
        logged_cap = False
        while True:
            hits = await self._storage.search(name, query_vector=vector, limit=m)
            results: list[tuple[str, float]] = []
            for hit in hits:
                if hit.score < params.sim_min:
                    return results
                if hit.score >= params.sim_dup:
                    continue
                born = hit.payload.get("born_sleep")
                if not isinstance(born, int) or isinstance(born, bool) or born >= wake_sleep:
                    continue
                results.append((trace_ref(kind, hit.point_id), hit.score))
                if len(results) >= params.n_pair:
                    return results
            if len(hits) < m or m >= n_all:
                return results
            if m >= _RECALL_SEARCH_CAP:
                if not logged_cap:
                    log.info(
                        "episodic memory: associative replay searched the nearest %d of %d traces",
                        m,
                        n_all,
                    )
                    logged_cap = True
                return results
            m = min(m * 8, n_all, _RECALL_SEARCH_CAP)

    async def prune(self) -> dict[str, Any]:
        """Apply pruning that was deferred by :meth:`downscale`.

        This is called after :meth:`associate` so associative replay can run
        before the final weakest-first pruning pass (paper A.10).
        """
        async with self._strength_lock:
            if self._pending_prune is None:
                return {"skipped": "no downscaling awaits pruning"}
            pending = self._pending_prune
            self._pending_prune = None
            counts = await self._prune_locked(set(pending.protected_keys))
            log.info(
                "episodic memory: sleep pruned %d traces at the floor and %d for the budget; store is %d bytes",
                counts["pruned_floor"],
                counts["pruned_budget"],
                self._bytes,
            )
            return {**counts, "store_bytes": self._bytes}

    async def shutdown(self) -> None:
        try:
            await self._storage.shutdown()
        except Exception:
            log.warning("storage shutdown failed", exc_info=True)
        try:
            await self._embedder.shutdown()
        except Exception:
            log.warning("embedder shutdown failed", exc_info=True)

    async def store(
        self,
        text: str,
        payload: dict[str, Any] | None = None,
        *,
        affect: dict[str, Any] | None = None,
        collection: str = "short_term",
    ) -> Optional[str]:
        """Store an entry. Returns the storage point_id (None for short-term)."""
        if collection not in DEFAULT_COLLECTIONS:
            raise ValueError(f"unknown collection {collection!r}")
        ts = float(self._clock())
        payload = dict(payload or {})
        for key in _RESERVED_PAYLOAD_KEYS:
            payload.pop(key, None)
        payload.setdefault("timestamp", ts)
        memory = StoredMemory(
            text=text,
            payload=payload,
            affect=affect,
            timestamp=ts,
            entity_time=self.entity_now(),
        )
        if collection == "short_term":
            self._rebuild_embeddings_if_desynced()
            if len(self._short_term) >= self._short_term_capacity:
                evicted = self._short_term.popleft()
                self._short_term_embeddings.popleft()
                await self._persist(evicted, "episodic")
            self._short_term.append(memory)
            self._short_term_embeddings.append(None)
            return None
        return await self._persist(memory, collection)

    async def _persist(self, memory: StoredMemory, collection: str) -> Optional[str]:
        vec = await self._embedder.encode(memory.text)
        coll_name = self.collection_name(collection)
        async with self._strength_lock:
            if self._import_pending and self.store_bytes > 2 * self._budget_bytes:
                self._persist_refusals += 1
                await self._storage.write_meta(self.strength_key, self._strength_meta())
                self._write_health()
                log.error(
                    "episodic memory: refused to store a trace: an interrupted import has blocked sleep for %d sleeps and the store is %d bytes, over twice its budget of %d; run python -m kaine.lifecycle.episodic_memory_recover or re-run the revive",
                    self._blocked_sleeps,
                    self.store_bytes,
                    self._budget_bytes,
                )
                return None
            payload = {
                k: v for k, v in memory.payload.items() if k not in _RESERVED_PAYLOAD_KEYS
            }
            payload["log_base"] = -self._log_gain
            payload["born_sleep"] = self._sleeps
            payload["entity_time"] = float(memory.entity_time)
            payload["size_bytes"] = record_size(
                self._storage.latent_dim,
                memory.text,
                payload,
                memory.affect,
            )
            point_id = await self._storage.upsert(
                coll_name,
                vector=vec,
                text=memory.text,
                payload=payload,
                affect=memory.affect,
            )
            self._wake_bytes += int(payload["size_bytes"])
            return point_id

    async def recall(
        self,
        query_text: str,
        *,
        k: int = 5,
        collection: str = "episodic",
    ) -> tuple[list[RecalledMemory], RecallSummary]:
        if collection not in DEFAULT_COLLECTIONS:
            raise ValueError(f"unknown collection {collection!r}")
        if collection == "short_term":
            return await self._recall_short_term(query_text, k)
        vec = await self._embedder.encode(query_text)
        coll_name = self.collection_name(collection)

        k = max(0, int(k))
        if k == 0:
            results = []
        else:
            n_all = await self._storage.count(coll_name, strict=True)
            m = min(4 * k, max(n_all, 1), _RECALL_SEARCH_CAP)
            while True:
                hits = await self._storage.search(
                    coll_name, query_vector=vec, limit=m
                )
                exhausted = len(hits) < m
                scored = []
                for hit in hits:
                    if hit.score <= 0.0:
                        continue
                    strength = self.strength_of(hit.payload)
                    scored.append(
                        (strength * hit.score, hit.score, _entity_time(hit.payload), hit, strength)
                    )
                scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
                floor = min((h.score for h in hits), default=0.0)
                # strength is at most 1, so an unfetched trace scores at most its
                # cosine, which is at most the smallest fetched cosine; the result is
                # therefore exact relative to the backend's cosine order.
                if (
                    exhausted
                    or floor <= 0.0
                    or (len(scored) >= k and scored[k - 1][0] >= floor)
                    or m >= n_all
                ):
                    break
                if not exhausted and m >= _RECALL_SEARCH_CAP:
                    # The cap binds: log once for this recall and keep the ranking so far.
                    log.info(
                        "episodic memory: recall ranked the %d nearest of %d traces; beyond that the order is approximate",
                        m,
                        n_all,
                    )
                    break
                m = min(m * 8, n_all, _RECALL_SEARCH_CAP)
            results = [
                replace(hit, score=product, similarity=sim, strength=strength)
                for product, sim, _, hit, strength in scored[:k]
            ]
            if bool(self._assoc) and k > 0:
                results = await self._recall_associations(vec, results, k, collection)

        summary = _summarize(results, collection)
        await self._invoke_hook(summary)
        return results, summary

    async def _recall_associations(
        self,
        vec: list[float],
        ranked: list[RecalledMemory],
        k: int,
        kind: str,
    ) -> list[RecalledMemory]:
        """Augment recall results with matching schema nodes and linked partners."""
        schemas_name = self.association_collection_names()[1]

        # 1. Merge in schema nodes that match the query.
        nodes = [n for n in self._assoc.nodes.values() if split_ref(n.center)[0] == kind]
        node_entries: list[tuple[float, float, Node, float]] = []
        if nodes:
            hits = await self._storage.search(
                schemas_name, query_vector=vec, limit=len(self._assoc.nodes)
            )
            for hit in hits:
                if hit.score <= 0.0:
                    continue
                node = self._assoc.node_by_id(hit.point_id)
                if node is None or split_ref(node.center)[0] != kind:
                    continue
                strength = self.node_strength(node)
                node_entries.append((strength * hit.score, hit.score, node, strength))

        trace_entries = [
            (r.score, r.similarity, 0, r) for r in ranked
        ]
        node_sort_entries = [
            (product, sim, 1, (node, strength))
            for product, sim, node, strength in node_entries
        ]
        merged = sorted(
            trace_entries + node_sort_entries,
            key=lambda t: (-t[0], -t[1], t[2]),
        )
        kept: list[RecalledMemory] = []
        node_results: set[int] = set()
        for product, sim, kind_order, item in merged[:k]:
            if kind_order == 0:
                kept.append(item)
            else:
                node_results.add(len(kept))
                node, strength = item
                _center_kind, center_key = split_ref(node.center)
                center_text = ""
                for p in await self._storage.get_points(
                    self.collection_name(kind), [center_key]
                ):
                    center_text = str(p.get("text") or "")
                    break
                kept.append(
                    RecalledMemory(
                        point_id=node.id,
                        score=product,
                        text=center_text,
                        payload={
                            "schema_node": True,
                            "center": center_key,
                            "members": [
                                split_ref(p)[1] for p in self._assoc.partners(node.center)
                            ],
                        },
                        affect=None,
                        similarity=sim,
                        strength=strength,
                    )
                )

        # 2. Append partners of kept traces.
        kept_keys = {point_key(r.point_id) for r in kept}
        partner_queue: list[tuple[str, str]] = []
        queued_keys: set[str] = set()
        for index, r in enumerate(kept):
            if index in node_results:
                continue
            ref = trace_ref(kind, r.point_id)
            for partner in self._assoc.partners(ref):
                pkey = split_ref(partner)[1]
                if pkey in kept_keys or pkey in queued_keys:
                    continue
                partner_queue.append((kind, partner))
                queued_keys.add(pkey)

        if partner_queue:
            by_kind: dict[str, list[str]] = {}
            for _, partner in partner_queue:
                pkind, pkey = split_ref(partner)
                by_kind.setdefault(pkind, []).append(pkey)
            fetched: dict[str, dict[str, Any]] = {}
            for pkind, keys in by_kind.items():
                for p in await self._storage.get_points(
                    self.collection_name(pkind), keys, with_vectors=True
                ):
                    fetched[trace_ref(pkind, p["id"])] = p
            for _, partner in partner_queue:
                p = fetched.get(partner)
                if p is None:
                    continue
                pvec = list(p["vector"])
                sim = _cosine_similarity(vec, pvec)
                strength = self.strength_of(p["payload"])
                kept.append(
                    RecalledMemory(
                        point_id=str(p["id"]),
                        score=strength * sim,
                        text=str(p.get("text") or ""),
                        payload=dict(p["payload"]),
                        affect=dict(p["affect"]) if p.get("affect") else None,
                        similarity=sim,
                        strength=strength,
                    )
                )

        return kept

    async def _recall_short_term(
        self, query_text: str, k: int
    ) -> tuple[list[RecalledMemory], RecallSummary]:
        """Recall from the short-term buffer using cosine similarity.

        The query is embedded once. Each short-term entry is embedded at most
        once per embedding space (in practice once, since a running core's
        embedder does not change); the embedding is held in memory only and is
        never exported. Equal cosine scores rank the more recent entry first.
        """
        self._rebuild_embeddings_if_desynced()

        if not self._short_term:
            summary = _summarize([], "short_term")
            return [], summary

        query_vector = await self._embedder.encode(query_text)
        current_space = dict(self._embedder.space)

        updated: list[tuple[dict[str, Any], list[float]] | None] = []
        for idx, memory in enumerate(self._short_term):
            slot = self._short_term_embeddings[idx]
            if slot is None or not same_space(slot[0], current_space):
                vec = await self._embedder.encode(memory.text)
                slot = (current_space, vec)
            updated.append(slot)
        self._short_term_embeddings = deque(updated)

        scored: list[tuple[float, int, StoredMemory]] = []
        for idx, (memory, slot) in enumerate(zip(self._short_term, self._short_term_embeddings)):
            score = _cosine_similarity(query_vector, slot[1])
            scored.append((score, idx, memory))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)

        results: list[RecalledMemory] = []
        for score, idx, memory in scored[: max(0, int(k))]:
            if score <= 0.0:
                continue
            results.append(
                RecalledMemory(
                    point_id=f"short_term:{idx}",
                    score=float(score),
                    text=memory.text,
                    payload=dict(memory.payload),
                    affect=dict(memory.affect) if memory.affect else None,
                    similarity=float(score),
                    strength=1.0,
                )
            )
        summary = _summarize(results, "short_term")
        # No hook for short-term — those are fast/working memory, not the
        # episodic re-experience semantics.
        return results, summary

    def _rebuild_embeddings_if_desynced(self) -> None:
        if len(self._short_term_embeddings) != len(self._short_term):
            log.warning(
                "episodic memory: short_term_embeddings length (%d) differs from short_term length (%d); resetting embeddings cache",
                len(self._short_term_embeddings),
                len(self._short_term),
            )
            self._short_term_embeddings = deque([None] * len(self._short_term))

    async def consolidate_now(self) -> int:
        """Flush every short-term entry into episodic. Returns count moved.

        The moved traces are kept with their episodic ids until the next
        pass or ``clear_last_consolidated()``, so this sleep's replay can
        draw on them.
        """
        self._rebuild_embeddings_if_desynced()
        batch: list[tuple[str, StoredMemory]] = []
        moved = 0
        try:
            while self._short_term:
                entry = self._short_term.popleft()
                self._short_term_embeddings.popleft()
                point_id = await self._persist(entry, "episodic")
                moved += 1
                if point_id is None:
                    continue
                batch.append((point_id, entry))
        finally:
            self._last_consolidated = batch
        return moved

    @property
    def last_consolidated(self) -> tuple[tuple[str, StoredMemory], ...]:
        """Read-only view of the latest consolidated traces."""
        return tuple(self._last_consolidated)

    def clear_last_consolidated(self) -> None:
        """Drop the latest consolidated traces (called after sleep)."""
        self._last_consolidated = []

    # ------------------------------------------------------------------
    # Full-fidelity capture / restore (preservation + revive)
    # ------------------------------------------------------------------

    async def export_state(self) -> dict[str, Any]:
        """Capture the whole memory store: short-term buffer + persisted points.

        Used by the episodic memory module's preservation. The persisted side delegates to the
        storage backend's ``export`` (which FAILS LOUDLY on an unreachable
        Qdrant). The short-term buffer is in-process working memory; it is
        captured here as ``StoredMemory`` fields so a revived entity resumes
        with the same working set.
        """
        async with self._strength_lock:
            short_term = [
                {
                    "text": m.text,
                    "payload": dict(m.payload),
                    "affect": dict(m.affect) if m.affect else None,
                    "timestamp": m.timestamp,
                    "entity_time": m.entity_time,
                }
                for m in self._short_term
            ]
            persisted = await self._storage.export(
                self.persisted_collection_names() + self.association_collection_names()
            )
            return {
                "collection_prefix": self._prefix,
                "short_term": short_term,
                "persisted": persisted,
                "embedding_space": self._embedder.space,
                "strength": self._strength_meta(),
            }

    async def import_state(self, state: dict[str, Any]) -> int:
        """Restore a store captured by :meth:`export_state`. Returns total points.

        Re-imports persisted collections under this core's own prefix, then
        rebuilds the short-term deque. FAILS LOUDLY (propagates StorageError)
        when the backend cannot re-import; revive must not yield a
        memory-poor lesser individual.

        A pending flag is set in the meta before any collection is replaced so
        an interrupted revive cannot be followed by a sleep that downscales a
        store whose strengths and meta disagree.
        """
        async with self._strength_lock:
            bundle_space = state.get("embedding_space") or LEGACY_EMBEDDING_SPACE
            if not same_space(bundle_space, self._embedder.space):
                raise StorageError(
                    f"episodic memory: bundle embedding space {bundle_space} does not match "
                    f"running embedder space {self._embedder.space}; cannot revive"
                )

            # The prefix names the collections inside the bundle, so it is never
            # mapped. A bundle without one predates the stored prefix and holds
            # its collections under the old default prefix.
            src_prefix = (
                state["collection_prefix"] if "collection_prefix" in state else _PREFIX_BEFORE_STORED
            )
            persisted = state.get("persisted") or {}
            persisted_kinds = [k for k in DEFAULT_COLLECTIONS if k != "short_term"]
            mapping: dict[str, str] = {}
            for kind in persisted_kinds:
                src_name = f"{src_prefix}{kind}"
                mapping[src_name] = self.collection_name(kind)

            assoc_targets: list[str] = []
            for kind in EPISODIC_MEMORY_ASSOCIATION_KINDS:
                src_name = f"{src_prefix}{kind}"
                target_name = f"{self._prefix}{kind}"
                if src_name in persisted or await self._storage.count(target_name) > 0:
                    mapping[src_name] = target_name
                    assoc_targets.append(target_name)

            strength = state.get("strength")
            if strength is not None:
                strength = _validate_strength(strength)
            else:
                for src_name, target_name in mapping.items():
                    for p in persisted.get(src_name, []):
                        if _log_base(p.get("payload") or {}) is not None:
                            raise StorageError(
                                "episodic memory: bundle carries trace strengths (log_base) "
                                "but no strength record; refusing to revive with meaningless strengths"
                            )

            # Validate every point for every mapped kind before writing anything.
            for src_name, target_name in mapping.items():
                for p in persisted.get(src_name, []):
                    vec = list(p.get("vector") or [])
                    if len(vec) != self._storage.latent_dim:
                        raise StorageError(
                            f"imported point in {src_name!r} -> {target_name!r} "
                            f"has vector dim {len(vec)} != storage latent_dim {self._storage.latent_dim}"
                        )
                    if not all(math.isfinite(v) for v in vec):
                        raise StorageError(
                            f"imported point in {src_name!r} -> {target_name!r} has non-finite vector"
                        )

            # Refuse a revive whose persisted collections are all foreign to this bundle.
            own_src_names = set(mapping.keys())
            non_empty_names = {n for n, pts in persisted.items() if pts}
            if non_empty_names and not (non_empty_names & own_src_names):
                raise StorageError(
                    f"revive found memory collections but none belongs to this bundle's prefix "
                    f"{src_prefix!r}: {sorted(non_empty_names)}"
                )

            # Mark the current meta as interrupted before touching collections.
            await self._storage.write_meta(
                self.strength_key,
                {**self._strength_meta(), "import_pending": True},
            )
            self._import_pending = True
            self._write_health()

            total = 0
            trace_total = 0
            trace_names = {self.collection_name(k) for k in persisted_kinds}
            replaced_kinds: list[str] = []
            try:
                for src_name, target_name in mapping.items():
                    n = await self._storage.replace_collection(
                        target_name, persisted.get(src_name, [])
                    )
                    total += n
                    if target_name in trace_names:
                        trace_total += n
                    replaced_kinds.append(target_name)
            except Exception:
                if replaced_kinds:
                    log.error(
                        "episodic memory: replace_collection failed after replacing kinds: %s",
                        replaced_kinds,
                    )
                raise

            # Restore trace-strength state after persisted collections are replaced.
            if strength is not None:
                # The bundle's meta describes the replaced collections; writing it
                # without the flag ends the import.
                self._load_strength({**strength, "import_pending": False})
                await self._storage.write_meta(self.strength_key, self._strength_meta())
                self._write_health()
            else:
                meta = {
                    "log_gain": 0.0,
                    "sleeps": 0,
                    "total": float(trace_total),
                    "entity_time": 0.0,
                    "bytes": await self._storage.total_size(list(mapping.values())),
                    "import_pending": True,
                }
                await self._storage.write_meta(self.strength_key, meta)
                self._load_strength(meta)
                changed = 0
                for name in mapping.values():
                    changed += await self._storage.backfill_strength(
                        [name], log_base=0.0
                    )
                if changed:
                    log.info(
                        "episodic memory: gave %d traces from before trace strengths a strength of 1",
                        changed,
                    )
                self._blocked_sleeps = 0
                self._persist_refusals = 0
                self._import_pending = False
                await self._storage.write_meta(self.strength_key, self._strength_meta())
                self._write_health()

            # Rebuild short-term only after persisted replaces succeed.
            self._short_term.clear()
            self._short_term_embeddings.clear()
            # A restored store must not keep a batch whose ids point at replaced points.
            self._last_consolidated = []
            for entry in state.get("short_term") or []:
                affect = entry.get("affect")
                self._short_term.append(
                    StoredMemory(
                        text=str(entry.get("text", "")),
                        payload=dict(entry.get("payload") or {}),
                        affect=dict(affect) if affect else None,
                        timestamp=float(entry.get("timestamp", 0.0)),
                        entity_time=float(entry.get("entity_time", 0.0)),
                    )
                )
                self._short_term_embeddings.append(None)

            self._pending_prune = None
            await self._load_associations()

            for name, points in persisted.items():
                if name not in mapping:
                    log.info(
                        "episodic memory: revive skips collection %s (%d points): not this bundle's own memory",
                        name,
                        len(points),
                    )

            await self._storage.write_stamp(self.stamp_key, self._embedder.space)
            await self._resume_entity_time()
            return total

    async def _invoke_hook(self, summary: RecallSummary) -> None:
        try:
            await self._hook(summary)
        except Exception:
            log.warning("emotional retrigger hook raised", exc_info=True)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        # Both vectors come from the same embedding space; a length mismatch
        # is a bug, never something to score by truncation.
        raise ValueError(f"cannot compare embeddings of length {len(a)} and {len(b)}")
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _summarize(results: Iterable[RecalledMemory], collection: str) -> RecallSummary:
    affects: list[dict[str, Any]] = []
    max_intensity = 0.0
    count = 0
    for r in results:
        count += 1
        if r.affect:
            affects.append(dict(r.affect))
            try:
                intensity = float(r.affect.get("intensity", 0.0))
            except (TypeError, ValueError):
                intensity = 0.0
            if intensity > max_intensity:
                max_intensity = intensity
    return RecallSummary(
        count=count,
        collection=collection,
        max_affect_intensity=max_intensity,
        affects=tuple(affects),
    )


def _log_base(payload: Any) -> float | None:
    """Return a finite numeric log_base, or None if absent or invalid."""
    if isinstance(payload, dict):
        value = payload.get("log_base")
        if isinstance(value, bool):
            return None
        if isinstance(value, (int, float)) and math.isfinite(value):
            return float(value)
    return None


def _entity_time(payload: Any) -> float:
    """Return a numeric finite entity_time, or 0.0 if absent or invalid."""
    if isinstance(payload, dict):
        value = payload.get("entity_time")
        if isinstance(value, bool):
            return 0.0
        if isinstance(value, (int, float)) and math.isfinite(value):
            return float(value)
    return 0.0


def _validate_strength(meta: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize the trace-strength meta record."""
    if not isinstance(meta, dict):
        raise StorageError(f"episodic memory: trace-strength record is malformed: {meta!r}")

    def _num(key: str) -> float:
        value = meta.get(key)
        if isinstance(value, bool):
            raise StorageError(f"episodic memory: trace-strength record is malformed: {meta!r}")
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise StorageError(f"episodic memory: trace-strength record is malformed: {meta!r}")
        return float(value)

    def _nonneg_int(key: str) -> int:
        value = meta.get(key, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise StorageError(f"episodic memory: trace-strength record is malformed: {meta!r}")
        return value

    sleeps = meta.get("sleeps")
    if isinstance(sleeps, bool) or not isinstance(sleeps, int) or sleeps < 0:
        raise StorageError(f"episodic memory: trace-strength record is malformed: {meta!r}")
    log_gain = _num("log_gain")
    total = _num("total")
    entity_time = _num("entity_time")
    bytes_value = meta.get("bytes")
    if isinstance(bytes_value, bool) or not isinstance(bytes_value, int) or bytes_value < 0:
        raise StorageError(f"episodic memory: trace-strength record is malformed: {meta!r}")
    if total < 0:
        raise StorageError(f"episodic memory: trace-strength record is malformed: {meta!r}")
    import_pending = meta.get("import_pending", False)
    if not isinstance(import_pending, bool):
        raise StorageError(f"episodic memory: trace-strength record is malformed: {meta!r}")
    blocked_sleeps = _nonneg_int("blocked_sleeps")
    persist_refusals = _nonneg_int("persist_refusals")
    return {
        "log_gain": log_gain,
        "sleeps": int(sleeps),
        "total": total,
        "bytes": int(bytes_value),
        "entity_time": entity_time,
        "import_pending": import_pending,
        "blocked_sleeps": blocked_sleeps,
        "persist_refusals": persist_refusals,
    }


async def recover_interrupted_import(
    storage: MemoryStorage,
    *,
    collection_prefix: str = "episodic_memory_",
    budget_bytes: int | None = None,
    health_path: Path | None = None,
) -> dict[str, Any]:
    """Operator recovery for an interrupted episodic memory module preservation import.

    Re-scans the persisted store and clears the import_pending flag so
    ordinary sleeps can resume. The store is kept as it stands; imported
    trace strengths remain relative to the pre-import log gain.
    """
    await storage.initialize()
    key = strength_key(collection_prefix)
    meta = await storage.read_meta(key)
    if meta is None or not _validate_strength(meta).get("import_pending"):
        return {"cleared": False}

    names = [f"{collection_prefix}{kind}" for kind in ("episodic", "semantic", "procedural")]
    assoc_names = [f"{collection_prefix}{kind}" for kind in EPISODIC_MEMORY_ASSOCIATION_KINDS]
    scan = await storage.scan_store(names)
    assoc_scan = await storage.scan_store(assoc_names)
    log_gain = float(meta.get("log_gain", 0.0))
    total = 0.0
    for lb, count in scan.get("log_base_counts", {}).items():
        total += count * _strength(float(lb), log_gain)
    total += scan.get("unstrengthed", 0)

    new_meta = {
        **meta,
        "bytes": scan["bytes"] + assoc_scan["bytes"],
        "total": total,
        "import_pending": False,
    }
    new_meta.pop("blocked_sleeps", None)
    new_meta.pop("persist_refusals", None)
    await storage.write_meta(key, new_meta)

    if health_path is not None:
        _write_health_file(
            health_path,
            {
                "import_pending": False,
                "blocked_sleeps": 0,
                "persist_refusals": 0,
                "store_bytes": scan["bytes"] + assoc_scan["bytes"],
                "budget_bytes": budget_bytes or 0,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )

    log.warning(
        "episodic memory: operator cleared an interrupted import; the store is kept as it stands. "
        "Imported traces' strengths are relative to the pre-import log gain."
    )
    return {"cleared": True, "store_bytes": scan["bytes"] + assoc_scan["bytes"], "total": total}
