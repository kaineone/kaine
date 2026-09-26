# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Live maturation-gate runner (`developmental-maturation-gate`).

This component is constructed in ``kaine.cycle.__main__`` after the bus and
module registry exist. It runs a periodic task during gestation that:

  1. Gathers injected readiness signals (womb readout, Hypnos sleep count,
     Phantasia consolidation passes, EntityClock lived time).
  2. Evaluates the fail-closed readiness predicate C1∧C2∧C3.
  3. Decides whether to birth, hold awaiting embodiment, hold awaiting operator
     ack, or keep gestating.
  4. Emits observable lifecycle events on ``lifecycle.out`` and writes the
     stage file on its first tick, when accumulated evidence changes, and at
     birth.

The runner itself changes no cognitive-module state; it only reads signals and
triggers the monotonic stage transition. Development remains emergent and is
only observed here (warmed-up-signal precedent: paper §6.6,
``soma-coldstart-regulation-warmup``).
"""

from __future__ import annotations

import asyncio
import logging
import math
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any, Callable, Mapping

from kaine.bus.schema import Event
from kaine.lifecycle import stage as lifecycle_stage
from kaine.lifecycle.maturation_gate import (
    ACTION_BIRTH,
    ACTION_HOLD_AWAITING_ACK,
    ACTION_HOLD_AWAITING_EMBODIMENT,
    LIFECYCLE_SOURCE,
    STAGE_BIRTH,
    STAGE_BIRTH_READY,
    STAGE_GESTATION_NO_STIMULUS,
    MaturationConfig,
    birth_payload,
    birth_ready_payload,
    decide_birth,
    embodiment_available,
    evaluate_readiness,
    gestation_no_stimulus_payload,
)
from kaine.perception_state import write_desired_locus

log = logging.getLogger(__name__)

# Default stream the womb module publishes ``gestation.readiness`` readouts to.
# The womb change owns the measurement; the maturation gate only reads it.
DEFAULT_WOMB_READOUT_STREAM = "womb.out"
DEFAULT_WOMB_READOUT_TYPE = "gestation.readiness"


class MaturationGateRunner:
    """Periodic maturation gate for a gestating entity."""

    def __init__(
        self,
        bus,
        config: MaturationConfig,
        registry,
        entity_clock,
        stage_state: lifecycle_stage.StageState,
        *,
        staging_enabled: bool = True,
        womb_feed_configured: bool = False,
        womb_readout_stream: str = DEFAULT_WOMB_READOUT_STREAM,
        womb_readout_type: str = DEFAULT_WOMB_READOUT_TYPE,
        hypnos_stream: str = "hypnos.out",
        paused_seconds: Callable[[], float] | None = None,
    ) -> None:
        self._bus = bus
        self._config = config
        self._registry = registry
        self._entity_clock = entity_clock
        self._stage = stage_state
        self._staging_enabled = bool(staging_enabled)
        self._womb_feed_configured = bool(womb_feed_configured)
        self._womb_stream = womb_readout_stream
        self._womb_type = womb_readout_type
        self._hypnos_stream = hypnos_stream
        self._paused_seconds: Callable[[], float] | None = paused_seconds
        self._is_paused: Callable[[], bool] | None = None
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        # Redis server time at the first evaluation, anchoring readout age.
        self._boot_ms: int | None = None
        # EntityClock baseline for per-boot subjective lived-time accumulation.
        self._clock_baseline: float | None = None
        # Paused-time baseline paired with _clock_baseline for exact subtraction.
        self._paused_baseline: float | None = None
        # Ensure the first tick anchors the stage file.
        self._stage_written = False
        # Track whether we have already emitted the birth-ready "awaiting
        # embodiment" signal so the log is not spammed every cadence tick.
        self._awaiting_embodiment_logged = False
        self._awaiting_ack_logged = False
        # Track whether we have already logged the single "birth deferred"
        # info line for the current frozen spell.
        self._birth_deferred_logged = False

    def set_pause_sources(
        self,
        *,
        paused_seconds: Callable[[], float] | None,
        is_paused: Callable[[], bool] | None,
    ) -> None:
        """Hand over the cycle's paused-time total and paused flag.

        The cycle is built after the runner, so the entrypoint hands over
        the cycle's paused-time total and its paused flag here.
        """
        self._paused_seconds = paused_seconds
        self._is_paused = is_paused
        self._paused_baseline = None

    @property
    def stage(self) -> lifecycle_stage.StageState:
        return self._stage

    def _lifecycle_event(
        self, type: str, payload: dict[str, Any], *, salience: float = 0.5
    ) -> Event:
        return Event(
            source=LIFECYCLE_SOURCE,
            type=type,
            payload=payload,
            salience=salience,
            timestamp=datetime.now(timezone.utc),
        )

    async def _publish(self, type: str, payload: dict[str, Any], *, salience: float = 0.5) -> None:
        try:
            await self._bus.publish(self._lifecycle_event(type, payload, salience=salience))
        except Exception:
            log.warning("could not publish %s", type, exc_info=True)

    def _phantasia_consolidation_passes(self) -> int | None:
        if "phantasia" not in self._registry:
            return None
        try:
            phantasia = self._registry.get("phantasia")
            return int(getattr(phantasia, "successful_training_passes", 0))
        except Exception:
            return None

    async def _mundus_availability(self) -> tuple[bool, bool, bool]:
        """Return (config_enabled, operator_approved, reachable)."""
        if "mundus" not in self._registry:
            return False, False, False
        try:
            from kaine.modules.mundus import module as mundus_module

            mundus = self._registry.get("mundus")
            config_enabled = bool(getattr(mundus, "enabled_by_config", False))
            approved = bool(mundus_module.operator_approved())
            reachable = bool(await mundus.probe_available())
            return config_enabled, approved, reachable
        except Exception:
            return False, False, False

    async def _begin_boot(self) -> None:
        """Anchor the boot timestamp from Redis; defer evaluation on failure."""
        if self._boot_ms is not None:
            return
        try:
            self._boot_ms = await self._bus.server_time_ms()
        except Exception:
            log.warning(
                "maturation gate: could not read server time; deferring evaluation",
                exc_info=True,
            )

    async def _count_new_sleeps(self) -> None:
        """Count hypnos sleep completions from the bus, idempotently.

        A fresh cursor is anchored at the stream tail on the first tick.
        Thereafter we scan forward from the persisted cursor, counting each
        ``hypnos.sleep.completed`` event from ``hypnos`` exactly once.
        Bus errors fail closed for this tick: they leave the stage unchanged.
        """
        stream = self._hypnos_stream
        cursor = self._stage.hypnos_cursor
        try:
            if cursor is None:
                latest = await self._bus.latest(stream)
                new_cursor = latest[0] if latest is not None else "0-0"
                self._stage = replace(self._stage, hypnos_cursor=new_cursor)
                return

            total = self._stage.sleep_count
            while True:
                entries, last_scanned = await self._bus.read_entries(
                    stream, last_id=cursor, count=100
                )
                for _, event in entries:
                    if event.type == "hypnos.sleep.completed" and event.source == "hypnos":
                        total += 1
                if last_scanned is None:
                    break
                cursor = last_scanned

            self._stage = replace(self._stage, sleep_count=total, hypnos_cursor=cursor)
        except Exception:
            log.warning("maturation gate: failed to count hypnos sleeps", exc_info=True)

    def _accumulate_lived_time(self) -> None:
        """Add subjective elapsed time since the last tick.

        The first tick of a runner instance anchors the baseline and adds
        nothing, so downtime between boots never counts. A frozen clock
        (scale 0) produces no positive delta. Frozen (paused) time is
        measured by the cycle and subtracted exactly so a suspended span does
        not count toward maturation.
        """
        if self._entity_clock is None:
            return
        try:
            now = self._entity_clock.now()
            if now is None:
                return
            now = float(now)
        except Exception:
            return

        paused: float | None = None
        if self._paused_seconds is not None:
            try:
                paused = float(self._paused_seconds())
                if not math.isfinite(paused):
                    raise ValueError("non-finite paused time")
            except Exception:
                # Source failed: drop both baselines so the next good tick
                # re-anchors and adds nothing. The pauses inside this span are
                # unknown, so it must not count; this fails toward counting less.
                self._clock_baseline = None
                self._paused_baseline = None
                return

        if self._clock_baseline is None:
            self._clock_baseline = now
            self._paused_baseline = paused if paused is not None else 0.0
            return

        if paused is None:
            delta = now - self._clock_baseline
        else:
            if self._paused_baseline is None:
                self._paused_baseline = paused
            delta = (now - self._clock_baseline) - (paused - self._paused_baseline)

        if delta > 0 and math.isfinite(delta):
            self._stage = replace(
                self._stage, lived_seconds=self._stage.lived_seconds + delta
            )

        self._clock_baseline = now
        if paused is not None:
            self._paused_baseline = paused

    async def _womb_readiness_readout(self) -> Mapping[str, Any] | None:
        """Read the latest womb ``gestation.readiness`` event from the bus.

        Returns ``None`` when the readout is absent, of the wrong type, older
        than this boot, or stale, so C1 fails closed. Stream ids and Redis
        ``TIME`` share the same clock, so host clock skew does not matter.
        """
        try:
            entry = await self._bus.latest(self._womb_stream)
            if entry is None:
                return None
            entry_id, event = entry
            if event.type != self._womb_type:
                return None
            if self._boot_ms is None:
                return None
            id_ms = int(entry_id.split("-")[0])
            if id_ms < self._boot_ms:
                return None

            now_ms = await self._bus.server_time_ms()
            max_age_ms = (
                self._config.readout_max_age_cadences
                * self._config.gate_cadence_seconds
                * 1000
            )
            if now_ms - id_ms > max_age_ms:
                return None

            readout = event.payload.get("readout")
            if isinstance(readout, dict):
                return readout
            if isinstance(event.payload, dict):
                return event.payload
            return None
        except Exception:
            log.debug("maturation gate: womb readiness readout failed closed", exc_info=True)
            return None

    def _persist_if_changed(self, before: lifecycle_stage.StageState) -> None:
        """Persist the stage if evidence changed or it has never been written."""
        if self._stage == before and self._stage_written:
            return
        try:
            lifecycle_stage.write_stage(self._stage)
            self._stage_written = True
        except OSError:
            log.warning("maturation gate: could not persist stage file", exc_info=True)

    async def _evaluate_once(self) -> None:
        """One gate evaluation: gather signals, decide, act, emit."""
        if not self._staging_enabled or not self._stage.is_gestating:
            return

        before = self._stage

        await self._begin_boot()
        if self._boot_ms is None:
            return

        if not self._womb_feed_configured:
            # Loud, repeated warning: never a silent senseless hold.
            log.warning("stage.gestation.no_stimulus: gestation active but no womb feed configured")
            await self._publish(
                STAGE_GESTATION_NO_STIMULUS,
                gestation_no_stimulus_payload(),
                salience=0.7,
            )
            return

        self._accumulate_lived_time()
        await self._count_new_sleeps()
        self._persist_if_changed(before)

        readiness_readout = await self._womb_readiness_readout()
        sleep_count = self._stage.sleep_count
        consolidation_passes = self._phantasia_consolidation_passes()
        lived_seconds = self._stage.lived_seconds

        readiness = evaluate_readiness(
            readiness_readout=readiness_readout,
            sleep_count=sleep_count,
            consolidation_passes=consolidation_passes,
            lived_seconds=lived_seconds,
            config=self._config,
        )

        if not readiness.ready:
            for name in readiness.unmet:
                log.debug("maturation gate: %s not yet met", name)
            return

        log.info(
            "maturation gate: developmental readiness reached (%s)",
            ", ".join(readiness.passed_markers),
        )

        # Fail closed: no birth while the entity is paused/frozen.
        if self._is_paused is not None:
            try:
                paused = self._is_paused()
            except Exception:
                paused = True
            if paused:
                if not self._birth_deferred_logged:
                    log.info("birth deferred: the entity is frozen")
                    self._birth_deferred_logged = True
                return
        self._birth_deferred_logged = False

        mundus_enabled, operator_approved, reachable = await self._mundus_availability()
        embodiment_ready = embodiment_available(
            mundus_enabled=mundus_enabled,
            operator_approved=operator_approved,
            reachable=reachable,
        )

        decision = decide_birth(
            readiness=readiness,
            embodiment_ready=embodiment_ready,
            require_operator_ack=self._config.require_operator_ack_for_birth,
            operator_ack=False,  # TODO: operator-ack surface for supervised shakedown
        )

        if decision.action == ACTION_BIRTH:
            await self._do_birth(readiness, self._stage.sleep_count, self._stage.lived_seconds)
        elif decision.action == ACTION_HOLD_AWAITING_EMBODIMENT:
            if not self._awaiting_embodiment_logged:
                log.warning("stage.birth.ready: awaiting embodiment (Mundus not available)")
                self._awaiting_embodiment_logged = True
            await self._publish(
                STAGE_BIRTH_READY,
                birth_ready_payload(decision),
                salience=0.7,
            )
        elif decision.action == ACTION_HOLD_AWAITING_ACK:
            if not self._awaiting_ack_logged:
                log.warning("stage.birth.ready: awaiting operator ack for supervised birth")
                self._awaiting_ack_logged = True
            await self._publish(
                STAGE_BIRTH_READY,
                birth_ready_payload(decision),
                salience=0.7,
            )

    async def _do_birth(
        self,
        readiness: Any,
        sleep_count: int | None,
        lived_seconds: float | None,
    ) -> None:
        """Perform the one-shot birth transition."""
        before = self._stage

        # Start embodiment before the stage file is written, so the locus source
        # is actually available when the entity becomes embodied.
        if "mundus" in self._registry:
            mundus = self._registry.get("mundus")
            try:
                ok = await mundus.activate()
            except Exception:
                ok = False
            if not ok:
                log.warning("maturation gate: Mundus activation failed; deferring birth")
                await self._publish(
                    STAGE_BIRTH_READY,
                    birth_ready_payload(
                        decide_birth(
                            readiness=readiness,
                            embodiment_ready=False,
                            require_operator_ack=False,
                            operator_ack=False,
                        )
                    ),
                    salience=0.7,
                )
                return

        after = lifecycle_stage.advance_to_embodied(before)
        if not lifecycle_stage.birth_is_new(before, after):
            return

        # Persist the monotonic transition.
        lifecycle_stage.write_stage(after)
        self._stage = after

        # Unlock the gestation locus lock. The unlock is attributed to gestation,
        # not the operator; the locus stays virtual while the handoff continues.
        try:
            write_desired_locus("virtual", locked=False, locked_by="gestation")
        except Exception:
            log.warning("could not unlock gestation locus after birth", exc_info=True)

        await self._publish(
            STAGE_BIRTH,
            birth_payload(
                readiness=readiness,
                sleep_count=sleep_count,
                lived_seconds=lived_seconds,
            ),
            salience=0.9,
        )
        log.info(
            "stage.birth: transitioned to embodied (sleep_count=%s, lived_seconds=%s)",
            sleep_count,
            lived_seconds,
        )

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run the gate loop until ``stop_event`` is set."""
        self._stop_event = stop_event
        if not self._staging_enabled or not self._stage.is_gestating:
            return

        cadence = max(1.0, float(self._config.gate_cadence_seconds))
        while not stop_event.is_set():
            try:
                await self._evaluate_once()
            except Exception:
                log.exception("maturation gate: evaluation failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=cadence)
            except asyncio.TimeoutError:
                # Expected: cadence elapsed, evaluate again.
                continue

    async def shutdown(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                # Expected: we just cancelled the task.
                return
