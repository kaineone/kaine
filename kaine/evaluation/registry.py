# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""SidecarRegistry — constructs and lifecycles every enabled observer.

The cycle entrypoint instantiates this when `[evaluation].enabled` is
true and calls `start()` before `cycle.run_forever()`. `stop()` is
called during cycle shutdown.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, Optional

from kaine.evaluation.ab_divergence import (
    ABDivergenceObserver,
    BareInferenceClient,
    HTTPBareInferenceClient,
)
from kaine.evaluation.affect_correlation import AffectCorrelationRecorder
from kaine.evaluation.attribution import AttributionRecorder
from kaine.evaluation.config import EvaluationConfig, ResearchEventLogConfig
from kaine.evaluation.eidolon_accuracy import EidolonAccuracyRunner
from kaine.evaluation.embeddings import (
    HashEmbedder,
    SentenceTransformerTextEmbedder,
    TextEmbedder,
)
from kaine.evaluation.memory_probes import (
    CognitiveQueryClient,
    MemoryProbeRunner,
    MemorySource,
)
from kaine.evaluation.observers.ablation_observer import AblationObserver
from kaine.evaluation.observers.coherence_observer import CoherenceObserver
from kaine.evaluation.observers.empatheia_observer import EmpatheiaObserver
from kaine.evaluation.observers.fatigue_observer import FatigueObserver
from kaine.evaluation.observers.nous_policy_observer import NousPolicyObserver
from kaine.evaluation.observers.prediction_error_observer import PredictionErrorObserver
from kaine.evaluation.observers.raw_bus_archive_consumer import RawBusArchiveConsumer
from kaine.evaluation.observers.replay_observer import ReplayObserver
from kaine.evaluation.observers.research_event_observer import ResearchEventObserver
from kaine.evaluation.observers.voice_alignment_divergence_observer import (
    VoiceAlignmentDivergenceObserver,
)
from kaine.evaluation.observers.welfare_observer import WelfareObserver
from kaine.evaluation.proactive_audit import ProactiveAuditObserver
from kaine.evaluation.sink import AsyncJsonlSink
from kaine.evaluation.sleep_snapshots import SleepSnapshotRecorder
from kaine.evaluation.trajectory import TrajectoryRecorder
from kaine.evaluation.voice_tracking import VoiceTrackingObserver

log = logging.getLogger(__name__)


