# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Any, ClassVar, Optional

from kaine import legacy_aliases
from kaine.bus.client import AsyncBus, tail_id
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.base import BaseModule
from kaine.modules.self_model.document import (
    SelfModelDocument,
    generate_launch_name,
    is_valid_name,
    load,
    save_atomic,
)
from kaine.modules.self_model.drift import (
    DriftDetector,
    DriftResult,
    SourceDistributionDrift,
)
from kaine.modules.self_model.self_inference import SelfInferenceEngine
from kaine.storage import resolve

log = logging.getLogger(__name__)


DEFAULT_PERSISTENCE_PATH = Path("state/self_model/self_model.json")


#: How many sources an episode reports in ``top_sources``.
_EPISODE_TOP_SOURCES = 5


def _episode_entry(
    *, onset: float, end: float, peak: float, count: int, sources: dict[str, int]
) -> dict[str, Any]:
    """One identity-history entry summarising a drift episode.

    ``timestamp`` (the onset), ``score`` (the peak) and ``top_sources`` keep
    the field names of the older per-alert entries so existing readers work.
    """
    ranked = sorted(sources.items(), key=lambda item: (-item[1], item[0]))
    return {
        "kind": "drift_episode",
        "timestamp": onset,
        "onset": onset,
        "end": end,
        "score": peak,
        "peak_score": peak,
        "count": count,
        "sources": dict(sources),
        "top_sources": [name for name, _ in ranked[:_EPISODE_TOP_SOURCES]],
    }


