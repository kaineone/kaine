# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Live maturation-gate runner (`developmental-maturation-gate`).

This component is constructed in ``kaine.cycle.__main__`` after the bus and
module registry exist. It runs a periodic task during the developmental phase that:

  1. Gathers injected readiness signals (stimulus source readout, sleep count,
     the world model module's consolidation passes, EntityClock lived time).
  2. Evaluates the fail-closed readiness predicate C1∧C2∧C3.
  3. Decides whether to mature, hold awaiting embodiment, hold awaiting operator
     ack, or keep gestating.
  4. Emits observable lifecycle events on ``lifecycle.out`` and writes the
     stage file on its first tick, when accumulated evidence changes, and at
     maturation.

The runner itself changes no cognitive-module state; it only reads signals and
triggers the monotonic stage transition. Development remains emergent and is
only observed here (warmed-up-signal precedent: paper §6.6,
``soma-coldstart-regulation-warmup``).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from kaine.bus.schema import Event
from kaine.lifecycle import stage as lifecycle_stage
from kaine.lifecycle.lived_time import LivedTimeAccumulator
from kaine.lifecycle.maturation_gate import (
    ACTION_HOLD_AWAITING_ACK,
    ACTION_HOLD_AWAITING_EMBODIMENT,
    ACTION_MATURATION,
    LIFECYCLE_SOURCE,
    STAGE_DEVELOPMENT_NO_STIMULUS,
    STAGE_MATURATION,
    STAGE_MATURATION_READY,
    MaturationConfig,
    decide_maturation,
    development_no_stimulus_payload,
    embodiment_available,
    evaluate_readiness,
    maturation_payload,
    maturation_ready_payload,
)
from kaine.perception_state import write_desired_locus

log = logging.getLogger(__name__)

# Default stream the stimulus source module publishes ``gestation.readiness`` readouts to.
# The stimulus source change owns the measurement; the maturation gate only reads it.
DEFAULT_STIMULUS_SOURCE_READOUT_STREAM = "gestation.out"
DEFAULT_STIMULUS_SOURCE_READOUT_TYPE = "gestation.readiness"


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
        stimulus_source_feed_configured: bool = False,
        stimulus_source_readout_stream: str = DEFAULT_STIMULUS_SOURCE_READOUT_STREAM,
        stimulus_source_readout_type: str = DEFAULT_STIMULUS_SOURCE_READOUT_TYPE,
        sleep_stream: str = "hypnos.out",
        paused_seconds: Callable[[], float] | None = None,
        maturation_request_path: Path | None = None,
        maturation_ack_path: Path | None = None,
    ) -> None:
        self._bus = bus
        self._config = config
        self._registry = registry
        self._entity_clock = entity_clock
        self._stage = stage_state
        self._staging_enabled = bool(staging_enabled)
        self._stimulus_source_feed_configured = bool(stimulus_source_feed_configured)
        self._stimulus_source_stream = stimulus_source_readout_stream
        self._stimulus_source_type = stimulus_source_readout_type
        self._sleep_stream = sleep_stream
        self._paused_seconds: Callable[[], float] | None = paused_seconds
        self._is_paused: Callable[[], bool] | None = None
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        # Redis server time at the first evaluation, anchoring readout age.
        self._boot_ms: int | None = None
        # Subjective-lived-time accumulator anchored per boot.
        self._lived = LivedTimeAccumulator(
            (lambda: entity_clock.now()) if entity_clock is not None else None,
            paused_seconds,
        )
        # Ensure the first tick anchors the stage file.
        self._stage_written = False
        # Track whether we have already emitted the maturation-ready "awaiting
        # embodiment" signal so the log is not spammed every cadence tick.
        self._awaiting_embodiment_logged = False
        self._awaiting_ack_logged = False
        # Track whether we have already logged the single "maturation deferred"
        # info line for the current frozen spell.
        self._maturation_deferred_logged = False
        # Optional one-shot hook handed over by the cycle entrypoint; called
        # after the stage file is written as embodied so the stimulus source can begin its
        # maturation transition.
        self._on_maturation: Callable[[], None] | None = None
        # Operator-supervised maturation acknowledgement file paths and state.
        from kaine.lifecycle.maturation_ack import MATURATION_ACK_PATH, MATURATION_REQUEST_PATH

        self._maturation_request_path = maturation_request_path or MATURATION_REQUEST_PATH
        self._maturation_ack_path = maturation_ack_path or MATURATION_ACK_PATH
        self._maturation_request = None
        self._last_status: dict[str, Any] = {}

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
        self._lived.set_paused_source(paused_seconds)

    def set_maturation_hook(self, fn: Callable[[], None] | None) -> None:
        """Hand over the stimulus source's ``begin_birth``; the runner calls it once, after the stage file says embodied."""
        self._on_maturation = fn

    @property
    def stage(self) -> lifecycle_stage.StageState:
        return self._stage

    @property
    def status(self) -> dict[str, Any]:
        """Content-free snapshot of the latest maturation-gate status for Nexus."""
        return dict(self._last_status)

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

    def _world_model_consolidation_passes(self) -> int | None:
        if "phantasia" not in self._registry:
            return None
        try:
            world_model = self._registry.get("phantasia")
            return int(getattr(world_model, "successful_training_passes", 0))
        except Exception:
            return None

    async def _embodiment_availability(self) -> tuple[bool, bool, bool]:
        """Return (config_enabled, operator_approved, reachable)."""
        if "mundus" not in self._registry:
            return False, False, False
        try:
            from kaine.modules.embodiment import module as embodiment_module

            embodiment = self._registry.get("mundus")
            config_enabled = bool(getattr(embodiment, "enabled_by_config", False))
            approved = bool(embodiment_module.operator_approved())
            reachable = bool(await embodiment.probe_available())
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
        """Count sleep completions from the bus, idempotently.

        A fresh cursor is anchored at the stream tail on the first tick.
        Thereafter we scan forward from the persisted cursor, counting each
        ``hypnos.sleep.completed`` event from ``hypnos`` exactly once.
        Bus errors fail closed for this tick: they leave the stage unchanged.
        """
        stream = self._sleep_stream
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

        Logic lives in ``LivedTimeAccumulator``.
        """
        delta = self._lived.step()
        if delta > 0:
            self._stage = replace(self._stage, lived_seconds=self._stage.lived_seconds + delta)

    async def _stimulus_source_readiness_readout(self) -> Mapping[str, Any] | None:
        """Read the latest stimulus source ``gestation.readiness`` event from the bus.

        The stream also carries presence and probe events, so the newest entry is
        rarely the readout. We therefore search the stream window newest-first
        and return the first matching event.

        Returns ``None`` when the readout is absent, of the wrong type, older
        than this boot, or stale, so C1 fails closed. Stream ids and Redis
        ``TIME`` share the same clock, so host clock skew does not matter.
        """
        try:
            if self._boot_ms is None:
                return None
            now_ms = await self._bus.server_time_ms()
            max_age_ms = (
                self._config.readout_max_age_cadences
                * self._config.gate_cadence_seconds
                * 1000
            )
            start_ms = max(self._boot_ms, now_ms - int(max_age_ms))
            entries = await self._bus.range(
                self._stimulus_source_stream, start=str(start_ms), end="+"
            )
            for entry_id, event in reversed(entries):
                if event.type != self._stimulus_source_type or event.source != "gestation":
                    continue
                if isinstance(event.payload, dict):
                    readout = event.payload.get("readout")
                    if isinstance(readout, dict):
                        return readout
                    return event.payload
                return None
            return None
        except Exception:
            log.debug(
                "maturation gate: womb readiness readout failed closed",
                exc_info=True,
            )
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
        from kaine.lifecycle.maturation_ack import (
            clear_request,
            is_acknowledged,
            new_request,
            read_ack,
            write_request,
        )
        from kaine.lifecycle.maturation_gate import Faculties

        if self._registry is None:
            faculties = Faculties()
        else:
            faculties = Faculties(
                sleep="hypnos" in self._registry,
                world_model="phantasia" in self._registry,
                embodiment="mundus" in self._registry,
            )
        world = "embodied" if faculties.embodiment else "perceptual"
        conditions = {
            "c2_sleep_required": bool(faculties.sleep),
            "c2_consolidation_required": bool(faculties.sleep and faculties.world_model),
        }

        def _set_status(
            *,
            readiness: Any = None,
            readout: Mapping[str, Any] | None = None,
            decision: Any = None,
            consolidation_passes: int | None = None,
        ) -> None:
            """Store a content-free status snapshot for Nexus."""
            self._last_status = {
                "lived_seconds": float(self._stage.lived_seconds or 0.0),
                "sleep_count": self._stage.sleep_count or 0,
                "consolidation_passes": consolidation_passes,
                "world": world,
                "conditions": conditions,
                "readiness": {
                    "ready": readiness.ready,
                    "passed": list(readiness.passed_markers),
                    "not_applicable": list(readiness.not_applicable),
                    "unmet": list(readiness.unmet),
                } if readiness is not None else None,
                "readout": dict(readout) if readout is not None else None,
                "decision": {
                    "action": decision.action,
                    "reason": decision.reason,
                } if decision is not None else None,
                "awaiting_ack": (
                    decision.action == ACTION_HOLD_AWAITING_ACK
                    if decision is not None else False
                ),
                "request_id": (
                    self._maturation_request.request_id
                    if self._maturation_request is not None else None
                ),
            }

        if not self._staging_enabled or not self._stage.is_gestating:
            _set_status()
            return

        before = self._stage

        await self._begin_boot()
        if self._boot_ms is None:
            _set_status()
            return

        if not self._stimulus_source_feed_configured:
            # Loud, repeated warning: never a silent senseless hold.
            log.warning("stage.gestation.no_stimulus: gestation active but no womb feed configured")
            await self._publish(
                STAGE_DEVELOPMENT_NO_STIMULUS,
                development_no_stimulus_payload(),
                salience=0.7,
            )
            _set_status()
            return

        self._accumulate_lived_time()
        await self._count_new_sleeps()
        self._persist_if_changed(before)

        readiness_readout = await self._stimulus_source_readiness_readout()
        sleep_count = self._stage.sleep_count
        consolidation_passes = self._world_model_consolidation_passes()
        lived_seconds = self._stage.lived_seconds

        readiness = evaluate_readiness(
            readiness_readout=readiness_readout,
            sleep_count=sleep_count,
            consolidation_passes=consolidation_passes,
            lived_seconds=lived_seconds,
            config=self._config,
            faculties=faculties,
        )

        if not readiness.ready:
            if self._maturation_request is not None:
                try:
                    clear_request(self._maturation_request_path)
                except OSError as exc:
                    log.warning("could not clear stale birth request: %s", exc)
                self._maturation_request = None
                self._awaiting_ack_logged = False
            _set_status(
                readiness=readiness,
                readout=readiness_readout,
                consolidation_passes=consolidation_passes,
            )
            for name in readiness.unmet:
                log.debug("maturation gate: %s not yet met", name)
            return

        log.info(
            "maturation gate: developmental readiness reached (%s)",
            ", ".join(readiness.passed_markers),
        )

        # Fail closed: no maturation while the entity is paused/frozen.
        if self._is_paused is not None:
            try:
                paused = self._is_paused()
            except Exception:
                paused = True
            if paused:
                if not self._maturation_deferred_logged:
                    log.info("birth deferred: the entity is frozen")
                    self._maturation_deferred_logged = True
                _set_status(
                    readiness=readiness,
                    readout=readiness_readout,
                    consolidation_passes=consolidation_passes,
                )
                return
        self._maturation_deferred_logged = False

        if faculties.embodiment:
            embodiment_enabled, operator_approved, reachable = await self._embodiment_availability()
            embodiment_ready = embodiment_available(
                embodiment_enabled=embodiment_enabled,
                operator_approved=operator_approved,
                reachable=reachable,
            )
        else:
            embodiment_ready = True

        operator_ack = is_acknowledged(
            self._maturation_request, read_ack(self._maturation_ack_path)
        )
        decision = decide_maturation(
            readiness=readiness,
            embodiment_ready=embodiment_ready,
            require_operator_ack=self._config.require_operator_ack_for_maturation,
            operator_ack=operator_ack,
            faculties=faculties,
        )

        if decision.action == ACTION_MATURATION:
            await self._do_maturation(
                readiness,
                self._stage.sleep_count,
                self._stage.lived_seconds,
                faculties,
            )
            _set_status(
                readiness=readiness,
                readout=readiness_readout,
                decision=decision,
                consolidation_passes=consolidation_passes,
            )
        elif decision.action == ACTION_HOLD_AWAITING_EMBODIMENT:
            if self._maturation_request is not None:
                try:
                    clear_request(self._maturation_request_path)
                except OSError as exc:
                    log.warning("could not clear stale birth request: %s", exc)
                self._maturation_request = None
                self._awaiting_ack_logged = False
            if not self._awaiting_embodiment_logged:
                log.warning("stage.birth.ready: awaiting embodiment (Mundus not available)")
                self._awaiting_embodiment_logged = True
            await self._publish(
                STAGE_MATURATION_READY,
                maturation_ready_payload(decision),
                salience=0.7,
            )
            _set_status(
                readiness=readiness,
                readout=readiness_readout,
                decision=decision,
                consolidation_passes=consolidation_passes,
            )
        elif decision.action == ACTION_HOLD_AWAITING_ACK:
            if self._maturation_request is None:
                try:
                    req = new_request(self._stage.gestation_started_at)
                    write_request(req, self._maturation_request_path)
                    self._maturation_request = req
                    log.info("operator birth acknowledgement requested: %s", req.request_id)
                except (OSError, ValueError) as exc:
                    log.warning(
                        "could not write birth request; treating as no operator ack: %s",
                        exc,
                    )
            if not self._awaiting_ack_logged:
                log.warning("stage.birth.ready: awaiting operator ack for supervised birth")
                self._awaiting_ack_logged = True
            await self._publish(
                STAGE_MATURATION_READY,
                maturation_ready_payload(decision),
                salience=0.7,
            )
            _set_status(
                readiness=readiness,
                readout=readiness_readout,
                decision=decision,
                consolidation_passes=consolidation_passes,
            )

    async def _do_maturation(
        self,
        readiness: Any,
        sleep_count: int | None,
        lived_seconds: float | None,
        faculties: Any = None,
    ) -> None:
        """Perform the one-shot maturation transition."""
        if faculties is None:
            from kaine.lifecycle.maturation_gate import Faculties
            faculties = Faculties()

        before = self._stage

        # Start embodiment before the stage file is written, so the locus source
        # is actually available when the entity becomes embodied.
        # The vocal module is activated before the embodiment module so the voice is available at maturation.
        if "vox" in self._registry:
            vocal = self._registry.get("vox")
            if hasattr(vocal, "set_dormant"):
                vocal.set_dormant(False)
                log.info("birth: vox activated")
        if "mundus" in self._registry:
            embodiment = self._registry.get("mundus")
            try:
                ok = await embodiment.activate()
            except Exception:
                ok = False
            if not ok:
                log.warning("maturation gate: Mundus activation failed; deferring birth")
                await self._publish(
                    STAGE_MATURATION_READY,
                    maturation_ready_payload(
                        decide_maturation(
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
        if not lifecycle_stage.maturation_is_new(before, after):
            return

        # Persist the monotonic transition.
        lifecycle_stage.write_stage(after)
        self._stage = after

        # Maturation is complete: clear the operator acknowledgement files. The
        # request is tied to this boot and must not be reused later.
        from kaine.lifecycle.maturation_ack import clear_ack, clear_request

        try:
            clear_request(self._maturation_request_path)
            clear_ack(self._maturation_ack_path)
        except OSError as exc:
            log.warning("could not clear birth acknowledgement files after birth: %s", exc)
        self._maturation_request = None

        # Unlock the developmental phase locus lock. The unlock is attributed to the developmental phase,
        # not the operator; the locus stays virtual while the handoff continues.
        try:
            write_desired_locus("virtual", locked=False, locked_by="gestation")
        except Exception:
            log.warning("could not unlock gestation locus after birth", exc_info=True)

        if self._on_maturation is not None:
            try:
                self._on_maturation()
            except Exception:
                log.warning("maturation gate: birth hook raised; continuing birth", exc_info=True)

        await self._publish(
            STAGE_MATURATION,
            maturation_payload(
                readiness=readiness,
                sleep_count=sleep_count,
                lived_seconds=lived_seconds,
                faculties=faculties,
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
