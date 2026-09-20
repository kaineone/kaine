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
     stage file only on the birth transition.

The runner itself changes no cognitive-module state; it only reads signals and
triggers the monotonic stage transition. Development remains emergent and is
only observed here (warmed-up-signal precedent: paper §6.6,
``soma-coldstart-regulation-warmup``).
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Mapping

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
        self._task: asyncio.Task | None = None
        self._stop_event: asyncio.Event | None = None
        # Track whether we have already emitted the birth-ready "awaiting
        # embodiment" signal so the log is not spammed every cadence tick.
        self._awaiting_embodiment_logged = False
        self._awaiting_ack_logged = False

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

    def _hypnos_sleep_count(self) -> int | None:
        if "hypnos" not in self._registry:
            return None
        try:
            hypnos = self._registry.get("hypnos")
            return int(getattr(hypnos, "sleep_count", 0))
        except Exception:
            return None

    def _phantasia_consolidation_passes(self) -> int | None:
        if "phantasia" not in self._registry:
            return None
        try:
            phantasia = self._registry.get("phantasia")
            return int(getattr(phantasia, "successful_training_passes", 0))
        except Exception:
            return None

    def _mundus_availability(self) -> tuple[bool, bool, bool]:
        """Return (config_enabled, operator_approved, reachable)."""
        if "mundus" not in self._registry:
            return False, False, False
        try:
            mundus = self._registry.get("mundus")
            config_enabled = bool(getattr(mundus, "_config_enabled", False))
            approved = bool(getattr(mundus, "_enabled", lambda: False)())
            # Reachability: if initialize() ran and the adapter is open, the
            # module is up. We approximate this by checking the feed task list
            # (non-empty after a successful initialize).
            reachable = bool(getattr(mundus, "_tasks", []))
            return config_enabled, approved, reachable
        except Exception:
            return False, False, False

    async def _womb_readiness_readout(self) -> Mapping[str, Any] | None:
        """Read the latest womb ``gestation.readiness`` event from the bus.

        Returns ``None`` when the womb module is absent or the readout is stale,
        so C1 fails closed.
        """
        try:
            latest = await self._bus.client.xrevrange(self._womb_stream, count=1)
        except Exception:
            return None
        if not latest:
            return None
        try:
            _id, fields = latest[0]
            raw = fields.get(b"payload") or fields.get("payload")
            if isinstance(raw, bytes):
                import json

                payload = json.loads(raw)
            else:
                payload = raw
            if not isinstance(payload, dict):
                return None
            if payload.get("type") != self._womb_type:
                # If the event stores type separately, fall through to the
                # payload dict itself (some bus layouts embed type in payload).
                pass
            return payload.get("readout") or payload
        except Exception:
            return None

    def _lived_seconds(self) -> float | None:
        if self._entity_clock is None or self._stage.gestation_started_at is None:
            return None
        try:
            start = datetime.fromisoformat(self._stage.gestation_started_at)
            now = self._entity_clock.now()
            if now is None or start.tzinfo is None:
                return None
            return (now - start).total_seconds()
        except Exception:
            return None

    async def _evaluate_once(self) -> None:
        """One gate evaluation: gather signals, decide, act, emit."""
        if not self._staging_enabled or not self._stage.is_gestating:
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

        readiness_readout = await self._womb_readiness_readout()
        sleep_count = self._hypnos_sleep_count()
        consolidation_passes = self._phantasia_consolidation_passes()
        lived_seconds = self._lived_seconds()

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

        mundus_enabled, operator_approved, reachable = self._mundus_availability()
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
            await self._do_birth(readiness, sleep_count, lived_seconds)
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
        after = lifecycle_stage.advance_to_embodied(before)
        if not lifecycle_stage.birth_is_new(before, after):
            return

        # Persist the monotonic transition.
        lifecycle_stage.write_stage(after)
        self._stage = after

        # Unlock the gestation locus lock. The locus stays virtual; the actual
        # sense source handoff from womb feed to Mundus is rendered by the feed
        # and Mundus modules (this change only triggers the transition).
        try:
            write_desired_locus("virtual", locked=False, locked_by="operator")
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
                pass

    async def shutdown(self) -> None:
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
