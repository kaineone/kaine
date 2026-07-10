# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar, Optional

from kaine.bus.client import AsyncBus
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule
from kaine.text_embedding import (
    DEFAULT_LATENT_DIM,
    Embedder,
    SentenceTransformerTextEmbedder,
)
from kaine.modules.mnemos.memory import (
    EmotionalRetriggerHook,
    MnemosCore,
)
from kaine.modules.mnemos.replay import ReplayEngine, ReplayEntry, ReplayEvent
from kaine.modules.mnemos.storage import (
    InMemoryStorage,
    MemoryStorage,
    QdrantStorage,
    RecalledMemory,
    SqliteVecStorage,
    StorageError,
)

log = logging.getLogger(__name__)


class Mnemos(BaseModule):
    name: ClassVar[str] = "mnemos"

    def holds_external_resources(self) -> bool:
        return True

    def __init__(
        self,
        bus: AsyncBus,
        *,
        core: Optional[MnemosCore] = None,
        embedder: Optional[Embedder] = None,
        storage: Optional[MemoryStorage] = None,
        backend: str = "qdrant",
        qdrant_host: str = "127.0.0.1",
        qdrant_port: int = 6533,
        qdrant_api_key: Optional[str] = None,
        collection_prefix: str = "mnemos_",
        short_term_capacity: int = 128,
        recall_top_k: int = 5,
        baseline_salience: float = 0.15,
        alert_salience: float = 0.6,
        retrigger_hook: EmotionalRetriggerHook | None = None,
        embedder_model_id: Optional[str] = None,
        embedder_device_preference: Optional[str] = None,
        recall_on_workspace: bool = True,
        recall_cooldown_s: float = 5.0,
        # Replay config
        replay_selection_top_k: int = 5,
        replay_affect_weight: float = 0.7,
        replay_recency_weight: float = 0.3,
        replay_redact_content: bool = True,
        # Peer stream names for affect + Hypnos window tracking
        thymos_stream: str = "thymos.out",
        hypnos_stream: str = "hypnos.out",
        # Shared subjective clock (injected at boot). The spontaneous-recall
        # cooldown is a cognitive throttle, so it runs in subjective time: at
        # time_scale != 1.0 the recall_cooldown_s window dilates with the rest
        # of the mind. Defaults to a real-time clock → behavior-identical.
        entity_clock: Optional[EntityClock] = None,
    ) -> None:
        super().__init__(bus)
        if not 0.0 <= baseline_salience <= 1.0:
            raise ValueError("baseline_salience must be in [0, 1]")
        if not 0.0 <= alert_salience <= 1.0:
            raise ValueError("alert_salience must be in [0, 1]")
        if recall_top_k <= 0:
            raise ValueError("recall_top_k must be positive")
        if recall_cooldown_s < 0:
            raise ValueError("recall_cooldown_s must be >= 0")
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        self._recall_top_k = int(recall_top_k)
        self._recall_on_workspace = bool(recall_on_workspace)
        self._recall_cooldown_s = float(recall_cooldown_s)
        self._clock = entity_clock or EntityClock()
        # Subjective-time timestamp of the last spontaneous recall; None until
        # the first recall fires so the very first cued tick is not suppressed.
        self._last_recall_monotonic: float | None = None

        # Affect state cache — updated whenever thymos.state arrives.
        # Stored as plain numerics (intensity + VAD) — no raw sense data.
        self._cached_affect: dict[str, Any] | None = None

        # Replay engine — selection and guard logic.
        self._replay_engine = ReplayEngine(
            selection_top_k=replay_selection_top_k,
            affect_weight=replay_affect_weight,
            recency_weight=replay_recency_weight,
            redact_content=replay_redact_content,
        )

        # Peer bus streams to subscribe to for affect and Hypnos window events.
        self._thymos_stream = thymos_stream
        self._hypnos_stream = hypnos_stream
        self._peer_cursors: dict[str, str] = {}

        if core is not None:
            self._core = core
        else:
            if embedder is None:
                kw = {}
                if embedder_model_id:
                    kw["model_id"] = embedder_model_id
                if embedder_device_preference is not None:
                    kw["device_preference"] = embedder_device_preference
                embedder = SentenceTransformerTextEmbedder(**kw)
            # Embedder's latent_dim may not be known until `await embedder.load()`
            # has happened. We pick a default for construction-time storage
            # sizing; the actual dimension is reconciled at initialize() time.
            try:
                _ld = embedder.latent_dim
                resolved_latent_dim = int(_ld) if isinstance(_ld, int) else DEFAULT_LATENT_DIM
            except (RuntimeError, AttributeError):
                resolved_latent_dim = DEFAULT_LATENT_DIM
            if storage is None:
                if backend == "qdrant":
                    if not qdrant_api_key:
                        raise ValueError(
                            "Mnemos backend=qdrant requires qdrant_api_key — "
                            "set [qdrant].api_key in config/secrets.toml"
                        )
                    storage = QdrantStorage(
                        latent_dim=resolved_latent_dim,
                        host=qdrant_host,
                        port=qdrant_port,
                        api_key=qdrant_api_key,
                    )
                elif backend == "inmemory":
                    storage = InMemoryStorage(latent_dim=resolved_latent_dim)
                elif backend in ("sqlite_vec", "sqlite-vec"):
                    # In-process edge vector store (Tier 0/1). sqlite_vec is
                    # imported lazily inside initialize(), so selecting it does
                    # not pull the dependency into a Tier-2 install (openspec
                    # runtime-backends).
                    storage = SqliteVecStorage(latent_dim=resolved_latent_dim)
                else:
                    raise ValueError(f"unknown backend {backend!r}")
            self._core = MnemosCore(
                embedder=embedder,
                storage=storage,
                collection_prefix=collection_prefix,
                short_term_capacity=short_term_capacity,
                retrigger_hook=retrigger_hook,
            )

    @property
    def core(self) -> MnemosCore:
        return self._core

    async def initialize(self) -> None:
        await self._core.initialize()
        # Seed cursors for peer streams so we only process new events from here.
        for stream in (self._thymos_stream, self._hypnos_stream):
            try:
                latest = await self._bus.client.xrevrange(stream, count=1)
            except Exception:
                latest = []
            if latest:
                entry_id = latest[0][0]
                if isinstance(entry_id, bytes):
                    entry_id = entry_id.decode()
                self._peer_cursors[stream] = entry_id
            else:
                self._peer_cursors[stream] = "0-0"
        await super().initialize()
        self._tasks.append(
            asyncio.create_task(
                self._peer_consumer_loop(), name=f"{self.name}-affect-consumer"
            )
        )

    async def shutdown(self) -> None:
        await super().shutdown()
        try:
            await self._core.shutdown()
        except Exception:
            log.warning("mnemos core shutdown failed", exc_info=True)

    async def on_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        text = _serialize_snapshot(snapshot)
        if not text:
            return
        # Spontaneous cue-based recall in the live loop. The cue is the snapshot
        # serialization (the same text we are about to store). Recall runs
        # BEFORE the store so the cue retrieves PRIOR related memories, not the
        # identical snapshot we store this tick. It is throttled by a monotonic
        # cooldown and is NOT gated on snapshot.inhibited — recall is internal
        # cognition (like storing), not an outward effector action.
        if self._recall_on_workspace and self._recall_cooldown_due():
            await self.recall(text)
            self._last_recall_monotonic = self._clock.now()
        payload = {
            "tick_index": snapshot.tick_index,
            "inhibited": snapshot.inhibited,
            "selected_count": len(snapshot.selected_events),
        }
        # Tag the stored trace with the current cached affect (intensity + VAD
        # as plain numerics — no raw sense data, per zero-persistence invariant).
        await self._core.store(
            text,
            payload=payload,
            affect=self._cached_affect,
            collection="short_term",
        )

    def _recall_cooldown_due(self) -> bool:
        if self._last_recall_monotonic is None:
            return True
        return (
            self._clock.now() - self._last_recall_monotonic
            >= self._recall_cooldown_s
        )

    # ------------------------------------------------------------------
    # Affect subscription (thymos.state) + Hypnos window tracking
    # ------------------------------------------------------------------

    async def _peer_consumer_loop(self) -> None:
        """Background loop: read thymos.out and hypnos.out for affect + window."""
        try:
            while not self._stopped.is_set():
                progressed = False
                for stream in (self._thymos_stream, self._hypnos_stream):
                    try:
                        entries = await self._bus.read(
                            stream,
                            last_id=self._peer_cursors.get(stream, "0"),
                            count=32,
                            block_ms=0,
                        )
                    except Exception:
                        continue
                    if entries:
                        progressed = True
                        self._peer_cursors[stream] = entries[-1][0]
                        for _, event in entries:
                            self._handle_peer_event(stream, event)
                if not progressed:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    def _handle_peer_event(self, stream: str, event: Event) -> None:
        if stream == self._thymos_stream and event.type == "thymos.state":
            state_dict = event.payload.get("state") or {}
            try:
                # Cache affect as plain numerics only (VAD + derived intensity).
                # Intensity is approximated as arousal (0–1); valence and
                # dominance are stored as-is in the [-1, 1] range.
                arousal = float(state_dict.get("arousal", 0.0))
                valence = float(state_dict.get("valence", 0.0))
                dominance = float(state_dict.get("dominance", 0.0))
                self._cached_affect = {
                    "intensity": arousal,
                    "valence": valence,
                    "dominance": dominance,
                }
            except Exception:
                log.warning("mnemos: failed to parse thymos.state payload", exc_info=True)
        elif stream == self._hypnos_stream:
            if event.type == "hypnos.sleep.started":
                self._replay_engine.open_window()
                log.debug("mnemos: Hypnos maintenance window opened")
            elif event.type == "hypnos.sleep.completed":
                self._replay_engine.close_window()
                log.debug("mnemos: Hypnos maintenance window closed")

    @property
    def cached_affect(self) -> dict[str, Any] | None:
        """Current cached affect state (intensity + VAD), or None before first thymos.state."""
        return self._cached_affect

    @property
    def replay_engine(self) -> ReplayEngine:
        """The replay engine (for tests and Hypnos orchestration)."""
        return self._replay_engine

    async def replay_now(self) -> list[ReplayEvent]:
        """Run the replay selection during the active Hypnos maintenance window.

        Selects traces from the short-term buffer and recently persisted
        episodic memories, publishes them as ``mnemos.replay`` events, and
        returns the list of published events.

        Raises `ReplayWindowError` if called outside an active Hypnos window.
        """
        # Build candidates from the short-term buffer (these have timestamps
        # and affect tags stored on StoredMemory objects).
        candidates: list[ReplayEntry] = []
        for idx, memory in enumerate(self._core._short_term):
            affect = memory.affect or {}
            try:
                intensity = float(affect.get("intensity", 0.0))
            except (TypeError, ValueError):
                intensity = 0.0
            candidates.append(
                ReplayEntry(
                    point_id=f"short_term:{idx}",
                    text=memory.text,
                    affect_intensity=intensity,
                    timestamp=memory.timestamp,
                    payload=dict(memory.payload),
                    affect=dict(affect) if affect else None,
                )
            )

        # Delegate selection + guard to the engine.  ReplayWindowError propagates.
        events = self._replay_engine.replay(candidates)

        # Publish each selected trace as a mnemos.replay event on the bus.
        for rev in events:
            await self.publish(
                "mnemos.replay",
                rev.loop_payload,
                salience=self._baseline_salience,
            )
        return events

    async def recall(
        self,
        query_text: str,
        *,
        k: int | None = None,
        collection: str = "episodic",
    ) -> list[RecalledMemory]:
        try:
            results, summary = await self._core.recall(
                query_text, k=k or self._recall_top_k, collection=collection
            )
        except StorageError as exc:
            log.error(
                "mnemos recall failed (storage error) — not publishing fake empty result: %s",
                exc,
            )
            await self.publish(
                "mnemos.recall",
                {
                    "count": 0,
                    "collection": collection,
                    "query_length": len(query_text),
                    "max_affect_intensity": 0.0,
                    "error": True,
                    "error_detail": str(exc),
                },
                salience=self._baseline_salience,
            )
            return []
        salience = (
            self._alert_salience
            if summary.max_affect_intensity >= 0.5
            else self._baseline_salience
        )
        await self.publish(
            "mnemos.recall",
            {
                "count": summary.count,
                "collection": summary.collection,
                "query_length": len(query_text),
                "max_affect_intensity": summary.max_affect_intensity,
            },
            salience=salience,
        )
        return results

    async def consolidate_now(self) -> int:
        return await self._core.consolidate_now()

    def downscale_activations(self, factor: float) -> int:
        """Scale all in-memory activation vectors by *factor* (Tononi & Cirelli 2014).

        Applies synaptic homeostasis: reduces absolute activation magnitudes
        while preserving relative ordering (cosine similarity is unchanged;
        only L2 norms shrink).  Called by Hypnos phase 2 (deep-consolidation)
        during the offline maintenance window.

        Works on the InMemoryStorage backend; gracefully skips collections
        on any backend that does not expose a mutable ``_collections`` dict.

        Args:
            factor: Multiplicative scaling factor in (0, 1].  Values >= 1.0
                    are a no-op; values <= 0 raise ValueError.

        Returns:
            Total number of vectors rescaled across all collections.
        """
        if factor <= 0.0:
            raise ValueError("downscale_activations factor must be > 0")
        factor = float(factor)
        if factor >= 1.0:
            return 0
        storage = self._core._storage
        collections = getattr(storage, "_collections", None)
        if collections is None:
            # QdrantStorage or other remote backend — no in-memory vectors
            # to scale; downscaling is a no-op for remote backends.
            log.debug(
                "downscale_activations: storage has no in-memory _collections; skipped"
            )
            return 0
        total = 0
        for _name, points in collections.items():
            for point in points:
                vec = point.get("vector")
                if isinstance(vec, list) and vec:
                    point["vector"] = [v * factor for v in vec]
                    total += 1
        log.info(
            "downscale_activations: scaled %d vectors by factor %.4f", total, factor
        )
        return total

    async def select_cross_period_traces(
        self,
        *,
        periods: int = 2,
        per_period: int = 3,
    ) -> dict[str, list[dict[str, Any]]]:
        """Select traces spanning *periods* contiguous time windows.

        "Memory period" is defined as a contiguous time bucket: all available
        traces (short-term buffer + persisted episodic points) are sorted by
        timestamp, then divided into *periods* equal-width windows
        (oldest → newest).  Up to *per_period* traces are sampled from each
        non-empty bucket.

        Returns a mapping ``{period_label: [trace_dict, ...]}`` where each
        trace dict carries ``point_id`` (str) and ``text`` (str) — the shape
        phase 3's ``_trace_id`` and scenario-cue helpers already consume.
        Affect fields (intensity/valence/dominance) are included as plain
        numerics when present; no raw sense-data is carried through.

        When there are fewer traces than *periods* the available traces are
        distributed across as many buckets as possible — phase 3 handles the
        degenerate case (< 2 populated periods) cleanly.

        Args:
            periods:    Number of contiguous time windows to bucket traces into.
            per_period: Maximum number of traces sampled from each bucket.
        """
        periods = max(1, int(periods))
        per_period = max(1, int(per_period))

        # ---- Collect all candidates (numeric/affect only; no raw sense data) ----
        all_traces: list[dict[str, Any]] = []

        # Short-term buffer — in-process, already parsed StoredMemory objects.
        for idx, memory in enumerate(self._core._short_term):
            affect = dict(memory.affect) if memory.affect else {}
            all_traces.append(
                {
                    "point_id": f"short_term:{idx}",
                    "text": memory.text,
                    "timestamp": memory.timestamp,
                    "affect_intensity": float(affect.get("intensity", 0.0)),
                    "valence": float(affect.get("valence", 0.0)),
                    "dominance": float(affect.get("dominance", 0.0)),
                }
            )

        # Episodic storage — use InMemoryStorage._collections directly when
        # available (same pattern as downscale_activations).  For remote
        # backends that don't expose _collections we skip (no in-process data
        # to bucket; phase 3 degrades gracefully).
        storage = self._core._storage
        collections = getattr(storage, "_collections", None)
        if collections is not None:
            episodic_key = self._core.collection_name("episodic")
            for point in collections.get(episodic_key, []):
                payload = dict(point.get("payload", {}))
                affect_raw = point.get("affect") or {}
                ts = float(payload.get("timestamp", 0.0))
                all_traces.append(
                    {
                        "point_id": str(point.get("id", "")),
                        "text": str(point.get("text", "")),
                        "timestamp": ts,
                        "affect_intensity": float(affect_raw.get("intensity", 0.0)),
                        "valence": float(affect_raw.get("valence", 0.0)),
                        "dominance": float(affect_raw.get("dominance", 0.0)),
                    }
                )

        if not all_traces:
            return {}

        # ---- Bucket by timestamp into *periods* contiguous windows ------------
        all_traces.sort(key=lambda t: t["timestamp"])
        ts_min = all_traces[0]["timestamp"]
        ts_max = all_traces[-1]["timestamp"]
        ts_span = ts_max - ts_min

        result: dict[str, list[dict[str, Any]]] = {}
        for i in range(periods):
            label = f"period_{i}"
            if ts_span == 0.0:
                # All traces share the same timestamp — put all in period_0.
                bucket = all_traces if i == 0 else []
            else:
                low = ts_min + (ts_span / periods) * i
                # Last bucket is inclusive of ts_max.
                high = ts_min + (ts_span / periods) * (i + 1)
                if i < periods - 1:
                    bucket = [t for t in all_traces if low <= t["timestamp"] < high]
                else:
                    bucket = [t for t in all_traces if low <= t["timestamp"] <= high]
            if bucket:
                result[label] = bucket[:per_period]

        return result

    def serialize(self) -> dict[str, Any]:
        """Synchronous metadata view (fork/merge snapshots, Nexus).

        The full memory contents are captured by the async
        :meth:`export_preservation_state` (used by preservation/revive); a
        plain synchronous ``serialize()`` cannot scroll a remote vector store
        without risking a deadlock inside a running event loop, so it stays
        metadata-only here and the preservation path carries the real memories.
        """
        return {
            "short_term_size": self._core.short_term_size,
            "collection_prefix": self._core._prefix,
        }

    def deserialize(self, state: dict[str, Any]) -> None:
        """Restore from a preservation capture when one is present.

        A metadata-only fork snapshot (``serialize()`` output) carries no
        ``memory_state`` and is a no-op here (short-term is in-process working
        memory for those). A preservation/revive capture carries
        ``memory_state`` (from :meth:`export_preservation_state`); when present
        it is restored synchronously for the in-process path.

        NOTE: the async :meth:`import_preservation_state` is the canonical
        restore used by revive (it drives the storage backend, which may be
        async/remote). ``deserialize`` only handles the synchronous in-memory
        case so a captured short-term buffer is never silently dropped on a
        plain restore; remote-backed memory must go through revive.
        """
        capture = state.get("memory_state")
        if not capture:
            return
        # Synchronous restore is only safe for the in-memory backend (no remote
        # I/O). For remote backends, revive's async import is required — refuse
        # rather than silently drop the captured memories.
        from kaine.modules.mnemos.storage import InMemoryStorage

        if not isinstance(self._core._storage, InMemoryStorage):
            raise RuntimeError(
                "Mnemos.deserialize received a memory capture but the backend is "
                "not InMemoryStorage; use the async revive path "
                "(import_preservation_state) which can drive the remote store — "
                "refusing to silently drop captured memories."
            )
        # Run synchronously without an event-loop dependency: InMemoryStorage's
        # import_ touches no I/O, so we drive the coroutine to completion.
        self._drive_sync(self._core.import_state(capture))

    @staticmethod
    def _drive_sync(coro: Any) -> Any:
        """Run a coroutine that performs no real I/O to completion, synchronously.

        InMemoryStorage.import_/export are pure in-process operations; this lets
        the synchronous ``deserialize`` restore a captured in-memory store
        without requiring a running event loop. It deliberately does NOT support
        coroutines that await real I/O.
        """
        try:
            coro.send(None)
        except StopIteration as stop:
            return stop.value
        raise RuntimeError(
            "Mnemos._drive_sync: coroutine awaited real I/O; use the async "
            "import_preservation_state path instead"
        )

    async def export_preservation_state(self) -> dict[str, Any]:
        """Async full-fidelity capture for preservation (memories included).

        FAILS LOUDLY if the store cannot be read (e.g. Qdrant unreachable) —
        preservation must not write a bundle that silently omits the memories.
        """
        return {
            "short_term_size": self._core.short_term_size,
            "collection_prefix": self._core._prefix,
            "memory_state": await self._core.export_state(),
        }

    async def import_preservation_state(self, state: dict[str, Any]) -> int:
        """Async restore used by revive; rebuilds the memory store. Fails loud."""
        capture = state.get("memory_state")
        if capture is None:
            raise RuntimeError(
                "Mnemos.import_preservation_state: capture has no memory_state — "
                "refusing to revive a memory-less lesser individual"
            )
        return await self._core.import_state(capture)