class SelfModel(BaseModule):
    name: ClassVar[str] = "self_model"

    def __init__(
        self,
        bus: AsyncBus,
        *,
        persistence_path: Path | str = DEFAULT_PERSISTENCE_PATH,
        drift_detector: Optional[DriftDetector] = None,
        drift_window: int = 100,
        drift_threshold: float = 0.6,
        save_interval_s: float = 30.0,
        internal_speech_stream: str = "language.internal",
        external_speech_stream: str = "language.external",
        identity_history_cap: int = 0,
        voice_observations_cap: int = 0,
        baseline_salience: float = 0.05,
        alert_salience: float = 0.7,
        # Self-inference engine (eidolon-self-inference change).
        # Injected by boot.py; default is disabled no-op.
        self_inference: Optional[SelfInferenceEngine] = None,
        # The entity's launch name from its identity, passed by boot. None in a
        # bare test setup, where the module mints its own as before.
        identity_name: Optional[str] = None,
        # True during a revive of a bundle whose identity has no name: the name is
        # decided after the revive lands and arrives through adopt_identity_name.
        # Until then the module neither mints nor keeps a name, and writes nothing.
        name_pending: bool = False,
        # True for a throwaway instance built by a preflight check. It still mints
        # a name so the check exercises the same path, but never logs it, so the
        # log does not read as if the entity had been renamed.
        preflight: bool = False,
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
        if identity_history_cap < 0:
            raise ValueError("identity_history_cap must be >= 0 (0 = no cap)")
        if voice_observations_cap < 0:
            raise ValueError("voice_observations_cap must be >= 0 (0 = no cap)")
        self._persistence_path = resolve(persistence_path)
        if identity_name is not None and not is_valid_name(identity_name):
            log.warning("ignoring an invalid identity name %r", identity_name)
            identity_name = None
        self._identity_name = identity_name or None
        self._preflight = bool(preflight)
        self._name_pending = bool(name_pending) and self._identity_name is None
        self._drift = drift_detector or SourceDistributionDrift(window=drift_window)
        self._drift_threshold = float(drift_threshold)
        self._save_interval_s = float(save_interval_s)
        self._internal_speech_stream = internal_speech_stream
        self._external_speech_stream = external_speech_stream
        self._identity_history_cap = int(identity_history_cap)
        self._voice_observations_cap = int(voice_observations_cap)
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        self._model: SelfModelDocument = SelfModelDocument()
        # Whether the newest identity_history entry is a drift episode that is
        # still open (the last broadcast alerted). In memory only: after a
        # restart the next alert opens a new episode.
        self._episode_open = False
        self._internal_cursor = "$"
        self._external_cursor = "$"
        self._last_save_at: float = 0.0
        self._drift_count = 0

        # Self-inference engine (disabled by default).
        self._inference = self_inference or SelfInferenceEngine(enabled=False)

        # Cursors for self-inference stream subscriptions.
        self._affect_cursor: str = "0-0"
        self._planning_cursor: str = "0-0"

    @property
    def model(self) -> SelfModelDocument:
        return self._model

    @property
    def entity_name(self) -> str | None:
        """The name in the current model, or ``None`` when it has none."""
        return self._model.name or None

    def adopt_identity_name(self, name: str) -> None:
        """Take ``name`` from the entity's identity and persist the document."""
        if not is_valid_name(name):
            log.warning("ignoring an invalid identity name %r", name)
            return
        self._identity_name = name
        self._name_pending = False
        if self._model.name != name:
            self._model = self._model.with_updates(name=name)
        try:
            save_atomic(self._persistence_path, self._model)
        except Exception:
            log.warning("failed to persist identity name", exc_info=True)
        log.info("self-model adopted identity name: %s", name)

    @property
    def drift_detector(self) -> DriftDetector:
        return self._drift

    @property
    def self_inference(self) -> SelfInferenceEngine:
        return self._inference

    async def initialize(self) -> None:
        self._model = load(self._persistence_path)
        if self._name_pending:
            # A revive decides the name after it lands; do not mint or keep one now.
            self._model = self._model.with_updates(name="")
        # The identity owns the entity's launch name; adopt it when the document
        # differs (a fork's copied document carries its parent's name).
        if self._identity_name is not None:
            if self._model.name != self._identity_name:
                self._model = self._model.with_updates(name=self._identity_name)
                try:
                    save_atomic(self._persistence_path, self._model)
                except Exception:
                    log.warning("failed to persist identity name", exc_info=True)
            if self._preflight:
                log.info("self-model preflight check: launch name generation ok")
            else:
                log.info("self-model name adopted from identity: %s", self._model.name)
        # Without an identity name, assign a launch name on first boot (Kaine + a
        # surname). Persisted, so it's stable across restarts.
        elif not self._model.name and not self._name_pending:
            self._model = self._model.with_updates(name=generate_launch_name())
            try:
                save_atomic(self._persistence_path, self._model)
            except Exception:
                log.warning("failed to persist launch name", exc_info=True)
            if self._preflight:
                log.info("self-model preflight check: launch name generation ok")
            else:
                log.info("self-model name minted: %s", self._model.name)

        # Apply operator seed (first boot only) before any observation.
        if self._inference.enabled:
            self._model = self._inference.apply_seed(self._model)

        self._internal_cursor = await self._latest_cursor(self._internal_speech_stream)
        self._external_cursor = await self._latest_cursor(self._external_speech_stream)

        if self._inference.enabled:
            self._affect_cursor = await self._latest_cursor("affect.out")
            self._planning_cursor = await self._latest_cursor("planning.out")

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
        # Publish an initial self-model snapshot to self_model.out so a bus-mediated
        # consumer (a split-host language module) can seed its persona at boot rather than
        # waiting for the first sleep-driven update. On a fresh start the model is
        # empty, so this seeds the same minimal persona as the single-host default.
        try:
            await self._publish_self_model()
        except Exception:
            log.debug("self-model initial self-model publish failed", exc_info=True)
        if self._inference.enabled:
            self._tasks.append(
                asyncio.create_task(
                    self._affect_consumer_loop(), name=f"{self.name}-affect-consumer"
                )
            )
            self._tasks.append(
                asyncio.create_task(
                    self._planning_consumer_loop(), name=f"{self.name}-planning-consumer"
                )
            )
            self._tasks.append(
                asyncio.create_task(
                    self._sleep_consumer_loop(), name=f"{self.name}-sleep-consumer"
                )
            )

    async def _latest_cursor(self, stream: str) -> str:
        """Resolve a stream's tail id so the loop only sees new utterances."""
        return await tail_id(self._bus, stream)

    async def shutdown(self) -> None:
        await super().shutdown()
        try:
            await self._save_to_disk()
        except Exception:
            log.warning("self-model final save failed", exc_info=True)

    async def on_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        sources = [ev.source for _, ev in snapshot.selected_events]
        result = self._drift.observe(sources)
        is_alert = result.score >= self._drift_threshold
        if not is_alert:
            # The score fell below the threshold: the drift episode ends.
            self._episode_open = False
        if is_alert:
            self._drift_count += 1
            await self._record_drift(result)
            await self.publish(
                "self_model.drift",
                {
                    "score": result.score,
                    "recent_count": result.recent_count,
                    "historical_count": result.historical_count,
                    "reference_count": result.reference_count,
                    "top_drifted_sources": list(result.top_drifted_sources),
                    "alert": True,
                },
                salience=self._alert_salience,
            )

    async def _record_drift(self, result: DriftResult) -> None:
        """Record one alerting broadcast into the current drift episode.

        identity_history holds one entry per contiguous drift EPISODE: a run of
        broadcasts whose score stays at or above the threshold. The episode
        summarises every alert in it (onset, end, peak score, count, and how
        often each source was among the top drifted sources), so nothing is
        lost while a sustained shift adds one entry rather than one per
        broadcast. The episode closes when a broadcast scores below the
        threshold.

        The list is owned by this module and updated in place, never copied
        per alert. An entry is replaced with a new dict rather than mutated,
        so a save serializing the model in another thread never sees a dict
        change size under it.
        """
        # Wall-clock event stamp (epoch) recording WHEN this drift was
        # observed — a persisted "when in the world" mark, not a cognitive
        # duration/cadence. Like the cycle's event-timestamp seam it stays
        # on real time, not the subjective EntityClock (which measures
        # felt durations, not absolute moments).
        # infrastructural: real time, not subjective
        now = time.time()
        score = float(result.score)
        top = list(result.top_drifted_sources)
        history = self._model.identity_history
        last = history[-1] if history else None
        if (
            self._episode_open
            and isinstance(last, dict)
            and last.get("kind") == "drift_episode"
        ):
            sources = legacy_aliases.map_module_keys(dict(last.get("sources") or {}))
            for source in top:
                sources[source] = int(sources.get(source, 0)) + 1
            peak = max(float(last.get("peak_score", score)), score)
            history[-1] = _episode_entry(
                onset=float(last.get("onset", now)),
                end=now,
                peak=peak,
                count=int(last.get("count", 0)) + 1,
                sources=sources,
            )
        else:
            history.append(
                _episode_entry(
                    onset=now,
                    end=now,
                    peak=score,
                    count=1,
                    sources={source: 1 for source in top},
                )
            )
            self._episode_open = True
            # identity_history is the entity's own record of how its self-model
            # has drifted: 0 (the default) keeps every episode. A positive cap
            # keeps the most recent N episodes.
            cap = self._identity_history_cap
            if cap > 0 and len(history) > cap:
                del history[: len(history) - cap]

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
                    entries, last_scanned = await self._bus.read_entries(
                        stream,
                        last_id=self._get_cursor(channel),
                        count=64,
                        block_ms=0,
                    )
                except Exception:
                    await asyncio.sleep(0.1)
                    continue
                if last_scanned is not None:
                    self._set_cursor(channel, last_scanned)
                    for entry_id, ev in entries:
                        self._record_voice(channel, ev.payload)
                        # Feed into self-inference (type label only; no text).
                        if channel == "internal":
                            self._inference.observe_language(ev.payload, ev.type)
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
        # voice_observations is the entity's memory of its developing voice:
        # 0 (the default) keeps every entry; a positive cap keeps the most
        # recent N entries.
        voice_cap = self._voice_observations_cap
        if voice_cap > 0 and len(observations) > voice_cap:
            observations = observations[-voice_cap:]
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

    async def _affect_consumer_loop(self) -> None:
        """Subscribe to affect.out for state and drive events."""
        try:
            while not self._stopped.is_set():
                try:
                    entries, last_scanned = await self._bus.read_entries(
                        "affect.out",
                        last_id=self._affect_cursor,
                        count=64,
                        block_ms=0,
                    )
                except Exception:
                    await asyncio.sleep(0.1)
                    continue
                if last_scanned is not None:
                    self._affect_cursor = last_scanned
                    for _, ev in entries:
                        if ev.type == "affect.state":
                            self._inference.observe_affect_state(ev.payload)
                        elif ev.type == "affect.drive":
                            self._inference.observe_affect_drive(ev.payload)
                else:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def _planning_consumer_loop(self) -> None:
        """Subscribe to planning.out for policy events."""
        try:
            while not self._stopped.is_set():
                try:
                    entries, last_scanned = await self._bus.read_entries(
                        "planning.out",
                        last_id=self._planning_cursor,
                        count=64,
                        block_ms=0,
                    )
                except Exception:
                    await asyncio.sleep(0.1)
                    continue
                if last_scanned is not None:
                    self._planning_cursor = last_scanned
                    for _, ev in entries:
                        if ev.type == "planning.policy":
                            self._inference.observe_planning_policy(ev.payload)
                else:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def _sleep_consumer_loop(self) -> None:
        """Subscribe to sleep.out for maintenance cycle end events."""
        cursor = await self._latest_cursor("sleep.out")
        try:
            while not self._stopped.is_set():
                try:
                    entries, last_scanned = await self._bus.read_entries(
                        "sleep.out",
                        last_id=cursor,
                        count=32,
                        block_ms=0,
                    )
                except Exception:
                    await asyncio.sleep(0.1)
                    continue
                if last_scanned is not None:
                    cursor = last_scanned
                    for _, ev in entries:
                        if ev.type == "sleep.sleep.completed":
                            self._model = self._inference.maintenance_cycle_end(
                                self._model
                            )
                            # Publish updated self-model to self_model.out so
                            # the dashboard diagnostics and sidecar can read the fields.
                            await self._publish_self_model()
                else:
                    await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def ensure_situation_fact(self, text: str, *, replaces: tuple[str, ...] = ()) -> bool:
        """Tell the entity a fact about its situation.

        The fact is persisted and published at once, so the language organ can
        condition on it immediately. It is not a value or norm and never touches
        drift or identity history. A fact listed in ``replaces`` (an earlier
        wording) is replaced in place.
        """
        text = text.strip()
        if not text:
            raise ValueError("situation fact text must be non-empty")
        old = set(replaces) - {text}
        facts = list(self._model.situation_facts)
        if text in facts:
            new = [f for f in facts if f not in old]
        else:
            new = []
            replaced = False
            for f in facts:
                if f in old:
                    if not replaced:
                        new.append(text)
                        replaced = True
                else:
                    new.append(f)
            if not replaced:
                new.append(text)
        if new == facts:
            return False
        self._model = self._model.with_updates(situation_facts=new)
        await self._publish_self_model()
        await self._save_to_disk()
        return True

    async def _publish_self_model(self) -> None:
        """Publish the populated self-model fields to self_model.out.

        This is the bus-mediated self-model snapshot other trusted-host modules
        (notably the language module's persona seeding) consume in place of an in-process
        self-model module reference, so the language organ can run in a separate process /
        host over the shared bus (``distributed-deployment``). ``name`` is
        included so a split language module seeds the same persona as the single-host
        default.
        """
        m = self._model
        await self.publish(
            "self_model.document",
            {
                "name": getattr(m, "name", None),
                "values": list(m.values),
                "behavioral_norms": list(m.behavioral_norms),
                "situation_facts": list(m.situation_facts),
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
                    log.warning("self-model periodic save failed", exc_info=True)
        except asyncio.CancelledError:
            raise

    async def _save_to_disk(self) -> None:
        if self._name_pending:
            # Keep the stored document untouched until the revive names the entity.
            return
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
            self._model = SelfModelDocument.from_json(state["model"])
            # The identity owns the name: a fork's copied state carries its
            # parent's, so the restored model takes the identity's name.
            if self._identity_name is not None and self._model.name != self._identity_name:
                self._model = self._model.with_updates(name=self._identity_name)
        if "drift_count" in state:
            self._drift_count = int(state["drift_count"])
        if "internal_cursor" in state:
            self._internal_cursor = str(state["internal_cursor"])
        if "external_cursor" in state:
            self._external_cursor = str(state["external_cursor"])
