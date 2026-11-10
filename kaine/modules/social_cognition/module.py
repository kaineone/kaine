# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The social cognition / theory-of-mind module.

Consumes ``audition.emotion`` and ``audition.transcription`` events and
the workspace broadcast to build and maintain per-agent social models.
Publishes:

- ``social_cognition.agent_model`` — familiarity, reliability, interaction_count
  (numeric metadata only — no raw sense data).
- ``social_cognition.social_error`` — salience-only signal (agent id, salience,
  deviation magnitude only — never raw behavioral data or transcript text).
- ``social_cognition.identity_update`` — a voice or face embedding matched (or
  minted) an agent; carries agent id, modality, confidence and binding
  confidence, never the embedding.

Agent identity defaults to a single operator-set speaker label (default
``"operator"``). With speaker or face identification enabled, voice and face
embeddings are matched against known agents, new agents are minted for
unmatched embeddings, and co-occurring voice and face identities are bound
and merged by the cross-modal binder.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, ClassVar, Optional, Sequence

from kaine.bus.client import AsyncBus, tail_id
from kaine.bus.schema import OPERATOR_SOURCES, Event
from kaine.bus.streams import AUDITION_STREAM, VISION_STREAM
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.base import BaseModule
from kaine.modules.social_cognition.agent import AgentModel
from kaine.modules.social_cognition.binder import BindingObservation, CrossModalBinder
from kaine.modules.social_cognition.exemplar_buffer import ExemplarBuffer
from kaine.modules.social_cognition.store import AgentStore, InMemoryAgentStore, QdrantAgentStore
from kaine.text_embedding import Embedder

log = logging.getLogger(__name__)


