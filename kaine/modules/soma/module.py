# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any, ClassVar, Optional

from kaine.bus.client import AsyncBus
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule
from kaine.modules.soma.detector import (
    AnomalyDetector,
    ThresholdAnomalyDetector,
)
from kaine.modules.soma.fatigue import FatigueAccumulator
from kaine.modules.soma.forward import (
    DEFAULT_FEATURE_DIM,
    SubstrateForwardModel,
    metrics_to_feature_vector,
)
from kaine.modules.soma.reader import MetricsReader, SystemMetricsReader
from kaine.modules.soma.regulation import RegulationDetector
from kaine.modules.soma.wellness import compute_wellness

log = logging.getLogger(__name__)


DEFAULT_THRESHOLDS: dict[str, float] = {
    "cpu_percent": 90.0,
    "ram_percent": 90.0,
    "gpu_*_temp_c": 83.0,
    "gpu_*_vram_percent": 92.0,
    "cycle_latency_avg_ms": 600.0,
}

DEFAULT_WEIGHTS: dict[str, float] = {
    "cpu_percent": 1.0,
    "ram_percent": 1.0,
    "cycle_latency_avg_ms": 1.0,
}


class Soma(BaseModule):
    name: ClassVar[str] = "soma"

    def __init__(
        self,
        bus: AsyncBus,
        *,
        reader: Optional[MetricsReader] = None,
        detector: Optional[AnomalyDetector] = None,
        read_interval_s: float = 1.0,
        weights: Optional[dict[str, float]] = None,
        thresholds: Optional[dict[str, float]] = None,
        cycle_latency_target_ms: float = 300.0,
        cycle_latency_window: int = 64,
        baseline_salience: float = 0.1,
        alert_salience: float = 0.7,
        cycle_stream: str = "cycle.out",
        # --- Forward model / fatigue / regulation config ---
        forward_model_units: int = 32,
        prediction_error_window: int = 32,
        fatigue_decay_per_s: float = 0.01,
        fatigue_maintenance_threshold: float = 100.0,
        regulation_sustain_window_s: float = 30.0,
        regulation_threshold: float = 0.5,
        # --- Developmental warm-up (soma-coldstart-regulation-warmup) ---
        # While the interoceptive forward model is still learning this host's
        # substrate baseline, WITHHOLD the punitive allostatic actions its
        # (untrained) prediction error would trigger and DAMPEN its inflation of
        # the fatigue accumulator. The prediction-error signal itself is never
        # altered, and the absolute [soma.thresholds] limits are never gated
        # (see tick_once). Grounded in the paper's warmed-up-signal logic.
        regulation_warmup_enabled: bool = True,
        regulation_warmup_min_samples: int = 1000,
        regulation_warmup_min_seconds: float = 1200.0,
        regulation_warmup_require_error_stabilized: bool = False,
        regulation_warmup_stable_window: int = 32,
        regulation_warmup_stable_variance: float = 0.02,
        # Shared subjective clock (injected at boot). The fatigue accumulator's
        # dt integral and the interoception sampling cadence are COGNITIVE
        # timers and so run in subjective time: at time_scale != 1.0 fatigue
        # accrues — and Soma samples — at the dilated rate, coherently with the
        # rest of the mind. Defaults to a real-time clock so standalone use and
        # the existing tests are behavior-identical.
        entity_clock: Optional[EntityClock] = None,
    ) -> None:
        super().__init__(bus)
        if read_interval_s <= 0:
            raise ValueError("read_interval_s must be positive")
        if not 0.0 <= baseline_salience <= 1.0:
            raise ValueError("baseline_salience must be in [0, 1]")
        if not 0.0 <= alert_salience <= 1.0:
            raise ValueError("alert_salience must be in [0, 1]")
        # When no reader is injected, size the latency-averaging window from
        # config. An injected reader (e.g. in tests) brings its own window.
        self._reader: MetricsReader = reader or SystemMetricsReader(
            cycle_latency_window=int(cycle_latency_window)
        )
        self._detector: AnomalyDetector = detector or ThresholdAnomalyDetector(
            thresholds or DEFAULT_THRESHOLDS
        )
        self._read_interval_s = float(read_interval_s)
        self._clock = entity_clock or EntityClock()
        self._weights = dict(weights) if weights is not None else dict(DEFAULT_WEIGHTS)
        self._cycle_latency_target_ms = float(cycle_latency_target_ms)
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        self._cycle_stream = cycle_stream
        self._cycle_cursor = "0"

        # --- Predictive interoception ---
        self._forward_model = SubstrateForwardModel(
            feature_dim=DEFAULT_FEATURE_DIM,
            units=int(forward_model_units),
        )
        self._prediction_error_window: deque[float] = deque(
            maxlen=int(prediction_error_window)
        )
        self._last_prediction_error: float = 0.0

        # --- Fatigue accumulator ---
        self._fatigue = FatigueAccumulator(
            decay_per_s=float(fatigue_decay_per_s),
            maintenance_threshold=float(fatigue_maintenance_threshold),
        )
        self._fatigue_threshold_emitted: bool = False

        # --- Homeostatic regulation ---
        self._regulation = RegulationDetector(
            threshold=float(regulation_threshold),
            sustain_window_s=float(regulation_sustain_window_s),
        )

        # --- Developmental warm-up state ---
        # A grace window applied ONLY to the action path (regulation advisories +
        # fatigue-accumulator input) while the forward model learns the host
        # baseline. It NEVER touches the signal path (soma.report / soma.fatigue),
        # and a live hard-threshold breach overrides it unconditionally.
        if regulation_warmup_min_samples < 0:
            raise ValueError("regulation_warmup_min_samples must be >= 0")
        if regulation_warmup_min_seconds < 0:
            raise ValueError("regulation_warmup_min_seconds must be >= 0")
        if regulation_warmup_stable_window <= 0:
            raise ValueError("regulation_warmup_stable_window must be positive")
        if regulation_warmup_stable_variance < 0:
            raise ValueError("regulation_warmup_stable_variance must be >= 0")
        self._warmup_enabled = bool(regulation_warmup_enabled)
        self._warmup_min_samples = int(regulation_warmup_min_samples)
        self._warmup_min_seconds = float(regulation_warmup_min_seconds)
        self._warmup_require_error_stabilized = bool(
            regulation_warmup_require_error_stabilized
        )
        self._warmup_stable_window = int(regulation_warmup_stable_window)
        self._warmup_stable_variance = float(regulation_warmup_stable_variance)
        # Runtime warm-up bookkeeping (ephemeral, per-boot / per-fork — never
        # serialised, so a fork boots its own developmental window on its own
        # subjective clock; see design §9.5).
        self._samples_seen: int = 0
        self._boot_subjective_time: Optional[float] = None
        self._warmup_started_emitted: bool = False
        self._warmup_completed: bool = False

        # --- Hypnos sleep flag ---
        self._in_hypnos: bool = False

        # --- Hypnos event consumer ---
        self._hypnos_cursor: str = "0"

    # ------------------------------------------------------------------
    # Developmental warm-up (soma-coldstart-regulation-warmup)
    #
    # EMERGENT-NOT-HARDWIRED / grounding: this is a *developmental stage*, not an
    # innate hardwired behaviour. It mirrors the paper's individuation boundary
    # (§6.6), which "warms up" its signal — "it does not read as individuated
    # until the entity has accumulated a minimum of logged lived events and a
    # minimum of lived running time, so a just-booted or sensory-starved entity
    # never trips a false individuation." We apply the identical warmed-up-signal
    # shape to Soma's allostatic regulation (§3.4.1): a just-booted entity should
    # not trip a false *substrate* alarm from a forward model that has not yet
    # learned its own body. The two thresholds below are the direct analogues of
    # "logged lived events" (adaptation samples) and "lived running time"
    # (subjective seconds on the injected EntityClock) — grounded in existing
    # architecture logic, not an arbitrary constant.
    # ------------------------------------------------------------------

    def _lived_seconds(self) -> float:
        """Subjective seconds since Soma's first tick (per-boot / per-fork)."""
        if self._boot_subjective_time is None:
            return 0.0
        return max(0.0, self._clock.now() - self._boot_subjective_time)

    def _error_stabilized(self) -> bool:
        """Optional AND-guard: recent prediction-error variance is below bound."""
        window = list(self._prediction_error_window)
        if len(window) < self._warmup_stable_window:
            return False
        recent = window[-self._warmup_stable_window :]
        mean = sum(recent) / len(recent)
        var = sum((x - mean) ** 2 for x in recent) / len(recent)
        return var <= self._warmup_stable_variance

    def _warmup_conditions_met(self) -> bool:
        """True when the §6.6-shaped end-condition is satisfied.

        Conjunction (never disjunction): BOTH a minimum number of forward-model
        adaptation samples AND a minimum of lived subjective time, plus the
        optional error-stabilization guard which can only *extend* the window.
        """
        samples_ok = self._samples_seen >= self._warmup_min_samples
        time_ok = self._lived_seconds() >= self._warmup_min_seconds
        if not (samples_ok and time_ok):
            return False
        if self._warmup_require_error_stabilized and not self._error_stabilized():
            return False
        return True

    @property
    def warmup_active(self) -> bool:
        """Whether the developmental warm-up is currently gating the action path.

        False when the feature is disabled or the warm-up has already completed
        (a latch — once warmed up, a later error destabilization can never
        re-enter warm-up, honouring "the guard can only extend, never shorten").
        """
        if not self._warmup_enabled or self._warmup_completed:
            return False
        return not self._warmup_conditions_met()

    def _warming_baseline(self, prior_errors: list[float]) -> float:
        """The forward model's current typical error (rolling mean of the prior
        window). Cold-start error hovers near this baseline uniformly, so
        subtracting it strips the model-ignorance contribution while genuine
        error *above* the baseline still accrues into fatigue."""
        if not prior_errors:
            return 0.0
        return sum(prior_errors) / len(prior_errors)

    async def initialize(self) -> None:
        await self._reader.initialize()
        await super().initialize()
        self._tasks.append(
            asyncio.create_task(self._produce_loop(), name=f"{self.name}-producer")
        )
        self._tasks.append(
            asyncio.create_task(
                self._cycle_consumer_loop(), name=f"{self.name}-cycle-consumer"
            )
        )
        self._tasks.append(
            asyncio.create_task(
                self._hypnos_event_loop(), name=f"{self.name}-hypnos-consumer"
            )
        )

    async def shutdown(self) -> None:
        await super().shutdown()
        try:
            await self._reader.shutdown()
        except Exception:
            log.warning("metrics reader shutdown failed", exc_info=True)

    async def tick_once(self) -> dict[str, Any]:
        """Read metrics, evaluate, update forward model / fatigue / regulation, publish."""
        metrics = await self._reader.read_metrics()
        wellness = compute_wellness(
            metrics,
            weights=self._weights,
            cycle_latency_target_ms=self._cycle_latency_target_ms,
        )
        alert = self._detector.evaluate(metrics)

        # --- Forward model step ---
        feature_vec = metrics_to_feature_vector(
            metrics,
            feature_dim=DEFAULT_FEATURE_DIM,
            cycle_latency_target_ms=self._cycle_latency_target_ms,
        )
        if self._in_hypnos:
            self._forward_model.suspended = True
        else:
            self._forward_model.suspended = False
        # The window as it stood BEFORE this tick's error — the warming baseline
        # is computed against prior errors so a single spike still reads as a
        # spike (see _warming_baseline / the fatigue dampening below).
        prior_errors = list(self._prediction_error_window)
        prediction_error = self._forward_model.step(feature_vec)
        self._last_prediction_error = prediction_error
        self._prediction_error_window.append(prediction_error)

        # --- Subjective clock / warm-up bookkeeping ---
        # Subjective time: the fatigue dt integral and the regulation
        # sustain-window are cognitive, so they advance at the entity's
        # time_scale (the same clock the cycle paces on). At scale 1.0 this is
        # byte-identical to the previous time.monotonic() reading.
        now = self._clock.now()
        if self._boot_subjective_time is None:
            self._boot_subjective_time = now
        # samples_seen = real forward-model adaptation steps ("logged lived
        # events" analogue). Read straight from the model so a suspended/Hypnos
        # or sensory-starved entity does not age out of warm-up.
        self._samples_seen = int(getattr(self._forward_model, "adaptation_steps", 0))

        # --- Developmental warm-up gate (ACTION PATH ONLY) ---
        # A live hard-threshold breach OVERRIDES the gate unconditionally: the
        # [soma.thresholds] limits are absolute, not learned predictions, so a
        # real substrate problem (e.g. GPU >= 83 C) always actuates and always
        # integrates fatigue at full weight, even during warm-up (design §4).
        hard_breach = alert.is_alert
        warmup_active = self.warmup_active
        gate = warmup_active and not hard_breach

        # Emit the warm-up boundary marker once, at boot.
        if warmup_active and not self._warmup_started_emitted:
            self._warmup_started_emitted = True
            await self.publish(
                "soma.warmup.started",
                {
                    "min_samples": self._warmup_min_samples,
                    "min_seconds": self._warmup_min_seconds,
                    "samples_seen": self._samples_seen,
                    "lived_seconds": self._lived_seconds(),
                },
                salience=self._baseline_salience,
            )
            log.info(
                "soma developmental warm-up STARTED "
                "(min_samples=%d, min_seconds=%.0f): withholding cold-start "
                "allostatic actions until the forward model learns the host "
                "baseline; the prediction-error signal and hard thresholds are "
                "unaffected",
                self._warmup_min_samples,
                self._warmup_min_seconds,
            )

        # --- Fatigue update (Option A: dampen the INPUT during warm-up) ---
        # We change what fatigue *is* during warm-up, not what we *report*: the
        # published fatigue_value honestly reflects the dampened accrual. The raw
        # prediction_error — the "cry" — is untouched and published in full below.
        fatigue_input = prediction_error
        if gate:
            baseline = self._warming_baseline(prior_errors)
            fatigue_input = max(0.0, prediction_error - baseline)
            if fatigue_input < prediction_error:
                log.debug(
                    "soma warm-up: fatigue input damped %.4f -> %.4f "
                    "(warming baseline=%.4f)",
                    prediction_error,
                    fatigue_input,
                    baseline,
                )
        fatigue_would_cross = self._fatigue.would_cross(fatigue_input, now=now)
        raw_would_cross = self._fatigue.would_cross(prediction_error, now=now)
        fatigue_crossed = self._fatigue.update(fatigue_input, now=now)
        if gate and raw_would_cross and not fatigue_would_cross:
            log.info(
                "soma warm-up: fatigue accumulator would have crossed the "
                "maintenance threshold on cold-start error alone (raw "
                "prediction_error=%.4f) but the dampened input held it below; "
                "no premature maintenance forced",
                prediction_error,
            )

        # --- Regulation advisory (withheld during warm-up unless overridden) ---
        advisory = self._regulation.update(prediction_error, now=now)
        withheld_advisory = None
        if advisory is not None and gate:
            withheld_advisory = advisory
            advisory = None

        # --- Build payload ---
        payload: dict[str, Any] = {
            "metrics": metrics,
            "wellness": wellness,
            "alerts": list(alert.keys),
            "prediction_error": prediction_error,
            "fatigue_value": self._fatigue.value,
            "fatigue_threshold": self._fatigue.threshold,
            "warmup_active": warmup_active,
        }

        # Salience: driven by prediction error (blended with alert).
        error_salience = self._forward_model.prediction_error_to_salience(
            prediction_error,
            self._baseline_salience,
            self._alert_salience,
            error_window=list(self._prediction_error_window),
        )
        salience = self._alert_salience if alert.is_alert else error_salience
        await self.publish("soma.report", payload, salience=salience)

        # --- Publish soma.fatigue if threshold newly crossed ---
        if fatigue_crossed and not self._fatigue_threshold_emitted:
            self._fatigue_threshold_emitted = True
            await self.publish(
                "soma.fatigue",
                {
                    "value": self._fatigue.value,
                    "threshold": self._fatigue.threshold,
                    "crossed": True,
                },
                salience=self._alert_salience,
            )
        elif self._fatigue.value < self._fatigue.threshold:
            # Reset emission guard when fatigue drops below threshold
            # (e.g. after maintenance reset).
            self._fatigue_threshold_emitted = False

        # --- Publish soma.regulation advisory if one was raised ---
        if advisory is not None:
            await self.publish(
                "soma.regulation",
                advisory,
                salience=self._alert_salience,
            )

        # --- Warm-up withheld an advisory: record it, never a silent no-op ---
        # Emitted on soma.out as a NON-ACTUATING event type (the cycle engine's
        # consume_soma_regulation ignores anything that is not `soma.regulation`),
        # so the "cry" is auditable without throttling/shedding/maintenance.
        if withheld_advisory is not None:
            await self.publish(
                "soma.regulation.withheld",
                {
                    "would_be_action": withheld_advisory["action"],
                    "prediction_error": prediction_error,
                    "sustain_elapsed_s": self._regulation.sustain_elapsed_s(now),
                    "severity": withheld_advisory.get("severity"),
                    "reason": "warmup",
                },
                salience=self._baseline_salience,
            )
            log.info(
                "soma warm-up WITHHELD allostatic advisory %r "
                "(prediction_error=%.4f, sustained=%.1fs): cold-start model "
                "ignorance, no concurrent hard-threshold breach",
                withheld_advisory["action"],
                prediction_error,
                self._regulation.sustain_elapsed_s(now),
            )

        # --- Warm-up completion boundary (latched once) ---
        if (
            self._warmup_enabled
            and self._warmup_started_emitted
            and not self._warmup_completed
            and self._warmup_conditions_met()
        ):
            self._warmup_completed = True
            await self.publish(
                "soma.warmup.completed",
                {
                    "samples_seen": self._samples_seen,
                    "lived_seconds": self._lived_seconds(),
                },
                salience=self._baseline_salience,
            )
            log.info(
                "soma developmental warm-up COMPLETED "
                "(samples_seen=%d, lived_seconds=%.1f): normal allostatic "
                "regulation and full fatigue accrual resume",
                self._samples_seen,
                self._lived_seconds(),
            )

        return payload

    async def _produce_loop(self) -> None:
        try:
            while not self._stopped.is_set():
                try:
                    await self.tick_once()
                except Exception:
                    log.exception("soma producer iteration failed")
                try:
                    # Interoception sampling cadence — a cognitive rhythm, so
                    # the SUBJECTIVE read_interval_s maps to real_interval /
                    # scale wall seconds (the clock's own translation). At scale
                    # 1.0 this equals read_interval_s exactly. The wait_for keeps
                    # the prompt-shutdown race (stopped wakes it immediately).
                    await asyncio.wait_for(
                        self._stopped.wait(),
                        timeout=self._subjective_poll_timeout(self._read_interval_s),
                    )
                except asyncio.TimeoutError:
                    continue
                break
        except asyncio.CancelledError:
            raise

    def _subjective_poll_timeout(self, subjective_s: float) -> float:
        """Real-clock timeout for a SUBJECTIVE cadence, scale-aware.

        ``subjective_s`` subjective seconds take ``subjective_s / scale`` real
        seconds. At scale 1.0 this is ``subjective_s`` unchanged. At scale 0 the
        entity is frozen via the pause path; the poll falls back to the
        subjective value so the loop neither divides by zero nor spins.
        """
        scale = self._clock.scale
        if scale <= 0:
            return subjective_s
        return subjective_s / scale

    async def _cycle_consumer_loop(self) -> None:
        try:
            while not self._stopped.is_set():
                try:
                    entries = await self._bus.read(
                        self._cycle_stream,
                        last_id=self._cycle_cursor,
                        count=64,
                        block_ms=0,
                    )
                    if entries:
                        self._cycle_cursor = entries[-1][0]
                        for _, event in entries:
                            if event.type == "cycle.tick":
                                latency = event.payload.get("wall_duration_ms")
                                if latency is not None:
                                    self._reader.update_cycle_latency_sample(
                                        float(latency)
                                    )
                    else:
                        await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("soma cycle consumer iteration failed")
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise

    async def _hypnos_event_loop(self) -> None:
        """Subscribe to hypnos.out to set/clear the _in_hypnos flag."""
        try:
            while not self._stopped.is_set():
                try:
                    entries = await self._bus.read(
                        "hypnos.out",
                        last_id=self._hypnos_cursor,
                        count=32,
                        block_ms=0,
                    )
                    if entries:
                        self._hypnos_cursor = entries[-1][0]
                        for _, event in entries:
                            if event.type == "hypnos.sleep.started":
                                self._in_hypnos = True
                                self._fatigue.faster_decay = True
                                log.debug(
                                    "soma: _in_hypnos=True (hypnos.sleep.started)"
                                )
                            elif event.type == "hypnos.sleep.completed":
                                self._in_hypnos = False
                                self._fatigue.faster_decay = False
                                self._fatigue.reset()
                                self._fatigue_threshold_emitted = False
                                self._regulation.reset()
                                log.debug(
                                    "soma: _in_hypnos=False (hypnos.sleep.completed); "
                                    "fatigue reset"
                                )
                    else:
                        await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("soma hypnos consumer iteration failed")
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise

    def serialize(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "cycle_cursor": self._cycle_cursor,
            "read_interval_s": self._read_interval_s,
            "forward_model": self._forward_model.state_dict(),
            "fatigue": self._fatigue.state_dict(),
        }
        return state

    def deserialize(self, state: dict[str, Any]) -> None:
        if "cycle_cursor" in state:
            self._cycle_cursor = str(state["cycle_cursor"])
        if "read_interval_s" in state:
            self._read_interval_s = float(state["read_interval_s"])
        if "forward_model" in state:
            try:
                self._forward_model.load_state_dict(state["forward_model"])
            except Exception:
                log.warning("failed to restore forward model weights", exc_info=True)
        if "fatigue" in state:
            try:
                self._fatigue.load_state_dict(state["fatigue"])
            except Exception:
                log.warning("failed to restore fatigue state", exc_info=True)
