# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""MnemosCore — orchestrates embedder + storage + short-term buffer.

This is the thing the Mnemos `BaseModule` wraps. It also exists
independently so callers (tests, Hypnos, future Lingua introspection)
can drive memory operations without spinning up a bus.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Iterable, Optional

from kaine.memory_kinds import MNEMOS_COLLECTION_KINDS
from kaine.modules.mnemos.embeddings import Embedder
from kaine.modules.mnemos.storage import MemoryStorage, RecalledMemory

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
        self._hook = retrigger_hook or _noop_hook
        self._clock = clock

    def collection_name(self, kind: str) -> str:
        if kind not in DEFAULT_COLLECTIONS:
            raise ValueError(f"unknown collection kind {kind!r}")
        return f"{self._prefix}{kind}"

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

    async def initialize(self) -> None:
        await self._embedder.load()
        await self._storage.initialize()
        # Persisted collections only. Short-term lives in process.
        for kind in ("episodic", "semantic", "procedural"):
            await self._storage.ensure_collection(self.collection_name(kind))

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
            if len(self._short_term) >= self._short_term_capacity:
                evicted = self._short_term.popleft()
                await self._persist(evicted, "episodic")
            self._short_term.append(memory)
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
            return self._recall_short_term(query_text, k)
        vec = await self._embedder.encode(query_text)
        coll_name = self.collection_name(collection)
        results = await self._storage.search(coll_name, query_vector=vec, limit=k)
        summary = _summarize(results, collection)
        await self._invoke_hook(summary)
        return results, summary

    def _recall_short_term(self, query_text: str, k: int) -> tuple[list[RecalledMemory], RecallSummary]:
        # Short-term recall is linear and uses a cheap substring score so
        # tests don't need an embedder roundtrip per query.
        q = query_text.lower()
        scored: list[tuple[float, StoredMemory, int]] = []
        for idx, m in enumerate(self._short_term):
            base = 1.0 if q in m.text.lower() else 0.0
            scored.append((base, m, idx))
        scored.sort(key=lambda t: (t[0], t[2]), reverse=True)
        results: list[RecalledMemory] = []
        for score, m, idx in scored[: max(0, int(k))]:
            results.append(
                RecalledMemory(
                    point_id=f"short_term:{idx}",
                    score=score,
                    text=m.text,
                    payload=dict(m.payload),
                    affect=dict(m.affect) if m.affect else None,
                )
            )
        summary = _summarize(results, "short_term")
        # No hook for short-term — those are fast/working memory, not the
        # episodic re-experience semantics.
        return results, summary

    async def consolidate_now(self) -> int:
        """Flush every short-term entry into episodic. Returns count moved."""
        moved = 0
        while self._short_term:
            entry = self._short_term.popleft()
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
        persisted = await self._storage.export()
        return {
            "collection_prefix": self._prefix,
            "short_term": short_term,
            "persisted": persisted,
        }

    async def import_state(self, state: dict[str, Any]) -> int:
        """Restore a store captured by :meth:`export_state`. Returns total points.

        Rebuilds the short-term deque and re-imports persisted collections.
        FAILS LOUDLY (propagates StorageError) when the backend cannot
        re-import — revive must not yield a memory-poor lesser individual.
        """
        self._short_term.clear()
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
        return await self._storage.import_(state.get("persisted") or {})

    async def _invoke_hook(self, summary: RecallSummary) -> None:
        try:
            await self._hook(summary)
        except Exception:
            log.warning("emotional retrigger hook raised", exc_info=True)


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