# Raw-perceptual event types whose verbatim payload must NEVER be persisted into
# memory text at the encoding site. Mnemos memory is legitimately persistent
# cognitive state, but a raw transcript / raw visual frame selected into the
# workspace is RAW sense data — covered by the project's zero-raw-sense-data
# persistence invariant. This denylist is defence-in-depth at the SOURCE,
# independent of any downstream redaction (replay observer etc.). The
# event's metadata (source/type/entry_id) is still recorded; only its payload
# is dropped.
_RAW_PERCEPTUAL_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "audition.transcription",
        "mundus.visual.raw",
    }
)


def _serialize_snapshot(snapshot: WorkspaceSnapshot) -> str:
    pieces: list[str] = []
    pieces.append(f"tick={snapshot.tick_index}")
    pieces.append("inhibited" if snapshot.inhibited else "active")
    for entry_id, event in snapshot.selected_events or []:
        if event.type in _RAW_PERCEPTUAL_EVENT_TYPES:
            # Record that a raw-perceptual event was in the workspace, but never
            # its verbatim payload (raw sense data must not persist into memory).
            pieces.append(
                f"{event.source}:{event.type}@{entry_id}=<raw-perceptual omitted>"
            )
            continue
        pieces.append(
            f"{event.source}:{event.type}@{entry_id}={event.payload}"
        )
    return " | ".join(pieces) if pieces else ""
