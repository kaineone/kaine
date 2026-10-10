# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Empatheia — social cognition / theory-of-mind module.

Consumes ``audition.emotion`` and ``audition.transcription`` events and
the workspace broadcast to build and maintain per-agent social models.
Publishes:

- ``empatheia.agent_model`` — familiarity, reliability, interaction_count
  (numeric metadata only — no raw sense data).
- ``empatheia.social_error`` — salience-only signal (agent id, salience,
  deviation magnitude only — never raw behavioral data or transcript text).

Agent identity v1: a single operator-set speaker label (default
``"operator"``). Speaker diarization is future work (paper §10).
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, ClassVar, Optional, Sequence

from kaine.bus.client import AsyncBus
from kaine.bus.schema import OPERATOR_SOURCES, Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.base import BaseModule
from kaine.modules.empatheia.agent import AgentModel
from kaine.modules.empatheia.store import AgentStore, InMemoryAgentStore, QdrantAgentStore
from kaine.text_embedding import Embedder

log = logging.getLogger(__name__)


class Empatheia(BaseModule):
    name: ClassVar[str] = "empatheia"
    relieves_drives: ClassVar[frozenset[str]] = frozenset({"social_drive"})
    preservation_state_key: ClassVar[str | None] = "profiles"

    def holds_external_resources(self) -> bool:
        return True

    def __init__(
        self,
        bus: AsyncBus,
        *,
        store: Optional[AgentStore] = None,
        embedder: Optional[Embedder] = None,
        backend: str = "inmemory",
        collection: str = "empatheia_agents",
        speaker_label: str = "operator",
        operator_sources: Sequence[str] = OPERATOR_SOURCES,
        deviation_threshold: float = 0.5,
        baseline_salience: float = 0.15,
        alert_salience: float = 0.6,
        # Qdrant connection (only used when backend="qdrant").
        qdrant_host: str = "127.0.0.1",
        qdrant_port: int = 6533,
        qdrant_api_key: Optional[str] = None,
    ) -> None:
        super().__init__(bus)
        if not 0.0 <= baseline_salience <= 1.0:
            raise ValueError("baseline_salience must be in [0, 1]")
        if not 0.0 <= alert_salience <= 1.0:
            raise ValueError("alert_salience must be in [0, 1]")
        if not 0.0 < deviation_threshold <= 1.0:
            raise ValueError("deviation_threshold must be in (0, 1]")

        self._speaker_label = speaker_label
        self._operator_sources = frozenset(operator_sources)
        self._deviation_threshold = float(deviation_threshold)
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)

        if store is not None:
            self._store = store
        elif backend == "inmemory":
            self._store: AgentStore = InMemoryAgentStore()
        elif backend == "qdrant":
            if not qdrant_api_key:
                raise ValueError(
                    "Empatheia backend=qdrant requires qdrant_api_key — "
                    "set [qdrant].api_key in config/secrets.toml"
                )
            from kaine.text_embedding import make_text_embedder

            if embedder is None:
                embedder = make_text_embedder({})
            self._store = QdrantAgentStore(
                host=qdrant_host,
                port=qdrant_port,
                api_key=qdrant_api_key,
                collection=collection,
                latent_dim=embedder.latent_dim,
                embedder=embedder,
            )
        else:
            raise ValueError(f"unknown backend {backend!r}")

        # Cursor for audition.out stream (emotion + transcription events).
        self._audition_cursor: str = "0-0"

    @property
    def store(self) -> AgentStore:
        return self._store

    async def initialize(self) -> None:
        # Load the embedder before opening the Qdrant store so a missing model
        # fails the module's start loudly instead of writing zero vectors.
        if isinstance(self._store, QdrantAgentStore) and self._store._embedder is not None:
            await self._store._embedder.load()
        await self._store.initialize()
        # Seed the audition cursor to "now" so we only process new events.
        try:
            latest = await self._bus.client.xrevrange("audition.out", count=1)
        except Exception:
            latest = []
        if latest:
            entry_id = latest[0][0]
            if isinstance(entry_id, bytes):
                entry_id = entry_id.decode()
            self._audition_cursor = entry_id
        else:
            self._audition_cursor = "0-0"
        await super().initialize()
        self._tasks.append(
            asyncio.create_task(
                self._audition_consumer_loop(),
                name="empatheia-audition-consumer",
            )
        )

    async def shutdown(self) -> None:
        await super().shutdown()
        try:
            await self._store.shutdown()
        except Exception:
            log.warning("empatheia store shutdown failed", exc_info=True)

    # ------------------------------------------------------------------
    # Workspace broadcast (optional: update on workspace context)
    # ------------------------------------------------------------------

    async def on_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        """React to workspace ticks — currently a no-op placeholder.

        Empatheia's actual work is event-driven, not tick-driven: it runs in
        `_audition_consumer_loop`, reacting to `audition.out` emotion and
        transcription events. This hook is reserved for future coalition-aware
        behaviour (e.g. speaker diarization cues) and intentionally does nothing.
        """
        return

    # ------------------------------------------------------------------
    # Audition event consumer
    # ------------------------------------------------------------------

    async def _audition_consumer_loop(self) -> None:
        """Background loop: read audition.out for emotion + transcription events."""
        try:
            while not self._stopped.is_set():
                try:
                    entries, last_scanned = await self._bus.read_entries(
                        "audition.out",
                        last_id=self._audition_cursor,
                        count=32,
                        block_ms=0,
                    )
                except Exception:
                    await asyncio.sleep(0.05)
                    continue
                if last_scanned is not None:
                    self._audition_cursor = last_scanned
                    for _, event in entries:
                        await self._handle_audition_event(event)
                else:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def _handle_audition_event(self, event: Event) -> None:
        """Dispatch incoming audition events to the right handler."""
        if event.type == "audition.emotion":
            await self._handle_emotion(event)
        elif event.type == "audition.transcription":
            await self._handle_transcription(event)

    def _agent_for(self, event: Event) -> str:
        """Map an audition event to the agent id it updates.

        Operator channels (or events with no channel) update the configured
        speaker label. Every other channel gets its own ``media:<channel>``
        agent so film voices cannot shape the operator model.
        """
        source_label = event.payload.get("source_label")
        if source_label is None or source_label in self._operator_sources:
            return self._speaker_label
        return f"media:{source_label}"

    async def _handle_emotion(self, event: Event) -> None:
        """Fold an emotion observation into the current agent model."""
        payload = event.payload
        # Skip fold when the emotion model didn't run (degraded flag surfaced
        # by Audition when funasr is unavailable). Folding placeholder neutral
        # observations would inflate interaction counts and familiarity scores.
        if payload.get("degraded"):
            return
        category = str(payload.get("category") or "neutral")
        confidence = float(payload.get("confidence") or 0.0)
        prediction_error = float(payload.get("prediction_error") or 0.0)

        agent_id = self._agent_for(event)
        model = await self._store.get(agent_id)
        if model is None:
            model = AgentModel(id=agent_id, label=agent_id)

        deviation = model.update_from_emotion(
            category,
            confidence,
            prediction_error,
            deviation_threshold=self._deviation_threshold,
        )

        await self._store.put(model)
        await self._publish_agent_model(
            model, source_label=event.payload.get("source_label")
        )

        if deviation > self._deviation_threshold:
            await self._publish_social_error(model, deviation)

    async def _handle_transcription(self, event: Event) -> None:
        """Bump interaction count on transcription (no histogram update needed).

        Transcription events are tracked so that extended conversational
        turns register as interactions even when the emotion model has low
        confidence. We do NOT store the transcript text.
        """
        agent_id = self._agent_for(event)
        model = await self._store.get(agent_id)
        if model is None:
            model = AgentModel(id=agent_id, label=agent_id)

        # A transcription event counts as an interaction but does not
        # change the emotion histogram. We fold it in as a neutral,
        # low-confidence observation so the interaction_count ticks up.
        # We do NOT record any text from the payload.
        model.update_from_emotion(
            "neutral",
            confidence=0.0,
            prediction_error=0.0,
            deviation_threshold=self._deviation_threshold,
        )
        await self._store.put(model)
        await self._publish_agent_model(
            model, source_label=event.payload.get("source_label")
        )

    # ------------------------------------------------------------------
    # Publications
    # ------------------------------------------------------------------

    async def _publish_agent_model(
        self, model: AgentModel, *, source_label: str | None = None
    ) -> None:
        """Publish empatheia.agent_model with numeric metadata only.

        If source_label is provided it is included so listeners can map the
        model back to the originating audio channel.
        """
        familiarity = model.familiarity()
        salience = self._baseline_salience + familiarity * (
            self._alert_salience - self._baseline_salience
        )
        payload = {
            "agent_id": model.id,
            "agent_label": model.label,
            "familiarity": familiarity,
            "reliability": model.reliability,
            "interaction_count": model.interaction_count,
        }
        if source_label is not None:
            payload["source_label"] = str(source_label)
        await self.publish(
            "empatheia.agent_model",
            payload,
            salience=salience,
        )

    async def _publish_social_error(
        self, model: AgentModel, deviation: float
    ) -> None:
        """Publish empatheia.social_error — salience-only signal.

        Payload contains ONLY: agent id, salience, deviation magnitude.
        No raw behavioral data, no transcript text, no histogram.
        """
        # Scale salience by deviation: higher deviation → higher salience.
        salience = min(
            1.0,
            self._baseline_salience + deviation * (self._alert_salience - self._baseline_salience),
        )
        await self.publish(
            "empatheia.social_error",
            {
                "agent_id": model.id,
                "agent_label": model.label,
                "salience": salience,
                "deviation_magnitude": deviation,
            },
            salience=salience,
        )

    # ------------------------------------------------------------------
    # Fork/merge support
    # ------------------------------------------------------------------

    def serialize(self) -> dict[str, Any]:
        """Snapshot all agent profiles for the fork/merge subsystem."""
        raw = self._store.serialize()
        import json
        profiles = json.loads(raw.decode("utf-8"))
        return {"profiles": profiles}

    def deserialize(self, state: dict[str, Any]) -> None:
        """Restore agent profiles from a fork/merge snapshot."""
        import json
        profiles = state.get("profiles") or {}
        self._store.deserialize(json.dumps(profiles).encode("utf-8"))

    async def export_preservation_state(self) -> dict[str, Any]:
        """Capture every agent profile for preservation."""
        profiles = await self._store.all_profiles()
        return {"profiles": {agent_id: model.to_dict() for agent_id, model in profiles.items()}}

    async def import_preservation_state(self, state: dict[str, Any]) -> int:
        """Restore agent profiles from a preservation bundle.

        Re-embeds every profile with the running embedder and replaces
        the store's contents. Returns the number of profiles restored.
        """
        if not getattr(self._store, "_initialized", False):
            raise RuntimeError("Empatheia store has not been initialized")
        profiles = state.get("profiles") or {}
        models = [AgentModel.from_dict(d) for d in profiles.values()]
        await self._store.replace_all(models)
        return len(models)
