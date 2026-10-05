# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""MnemosCore — orchestrates embedder + storage + short-term buffer.

This is the thing the Mnemos `BaseModule` wraps. It also exists
independently so callers (tests, Hypnos, future Lingua introspection)
can drive memory operations without spinning up a bus.
"""
from __future__ import annotations

import logging
import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Optional

from kaine.embedding_defaults import LEGACY_EMBEDDING_SPACE
from kaine.memory_kinds import MNEMOS_COLLECTION_KINDS, stamp_key
from kaine.modules.mnemos.embeddings import Embedder
from kaine.modules.mnemos.storage import MemoryStorage, RecalledMemory, StorageError
from kaine.text_embedding import same_space

log = logging.getLogger(__name__)


# Canonical memory-collection kinds. Sourced from the boundary-neutral
# kaine.memory_kinds so kaine.lifecycle.decommission (which must not import
# kaine.modules) can share the single source of truth.
DEFAULT_COLLECTIONS: tuple[str, str, str, str] = MNEMOS_COLLECTION_KINDS


@dataclass(frozen=True)
class StoredMemory:
    text: str
    payload: dict[str, Any]
    affect: dict[str, Any] | None
    timestamp: float


@dataclass(frozen=True)
class RecallSummary:
    count: int
    collection: str
    max_affect_intensity: float
    affects: tuple[dict[str, Any], ...] = field(default_factory=tuple)


EmotionalRetriggerHook = Callable[[RecallSummary], Awaitable[None]]


async def _noop_hook(_: RecallSummary) -> None:
    return


class MnemosCore:
    def __init__(
        self,
        embedder: Embedder,
        storage: MemoryStorage,
        *,
        collection_prefix: str = "mnemos_",
        short_term_capacity: int = 128,
        retrigger_hook: EmotionalRetriggerHook | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        if short_term_capacity <= 0:
            raise ValueError("short_term_capacity must be positive")
        self._embedder = embedder
        self._storage = storage
        self._prefix = collection_prefix
        self._short_term_capacity = int(short_term_capacity)
        self._short_term: deque[StoredMemory] = deque()
        self._short_term_embeddings: deque[tuple[dict[str, Any], list[float]] | None] = deque()
        self._hook = retrigger_hook or _noop_hook
        self._clock = clock

    def collection_name(self, kind: str) -> str:
        if kind not in DEFAULT_COLLECTIONS:
            raise ValueError(f"unknown collection kind {kind!r}")
        return f"{self._prefix}{kind}"

    def persisted_collection_names(self) -> list[str]:
        return [self.collection_name(k) for k in DEFAULT_COLLECTIONS if k != "short_term"]

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

    async def initialize(self) -> None:
        await self._embedder.load()
        await self._storage.initialize()
        # Persisted collections only. Short-term lives in process.
        for kind in ("episodic", "semantic", "procedural"):
            await self._storage.ensure_collection(self.collection_name(kind))
        await self._check_embedding_space_stamp()

    async def _check_embedding_space_stamp(self) -> None:
        space = self._embedder.space
        stamp = await self._storage.read_stamp(self.stamp_key)
        own_collections = self.persisted_collection_names()

        if stamp is not None:
            if same_space(stamp, space):
                return
            # The stamp is stale. If the being's own persisted collections are
            # empty there is nothing to mix, so replace the stamp.
            total = 0
            for name in own_collections:
                total += await self._storage.count(name, strict=True)
            if total == 0:
                await self._storage.write_stamp(self.stamp_key, space)
                log.warning(
                    "mnemos: memory store is empty; its stale embedding-space stamp %s is replaced with %s",
                    stamp,
                    space,
                )
                return
            raise StorageError(
                f"mnemos: the memory store is stamped with embedding space {stamp} "
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
                    f"mnemos: memory store collection {name!r} has vector "
                    f"dimension {dim} but the legacy KAINE space requires "
                    f"{LEGACY_EMBEDDING_SPACE['dim']}; its memories must be "
                    f"re-embedded before this embedder can use them"
                )

        if same_space(space, LEGACY_EMBEDDING_SPACE):
            await self._storage.write_stamp(self.stamp_key, LEGACY_EMBEDDING_SPACE)
            log.warning(
                "mnemos: memory store predates embedding-space stamps; stamped as %s",
                LEGACY_EMBEDDING_SPACE,
            )
        else:
            raise StorageError(
                f"mnemos: the memory store is stamped with embedding space {LEGACY_EMBEDDING_SPACE} "
                f"but the embedder is {space}; its memories must be re-embedded "
                f"before this embedder can use them"
            )

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
        payload.setdefault("timestamp", ts)
        memory = StoredMemory(text=text, payload=payload, affect=affect, timestamp=ts)
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

    async def _persist(self, memory: StoredMemory, collection: str) -> str:
        vec = await self._embedder.encode(memory.text)
        coll_name = self.collection_name(collection)
        return await self._storage.upsert(
            coll_name,
            vector=vec,
            text=memory.text,
            payload=memory.payload,
            affect=memory.affect,
        )

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
        results = await self._storage.search(coll_name, query_vector=vec, limit=k)
        summary = _summarize(results, collection)
        await self._invoke_hook(summary)
        return results, summary

    async def _recall_short_term(
        self, query_text: str, k: int
    ) -> tuple[list[RecalledMemory], RecallSummary]:
        """Recall from the short-term buffer using cosine similarity.

        The query is embedded once. Each short-term entry is embedded at most
        once in its lifetime; the embedding is held in memory only and is never
        exported. Equal cosine scores rank the more recent entry first.
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
            results.append(
                RecalledMemory(
                    point_id=f"short_term:{idx}",
                    score=float(score),
                    text=memory.text,
                    payload=dict(memory.payload),
                    affect=dict(memory.affect) if memory.affect else None,
                )
            )
        summary = _summarize(results, "short_term")
        # No hook for short-term — those are fast/working memory, not the
        # episodic re-experience semantics.
        return results, summary

    def _rebuild_embeddings_if_desynced(self) -> None:
        if len(self._short_term_embeddings) != len(self._short_term):
            log.warning(
                "mnemos: short_term_embeddings length (%d) differs from short_term length (%d); resetting embeddings cache",
                len(self._short_term_embeddings),
                len(self._short_term),
            )
            self._short_term_embeddings = deque([None] * len(self._short_term))

    async def consolidate_now(self) -> int:
        """Flush every short-term entry into episodic. Returns count moved."""
        self._rebuild_embeddings_if_desynced()
        moved = 0
        while self._short_term:
            entry = self._short_term.popleft()
            self._short_term_embeddings.popleft()
            await self._persist(entry, "episodic")
            moved += 1
        return moved

    # ------------------------------------------------------------------
    # Full-fidelity capture / restore (preservation + revive)
    # ------------------------------------------------------------------

    async def export_state(self) -> dict[str, Any]:
        """Capture the whole memory store: short-term buffer + persisted points.

        Used by Mnemos preservation. The persisted side delegates to the
        storage backend's ``export`` (which FAILS LOUDLY on an unreachable
        Qdrant). The short-term buffer is in-process working memory; it is
        captured here as ``StoredMemory`` fields so a revived entity resumes
        with the same working set.
        """
        short_term = [
            {
                "text": m.text,
                "payload": dict(m.payload),
                "affect": dict(m.affect) if m.affect else None,
                "timestamp": m.timestamp,
            }
            for m in self._short_term
        ]
        persisted = await self._storage.export(self.persisted_collection_names())
        return {
            "collection_prefix": self._prefix,
            "short_term": short_term,
            "persisted": persisted,
            "embedding_space": self._embedder.space,
        }

    async def import_state(self, state: dict[str, Any]) -> int:
        """Restore a store captured by :meth:`export_state`. Returns total points.

        Re-imports persisted collections under this core's own prefix, then
        rebuilds the short-term deque. FAILS LOUDLY (propagates StorageError)
        when the backend cannot re-import — revive must not yield a
        memory-poor lesser individual.
        """
        bundle_space = state.get("embedding_space") or LEGACY_EMBEDDING_SPACE
        if not same_space(bundle_space, self._embedder.space):
            raise StorageError(
                f"mnemos: bundle embedding space {bundle_space} does not match "
                f"running embedder space {self._embedder.space}; cannot revive"
            )

        src_prefix = (
            state["collection_prefix"] if "collection_prefix" in state else "mnemos_"
        )
        persisted = state.get("persisted") or {}
        persisted_kinds = [k for k in DEFAULT_COLLECTIONS if k != "short_term"]
        mapping: dict[str, str] = {}
        for kind in persisted_kinds:
            src_name = f"{src_prefix}{kind}"
            mapping[src_name] = self.collection_name(kind)

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

        total = 0
        replaced_kinds: list[str] = []
        try:
            for src_name, target_name in mapping.items():
                n = await self._storage.replace_collection(
                    target_name, persisted.get(src_name, [])
                )
                total += n
                replaced_kinds.append(target_name)
        except Exception:
            if replaced_kinds:
                log.error(
                    "mnemos: replace_collection failed after replacing kinds: %s",
                    replaced_kinds,
                )
            raise

        # Rebuild short-term only after persisted replaces succeed.
        self._short_term.clear()
        self._short_term_embeddings.clear()
        for entry in state.get("short_term") or []:
            affect = entry.get("affect")
            self._short_term.append(
                StoredMemory(
                    text=str(entry.get("text", "")),
                    payload=dict(entry.get("payload") or {}),
                    affect=dict(affect) if affect else None,
                    timestamp=float(entry.get("timestamp", 0.0)),
                )
            )
            self._short_term_embeddings.append(None)

        for name, points in persisted.items():
            if name not in mapping:
                log.info(
                    "mnemos: revive skips collection %s (%d points): not this bundle's own memory",
                    name,
                    len(points),
                )

        await self._storage.write_stamp(self.stamp_key, self._embedder.space)
        return total

    async def _invoke_hook(self, summary: RecallSummary) -> None:
        try:
            await self._hook(summary)
        except Exception:
            log.warning("emotional retrigger hook raised", exc_info=True)


def _cosine_similarity(a: list[float], b: list[float]) -> float:
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