class SocialCognition(BaseModule):
    name: ClassVar[str] = "social_cognition"
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
        collection: str = "social_cognition_agents",
        speaker_label: str = "operator",
        operator_sources: Sequence[str] = OPERATOR_SOURCES,
        deviation_threshold: float = 0.5,
        baseline_salience: float = 0.15,
        alert_salience: float = 0.6,
        # Qdrant connection (only used when backend="qdrant").
        qdrant_host: str = "127.0.0.1",
        qdrant_port: int = 6533,
        qdrant_api_key: Optional[str] = None,
        speaker_identification_enabled: bool = False,
        face_identification_enabled: bool = False,
        speaker_identification_threshold: float = 0.6,
        face_identification_threshold: float = 0.6,
        co_occurrence_window_s: float = 3.0,
        binding_merge_threshold: float = 0.9,
        p_common_prior: float = 0.7,
        exemplar_max_size: int = 20,
        consolidation_threshold: int = 5,
        exemplar_diversity_floor: float = 0.01,
        exemplar_ema_decay: float = 0.9,
        reliability_floor: float = 0.3,
        expression_processing_enabled: bool = False,
        gaze_processing_enabled: bool = False,
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
                    "Social cognition backend=qdrant requires qdrant_api_key — "
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

        self._speaker_identification_enabled = bool(speaker_identification_enabled)
        self._face_identification_enabled = bool(face_identification_enabled)
        self._speaker_identification_threshold = float(speaker_identification_threshold)
        self._face_identification_threshold = float(face_identification_threshold)
        self._co_occurrence_window_s = float(co_occurrence_window_s)
        self._binding_merge_threshold = float(binding_merge_threshold)
        self._p_common_prior = float(p_common_prior)
        self._exemplar_max_size = int(exemplar_max_size)
        self._consolidation_threshold = int(consolidation_threshold)
        self._exemplar_diversity_floor = float(exemplar_diversity_floor)
        self._exemplar_ema_decay = float(exemplar_ema_decay)
        self._reliability_floor = float(reliability_floor)
        self._expression_processing_enabled = bool(expression_processing_enabled)
        self._gaze_processing_enabled = bool(gaze_processing_enabled)

        self._binder: Optional[CrossModalBinder] = None
        if self._speaker_identification_enabled or self._face_identification_enabled:
            self._binder = CrossModalBinder(
                co_occurrence_window_s=self._co_occurrence_window_s,
                merge_threshold=self._binding_merge_threshold,
                p_common_prior=self._p_common_prior,
            )
        # source_label -> identified agent id, set by the voice identity path.
        self._identity_cache: dict[str, str] = {}
        self._merged_into: dict[str, str] = {}
        self._merge_lock = asyncio.Lock()

        # Cursor for audition.out stream (emotion + transcription events).
        self._audition_cursor: str = "0-0"
        self._vision_cursor: str = "0-0"

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
        self._audition_cursor = await tail_id(self._bus, AUDITION_STREAM)
        await super().initialize()
        self._tasks.append(
            asyncio.create_task(
                self._audition_consumer_loop(),
                name="social-cognition-audition-consumer",
            )
        )
        if self._face_identification_enabled:
            self._vision_cursor = await tail_id(self._bus, VISION_STREAM)
            self._tasks.append(
                asyncio.create_task(
                    self._vision_consumer_loop(),
                    name="social-cognition-vision-consumer",
                )
            )

    async def shutdown(self) -> None:
        await super().shutdown()
        try:
            await self._store.shutdown()
        except Exception:
            log.warning("social cognition store shutdown failed", exc_info=True)

    # ------------------------------------------------------------------
    # Workspace broadcast (optional: update on workspace context)
    # ------------------------------------------------------------------

    async def on_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        """Take nothing from the broadcast.

        The paper gives the social cognition module per-agent tone-of-voice
        models with familiarity and a social prediction error, all built from
        heard speech, so its work runs in `_audition_consumer_loop` on
        `audition.out` events. The broadcast reaches every module; this one
        has no use for it.
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
                        AUDITION_STREAM,
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

    async def _vision_consumer_loop(self) -> None:
        """Background loop: read vision.out for face detection events."""
        try:
            while not self._stopped.is_set():
                try:
                    entries, last_scanned = await self._bus.read_entries(
                        VISION_STREAM,
                        last_id=self._vision_cursor,
                        count=32,
                        block_ms=0,
                    )
                except Exception:
                    await asyncio.sleep(0.05)
                    continue
                if last_scanned is not None:
                    self._vision_cursor = last_scanned
                    for _, event in entries:
                        if event.type == "vision.face_detection":
                            await self._handle_face_detection(event)
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
        elif event.type == "audition.speaker_embedding" and self._speaker_identification_enabled:
            await self._handle_speaker_embedding(event)

    def _agent_for(self, event: Event) -> str:
        """Map an audition event to the agent id it updates.

        Operator channels (or events with no channel) update the configured
        speaker label. Every other channel gets its own ``media:<channel>``
        agent so film voices cannot shape the operator model.
        """
        source_label = event.payload.get("source_label")
        if self._speaker_identification_enabled and source_label is not None:
            identified = self._identity_cache.get(str(source_label))
            if identified is not None:
                return identified
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
        # A skipped reading publishes no error; pass None through so the
        # agent model does not average a made-up 0.
        raw_error = payload.get("prediction_error")
        prediction_error = None if raw_error is None else float(raw_error)

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
        # The placeholder carries no error, so it leaves the error
        # average alone. We do NOT record any text from the payload.
        model.update_from_emotion(
            "neutral",
            confidence=0.0,
            prediction_error=None,
            deviation_threshold=self._deviation_threshold,
        )
        await self._store.put(model)
        await self._publish_agent_model(
            model, source_label=event.payload.get("source_label")
        )

    # ------------------------------------------------------------------
    # Perceptual identity
    # ------------------------------------------------------------------

    def _make_buffer(self, dim: int) -> ExemplarBuffer:
        return ExemplarBuffer(
            dim,
            max_size=self._exemplar_max_size,
            consolidation_threshold=self._consolidation_threshold,
            diversity_floor=self._exemplar_diversity_floor,
            ema_decay=self._exemplar_ema_decay,
            reliability_floor=self._reliability_floor,
        )

    def _rebuild_buffer(self, dim: int, exemplars: list[dict[str, Any]]) -> ExemplarBuffer:
        buf = self._make_buffer(dim)
        for item in exemplars:
            buf.add(item["embedding"], timestamp=item.get("timestamp"))
        return buf

    def _get_or_create_voice_buffer(self, model: AgentModel) -> ExemplarBuffer:
        if model.voice_exemplars:
            return self._rebuild_buffer(192, model.voice_exemplars)
        return self._make_buffer(192)

    def _get_or_create_face_buffer(self, model: AgentModel) -> ExemplarBuffer:
        if model.face_exemplars:
            return self._rebuild_buffer(128, model.face_exemplars)
        return self._make_buffer(128)

    @staticmethod
    def _store_voice_buffer(model: AgentModel, buf: ExemplarBuffer) -> None:
        model.voice_exemplars = buf.to_dict()["exemplars"]
        model.voice_centroid = buf.centroid
        model.voice_sample_count = buf.count
        model.voice_reliability = buf.reliability()

    @staticmethod
    def _store_face_buffer(model: AgentModel, buf: ExemplarBuffer) -> None:
        model.face_exemplars = buf.to_dict()["exemplars"]
        model.face_centroid = buf.centroid
        model.face_sample_count = buf.count
        model.face_reliability = buf.reliability()

    @staticmethod
    def _update_binding_state(model: AgentModel) -> None:
        if model.binding_state == "bound":
            return
        has_voice = model.voice_centroid is not None
        has_face = model.face_centroid is not None
        if has_voice and has_face:
            model.binding_state = "unbound"
        elif has_voice:
            model.binding_state = "voice_only"
        elif has_face:
            model.binding_state = "face_only"

    def _resolve_agent(self, agent_id: str) -> str:
        """Follow the merge-redirect chain to the terminal (live) agent."""
        seen: set[str] = set()
        while agent_id in self._merged_into:
            if agent_id in seen:
                break
            seen.add(agent_id)
            agent_id = self._merged_into[agent_id]
        return agent_id

    def _binding_confidence_for(self, agent_id: str) -> Optional[float]:
        if self._binder is None:
            return None
        best: Optional[float] = None
        for (a, b), conf in self._binder._confidence.items():
            if agent_id in (a, b) and (best is None or conf > best):
                best = conf
        return best

    async def _handle_speaker_embedding(self, event: Event) -> None:
        """Match a voice embedding to a known agent, or mint a new one."""
        payload = event.payload
        embedding = payload.get("embedding")
        if not embedding:
            return
        embedding = [float(x) for x in embedding]
        detection_conf = float(payload.get("confidence") or 0.0)
        timestamp = event.timestamp.timestamp()

        matches = await self._store.search_by_voice(
            embedding, self._speaker_identification_threshold
        )
        if matches:
            agent_id, confidence = matches[0]
            model = await self._store.get(agent_id)
            is_new = model is None
            if model is None:
                model = AgentModel(id=agent_id, label=agent_id)
        else:
            agent_id = f"person:{uuid.uuid4().hex[:8]}"
            model = AgentModel(id=agent_id, label=agent_id)
            confidence = detection_conf
            is_new = True

        buf = self._get_or_create_voice_buffer(model)
        buf.add(embedding, timestamp=timestamp)
        self._store_voice_buffer(model, buf)
        self._update_binding_state(model)
        await self._store.put(model)

        source_label = payload.get("source_label")
        if source_label is not None:
            self._identity_cache[str(source_label)] = agent_id

        if self._binder is not None:
            self._binder.observe_voice(agent_id, confidence, buf.reliability(), timestamp)
            await self._process_bindings()
            # A merge may have redirected this agent.
            agent_id = self._resolve_agent(agent_id)

        await self._publish_identity_update(
            agent_id,
            "voice",
            confidence,
            is_new,
            self._binding_confidence_for(agent_id),
        )

    async def _handle_face_detection(self, event: Event) -> None:
        """Match each detected face to a known agent, or mint a new one."""
        timestamp = event.timestamp.timestamp()
        for face in event.payload.get("faces") or []:
            embedding = face.get("embedding")
            if not embedding:
                continue
            embedding = [float(x) for x in embedding]
            detection_conf = float(face.get("confidence") or 0.0)

            matches = await self._store.search_by_face(
                embedding, self._face_identification_threshold
            )
            if matches:
                agent_id, confidence = matches[0]
                model = await self._store.get(agent_id)
                is_new = model is None
                if model is None:
                    model = AgentModel(id=agent_id, label=agent_id)
            else:
                agent_id = f"person:{uuid.uuid4().hex[:8]}"
                model = AgentModel(id=agent_id, label=agent_id)
                confidence = detection_conf
                is_new = True

            buf = self._get_or_create_face_buffer(model)
            buf.add(embedding, timestamp=timestamp)
            self._store_face_buffer(model, buf)
            self._update_binding_state(model)
            await self._store.put(model)

            if self._binder is not None:
                self._binder.observe_face(agent_id, confidence, buf.reliability(), timestamp)
                await self._process_bindings()
                agent_id = self._resolve_agent(agent_id)

            await self._publish_identity_update(
                agent_id,
                "face",
                confidence,
                is_new,
                self._binding_confidence_for(agent_id),
            )

    async def _process_bindings(self) -> None:
        if self._binder is None:
            return
        async with self._merge_lock:
            for obs in self._binder.check_bindings():
                if obs.voice_agent_id == obs.face_agent_id:
                    continue
                if self._binder.should_merge(obs.voice_agent_id, obs.face_agent_id):
                    await self._handle_binding_merge(obs)

    async def _handle_binding_merge(self, observation: BindingObservation) -> None:
        """Merge the two agents of a bound voice/face pair into the better-observed one."""
        assert self._binder is not None
        a = await self._store.get(observation.voice_agent_id)
        b = await self._store.get(observation.face_agent_id)
        if a is None or b is None or a.id == b.id:
            return
        if (a.voice_sample_count + a.face_sample_count) >= (
            b.voice_sample_count + b.face_sample_count
        ):
            kept, gone = a, b
        else:
            kept, gone = b, a

        if gone.voice_exemplars:
            buf = self._get_or_create_voice_buffer(kept)
            for item in gone.voice_exemplars:
                buf.add(item["embedding"], timestamp=item.get("timestamp"))
            self._store_voice_buffer(kept, buf)
        if gone.face_exemplars:
            buf = self._get_or_create_face_buffer(kept)
            for item in gone.face_exemplars:
                buf.add(item["embedding"], timestamp=item.get("timestamp"))
            self._store_face_buffer(kept, buf)
        kept.interaction_count += gone.interaction_count
        kept.binding_state = "bound"
        kept.binding_confidence = self._binder.binding_confidence(kept.id, gone.id)
        await self._store.put(kept)

        await self._store.delete(gone.id)

        self._binder.record_merge(kept.id, gone.id)
        self._merged_into[gone.id] = kept.id
        for k, v in list(self._merged_into.items()):
            if v == gone.id:
                self._merged_into[k] = kept.id
        for label, agent_id in list(self._identity_cache.items()):
            if agent_id == gone.id:
                self._identity_cache[label] = kept.id

        await self._publish_identity_update(
            kept.id, "both", kept.binding_confidence or 0.0, False, kept.binding_confidence
        )

    async def _publish_identity_update(
        self,
        agent_id: str,
        modality: str,
        confidence: float,
        is_new: bool,
        binding_confidence: Optional[float],
    ) -> None:
        await self.publish(
            "social_cognition.identity_update",
            {
                "agent_id": agent_id,
                "modality": modality,
                "confidence": confidence,
                "is_new": is_new,
                "binding_confidence": binding_confidence,
            },
            salience=self._baseline_salience,
        )

    # ------------------------------------------------------------------
    # Publications
    # ------------------------------------------------------------------

    async def _publish_agent_model(
        self, model: AgentModel, *, source_label: str | None = None
    ) -> None:
        """Publish social_cognition.agent_model: numeric metadata and labels, no content.

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
            "social_cognition.agent_model",
            payload,
            salience=salience,
        )

    async def _publish_social_error(
        self, model: AgentModel, deviation: float
    ) -> None:
        """Publish social_cognition.social_error — salience-only signal.

        Payload contains ONLY: agent id, salience, deviation magnitude.
        No raw behavioral data, no transcript text, no histogram.
        """
        # Scale salience by deviation: higher deviation → higher salience.
        salience = min(
            1.0,
            self._baseline_salience + deviation * (self._alert_salience - self._baseline_salience),
        )
        await self.publish(
            "social_cognition.social_error",
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
            raise RuntimeError("Social cognition store has not been initialized")
        profiles = state.get("profiles") or {}
        models = [AgentModel.from_dict(d) for d in profiles.values()]
        await self._store.replace_all(models)
        return len(models)
