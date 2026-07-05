# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, ClassVar, Optional

from kaine.bus.client import AsyncBus
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule
from kaine.modules.hypnos.phases import (
    PhaseResult,
    affective_reset,
    associative_replay,
    deep_consolidation,
    light_consolidation,
)
from kaine.modules.hypnos.scheduler import RestScheduler
from kaine.modules.hypnos.voice_alignment import (
    ConsolidationDivergence,
    DPOPairBuilder,
    FakeTrainer,
    Trainer,
    TrainingResult,
    VoiceAlignmentConfig,
    consolidation_magnitude,
    operator_approved,
    write_consolidation_divergence,
)

log = logging.getLogger(__name__)


class HypnosBusyError(RuntimeError):
    """Raised when enter_sleep() is invoked while sleep is in progress."""


class Hypnos(BaseModule):
    name: ClassVar[str] = "hypnos"

    def holds_external_resources(self) -> bool:
        return True

    def __init__(
        self,
        bus: AsyncBus,
        *,
        mnemos: Optional[Any] = None,
        nous_process: Optional[Any] = None,
        thymos: Optional[Any] = None,
        chronos_resetters: Optional[list[Any]] = None,
        trainer: Optional[Trainer] = None,
        voice_alignment_config: Optional[VoiceAlignmentConfig] = None,
        # On-device GPU window runner: an async callable
        # ``runner(train_thunk) -> (TrainingResult, OrganWindowResult)`` that
        # brackets the trainer call with the organ unload→reload time-share
        # (kaine.modules.hypnos.organ_window). Injected by boot when a real
        # trainer is wired; None → train directly with the organ resident (the
        # pre-existing behavior, e.g. FakeTrainer / tests / multi-GPU host).
        organ_window_runner: Optional[Any] = None,
        # Boundary-neutral semantic embedder for the consolidation-divergence
        # MAGNITUDE (kaine.text_embedding, never kaine.evaluation). When None,
        # the magnitude is reported null (honest degradation). Defaults to the
        # semantic embedder; tests inject a HashEmbedder or None.
        consolidation_embedder: Optional[Any] = None,
        consolidation_divergence_path: Optional[Path] = None,
        scheduler: Optional[RestScheduler] = None,
        interval_seconds: float = 3600.0,
        max_deferral_seconds: float = 600.0,
        per_defer_seconds: float = 60.0,
        nous_step_burst: int = 200,
        baseline_salience: float = 0.5,
        alert_salience: float = 0.8,
        # Consolidation config (hypnos-fatigue-phases)
        fatigue_triggered: bool = True,
        downscale_factor: float = 0.9,
        replay_window_s: float = 5.0,
        # Phase-3 associative replay (hypnos-consolidation)
        associative_replay_enabled: bool = False,
        phantasia: Optional[Any] = None,
        # Active-module registry for oscillator hook (phase 1)
        active_modules: Optional[list[Any]] = None,
        # Perception locus path (for suspension during replay window)
        perception_desired_path: Optional[Path] = None,
        # Shared subjective clock (injected at boot). The rest scheduler's
        # sleep-due interval + deferral window model the ENTITY'S rest, so they
        # run in subjective time — at time_scale != 1.0 the entity's sleep
        # pressure builds at the dilated rate, coherent with fatigue. Wired into
        # the RestScheduler's clock when no scheduler is injected. The sleep
        # pipeline's own elapsed_ms / started_at stamps stay on REAL time (they
        # measure infrastructure latency, like the cycle slip). Defaults to a
        # real-time clock → behavior-identical.
        entity_clock: Optional[EntityClock] = None,
    ) -> None:
        super().__init__(bus)
        if not 0.0 <= baseline_salience <= 1.0:
            raise ValueError("baseline_salience must be in [0, 1]")
        if not 0.0 <= alert_salience <= 1.0:
            raise ValueError("alert_salience must be in [0, 1]")
        if not 0.0 < downscale_factor <= 1.0:
            raise ValueError("downscale_factor must be in (0, 1]")
        self._mnemos = mnemos
        self._nous_process = nous_process
        self._thymos = thymos
        self._chronos_resetters = list(chronos_resetters or [])
        self._trainer: Trainer = trainer or FakeTrainer()
        self._organ_window_runner = organ_window_runner
        self._voice_config: VoiceAlignmentConfig = (
            voice_alignment_config
            or VoiceAlignmentConfig(
                intent_log_path=Path("state/lingua/intent_expression.jsonl"),
                adapter_output_dir=Path("state/hypnos/adapters"),
            )
        )
        self._clock = entity_clock or EntityClock()
        self._scheduler = scheduler or RestScheduler(
            interval_seconds=interval_seconds,
            max_deferral_seconds=max_deferral_seconds,
            per_defer_seconds=per_defer_seconds,
            # Subjective time: the sleep-due interval and deferral window run on
            # the entity's clock, so dilation moves rest pressure coherently
            # with fatigue. At scale 1.0 the clock reads real elapsed seconds, so
            # the schedule is unchanged.
            clock=self._clock.now,
        )
        self._nous_step_burst = int(nous_step_burst)
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        # Consolidation config
        self._fatigue_triggered = bool(fatigue_triggered)
        self._downscale_factor = float(downscale_factor)
        self._replay_window_s = float(replay_window_s)
        # Phase-3 associative replay
        self._associative_replay_enabled = bool(associative_replay_enabled)
        self._phantasia = phantasia
        # Module registry for oscillator hook
        self._active_modules: list[Any] = list(active_modules or [])
        # Perception locus path
        self._perception_desired_path = perception_desired_path

        self._sleep_lock = asyncio.Lock()
        self._builder = DPOPairBuilder()
        self._last_sleep_at: Optional[float] = None
        # Consolidation-divergence magnitude embedder + persisted state path.
        # The embedder lives in the boundary-neutral kaine.text_embedding so
        # Hypnos (core) never imports kaine.evaluation. Injected by the cycle
        # entrypoint (the semantic embedder, so magnitude is on the SAME scale
        # as the A/B meter) — mirroring how the A/B observer's embedder is wired
        # at the entrypoint, not defaulted in the module. When None the
        # magnitude is reported null (honest degradation); the rate/counts are
        # always emitted.
        self._consolidation_embedder: Any = consolidation_embedder
        self._consolidation_divergence_path = consolidation_divergence_path
        self._sleep_count: int = 0

        # Fatigue trigger state
        self._soma_cursor: str = "0"
        self._fatigue_triggered_sleep: bool = False  # did fatigue fire this cycle?

    @property
    def scheduler(self) -> RestScheduler:
        return self._scheduler

    @property
    def trainer(self) -> Trainer:
        return self._trainer

    @property
    def is_sleeping(self) -> bool:
        return self._sleep_lock.locked()

    def try_defer(self) -> bool:
        return self._scheduler.try_defer()

    def is_due(self) -> bool:
        return self._scheduler.is_due()

    async def initialize(self) -> None:
        await super().initialize()
        if self._fatigue_triggered:
            # Seed cursor so we only process new soma events from now on.
            try:
                latest = await self._bus.client.xrevrange("soma.out", count=1)
            except Exception:
                latest = []
            if latest:
                entry_id = latest[0][0]
                if isinstance(entry_id, bytes):
                    entry_id = entry_id.decode()
                self._soma_cursor = entry_id
            self._tasks.append(
                asyncio.create_task(
                    self._soma_consumer_loop(), name="hypnos-soma-consumer"
                )
            )

    async def _soma_consumer_loop(self) -> None:
        """Background loop: watch soma.out for maintenance triggers.

        Two event shapes on ``soma.out`` trigger an immediate maintenance
        cycle when Hypnos is not already sleeping (subject to the same
        non-interruptibility / freeze-preemption guards as the interval-based
        trigger):

        * ``soma.fatigue`` with ``crossed == true`` — the fatigue accumulator
          crossed its maintenance threshold.
        * ``soma.regulation`` with ``action == "request_maintenance"`` — the
          homeostatic regulator escalated to requesting an earlier offline
          cycle.  The linkage is event-driven: Hypnos observes the advisory
          directly on ``soma.out`` (the cycle engine separately latches an
          advisory ``maintenance_requested`` flag for diagnostics, but Hypnos
          does not read that flag).
        """
        try:
            while not self._stopped.is_set():
                try:
                    entries = await self._bus.read(
                        "soma.out",
                        last_id=self._soma_cursor,
                        count=32,
                        block_ms=0,
                    )
                    if entries:
                        self._soma_cursor = entries[-1][0]
                        for _, event in entries:
                            fatigue_trigger = (
                                event.type == "soma.fatigue"
                                and event.payload.get("crossed", False)
                            )
                            regulation_trigger = (
                                event.type == "soma.regulation"
                                and event.payload.get("action")
                                == "request_maintenance"
                            )
                            if not (fatigue_trigger or regulation_trigger):
                                continue
                            if fatigue_trigger:
                                log.info(
                                    "hypnos: soma.fatigue crossed=true — "
                                    "triggering fatigue-driven maintenance"
                                )
                            else:
                                log.info(
                                    "hypnos: soma.regulation request_maintenance "
                                    "— triggering regulation-driven maintenance"
                                )
                            if not self._sleep_lock.locked():
                                asyncio.create_task(
                                    self._fatigue_triggered_enter_sleep(),
                                    name="hypnos-fatigue-sleep",
                                )
                    else:
                        await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("hypnos soma consumer iteration failed")
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise

    async def _fatigue_triggered_enter_sleep(self) -> None:
        """Fire a maintenance cycle in response to soma.fatigue threshold crossing."""
        try:
            self._fatigue_triggered_sleep = True
            await self.enter_sleep()
        except HypnosBusyError:
            log.debug("hypnos: fatigue trigger: already sleeping")
        except Exception:
            log.exception("hypnos: fatigue-triggered sleep failed")
        finally:
            self._fatigue_triggered_sleep = False

    async def enter_sleep(self) -> dict[str, Any]:
        """Run the five-phase sleep pipeline. Returns a summary dict."""
        if self._sleep_lock.locked():
            raise HypnosBusyError("Hypnos sleep is already in progress")

        async with self._sleep_lock:
            return await self._run_pipeline()

    def _suspend_perception(self) -> None:
        """Set locus to 'off' to suspend external perception during replay window.

        Reuses the perception_state.write_desired_locus machinery (the same
        path used by PerceptionLocus and the Nexus operator toggle).  Zero
        raw-sense-data persistence is preserved: we only write the desired
        locus flag, never any sensory content.
        """
        try:
            from kaine.perception_state import write_desired_locus
            write_desired_locus("off", path=self._perception_desired_path)
            log.debug("hypnos: perception locus -> off (replay window)")
        except Exception:
            log.warning(
                "hypnos: perception suspension (write_desired_locus) failed",
                exc_info=True,
            )

    def _restore_perception(self) -> None:
        """Restore locus to 'physical' after the replay window ends."""
        try:
            from kaine.perception_state import write_desired_locus
            write_desired_locus("physical", path=self._perception_desired_path)
            log.debug("hypnos: perception locus -> physical (replay window closed)")
        except Exception:
            log.warning(
                "hypnos: perception restore (write_desired_locus) failed",
                exc_info=True,
            )

    async def _reinject_association(self, scenario: dict[str, Any]) -> None:
        """Re-inject a phase-3 cross-period association into the workspace.

        Published as ``hypnos.association`` on the Hypnos out-stream; the
        syneidesis broadcast then surfaces it to Nous (pymdp belief update)
        and Thymos (re-appraisal) through the NORMAL cognitive cycle — there
        is no separate belief-revision burst.  Carries only compact scenario
        descriptors (no raw sense data); zero-persistence invariant holds.
        """
        await self.publish(
            "hypnos.association",
            dict(scenario),
            salience=self._baseline_salience,
        )

    async def _run_pipeline(self) -> dict[str, Any]:
        # Pipeline latency + the started_at/last_sleep_at marks measure REAL
        # infrastructure wall-time (how long the sleep work actually took / when
        # it ran), like the cycle's slip measurement — never the subjective
        # clock. Only the sleep-DUE scheduling (RestScheduler, above) is
        # subjective.
        # infrastructural: real time, not subjective
        start = time.monotonic()
        await self.publish(
            "hypnos.sleep.started",
            {"started_at": time.time()},  # infrastructural: real time
            salience=self._baseline_salience,
        )
        phase_results: list[PhaseResult] = []

        # --- Phase 1: Light Consolidation ---
        # Weak-trace decay + strong-trace tagging + oscillator frequency hook
        phase_results.append(
            await light_consolidation(
                self._mnemos,
                active_modules=self._active_modules,
                frequency_scale=0.5,
            )
        )

        # --- Phase 2: Deep Consolidation + Downscaling ---
        # Global activation downscaling; perception suspended during replay window.
        phase_results.append(
            await deep_consolidation(
                self._mnemos,
                downscale_factor=self._downscale_factor,
                suspend_perception=self._suspend_perception,
                restore_perception=self._restore_perception,
                replay_window_s=self._replay_window_s,
            )
        )

        # --- Phase 3: Associative Replay (cross-period; behind feature flag) ---
        # Selects cross-period traces, cues Phantasia, and re-injects the
        # resulting novel associations into the workspace so Nous (pymdp) and
        # Thymos process them via the NORMAL cognitive cycle — no NAR burst.
        phase_results.append(
            await associative_replay(
                enabled=self._associative_replay_enabled,
                mnemos=self._mnemos,
                phantasia=self._phantasia,
                reinject=self._reinject_association,
            )
        )

        # --- Phase 4: Affective Reset + (implicit) Soma fatigue reset ---
        # The Soma fatigue accumulator is reset via the hypnos.sleep.completed
        # event that Soma subscribes to (soma-forward-model-fatigue wiring).
        # Publishing that event at the end of this pipeline zeroes Soma's
        # FatigueAccumulator without requiring a direct module reference.
        phase_results.append(await affective_reset(self._thymos))

        # --- Phase 5: Voice Alignment ---
        voice_result, voice_phase = await self._run_voice_alignment()
        phase_results.append(voice_phase)

        elapsed_ms = (time.monotonic() - start) * 1000.0
        self._last_sleep_at = time.time()
        self._scheduler.mark_completed()

        summary = {
            "total_elapsed_ms": elapsed_ms,
            "phases": [asdict(r) for r in phase_results],
            "voice_alignment": {
                "accepted": voice_result.accepted,
                "adapter_path": str(voice_result.adapter_path) if voice_result.adapter_path else None,
                "capability_loss": voice_result.capability_loss,
                "reason": voice_result.reason,
                "samples_used": voice_result.samples_used,
            },
            # Top-level keys for the evaluation sidecar's voice_tracking
            # observer; reflect TrainingResult fields one-for-one so
            # voice-tracking samples land non-None once training is
            # really running.
            "pairs_processed": voice_result.samples_used,
            "pairs_above_threshold": voice_result.samples_used,
            "dpo_loss": voice_result.dpo_loss,
            "adapter_accepted": voice_result.accepted,
            "capability_score_before": voice_result.capability_score_before,
            "capability_score_after": voice_result.capability_score_after,
            "mean_intent_expression_similarity_before": (
                voice_result.mean_intent_expression_similarity_before
            ),
            "mean_intent_expression_similarity_after": (
                voice_result.mean_intent_expression_similarity_after
            ),
            # Whether this cycle was fatigue-triggered
            "fatigue_triggered": self._fatigue_triggered_sleep,
        }
        all_succeeded = all(r.success for r in phase_results)
        salience = (
            self._baseline_salience if all_succeeded else self._alert_salience
        )
        # Publishing hypnos.sleep.completed causes Soma to reset its
        # FatigueAccumulator (soma._hypnos_event_loop handles this event).
        await self.publish("hypnos.sleep.completed", summary, salience=salience)
        return summary

    async def _emit_consolidation_divergence(
        self,
    ) -> tuple[list[Any], dict[str, Any]]:
        """Build the DPO pairs and surface the content-free divergence metric.

        Computed EVERY sleep — before the two-layer safety gate — so the
        organ-level divergence signal is emitted even when training is
        skipped/disabled or the adapter is later rejected (the divergence
        happened independent of whether the organ was retrained).

        Returns ``(pairs, metric_payload)``. ``pairs`` is reused by the training
        path so the log is not scanned twice; ``metric_payload`` is the
        content-free aggregate dict merged into the phase metadata. The metric
        is published on ``hypnos.consolidation_divergence`` and persisted to a
        small state file for the core ``assess_divergence`` to read.

        Boundary: only counts + a scalar magnitude leave here. The magnitude is
        computed with the boundary-neutral ``kaine.text_embedding`` embedder —
        Hypnos never imports ``kaine.evaluation``. NEVER the prompt/chosen/
        rejected utterance text.
        """
        self._sleep_count += 1
        try:
            pairs, scanned, usable = self._builder.build_with_counts(
                self._voice_config.intent_log_path,
                max_pairs=self._voice_config.max_samples,
            )
        except Exception:
            log.warning(
                "consolidation divergence: pair build failed", exc_info=True
            )
            pairs, scanned, usable = [], 0, 0
        rate = usable / max(1, scanned)
        magnitude, embedder_kind = await consolidation_magnitude(
            pairs, embedder=self._consolidation_embedder
        )
        metric = ConsolidationDivergence(
            records_scanned=scanned,
            usable_pairs=usable,
            divergence_rate=rate,
            divergence_magnitude=magnitude,
            embedder=embedder_kind,
        )
        payload = metric.as_payload()
        payload["sleep_index"] = self._sleep_count
        # Persist for the core lifecycle assessment (boundary-neutral seam: a
        # written record, not an import).
        kwargs: dict[str, Any] = {"sleep_index": self._sleep_count}
        if self._consolidation_divergence_path is not None:
            kwargs["path"] = self._consolidation_divergence_path
        write_consolidation_divergence(metric, **kwargs)
        # Content-free bus event (rides the existing metric path).
        await self.publish(
            "hypnos.consolidation_divergence",
            dict(payload),
            salience=self._baseline_salience,
        )
        return pairs, payload

    async def _run_voice_alignment(self) -> tuple[TrainingResult, PhaseResult]:
        start_ms = time.monotonic() * 1000.0
        # Surface the organ-level divergence metric FIRST — unconditionally, on
        # every sleep — so it is emitted even when training is skipped/disabled
        # or the adapter is rejected below.
        pairs, divergence_payload = await self._emit_consolidation_divergence()

        def _meta(extra: dict[str, Any]) -> dict[str, Any]:
            merged = {"consolidation_divergence": dict(divergence_payload)}
            merged.update(extra)
            return merged

        # Two-layer safety gate. Both `[hypnos.voice_alignment].enabled`
        # AND the env var KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1
        # must be set. Mirrors KAINE_CYCLE_OPERATOR_PRESENT for first boot.
        if not self._voice_config.enabled:
            skip_reason = "config disabled"
            log.info("voice_alignment skipped: %s", skip_reason)
            voice_result = TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason=f"skipped: {skip_reason}",
                samples_used=0,
            )
            return voice_result, PhaseResult(
                phase="voice_alignment",
                success=True,
                elapsed_ms=time.monotonic() * 1000.0 - start_ms,
                metadata=_meta({"skipped": skip_reason, "training_skipped": True}),
            )
        if not operator_approved():
            skip_reason = (
                "operator approval not granted "
                "(set KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1)"
            )
            log.warning("voice_alignment skipped: %s", skip_reason)
            voice_result = TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason=f"skipped: {skip_reason}",
                samples_used=0,
            )
            return voice_result, PhaseResult(
                phase="voice_alignment",
                success=True,
                elapsed_ms=time.monotonic() * 1000.0 - start_ms,
                metadata=_meta({"skipped": skip_reason, "training_skipped": True}),
            )
        if not pairs:
            voice_result = TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason="no usable DPO pairs in intent-expression log",
                samples_used=0,
            )
            return voice_result, PhaseResult(
                phase="voice_alignment",
                success=True,
                elapsed_ms=time.monotonic() * 1000.0 - start_ms,
                metadata=_meta({"pairs": 0, "training_skipped": True}),
            )
        window_meta: dict[str, Any] = {}
        try:

            async def _train() -> TrainingResult:
                return await self._trainer.train(pairs, self._voice_config)

            if self._organ_window_runner is not None:
                # On-device GPU window: the runner brackets the trainer call with
                # the organ unload→reload time-share (or skips it on a multi-GPU /
                # manual host). It ALWAYS reloads a working organ before returning,
                # even on a training crash/timeout, so the entity is never left
                # voiceless on wake.
                voice_result, window = await self._organ_window_runner(_train)
                window_meta = {
                    "organ_window_bracketed": window.bracketed,
                    "organ_restored": window.organ_restored,
                }
                if window.skipped_reason:
                    window_meta["organ_window_skipped"] = window.skipped_reason
                if window.error:
                    window_meta["organ_window_error"] = window.error
                if voice_result is None:
                    # Training crashed inside the window; the organ was reloaded.
                    voice_result = TrainingResult(
                        accepted=False,
                        adapter_path=None,
                        capability_loss=0.0,
                        reason=f"training failed in organ window: {window.error}",
                        samples_used=len(pairs),
                    )
                    return voice_result, PhaseResult(
                        phase="voice_alignment",
                        success=False,
                        elapsed_ms=time.monotonic() * 1000.0 - start_ms,
                        error=voice_result.reason,
                        metadata=_meta(window_meta),
                    )
            else:
                voice_result = await _train()
        except Exception as exc:
            log.exception("voice_alignment trainer raised")
            voice_result = TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason=f"trainer raised: {type(exc).__name__}: {exc}",
                samples_used=len(pairs),
            )
            return voice_result, PhaseResult(
                phase="voice_alignment",
                success=False,
                elapsed_ms=time.monotonic() * 1000.0 - start_ms,
                error=voice_result.reason,
                metadata=_meta(window_meta),
            )
        # Capability-loss veto.
        if (
            voice_result.accepted
            and voice_result.capability_loss > self._voice_config.capability_loss_threshold
        ):
            log.warning(
                "voice alignment rejected: capability loss %.4f > threshold %.4f",
                voice_result.capability_loss,
                self._voice_config.capability_loss_threshold,
            )
            voice_result = TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=voice_result.capability_loss,
                reason=(
                    f"capability loss {voice_result.capability_loss:.4f} "
                    f"exceeds threshold {self._voice_config.capability_loss_threshold:.4f}"
                ),
                samples_used=voice_result.samples_used,
                metadata=voice_result.metadata,
            )
        phase_meta = {
            "pairs": len(pairs),
            "accepted": voice_result.accepted,
            "reason": voice_result.reason,
        }
        phase_meta.update(window_meta)
        return voice_result, PhaseResult(
            phase="voice_alignment",
            success=True,
            elapsed_ms=time.monotonic() * 1000.0 - start_ms,
            metadata=_meta(phase_meta),
        )

    def serialize(self) -> dict[str, Any]:
        return {
            "last_sleep_at": self._last_sleep_at,
            "original_due_at": self._scheduler.original_due_at,
            "effective_due_at": self._scheduler.effective_due_at,
        }

    def deserialize(self, state: dict[str, Any]) -> None:
        if "last_sleep_at" in state:
            value = state["last_sleep_at"]
            self._last_sleep_at = None if value is None else float(value)
