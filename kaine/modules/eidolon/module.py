# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, ClassVar, Optional

from kaine.bus.client import AsyncBus
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.base import BaseModule
from kaine.modules.eidolon.document import (
    SelfModel,
    generate_launch_name,
    load,
    save_atomic,
)
from kaine.modules.eidolon.drift import (
    DriftDetector,
    DriftResult,
    SourceDistributionDrift,
)
from kaine.modules.eidolon.self_inference import SelfInferenceEngine

log = logging.getLogger(__name__)


DEFAULT_PERSISTENCE_PATH = Path("state/eidolon/self_model.json")


class Eidolon(BaseModule):
    name: ClassVar[str] = "eidolon"

    def __init__(
        self,
        bus: AsyncBus,
        *,
        persistence_path: Path | str = DEFAULT_PERSISTENCE_PATH,
        drift_detector: Optional[DriftDetector] = None,
        drift_window: int = 100,
        drift_threshold: float = 0.6,
        save_interval_s: float = 30.0,
        internal_speech_stream: str = "lingua.internal",
        external_speech_stream: str = "lingua.external",
        identity_history_cap: int = 256,
        voice_observations_cap: int = 256,
        baseline_salience: float = 0.05,
        alert_salience: float = 0.7,
        # Self-inference engine (eidolon-self-inference change).
        # Injected by boot.py; default is disabled no-op.
        self_inference: Optional[SelfInferenceEngine] = None,
    ) -> None:
        super().__init__(bus)
        if not 0.0 <= baseline_salience <= 1.0:
            raise ValueError("baseline_salience must be in [0, 1]")
        if not 0.0 <= alert_salience <= 1.0:
            raise ValueError("alert_salience must be in [0, 1]")
        if drift_threshold < 0:
            raise ValueError("drift_threshold must be >= 0")
        if save_interval_s <= 0:
            raise ValueError("save_interval_s must be positive")
        if identity_history_cap <= 0:
            raise ValueError("identity_history_cap must be positive")
        if voice_observations_cap <= 0:
            raise ValueError("voice_observations_cap must be positive")
        self._persistence_path = Path(persistence_path)
        self._drift = drift_detector or SourceDistributionDrift(window=drift_window)
        self._drift_threshold = float(drift_threshold)
        self._save_interval_s = float(save_interval_s)
        self._internal_speech_stream = internal_speech_stream
        self._external_speech_stream = external_speech_stream
        self._identity_history_cap = int(identity_history_cap)
        self._voice_observations_cap = int(voice_observations_cap)
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        self._model: SelfModel = SelfModel()
        self._internal_cursor = "$"
        self._external_cursor = "$"
        self._last_save_at: float = 0.0
        self._drift_count = 0

        # Self-inference engine (disabled by default).
        self._inference = self_inference or SelfInferenceEngine(enabled=False)

        # Cursors for self-inference stream subscriptions.
        self._thymos_cursor: str = "0-0"
        self._nous_cursor: str = "0-0"

    @property
    def model(self) -> SelfModel:
        return self._model

    @property
    def drift_detector(self) -> DriftDetector:
        return self._drift

    @property
    def self_inference(self) -> SelfInferenceEngine:
        return self._inference

    async def initialize(self) -> None:
        self._model = load(self._persistence_path)
        # Assign a launch name on first boot (Kaine + a surname). Persisted, so
        # it's stable across restarts; an entity may later rename itself.
        if not self._model.name:
            self._model = self._model.with_updates(name=generate_launch_name())
            try:
                save_atomic(self._persistence_path, self._model)
            except Exception:
                log.warning("failed to persist launch name", exc_info=True)
            log.info("eidolon assigned launch name: %s", self._model.name)

        # Apply operator seed (first boot only) before any observation.
        if self._inference.enabled:
            self._model = self._inference.apply_seed(self._model)

        self._internal_cursor = await self._latest_cursor(self._internal_speech_stream)
        self._external_cursor = await self._latest_cursor(self._external_speech_stream)

        if self._inference.enabled:
            self._thymos_cursor = await self._latest_cursor("thymos.out")
            self._nous_cursor = await self._latest_cursor("nous.out")

        await super().initialize()
        self._tasks.append(
            asyncio.create_task(
                self._internal_speech_loop(), name=f"{self.name}-internal-speech"
            )
        )
        self._tasks.append(
            asyncio.create_task(
                self._external_speech_loop(), name=f"{self.name}-external-speech"
            )
        )
        self._tasks.append(
            asyncio.create_task(
                self._periodic_save_loop(), name=f"{self.name}-periodic-save"
            )
        )
        if self._inference.enabled:
            self._tasks.append(
                asyncio.create_task(
                    self._thymos_consumer_loop(), name=f"{self.name}-thymos-consumer"
                )
            )
            self._tasks.append(
                asyncio.create_task(
                    self._nous_consumer_loop(), name=f"{self.name}-nous-consumer"
                )
            )
            self._tasks.append(
                asyncio.create_task(
                    self._hypnos_consumer_loop(), name=f"{self.name}-hypnos-consumer"
                )
            )

    async def _latest_cursor(self, stream: str) -> str:
        """Resolve a stream's tail id so the loop only sees new utterances."""
        try:
            latest = await self._bus.client.xrevrange(stream, count=1)
        except Exception:
            latest = []
        if latest:
            entry_id = latest[0][0]
            if isinstance(entry_id, bytes):
                entry_id = entry_id.decode()
            return entry_id
        return "0-0"

    async def shutdown(self) -> None:
        await super().shutdown()
        try:
            await self._save_to_disk()
        except Exception:
            log.warning("eidolon final save failed", exc_info=True)

    async def on_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        sources = [ev.source for _, ev in snapshot.selected_events]
        result = self._drift.observe(sources)
        is_alert = result.score >= self._drift_threshold
        if is_alert:
            self._drift_count += 1
            await self._record_drift(result)
            await self.publish(
                "eidolon.drift",
                {
                    "score": result.score,
                    "recent_count": result.recent_count,
                    "historical_count": result.historical_count,
                    "top_drifted_sources": list(result.top_drifted_sources),
                },
                salience=self._alert_salience,
            )

    async def _record_drift(self, result: DriftResult) -> None:
        history = list(self._model.identity_history)
        history.append(
            {
                # Wall-clock event stamp (epoch) recording WHEN this drift was
                # observed — a persisted "when in the world" mark, not a cognitive
                # duration/cadence. Like the cycle's event-timestamp seam it stays
                # on real time, not the subjective EntityClock (which measures
                # felt durations, not absolute moments).
                # infrastructural: real time, not subjective
                "timestamp": time.time(),
                "score": result.score,
                "top_sources": list(result.top_drifted_sources),
            }
        )
        if len(history) > self._identity_history_cap:
            history = history[-self._identity_history_cap :]
        self._model = self._model.with_updates(identity_history=history)

    async def _internal_speech_loop(self) -> None:
        await self._speech_loop(self._internal_speech_stream, "internal")

    async def _external_speech_loop(self) -> None:
        await self._speech_loop(self._external_speech_stream, "external")

    async def _speech_loop(self, stream: str, channel: str) -> None:
        """Observe one speech channel, recording lightweight per-utterance
        features (never the raw text) and bumping that channel's count."""
        try:
            while not self._stopped.is_set():
                try:
                    entries = await self._bus.read(
                        stream,
                        last_id=self._get_cursor(channel),
                        count=64,
                        block_ms=0,
                    )
                except Exception:
                    await asyncio.sleep(0.1)
                    continue
                if entries:
                    self._set_cursor(channel, entries[-1][0])
                    for entry_id, ev in entries:
                        self._record_voice(channel, ev.payload)
                        # Feed into self-inference (type label only; no text).
                        if channel == "internal":
                            self._inference.observe_lingua(ev.payload, ev.type)
                else:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    def _get_cursor(self, channel: str) -> str:
        return (
            self._internal_cursor if channel == "internal" else self._external_cursor
        )

    def _set_cursor(self, channel: str, cursor: str) -> None:
        if channel == "internal":
            self._internal_cursor = cursor
        else:
            self._external_cursor = cursor

    def _record_voice(self, channel: str, payload: dict[str, Any]) -> None:
        """Derive features from the utterance text and discard the text.

        Only `{timestamp, channel, length, word_count}` is kept; raw speech
        content is never persisted into the self-model (privacy boundary).
        """
        text = payload.get("text") or ""
        observation = {
            # Wall-clock event stamp (epoch): WHEN this utterance was heard.
            # A persisted record mark, not a cognitive interval — stays real,
            # not subjective (see _record_drift).
            # infrastructural: real time, not subjective
            "timestamp": time.time(),
            "channel": channel,
            "length": len(text),
            "word_count": len(text.split()),
        }
        observations = list(self._model.voice_observations)
        observations.append(observation)
        if len(observations) > self._voice_observations_cap:
            observations = observations[-self._voice_observations_cap :]
        if channel == "internal":
            new_count = self._model.internal_speech_count + 1
            self._model = self._model.with_updates(
                internal_speech_count=new_count,
                voice_observations=observations,
            )
        else:
            new_count = self._model.external_speech_count + 1
            self._model = self._model.with_updates(
                external_speech_count=new_count,
                voice_observations=observations,
            )

    # ------------------------------------------------------------------
    # Self-inference consumer loops (run only when inference is enabled)

    async def _thymos_consumer_loop(self) -> None:
        """Subscribe to thymos.out for state and drive events."""
        try:
            while not self._stopped.is_set():
                try:
                    entries = await self._bus.read(
                        "thymos.out",
                        last_id=self._thymos_cursor,
                        count=64,
                        block_ms=0,
                    )
                except Exception:
                    await asyncio.sleep(0.1)
                    continue
                if entries:
                    self._thymos_cursor = entries[-1][0]
                    for _, ev in entries:
                        if ev.type == "thymos.state":
                            self._inference.observe_thymos_state(ev.payload)
                        elif ev.type == "thymos.drive":
                            self._inference.observe_thymos_drive(ev.payload)
                else:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def _nous_consumer_loop(self) -> None:
        """Subscribe to nous.out for policy events."""
        try:
            while not self._stopped.is_set():
                try:
                    entries = await self._bus.read(
                        "nous.out",
                        last_id=self._nous_cursor,
                        count=64,
                        block_ms=0,
                    )
                except Exception:
                    await asyncio.sleep(0.1)
                    continue
                if entries:
                    self._nous_cursor = entries[-1][0]
                    for _, ev in entries:
                        if ev.type == "nous.policy":
                            self._inference.observe_nous_policy(ev.payload)
                else:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def _hypnos_consumer_loop(self) -> None:
        """Subscribe to hypnos.out for maintenance cycle end events."""
        cursor = await self._latest_cursor("hypnos.out")
        try:
            while not self._stopped.is_set():
                try:
                    entries = await self._bus.read(
                        "hypnos.out",
                        last_id=cursor,
                        count=32,
                        block_ms=0,
                    )
                except Exception:
                    await asyncio.sleep(0.1)
                    continue
                if entries:
                    cursor = entries[-1][0]
                    for _, ev in entries:
                        if ev.type == "hypnos.sleep.completed":
                            self._model = self._inference.maintenance_cycle_end(
                                self._model
                            )
                            # Publish updated self-model to eidolon.out so
                            # Nexus diagnostics and sidecar can read the fields.
                            await self._publish_self_model()
                else:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def _publish_self_model(self) -> None:
        """Publish the populated self-model fields to eidolon.out."""
        m = self._model
        await self.publish(
            "eidolon.self_model",
            {
                "values": list(m.values),
                "behavioral_norms": list(m.behavioral_norms),
                "personality_baseline": dict(m.personality_baseline),
                "capability_map": dict(m.capability_map),
            },
            salience=self._baseline_salience,
        )

    async def _periodic_save_loop(self) -> None:
        try:
            while not self._stopped.is_set():
                try:
                    # Persistence cadence (disk flush of the self-model) — pure
                    # housekeeping, not cognition. It must fire on real wall time
                    # regardless of the entity's time_scale, so it stays off the
                    # subjective EntityClock.
                    # infrastructural: real time, not subjective
                    await asyncio.wait_for(
                        self._stopped.wait(), timeout=self._save_interval_s
                    )
                except asyncio.TimeoutError:
                    # Expected: the interval elapsing without a stop signal is
                    # exactly what wakes this loop to run the periodic save.
                    pass
                if self._stopped.is_set():
                    return
                try:
                    await self._save_to_disk()
                except Exception:
                    log.warning("eidolon periodic save failed", exc_info=True)
        except asyncio.CancelledError:
            raise

    async def _save_to_disk(self) -> None:
        snapshot = self._model

        def _write_sync() -> None:
            save_atomic(self._persistence_path, snapshot)

        await asyncio.to_thread(_write_sync)
        # infrastructural: real time, not subjective (last-flush wall mark)
        self._last_save_at = time.monotonic()

    def serialize(self) -> dict[str, Any]:
        return {
            "model": self._model.to_json(),
            "drift_count": self._drift_count,
            "internal_cursor": self._internal_cursor,
            "external_cursor": self._external_cursor,
        }

    def deserialize(self, state: dict[str, Any]) -> None:
        if "model" in state:
            self._model = SelfModel.from_json(state["model"])
        if "drift_count" in state:
            self._drift_count = int(state["drift_count"])
        if "internal_cursor" in state:
            self._internal_cursor = str(state["internal_cursor"])
        if "external_cursor" in state:
            self._external_cursor = str(state["external_cursor"])