class SidecarRegistry:
    def __init__(
        self,
        *,
        bus,
        config: EvaluationConfig,
        research_event_log_config: Optional[ResearchEventLogConfig] = None,
        thymos_state_provider: Optional[Callable[[], dict[str, Any]]] = None,
        last_user_input_provider=None,
        sleep_state_provider: Optional[Callable[[], dict[str, Any]]] = None,
        memory_source: Optional[MemorySource] = None,
        cognitive_query_client: Optional[CognitiveQueryClient] = None,
        bare_inference_client: Optional[BareInferenceClient] = None,
        embedder: Optional[TextEmbedder] = None,
    ) -> None:
        self._bus = bus
        self._config = config
        # Independent of `config.enabled` — the curated research event log and
        # the local-only raw archive are each gated on their own flags.
        self._research_cfg = research_event_log_config or ResearchEventLogConfig()
        self._thymos_provider = thymos_state_provider
        self._last_input_provider = last_user_input_provider
        self._sleep_state_provider = sleep_state_provider
        self._memory_source = memory_source
        self._cognitive_client = cognitive_query_client
        self._bare_client = bare_inference_client
        self._embedder = embedder
        self._sinks: list[AsyncJsonlSink] = []
        self._observers: list[Any] = []
        self._started = False
        # Sidecar observers exposed for Nexus diagnostics.
        self._prediction_error_observer: PredictionErrorObserver | None = None
        self._welfare_observer: WelfareObserver | None = None
        # The live oscillatory-ablation recorder is NOT a bus subscriber (it is
        # driven directly by the cycle), so it is held apart from _observers and
        # its record() is exposed via the ablation_recorder property. Its sink IS
        # tracked in _sinks for normal start/stop.
        self._ablation_observer: AblationObserver | None = None

    @property
    def started(self) -> bool:
        return self._started

    @property
    def ablation_recorder(self):
        """The cycle-facing ``(primary, counterfactual) -> None`` recorder, or
        None when the live oscillatory ablation is disabled. The composition root
        attaches it to the cycle via ``cycle.set_ablation_recorder`` after build."""
        return self._ablation_observer.record if self._ablation_observer else None

    @property
    def _research_active(self) -> bool:
        """True when any research-event-log component is enabled, regardless of
        the evaluation sidecar master flag."""
        return bool(
            self._research_cfg.enabled or self._research_cfg.raw_archive.enabled
        )

    @property
    def observers(self) -> list[Any]:
        return list(self._observers)

    @property
    def prediction_error_observer(self) -> "PredictionErrorObserver | None":
        return self._prediction_error_observer

    @property
    def welfare_observer(self) -> "WelfareObserver | None":
        return self._welfare_observer

    def _make_sink(self, subdir: str, name: str) -> AsyncJsonlSink:
        paths = self._config.paths
        if subdir == "_trajectory_root":
            root = Path(paths.trajectory_dir)
        else:
            root = Path(paths.evaluation_logs) / subdir
        sink = AsyncJsonlSink(
            root, name=name, retention_days=paths.retention_days
        )
        self._sinks.append(sink)
        return sink

    def _embedder_default(self) -> TextEmbedder:
        if self._embedder is not None:
            return self._embedder
        try:
            return SentenceTransformerTextEmbedder()
        except Exception:
            if self._config.require_semantic_embedder:
                raise RuntimeError(
                    "require_semantic_embedder=true but SentenceTransformerTextEmbedder "
                    "failed to load; refusing to fall back to HashEmbedder (fail-closed). "
                    "Install sentence-transformers or set require_semantic_embedder=false."
                ) from None
            log.error(
                "SentenceTransformerTextEmbedder failed to load — falling back to "
                "HashEmbedder. WARNING: A/B-divergence and memory-probe cosine metrics "
                "will be LEXICAL token-hash similarity, NOT semantic similarity. "
                "All records will carry embedder='hash' for filtering.",
                exc_info=True,
            )
            return HashEmbedder()

    def _bare_client_default(self) -> BareInferenceClient:
        if self._bare_client is not None:
            return self._bare_client
        return HTTPBareInferenceClient(
            base_url=self._config.chat_url,
            model_id=self._config.chat_model_id,
            timeout_s=self._config.chat_timeout_s,
            think=self._config.chat_think,
            api_key=self._config.chat_api_key,
        )

    def _make_sink_at(self, dir_path: str, name: str, retention_days: int) -> AsyncJsonlSink:
        """Create a sink rooted at an explicit path (used by the research event
        log and the local-only raw archive, which set their own directories
        rather than living under ``paths.evaluation_logs/<subdir>``)."""
        sink = AsyncJsonlSink(
            Path(dir_path), name=name, retention_days=int(retention_days)
        )
        self._sinks.append(sink)
        return sink

    def _build_research_components(self) -> None:
        """Construct the curated research event observer and/or the local-only
        raw archive consumer, each on its OWN config gate — independent of the
        evaluation sidecar master flag (``self._config.enabled``)."""
        rcfg = self._research_cfg
        if rcfg.enabled:
            sink = self._make_sink_at(
                rcfg.log_dir, "research_events", rcfg.retention_days
            )
            self._observers.append(ResearchEventObserver(self._bus, sink))
        if rcfg.raw_archive.enabled:
            # LOCAL-ONLY, never export-eligible — path is outside data/evaluation/.
            sink = self._make_sink_at(
                rcfg.raw_archive.archive_dir,
                "raw_bus_archive",
                rcfg.raw_archive.retention_days,
            )
            self._observers.append(
                RawBusArchiveConsumer(self._bus, sink, rcfg.raw_archive)
            )

    def build(self) -> None:
        # The research event log is gated independently of the evaluation
        # sidecar, so build its components even when [evaluation].enabled=false.
        self._build_research_components()
        if not self._config.enabled:
            return
        config = self._config
        if config.workspace_trajectory:
            sink = self._make_sink("_trajectory_root", "trajectory")
            self._observers.append(
                TrajectoryRecorder(
                    self._bus, sink, thymos_state_provider=self._thymos_provider
                )
            )
        if config.module_attribution:
            sink = self._make_sink("attribution", "attribution")
            self._observers.append(AttributionRecorder(self._bus, sink))
        if config.proactive_audit:
            sink = self._make_sink("proactive_audit", "proactive_audit")
            self._observers.append(
                ProactiveAuditObserver(
                    self._bus,
                    sink,
                    thymos_state_provider=self._thymos_provider,
                    last_user_input_provider=self._last_input_provider,
                )
            )
        if config.sleep_snapshots:
            sink = self._make_sink("sleep_snapshots", "sleep_snapshots")
            self._observers.append(
                SleepSnapshotRecorder(
                    self._bus, sink, state_provider=self._sleep_state_provider
                )
            )
        if config.voice_tracking:
            sink = self._make_sink("voice_tracking", "voice_tracking")
            self._observers.append(VoiceTrackingObserver(self._bus, sink))
        if config.oscillatory_ablation:
            # Recorder, not a bus subscriber: its record() is handed to the cycle
            # via ablation_recorder; only its sink joins the managed lifecycle.
            sink = self._make_sink("ablation", "ablation")
            self._ablation_observer = AblationObserver(sink)
        if config.affect_correlation:
            sink = self._make_sink("affect_correlation", "affect_correlation")
            self._observers.append(
                AffectCorrelationRecorder(
                    self._bus, sink, thymos_state_provider=self._thymos_provider
                )
            )
        if config.ab_divergence:
            sink = self._make_sink("ab_divergence", "ab_divergence")
            self._observers.append(
                ABDivergenceObserver(
                    self._bus,
                    sink,
                    embedder=self._embedder_default(),
                    client=self._bare_client_default(),
                    sample_rate=config.ab_sample_rate,
                    last_user_input_provider=self._last_input_provider,
                )
            )
        if config.memory_probes and self._memory_source and self._cognitive_client:
            sink = self._make_sink("memory_probes", "memory_probes")
            self._observers.append(
                MemoryProbeRunner(
                    sink,
                    memory_source=self._memory_source,
                    cognitive_client=self._cognitive_client,
                    bare_client=self._bare_client_default(),
                    embedder=self._embedder_default(),
                    interval_seconds=config.memory_probe_interval_minutes * 60.0,
                    context_window_seconds=config.llm_context_window_seconds,
                )
            )
        if config.eidolon_accuracy and self._cognitive_client:
            sink = self._make_sink("eidolon_accuracy", "eidolon_accuracy")
            self._observers.append(
                EidolonAccuracyRunner(
                    sink,
                    cognitive_client=self._cognitive_client,
                    evaluation_logs_dir=Path(config.paths.evaluation_logs),
                    interval_seconds=config.eidolon_accuracy_interval_hours * 3600.0,
                )
            )

        # --- sidecar observers (all gated by config.observers toggles) ---
        obs_cfg = config.observers
        if obs_cfg.coherence:
            sink = self._make_sink("coherence", "coherence")
            self._observers.append(CoherenceObserver(self._bus, sink))
        if obs_cfg.replay:
            sink = self._make_sink("replay", "replay")
            # ReplayObserver is a composite of two StreamSubscriberObservers
            # (mnemos + phantasia).  Register the inner observers so the
            # registry lifecycle (start/stop, _task checks) works uniformly.
            replay_wrapper = ReplayObserver(
                self._bus, sink, redact_content=obs_cfg.replay_redact_content
            )
            self._observers.append(replay_wrapper._mnemos)
            self._observers.append(replay_wrapper._phantasia)
        if obs_cfg.empatheia:
            sink = self._make_sink("empatheia", "empatheia")
            self._observers.append(EmpatheiaObserver(self._bus, sink))
        if obs_cfg.voice_alignment_divergence:
            sink = self._make_sink(
                "voice_alignment_divergence", "voice_alignment_divergence"
            )
            self._observers.append(
                VoiceAlignmentDivergenceObserver(self._bus, sink)
            )
        if obs_cfg.fatigue:
            sink = self._make_sink("fatigue", "fatigue")
            self._observers.append(FatigueObserver(self._bus, sink))
        if obs_cfg.prediction_error:
            sink = self._make_sink("prediction_error", "prediction_error")
            pe_obs = PredictionErrorObserver(self._bus, sink)
            self._prediction_error_observer = pe_obs
            self._observers.append(pe_obs)
        if obs_cfg.welfare:
            sink = self._make_sink("welfare", "welfare")
            wf_cfg = self._config.welfare
            wf_obs = WelfareObserver(
                self._bus,
                sink,
                interoceptive_distress_threshold=wf_cfg.interoceptive_distress_threshold,
                interoceptive_distress_duration_s=wf_cfg.interoceptive_distress_duration_s,
            )
            self._welfare_observer = wf_obs
            self._observers.append(wf_obs)
        if obs_cfg.nous_policy:
            sink = self._make_sink("nous_policy", "nous_policy")
            self._observers.append(NousPolicyObserver(self._bus, sink))

    async def start(self) -> None:
        # Start when the evaluation sidecar OR any research-event-log component
        # is enabled — the research log is independent of [evaluation].enabled.
        if self._started or not (self._config.enabled or self._research_active):
            return
        if not self._observers:
            self.build()
        for sink in self._sinks:
            await sink.start()
        for observer in self._observers:
            await observer.start()
        self._started = True
        log.info("sidecar started with %d observers", len(self._observers))

    async def stop(self) -> None:
        if not self._started:
            return
        for observer in self._observers:
            try:
                await observer.stop()
            except Exception:
                log.warning("observer %s stop failed", observer.name, exc_info=True)
        for sink in self._sinks:
            try:
                await sink.stop()
            except Exception:
                log.warning("sink %s stop failed", sink.name, exc_info=True)
        self._started = False
