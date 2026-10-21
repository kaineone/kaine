# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, ClassVar, Optional

from kaine.bus.client import AsyncBus
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule
from kaine.modules.sleep.corpus import (
    check_corpus_ceiling,
    intent_record_paths,
    rotate_intent_log,
)
from kaine.modules.sleep.phases import (
    PhaseResult,
    affective_reset,
    associative_replay,
    deep_consolidation,
    light_consolidation,
)
from kaine.modules.sleep.scheduler import RestScheduler
from kaine.modules.sleep.voice_alignment import (
    TRAINING_SOURCES,
    DPOPair,
    DPOPairBuilder,
    FakeTrainer,
    Trainer,
    TrainingResult,
    VoiceAlignmentConfig,
    operator_approved,
)
from kaine.modules.sleep.voice_measures import (
    compute_sleep_measures,
    load_base_profile,
    organ_gguf_sha256,
)
from kaine.persistence.encrypted_jsonl import has_plaintext_line, rewrite_encrypted
from kaine.persistence.system_prompts import read_system_prompt, store_dir_for
from kaine.state_io import write_json_atomic
from kaine.storage import resolve

log = logging.getLogger(__name__)

# Bound on each wait in Sleep.shutdown(): the in-flight sleep, then the held tasks.
_SHUTDOWN_WAIT_S = 5.0


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


class SleepBusyError(RuntimeError):
    """Raised when enter_sleep() is invoked while sleep is in progress."""


class Sleep(BaseModule):
    name: ClassVar[str] = "sleep"

    def holds_external_resources(self) -> bool:
        return True

    def __init__(
        self,
        bus: AsyncBus,
        *,
        episodic_memory: Optional[Any] = None,
        affect: Optional[Any] = None,
        sequence_resetters: Optional[list[Any]] = None,
        trainer: Optional[Trainer] = None,
        voice_alignment_config: Optional[VoiceAlignmentConfig] = None,
        # On-device GPU window runner: an async callable
        # ``runner(train_thunk) -> (TrainingResult, OrganWindowResult)`` that
        # brackets the trainer call with the organ unload→reload time-share
        # (kaine.modules.sleep.organ_window). Injected by boot when a real
        # trainer is wired; None → train directly with the organ resident (the
        # pre-existing behavior, e.g. FakeTrainer / tests / multi-GPU host).
        organ_window_runner: Optional[Any] = None,
        scheduler: Optional[RestScheduler] = None,
        interval_seconds: float = 3600.0,
        max_deferral_seconds: float = 600.0,
        per_defer_seconds: float = 60.0,
        baseline_salience: float = 0.5,
        alert_salience: float = 0.8,
        # Consolidation config (hypnos-fatigue-phases)
        fatigue_triggered: bool = True,
        replay_window_s: float = 5.0,
        # Phase-3 associative replay (hypnos-consolidation)
        associative_replay_enabled: bool = False,
        world_model: Optional[Any] = None,
        # Active-module registry for oscillator hook (phase 1)
        active_modules: Optional[list[Any]] = None,
        # the perceptual locus module path (for suspension during replay window)
        perception_desired_path: Optional[Path] = None,
        # Shared playlist clock (playlist-sleep-pause), injected by boot when a
        # playlist feed runs — the SAME instance both feeds read. pause()/
        # resume() are called at the perception suspend/restore seam so
        # playback freezes for the whole sleep window and resumes at the pause
        # point. None in non-playlist modes; the seam calls are honest no-ops.
        playlist_clock: Optional[Any] = None,
        # Shared subjective clock (injected at boot). The rest scheduler's
        # sleep-due interval + deferral window model the ENTITY'S rest, so they
        # run in subjective time — at time_scale != 1.0 the entity's sleep
        # pressure builds at the dilated rate, coherent with fatigue. Wired into
        # the RestScheduler's clock when no scheduler is injected. The sleep
        # pipeline's own elapsed_ms / started_at stamps stay on REAL time (they
        # measure infrastructure latency, like the cycle slip). Defaults to a
        # real-time clock → behavior-identical.
        entity_clock: Optional[EntityClock] = None,
        # Minimum entity-time seconds between a sleep's end and a planning-module-requested
        # rest; bounds rest requests from an exploring planning module.
        requested_rest_min_interval_s: float = 1800.0,
        # Developmental-phase rest duration, Delta_rest from paper section 3.5
        # and Table A1: 1260 s is the mean length of a quiescent episode (state 1F).
        developmental_rest_s: float = 1260.0,
        # Path to the organ GGUF served by the language module. Used to identify the correct
        # base voice profile for distinctiveness measurement; None means the
        # digest is unknown and distinctiveness will be null.
        organ_gguf_path: Optional[Path] = None,
        # sleep housekeeping, paper 3.5 and A.5; None runs none
        housekeeper: Optional[Any] = None,
        # Shared housekeeping pressure holder (paper A.5): each successful
        # housekeeping report sets the pressure that scales awake fatigue
        # build-up at nu_act (1 + P^hk). None leaves fatigue unchanged.
        housekeeping_pressure: Optional[Any] = None,
    ) -> None:
        super().__init__(bus)
        self._organ_gguf_path = organ_gguf_path
        self._housekeeper = housekeeper
        self._housekeeping_pressure = housekeeping_pressure
        if not 0.0 <= baseline_salience <= 1.0:
            raise ValueError("baseline_salience must be in [0, 1]")
        if not 0.0 <= alert_salience <= 1.0:
            raise ValueError("alert_salience must be in [0, 1]")
        self._episodic_memory = episodic_memory
        self._affect = affect
        self._sequence_resetters = list(sequence_resetters or [])
        self._trainer: Trainer = trainer or FakeTrainer()
        self._organ_window_runner = organ_window_runner
        self._voice_config: VoiceAlignmentConfig = voice_alignment_config or VoiceAlignmentConfig(
            intent_log_path=resolve("state/language/intent_expression.jsonl"),
            adapter_output_dir=resolve("state/sleep/adapters"),
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
        self._baseline_salience = float(baseline_salience)
        self._alert_salience = float(alert_salience)
        # Consolidation config
        self._fatigue_triggered = bool(fatigue_triggered)
        self._replay_window_s = float(replay_window_s)
        # Phase-3 associative replay
        self._associative_replay_enabled = bool(associative_replay_enabled)
        self._world_model = world_model
        # Module registry for oscillator hook
        self._active_modules: list[Any] = list(active_modules or [])
        # the perceptual locus module path
        self._perception_desired_path = perception_desired_path
        # Shared playlist clock (may be None in non-playlist modes).
        self._playlist_clock = playlist_clock
        # Pre-sleep desired locus, remembered in MEMORY only (survives one
        # sleep window within one process; deliberately NOT persisted to
        # disk — after a mid-sleep crash desired.json honestly still reads
        # 'off', because perception was suspended).
        self._pre_sleep_locus: Optional[str] = None

        self._sleep_lock = asyncio.Lock()
        # Tasks that must outlive a cancel of the sleep (the final affective reset).
        self._shielded_tasks: set[asyncio.Task[Any]] = set()
        self._builder = DPOPairBuilder()
        self._last_sleep_at: Optional[float] = None
        self._sleep_count: int = 0

        # Fatigue trigger state
        self._interoception_cursor: str = "0"
        self._affect_cursor: str = "0"
        # The planning and action selection modules' rest-request handling
        self._requested_rest_min_interval_s: float = requested_rest_min_interval_s
        if (
            isinstance(developmental_rest_s, bool)
            or not isinstance(developmental_rest_s, (int, float))
            or developmental_rest_s <= 0
            or not math.isfinite(developmental_rest_s)
        ):
            raise ValueError("developmental_rest_s must be a finite number greater than 0")
        self._developmental_rest_s = float(developmental_rest_s)
        self._entity_clock = entity_clock
        self._action_selection_cursor: str = "0"
        # Seed from boot time so a fresh boot or module restart cannot bypass
        # the requested-rest interval. Fatigue/regulation triggers are
        # unaffected; this only guards planning and action selection modules' rest requests.
        self._last_sleep_ended_at: Optional[float] = (
            self._entity_clock.now()
            if self._entity_clock is not None
            else time.monotonic()
        )
        self._requested_sleep_trigger: bool = False
        # The rest request a requested sleep answers; acceptance is announced
        # from inside the pipeline right after ``sleep.sleep.started``.
        self._pending_rest: Optional[dict[str, Any]] = None
        self._requested_rest_accepted: bool = False
        # Sleep-time ignition audit (change sleep-ignition-audit): per-stream
        # cursors, seeded at initialize() to the CURRENT stream tails (the same
        # persisted-cursor pattern as _interoception_cursor) so the first sleep audits
        # only the post-boot waking window, never history.
        self._audit_cursors: dict[str, str] = {
            stream: "0"
            for stream in (
                "action_selection.out",
                "action_selection_feedback.out",
                "language.external",
                "language.internal",
                "effectors.out",
                "planning.out",
                "vocal.out",
                "sleep.out",
            )
        }
        self._broadcast_cursor: str = "0"

    @property
    def scheduler(self) -> RestScheduler:
        return self._scheduler

    @property
    def sleep_count(self) -> int:
        """Number of sleeps this entity has run (the sleep_index), restored across restarts from the resume checkpoint and stage.json."""
        return self._sleep_count

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
        # The sleep index names corpus files and tags sleep events, so it must not restart at 0.
        try:
            from kaine.lifecycle.stage import read_stage
            stage_state = read_stage()
        except Exception:
            log.warning(
                "sleep: failed to read stage state for sleep index; continuing with %d",
                self._sleep_count,
                exc_info=True,
            )
        else:
            if stage_state is not None and stage_state.sleep_count > self._sleep_count:
                self._sleep_count = stage_state.sleep_count
            if self._sleep_count > 0:
                log.info("sleep: sleep index resumes at %d", self._sleep_count)
        self._sleep_pending = False
        self._sleep_task = None
        # M1 — interval-based maintenance poll: RestScheduler.is_due() is
        # checked periodically and fires enter_sleep() when due, entirely
        # independent of the interoception.fatigue consumer (fulfilling the boot.py
        # promise). Due-ness itself is judged on the scheduler's (subjective)
        # clock; this loop only polls often enough to notice.
        self._tasks.append(
            asyncio.create_task(self._maintenance_poll_loop(), name="sleep-maintenance-poll")
        )
        # Ignition-audit cursors: seed to the current stream tails (mirrors the
        # _interoception_cursor seeding below) — each sleep then reads everything new
        # since its cursor, bounded to the window since _last_sleep_at.
        for stream in self._audit_cursors:
            try:
                latest = await self._bus.client.xrevrange(stream, count=1)
            except Exception:
                latest = []
            if latest:
                tail = latest[0][0]
                if isinstance(tail, bytes):
                    tail = tail.decode()
                self._audit_cursors[stream] = tail
        try:
            latest_ws = await self._bus.client.xrevrange("workspace.broadcast", count=1)
        except Exception:
            latest_ws = []
        if latest_ws:
            tail = latest_ws[0][0]
            if isinstance(tail, bytes):
                tail = tail.decode()
            self._broadcast_cursor = tail
        # Seed cursor so we only process new action selection module intents from now on.
        try:
            latest = await self._bus.client.xrevrange("action_selection.out", count=1)
        except Exception:
            latest = []
        if latest:
            entry_id = latest[0][0]
            if isinstance(entry_id, bytes):
                entry_id = entry_id.decode()
            self._action_selection_cursor = entry_id
        self._tasks.append(
            asyncio.create_task(self._action_selection_consumer_loop(), name="sleep-action-selection-consumer")
        )
        if self._fatigue_triggered:
            # Seed cursor so we only process new interoception module events from now on.
            try:
                latest = await self._bus.client.xrevrange("interoception.out", count=1)
            except Exception:
                latest = []
            if latest:
                entry_id = latest[0][0]
                if isinstance(entry_id, bytes):
                    entry_id = entry_id.decode()
                self._interoception_cursor = entry_id
            # Seed cursor so we only process new affect module events from now on.
            try:
                latest = await self._bus.client.xrevrange("affect.out", count=1)
            except Exception:
                latest = []
            if latest:
                entry_id = latest[0][0]
                if isinstance(entry_id, bytes):
                    entry_id = entry_id.decode()
                self._affect_cursor = entry_id
            self._tasks.append(
                asyncio.create_task(self._interoception_consumer_loop(), name="sleep-interoception-consumer")
            )

    async def shutdown(self) -> None:
        """Stop the loops, then end any in-flight sleep, then await held tasks.

        Awaits ``BaseModule.shutdown()`` first so the background loops stop
        and no new sleep can start. If a sleep is still running it is cancelled
        and awaited, so it ends the way a cancelled sleep always does: the
        affective reset runs and an aborted ``sleep.sleep.completed`` is published.
        The held tasks are then awaited so none is left pending when the event
        loop closes. Each wait is bounded by ``_SHUTDOWN_WAIT_S``, and a task still
        pending after that is logged and left.
        """
        await super().shutdown()

        sleep_task = getattr(self, "_sleep_task", None)
        if isinstance(sleep_task, asyncio.Task) and not sleep_task.done():
            sleep_task.cancel()
            done, pending = await asyncio.wait({sleep_task}, timeout=_SHUTDOWN_WAIT_S)
            if pending:
                log.warning("sleep: shutdown wait expired with sleep still pending")
            for task in done:
                # Retrieve the exception so it is not reported at garbage collection.
                if not task.cancelled():
                    task.exception()

        held = set(self._shielded_tasks)
        if held:
            done, pending = await asyncio.wait(held, timeout=_SHUTDOWN_WAIT_S)
            if pending:
                log.warning(
                    "sleep: shutdown wait expired with %d held task(s) still pending",
                    len(pending),
                )
            for task in done:
                # Retrieve the exception so it is not reported at garbage collection.
                if not task.cancelled():
                    task.exception()

    async def _interoception_consumer_loop(self) -> None:
        """Background loop: watch interoception.out and affect.out for maintenance triggers.

        Three event shapes trigger an immediate maintenance cycle when the sleep
        module is not already sleeping (subject to the same non-interruptibility /
        freeze-preemption guards as the interval-based trigger):

        * ``interoception.fatigue`` with ``crossed == true`` — the fatigue accumulator
          crossed its maintenance threshold.
        * ``interoception.regulation`` with ``action == "request_maintenance"`` — the
          homeostatic regulator escalated to requesting an earlier offline
          cycle.  The linkage is event-driven: the sleep module observes the advisory
          directly on ``interoception.out`` (the cycle engine separately latches an
          advisory ``maintenance_requested`` flag for diagnostics, but the sleep module
          does not read that flag).
        * ``affect.regulation`` with ``action == "request_maintenance"`` on
          ``affect.out``: emotion regulation's tier 3 request (paper §3.5).
        """
        try:
            while not self._stopped.is_set():
                try:
                    idle = True
                    interoception_entries, interoception_last_scanned = await self._bus.read_entries(
                        "interoception.out",
                        last_id=self._interoception_cursor,
                        count=32,
                        block_ms=0,
                    )
                    if interoception_last_scanned:
                        # H2 — advance by the last SCANNED id (decodable or
                        # not) so a poison batch cannot wedge the cursor.
                        self._interoception_cursor = interoception_last_scanned
                    if interoception_entries:
                        idle = False
                        for _, event in interoception_entries:
                            fatigue_trigger = event.type == "interoception.fatigue" and event.payload.get(
                                "crossed", False
                            )
                            regulation_trigger = (
                                event.type == "interoception.regulation"
                                and event.payload.get("action") == "request_maintenance"
                            )
                            if not (fatigue_trigger or regulation_trigger):
                                continue
                            if fatigue_trigger:
                                trigger = "fatigue"
                                log.info(
                                    "sleep: interoception.fatigue crossed=true — "
                                    "triggering fatigue-driven maintenance"
                                )
                            else:
                                trigger = "maintenance_request"
                                log.info(
                                    "sleep: interoception.regulation request_maintenance "
                                    "— triggering regulation-driven maintenance"
                                )
                            await self._start_maintenance_sleep(trigger)

                    affect_entries, affect_last_scanned = await self._bus.read_entries(
                        "affect.out",
                        last_id=self._affect_cursor,
                        count=32,
                        block_ms=0,
                    )
                    if affect_last_scanned:
                        # H2: advance by the last SCANNED id (decodable or
                        # not) so a poison batch cannot wedge the cursor.
                        self._affect_cursor = affect_last_scanned
                    if affect_entries:
                        idle = False
                        for _, event in affect_entries:
                            if (
                                event.type == "affect.regulation"
                                and event.payload.get("action") == "request_maintenance"
                            ):
                                log.info(
                                    "sleep: affect.regulation request_maintenance, "
                                    "triggering affect-driven maintenance"
                                )
                                await self._start_maintenance_sleep("affect_regulation")
                            elif (
                                event.type == "affect.rest_request"
                                and event.payload.get("reason") == "stimulus_spent"
                            ):
                                log.info(
                                    "sleep: affect.rest_request (stimulus spent), "
                                    "starting a developmental rest"
                                )
                                await self._start_developmental_rest()

                    if idle:
                        await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("sleep interoception consumer iteration failed")
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise

    async def _start_maintenance_sleep(self, trigger: Optional[str] = None) -> None:
        """Guarded start of an event-driven maintenance sleep.

        Shared helper so the lock/pending guard is identical for every
        event-driven trigger site. ``trigger`` names what started the sleep
        and travels with it as a local value down to ``enter_sleep``, so a
        trigger that loses the guard cannot change the running sleep's record.
        """
        # L3: hold the task reference (no GC mid-sleep)
        # and guard with a pending flag so a second
        # trigger while one sleep is starting cannot
        # double-fire and mis-annotate the running
        # sleep's summary via the loser branch.
        if not self._sleep_lock.locked() and not self._sleep_pending:
            self._sleep_pending = True
            self._sleep_task = asyncio.create_task(
                self._fatigue_triggered_enter_sleep(trigger),
                name="sleep-fatigue-sleep",
            )

    async def _start_developmental_rest(self) -> None:
        """Guarded start of a developmental rest on a spent stimulus."""
        if not self._sleep_lock.locked() and not self._sleep_pending:
            self._sleep_pending = True
            self._sleep_task = asyncio.create_task(
                self._developmental_rest_enter_sleep(),
                name="sleep-developmental-rest",
            )

    async def _developmental_rest_enter_sleep(self) -> None:
        try:
            await self.enter_sleep(trigger="developmental_rest")
        except SleepBusyError:
            log.debug("sleep: developmental rest skipped, sleep already running")
        except Exception:
            log.exception("sleep: developmental rest enter_sleep failed")
        finally:
            self._sleep_pending = False

    async def _action_selection_consumer_loop(self) -> None:
        """Background loop: watch action_selection.out for rest requests.

        The planning-module-originated ``intent.rest`` events (and any other rest intents)
        request an entity-time sleep. Accepted requests start a maintenance
        cycle with trigger ``"requested"``; refusals publish a content-free
        ``sleep.rest_request`` event.
        """
        try:
            while not self._stopped.is_set():
                try:
                    entries, last_scanned = await self._bus.read_entries(
                        "action_selection.out",
                        last_id=self._action_selection_cursor,
                        count=32,
                        block_ms=0,
                    )
                    if last_scanned:
                        self._action_selection_cursor = last_scanned
                    if entries:
                        for _, event in entries:
                            if event.type != "intent.rest":
                                continue
                            payload = getattr(event, "payload", None) or {}
                            await self._handle_rest_request(payload)
                    else:
                        await asyncio.sleep(0.05)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("sleep action selection consumer iteration failed")
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise

    async def _fatigue_triggered_enter_sleep_inner(self, trigger: Optional[str] = None) -> None:
        """Fire a maintenance cycle for an event-driven trigger.

        ``trigger`` is passed on to ``enter_sleep`` and recorded by that
        sleep alone.
        """
        try:
            await self.enter_sleep(trigger=trigger)
        except SleepBusyError:
            log.debug("sleep: fatigue trigger: already sleeping")
        except Exception:
            log.exception("sleep: fatigue-triggered sleep failed")
        finally:
            # L3 — clear the trigger wrapper's in-flight annotation
            # (_sleep_pending) once the sleep settles, so a later trigger
            # may fire again. No trigger state outlives the sleep.
            self._sleep_pending = False

    async def _publish_rest_request(
        self, accepted: bool, reason: str, origin: Any, proposal_id: Any = None
    ) -> None:
        """Emit the content-free ``sleep.rest_request`` diagnostic.

        Always salience 0.0 so the diagnostic never competes for the workspace.
        """
        payload = {"accepted": accepted, "reason": reason, "origin": origin}
        if proposal_id is not None:
            payload["proposal_id"] = proposal_id
        try:
            await self.publish(
                "sleep.rest_request",
                payload,
                salience=0.0,
            )
        except Exception:
            log.warning("sleep: rest_request publish failed", exc_info=True)

    async def _handle_rest_request(self, payload: dict[str, Any]) -> None:
        """Accept or refuse a planning/action selection module rest request.

        Publishes a content-free ``sleep.rest_request`` diagnostic at
        salience 0.0 and, when accepted, starts a requested sleep through the
        same guarded path as fatigue/regulation triggers. ``accepted: true`` is
        announced from inside the pipeline immediately after
        ``sleep.sleep.started``; otherwise the reason is ``busy``,
        ``too_soon`` or, if the pipeline starts and then aborts, ``aborted``.
        """
        origin = payload.get("origin")
        proposal_id = payload.get("proposal_id")
        if self._sleep_lock.locked() or self._sleep_pending:
            await self._publish_rest_request(False, "busy", origin, proposal_id)
            log.debug(
                "sleep: rest request refused (reason=busy, origin=%s, proposal_id=%s)",
                origin, proposal_id,
            )
            return

        now = self._entity_clock.now() if self._entity_clock is not None else time.monotonic()
        last = self._last_sleep_ended_at
        if last is not None and (now - last) < self._requested_rest_min_interval_s:
            await self._publish_rest_request(False, "too_soon", origin, proposal_id)
            log.debug(
                "sleep: rest request refused (reason=too_soon, origin=%s, proposal_id=%s)",
                origin, proposal_id,
            )
            return

        # Attempt the guarded start. Acceptance is published by the pipeline once
        # the sleep has actually begun; if the guard loses the race, the task
        # publishes busy; if the pipeline aborts, the task publishes aborted.
        self._sleep_pending = True
        self._requested_sleep_trigger = True
        self._sleep_task = asyncio.create_task(
            self._requested_enter_sleep(origin, proposal_id),
            name="sleep-requested-sleep",
        )

    async def _requested_enter_sleep(self, origin: Any, proposal_id: Any) -> None:
        """Fire a maintenance cycle in response to an accepted rest request."""
        pending = {"proposal_id": proposal_id, "origin": origin}
        try:
            self._pending_rest = pending
            self._requested_rest_accepted = False
            await self.enter_sleep(trigger="requested")
        except SleepBusyError:
            log.debug(
                "sleep: requested sleep: already sleeping (origin=%s, proposal_id=%s)",
                origin, proposal_id,
            )
            await self._publish_rest_request(False, "busy", origin, proposal_id)
        except Exception:
            log.exception(
                "sleep: requested sleep failed (origin=%s, proposal_id=%s)",
                origin, proposal_id,
            )
            if self._requested_rest_accepted:
                await self._publish_rest_request(False, "aborted", origin, proposal_id)
            else:
                await self._publish_rest_request(False, "busy", origin, proposal_id)
        finally:
            self._sleep_pending = False
            self._requested_sleep_trigger = False
            self._pending_rest = None
            self._requested_rest_accepted = False

    async def enter_sleep(self, trigger: Optional[str] = None) -> dict[str, Any]:
        """Run the five-phase sleep pipeline. Perception is suspended for the whole sleep."""
        if self._sleep_lock.locked():
            raise SleepBusyError("Sleep is already in progress")

        async with self._sleep_lock:
            self._suspend_perception()
            try:
                if trigger is None:
                    return await self._run_pipeline()
                return await self._run_pipeline(trigger=trigger)
            finally:
                self._restore_perception()
                self._last_sleep_ended_at = (
                    self._entity_clock.now()
                    if self._entity_clock is not None
                    else time.monotonic()
                )

    def _suspend_perception(self) -> None:
        """Set locus to 'off' to suspend external perception for the sleep.

        Reuses the perception_state.write_desired_locus machinery (the same
        path used by PerceptualLocusLocus and the dashboard operator toggle).  Zero
        raw-sense-data persistence is preserved: we only write the desired
        locus flag, never any sensory content.

        The pre-sleep desired locus is remembered in memory (on this module) so
        wake restores it instead of hardcoding 'physical'; unknown or unreadable
        values coerce to the perception_state default. The shared playlist
        clock is paused AFTER the locus flip so the stimulus can never advance
        while the entity cannot perceive it; co-locating the pause with the
        locus write means the pipeline's `finally` restore covers both.
        """
        try:
            from kaine.perception_state import _coerce_locus, read_desired

            # First-write-wins within a window: only remember the locus on
            # the first suspend. A second suspend would read the "off" we
            # just wrote and clobber the true pre-sleep locus, causing
            # restore to leave perception dark. _restore_perception clears
            # this, re-arming the guard for the next window.
            if self._pre_sleep_locus is None:
                desired = read_desired(path=self._perception_desired_path)
                self._pre_sleep_locus = _coerce_locus(getattr(desired, "locus", "physical"))
        except Exception:
            # Honest degradation: nothing remembered → restore falls back to
            # 'physical' (the old behavior).
            self._pre_sleep_locus = None
            log.debug("sleep: could not read pre-sleep locus", exc_info=True)
        try:
            from kaine.perception_state import write_desired_locus

            write_desired_locus("off", path=self._perception_desired_path)
            log.debug("sleep: perceptual locus -> off (sleep)")
        except Exception:
            log.warning(
                "sleep: perception suspension (write_desired_locus) failed",
                exc_info=True,
            )
        # Pause the shared playlist clock under the sleep module's holder. A missing
        # clock (non-playlist modes) is an honest no-op, not a crash.
        if self._playlist_clock is not None:
            try:
                self._playlist_clock.pause("sleep")
            except Exception:
                log.warning("sleep: playlist clock pause failed", exc_info=True)

    def _restore_perception(self) -> None:
        """Restore the remembered pre-sleep locus when sleep ends
        (falling back to 'physical' only when nothing was remembered, e.g.
        suspend never ran), and resume the shared playlist clock so playback
        continues from the pause point. Only the locus flag is written — never
        any sensory content."""
        locus = self._pre_sleep_locus or "physical"
        self._pre_sleep_locus = None
        try:
            from kaine.perception_state import write_desired_locus

            write_desired_locus(locus, path=self._perception_desired_path)
            log.debug("sleep: perceptual locus -> %s (sleep ended)", locus)
        except Exception:
            log.warning(
                "sleep: perception restore (write_desired_locus) failed",
                exc_info=True,
            )
        # Resume the shared playlist clock under the sleep module's holder so the
        # stimulus resumes with perception (the invariant: clock paused ⇔
        # perception suspended).
        if self._playlist_clock is not None:
            try:
                self._playlist_clock.resume("sleep")
            except Exception:
                log.warning("sleep: playlist clock resume failed", exc_info=True)

    async def _publish_association(self, pair: dict[str, Any]) -> None:
        """Publish one phase-3 co-replayed pair as ``sleep.association`` on the sleep module's out-stream.

        Carries only the two point ids and the link weight (no memory content).
        """
        await self.publish(
            "sleep.association",
            dict(pair),
            salience=self._baseline_salience,
        )

    def _open_world_model_window(self) -> None:
        """Open the world model module's scenario window before phases 2 and 3."""
        method = getattr(self._world_model, "open_scenario_window", None)
        if method is None:
            return
        try:
            method()
        except Exception:
            log.warning("sleep: opening World model's scenario window failed", exc_info=True)

    def _close_world_model_window(self) -> None:
        """Close the world model module's scenario window after phases 2 and 3."""
        method = getattr(self._world_model, "close_scenario_window", None)
        if method is None:
            return
        try:
            method()
        except Exception:
            log.warning("sleep: closing World model's scenario window failed", exc_info=True)

    async def _run_final_affective_reset(self) -> PhaseResult:
        """Run phase 5, the affective reset, so that a cancel cannot interrupt it.

        The reset runs as its own task awaited through ``asyncio.shield``. A
        cancel that arrives while it runs cancels only the wait: the reset still
        finishes, and the CancelledError propagates to the caller.
        """
        task = asyncio.ensure_future(affective_reset(self._affect))
        # Hold a reference so a reset left running by a second cancel is not
        # garbage-collected before it finishes.
        self._shielded_tasks.add(task)
        task.add_done_callback(self._shielded_tasks.discard)
        return await asyncio.shield(task)

    def _rest_clock_now(self) -> float:
        """Return the current rest-hold clock time.

        Uses the injected entity clock when available so developmental rests
        can be tested with a fake clock; otherwise falls back to real time.
        """
        if self._entity_clock is not None:
            return self._entity_clock.now()
        return time.monotonic()

    async def _hold_developmental_rest(self, started: float) -> None:
        """Hold the developmental rest for the configured duration."""
        log.info(
            "sleep: developmental rest holds until %.0f s after it began",
            self._developmental_rest_s,
        )
        while not self._stopped.is_set():
            remaining = self._developmental_rest_s - (self._rest_clock_now() - started)
            if remaining <= 0:
                break
            await asyncio.sleep(min(1.0, remaining))
        log.info("sleep: developmental rest hold ended")

    async def _run_pipeline_inner(self, trigger: Optional[str] = None) -> dict[str, Any]:
        # Pipeline latency + the started_at/last_sleep_at marks measure REAL
        # infrastructure wall-time (how long the sleep work actually took / when
        # it ran), like the cycle's slip measurement — never the subjective
        # clock. Only the sleep-DUE scheduling (RestScheduler, above) is
        # subjective.
        # infrastructural: real time, not subjective
        start = time.monotonic()
        self._sleep_count += 1
        rest_started = self._rest_clock_now()
        await self.publish(
            "sleep.sleep.started",
            # infrastructural: real time. Every sleep carries its sleep_index
            # and the trigger that started it (None for a direct call).
            {
                "started_at": time.time(),
                "sleep_index": self._sleep_count,
                "trigger": trigger,
            },
            salience=self._baseline_salience,
        )
        if trigger == "requested" and self._pending_rest is not None:
            pending = self._pending_rest
            self._pending_rest = None
            self._requested_rest_accepted = True
            await self._publish_rest_request(
                True, "accepted", pending["origin"], pending.get("proposal_id")
            )
        phase_results: list[PhaseResult] = []
        housekeeping_report: Optional[dict[str, Any]] = None

        try:
            # --- Phase 1: Light Consolidation ---
            # Short-term to episodic transfer + oscillator frequency hook
            phase_results.append(
                await light_consolidation(
                    self._episodic_memory,
                    active_modules=self._active_modules,
                    frequency_scale=0.5,
                )
            )

            # --- Phases 2 and 3 keep the world model module's scenario window open ---
            # Phase 2's replay cues the world model module through episodic_memory.replay events on the bus
            # and phase 3 no longer cues it directly. The sleep module opens the world model module's scenario
            # window around both, so the window never depends on the world model module
            # having seen sleep.sleep.started, and closes it on any exit.
            self._open_world_model_window()
            try:
                # --- Phase 2: Deep Consolidation + Downscaling ---
                # Replay, then downscaling of trace strengths (paper A.10). Perception is already suspended for the whole sleep (enter_sleep).
                phase_results.append(
                    await deep_consolidation(
                        self._episodic_memory,
                        replay_window_s=self._replay_window_s,
                        defer_prune=self._associative_replay_enabled,
                    )
                )

                # --- Phase 3: Associative Replay (behind feature flag) ---
                # Co-replays related trace pairs of different periods as weighted links, then prunes (paper A.10).
                phase_results.append(
                    await associative_replay(
                        enabled=self._associative_replay_enabled,
                        episodic_memory=self._episodic_memory,
                        publish=self._publish_association,
                    )
                )
            finally:
                self._close_world_model_window()

            # --- Phase 4: Voice Alignment ---
            voice_result, voice_phase = await self._run_voice_alignment()
            phase_results.append(voice_phase)

            # Rotate the waking intent log into the per-sleep corpus now that voice
            # alignment has consumed it.  This must never break sleep, so failures
            # are caught and logged but do not halt the pipeline.
            corpus_summary: dict[str, Any] = {
                "rotated": None,
                "corpus_bytes": 0,
                "warned": False,
                "encrypted_rewrites": 0,
            }
            rotated_path: Optional[Path] = None
            # Only a rotation that raised is a failed measurement; a corpus-ceiling
            # check failing after a good rotation must not mask a fresh measure.
            rotation_failed = False
            rotation_done = False
            try:
                rotated_path = await asyncio.to_thread(
                    rotate_intent_log,
                    self._voice_config.intent_log_path,
                    self._voice_config.intent_log_path.parent / "intent_log",
                    sleep_index=self._sleep_count,
                )
                rotation_done = True
                if rotated_path is not None:
                    corpus_summary["rotated"] = rotated_path.name

                corpus_dir = self._voice_config.intent_log_path.parent / "intent_log"
                for f in sorted(corpus_dir.glob("sleep-*.jsonl")):
                    if await asyncio.to_thread(has_plaintext_line, f):
                        if await asyncio.to_thread(rewrite_encrypted, f):
                            corpus_summary["encrypted_rewrites"] += 1

                ceiling_info = await asyncio.to_thread(
                    check_corpus_ceiling,
                    self._voice_config.intent_log_path.parent / "intent_log",
                    ceiling_gb=self._voice_config.corpus_ceiling_gb,
                )
                corpus_summary["corpus_bytes"] = ceiling_info["corpus_bytes"]
                corpus_summary["warned"] = ceiling_info["warned"]
            except Exception as exc:
                rotation_failed = not rotation_done
                # Recorded so the summary never reads a failed rotation as "nothing
                # to rotate".
                corpus_summary["error"] = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "sleep: intent log corpus rotation/ceiling check failed",
                    exc_info=True,
                )

            # --- Voice measures (content-free) ----------------------------------
            # Computed from the freshly rotated corpus. Wrapped in try/except so a
            # measures failure can never break sleep.
            voice_measures: Optional[dict[str, Any]] = None
            if rotated_path is not None:
                try:
                    base_profiles_dir = (
                        Path(__file__).resolve().parent / "base_voice_profiles"
                    )
                    digest = await asyncio.to_thread(
                        organ_gguf_sha256,
                        self._organ_gguf_path,
                        self._voice_config.intent_log_path.parent / "organ_gguf_digest.json",
                    )
                    base_profile = await asyncio.to_thread(
                        load_base_profile,
                        digest,
                        base_profiles_dir,
                    )
                    cumulative_path = (
                        self._voice_config.intent_log_path.parent
                        / "voice_profile_cumulative.json"
                    )
                    cumulative: Optional[dict[str, Any]] = None
                    if cumulative_path.is_file():
                        try:
                            cumulative = json.loads(
                                cumulative_path.read_text(encoding="utf-8")
                            )
                        except Exception:
                            cumulative = None
                    measures, new_cumulative = await asyncio.to_thread(
                        compute_sleep_measures,
                        rotated_path,
                        base_profile=base_profile,
                        cumulative=cumulative,
                    )
                    voice_measures = measures
                    await asyncio.to_thread(
                        _append_jsonl,
                        self._voice_config.intent_log_path.parent / "voice_measures.jsonl",
                        measures,
                    )
                    await asyncio.to_thread(
                        write_json_atomic,
                        self._voice_config.intent_log_path.parent
                        / "voice_measures_latest.json",
                        measures,
                    )
                    if new_cumulative is not None:
                        await asyncio.to_thread(
                            write_json_atomic,
                            cumulative_path,
                            new_cumulative,
                        )
                except Exception:
                    log.warning(
                        "sleep: voice measures computation failed",
                        exc_info=True,
                    )
                    rotation_failed = True
                    voice_measures = None

            if rotation_failed:
                try:
                    await asyncio.to_thread(
                        write_json_atomic,
                        self._voice_config.intent_log_path.parent
                        / "voice_measures_latest.json",
                        {
                            "measurement_failed": True,
                            "timestamp": time.strftime(
                                "%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()
                            ),
                        },
                    )
                except Exception:
                    log.warning(
                        "sleep: failed to write measurement_failed marker",
                        exc_info=True,
                    )

            if trigger == "developmental_rest":
                await self._hold_developmental_rest(rest_started)

            if self._housekeeper is not None:
                store_bytes: Optional[int] = None
                for r in phase_results:
                    if getattr(r, "phase", None) == "deep_consolidation":
                        downscale = (getattr(r, "metadata", None) or {}).get("downscale")
                        if isinstance(downscale, dict):
                            found = downscale.get("store_bytes")
                            if isinstance(found, int) and not isinstance(found, bool):
                                store_bytes = found
                        break
                try:
                    housekeeping_report = await self._housekeeper.run(
                        episodic_store_bytes=store_bytes
                    )
                    if self._housekeeping_pressure is not None:
                        # Paper A.5: each successful housekeeping report sets
                        # the pressure that scales awake fatigue build-up.
                        self._housekeeping_pressure.set_from_sleep(housekeeping_report)
                except Exception:
                    log.warning("sleep: housekeeping failed (continuing)", exc_info=True)
                    housekeeping_report = {"failed": True}
                log.info(
                    "sleep: housekeeping report: stopped=%s moved_files=%s pressure=%s",
                    housekeeping_report.get("stopped"),
                    housekeeping_report.get("moved_files"),
                    housekeeping_report.get("pressure"),
                )
        finally:
            # Sleep ends with the affective reset on every path (paper §3.5),
            # including an exception or a cancel in phases 1 to 4.
            phase_results.append(await self._run_final_affective_reset())

        elapsed_ms = (time.monotonic() - start) * 1000.0
        # Capture the previous sleep mark BEFORE overwriting it; the ignition
        # audit window must start at the prior sleep (or boot), never the
        # current one. The current sleep's own sleep.sleep.started has a
        # timestamp >= previous_sleep_at, so it is included in the window.
        previous_sleep_at = self._last_sleep_at
        self._last_sleep_at = time.time()
        self._scheduler.mark_completed()

        summary = {
            "total_elapsed_ms": elapsed_ms,
            "phases": [asdict(r) for r in phase_results],
            "voice_alignment": {
                "accepted": voice_result.accepted,
                "adapter_path": str(voice_result.adapter_path)
                if voice_result.adapter_path
                else None,
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
            # The trigger that started this sleep, and whether it was fatigue
            "trigger": trigger,
            "fatigue_triggered": trigger == "fatigue",
        }
        # The counts the paper says each sleep records, at top level so the
        # research log can keep them.
        # Read defensively: the summary must never break the sleep.
        downscale_meta = None
        for r in phase_results:
            if getattr(r, "phase", None) == "deep_consolidation":
                found = (getattr(r, "metadata", None) or {}).get("downscale")
                downscale_meta = found if isinstance(found, dict) else None
                break
        summary["memory_pruned_floor"] = (
            downscale_meta.get("pruned_floor") if downscale_meta else None
        )
        summary["memory_pruned_budget"] = (
            downscale_meta.get("pruned_budget") if downscale_meta else None
        )
        summary["memory_store_bytes"] = (
            downscale_meta.get("store_bytes") if downscale_meta else None
        )
        summary["memory_downscale_blocked"] = (
            downscale_meta.get("blocked") if downscale_meta else None
        )
        summary["memory_blocked_sleeps"] = (
            downscale_meta.get("blocked_sleeps") if downscale_meta else None
        )
        summary["memory_persist_refusals"] = (
            downscale_meta.get("persist_refusals") if downscale_meta else None
        )

        # With associative replay on, pruning follows the co-replays in phase 3
        # (paper A.10), so its counts replace phase 2's.
        prune_meta = None
        for r in phase_results:
            if getattr(r, "phase", None) == "associative_replay":
                found = (getattr(r, "metadata", None) or {}).get("prune")
                prune_meta = found if isinstance(found, dict) else None
                break
        if prune_meta is not None and "skipped" not in prune_meta:
            summary["memory_pruned_floor"] = prune_meta.get("pruned_floor")
            summary["memory_pruned_budget"] = prune_meta.get("pruned_budget")
            summary["memory_store_bytes"] = prune_meta.get("store_bytes")
            summary["memory_links_pruned"] = prune_meta.get("links_pruned")
            summary["memory_nodes_pruned"] = prune_meta.get("nodes_pruned")
        summary["corpus"] = corpus_summary
        summary["voice_measures"] = voice_measures
        if self._housekeeper is not None:
            summary["housekeeping"] = housekeeping_report
        all_succeeded = all(r.success for r in phase_results)
        salience = self._baseline_salience if all_succeeded else self._alert_salience
        summary["alert"] = not all_succeeded
        # Sleep-time ignition audit (change sleep-ignition-audit): runs
        # unconditionally on EVERY sleep, before the completed publish, so the
        # content-free payload is emitted on sleep.out AND merged into the
        # completed metadata — riding sleep.sleep.completed into the
        # sleep_snapshots JSONL, carrying sleep_index.
        try:
            summary["ignition_audit"] = await self._run_ignition_audit(since=previous_sleep_at)
        except Exception:
            log.warning("sleep: ignition audit step failed (continuing)", exc_info=True)
        if trigger == "developmental_rest":
            summary["rest_seconds"] = self._developmental_rest_s
        # Publishing sleep.sleep.completed causes the interoception module to reset its
        # FatigueAccumulator (interoception._sleep_event_loop handles this event).
        await self.publish("sleep.sleep.completed", summary, salience=salience)
        return summary

    async def _drain_audit_stream(self, stream: str) -> list[tuple[str, Any]]:
        """Read everything new on ``stream`` since its audit cursor.

        Batch loop with ``block_ms=0`` until empty, advancing by the last
        SCANNED id (decodable or not) exactly like ``_interoception_consumer_loop`` so a
        poison batch cannot wedge the cursor.
        """
        events: list[tuple[str, Any]] = []
        cursor = self._audit_cursors.get(stream, "0")
        while True:
            entries, last_scanned = await self._bus.read_entries(
                stream, last_id=cursor, count=64, block_ms=0
            )
            if last_scanned:
                cursor = last_scanned
            # Stop only when read_entries saw nothing at all (decodable or not).
            if last_scanned is None:
                break
            events.extend(entries)
        self._audit_cursors[stream] = cursor
        return events

    async def _run_ignition_audit(self, since: Optional[float] = None) -> dict[str, Any]:
        """Sleep-time ignition audit (change sleep-ignition-audit) — pure data.

        Unconditional on every sleep: collects intents/realizations from
        ``action_selection.out`` / ``language.external`` / ``language.internal`` /
        ``effectors.out`` since the per-stream cursors, plus
        ``workspace.broadcast`` snapshots since the broadcast cursor (read via
        the decode-safe workspace path — never ``bus.range``, which cannot
        decode broadcast entries), bounded to the window starting at ``since``.
        ``None`` means from boot. Classification itself is the PURE
        ``classify_realizations`` — no bus, no I/O. The payload is content-free
        (counts, entry_ids, event types, salience values, sleep_index only);
        ``intent.act`` on ``planning.out`` is counted separately as unrealizable
        because no effector reads ``planning.out``. ANY exception degrades to a
        logged warning + ``{"error": <ExcTypeName>}`` — the sleep must never
        fail because auditing failed. Boundary: The sleep module never imports
        ``kaine.evaluation``; only ``kaine.modules.sleep.ignition_audit``.
        Realizations are linked to their intents through the intent log's
        record_id to intent_entry_id join.
        """
        from kaine.modules.sleep.corpus import intent_record_links
        from kaine.modules.sleep.ignition_audit import classify_realizations

        try:
            since_ms: Optional[float] = None
            if since is not None:
                since_ms = since * 1000.0

            def _in_window(entry_id: str) -> bool:
                if since_ms is None:
                    return True
                try:
                    return float(entry_id.split("-")[0]) >= since_ms
                except Exception:
                    return True  # honest default: keep, never guess

            intents: list[dict[str, Any]] = []
            realizations: list[dict[str, Any]] = []
            proposal_outcomes: list[dict[str, Any]] = []
            for stream in (
                "action_selection.out",
                "action_selection_feedback.out",
                "language.external",
                "language.internal",
                "effectors.out",
                "planning.out",
                "vocal.out",
                "sleep.out",
            ):
                for entry_id, event in await self._drain_audit_stream(stream):
                    if not _in_window(entry_id):
                        continue
                    record = {
                        "stream": stream,
                        "type": event.type,
                        "payload": dict(getattr(event, "payload", None) or {}),
                    }
                    if event.type.startswith("intent."):
                        intents.append(record)
                    elif event.type == "action_selection.proposal_outcome":
                        proposal_outcomes.append(record)
                    elif event.type == "sleep.sleep.started":
                        # A requested sleep counts as a realized rest event.
                        realizations.append(record)
                    else:
                        realizations.append(record)
            broadcasts: list[dict[str, Any]] = []
            cursor = self._broadcast_cursor
            while True:
                entries, last_scanned = await self._bus.read_workspace_entries(cursor, count=64)
                if last_scanned:
                    cursor = last_scanned
                if not entries:
                    break
                for entry_id, snap in entries:
                    if _in_window(entry_id):
                        broadcasts.append(snap)
            self._broadcast_cursor = cursor
            try:
                corpus_dir = self._voice_config.intent_log_path.parent / "intent_log"
                link_paths = (
                    await asyncio.to_thread(
                        intent_record_paths,
                        self._voice_config.intent_log_path,
                        corpus_dir,
                    )
                )[-2:]
                record_links = await asyncio.to_thread(
                    intent_record_links, link_paths
                )
            except Exception:
                log.warning(
                    "sleep: ignition audit could not read intent-log links (continuing unlinked)",
                    exc_info=True,
                )
                record_links = {}
            report = classify_realizations(
                broadcasts,
                intents,
                realizations,
                proposal_outcomes=proposal_outcomes,
                sleep_index=self._sleep_count,
                record_links=record_links,
            )
            payload = report.as_payload()
        except Exception as exc:
            log.warning("sleep: ignition audit failed (continuing)", exc_info=True)
            payload = {
                "sleep_index": self._sleep_count,
                "realized_total": 0,
                "unrealizable_planning_intents": 0,
                "synthesized_realizations": 0,
                "input": 0,
                "drive": 0,
                "self": 0,
                "planning_initiated": 0,
                "planning_proposals_realized": 0,
                "planning_proposals_declined": 0,
                "planning_proposals_forwarded": 0,
                "audit_error": type(exc).__name__,
            }
        # Content-free bus event on sleep.out. An intermediate publish must
        # never propagate (catch, log and continue, as for every intermediate publish).
        try:
            await self.publish(
                "sleep.ignition_audit",
                dict(payload),
                salience=self._baseline_salience,
            )
        except Exception:
            log.warning(
                "sleep: ignition-audit publish failed (continuing)",
                exc_info=True,
            )
        return payload

    async def _run_voice_alignment(self) -> tuple[TrainingResult, PhaseResult]:
        start_ms = time.monotonic() * 1000.0

        def _meta(extra: dict[str, Any]) -> dict[str, Any]:
            return dict(extra)

        # Two-layer safety gate. Both `[sleep.voice_alignment].enabled`
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
                "operator approval not granted (set KAINE_VOICE_ALIGNMENT_OPERATOR_APPROVED=1)"
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
        # Stage 0 gate: training on self-generated preferences is retired until
        # Stage 2 provides a validated preference source (D12).
        if self._voice_config.preference_source not in TRAINING_SOURCES:
            skip_reason = "skipped: no validated preference source (voice-development Stage 2)"
            log.info("voice_alignment skipped: %s", skip_reason)
            voice_result = TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason=skip_reason,
                samples_used=0,
            )
            return voice_result, PhaseResult(
                phase="voice_alignment",
                success=True,
                elapsed_ms=time.monotonic() * 1000.0 - start_ms,
                metadata=_meta(
                    {
                        "skipped": "no validated preference source",
                        "training_skipped": True,
                        "preference_source": self._voice_config.preference_source,
                    }
                ),
            )
        pairs: list[Any] = []
        try:
            paths = await asyncio.to_thread(
                intent_record_paths,
                self._voice_config.intent_log_path,
                self._voice_config.intent_log_path.parent / "intent_log",
            )
            pairs, _scanned, _usable = await asyncio.to_thread(
                self._builder.build_with_counts,
                paths,
                max_pairs=self._voice_config.max_samples,
            )
        except Exception:
            log.warning("voice_alignment: pair build failed", exc_info=True)
            pairs = []
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
        return await self._train_on_pairs(pairs, start_ms, _meta)

    async def _attach_system_prompts(
        self, pairs: list[DPOPair],
    ) -> tuple[list[DPOPair], int]:
        """Attach verified system prompts to DPO pairs.

        Drops pairs whose stored system prompt is missing or fails digest
        verification.  File I/O is run in a worker thread.
        """

        def _attach() -> tuple[list[DPOPair], int]:
            store_dir = store_dir_for(self._voice_config.intent_log_path)
            kept: list[DPOPair] = []
            dropped = 0
            for pair in pairs:
                digest = pair.metadata.get("system_digest")
                text = read_system_prompt(store_dir, digest) if digest else None
                if text is None:
                    dropped += 1
                    continue
                kept.append(dataclasses.replace(pair, system=text))
            return kept, dropped

        return await asyncio.to_thread(_attach)

    async def _train_on_pairs(
        self, pairs, start_ms, _meta
    ) -> tuple[TrainingResult, PhaseResult]:
        window_meta: dict[str, Any] = {}
        pairs, dropped = await self._attach_system_prompts(pairs)
        if not pairs:
            elapsed_ms = time.monotonic() * 1000.0 - start_ms
            voice_result = TrainingResult(
                accepted=False,
                adapter_path=None,
                capability_loss=0.0,
                reason=f"no pair has a verified system prompt ({dropped} dropped)",
                samples_used=0,
            )
            return voice_result, PhaseResult(
                phase="voice_alignment",
                success=True,
                elapsed_ms=elapsed_ms,
                metadata=_meta({"pairs_without_system": dropped}),
            )

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
            "pairs_without_system": dropped,
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
            # Kept for backward compatibility with pre-change readers/tests.
            "original_due_at": self._scheduler.original_due_at,
            "effective_due_at": self._scheduler.effective_due_at,
            # Persisted sleep index so filenames and audit tags do not restart at 0.
            "sleep_index": self._sleep_count,
            # Process-independent schedule: time remaining until sleep.
            "schedule": self._scheduler.export_remaining(),
        }

    def deserialize(self, state: dict[str, Any]) -> None:
        if "last_sleep_at" in state:
            value = state["last_sleep_at"]
            self._last_sleep_at = None if value is None else float(value)
        # The monotonic `original_due_at` / `effective_due_at` values belong to
        # the old process and must not be used directly. We restore from the
        # remaining-time snapshot instead.
        if "schedule" in state:
            sched = state["schedule"]
            try:
                if not isinstance(sched, dict):
                    raise ValueError("schedule must be a dict")
                self._scheduler.restore_remaining(
                    float(sched["original_due_in"]),
                    float(sched["effective_due_in"]),
                )
            except Exception as exc:
                log.warning(
                    "sleep: malformed schedule in snapshot; starting a fresh interval: %s",
                    exc,
                )
        else:
            log.info("sleep: snapshot has no schedule; starting a fresh interval")
        if "sleep_index" in state:
            value = state["sleep_index"]
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                self._sleep_count = max(self._sleep_count, value)
            else:
                log.warning("sleep: malformed sleep_index in snapshot; keeping %d", self._sleep_count)

    async def _run_pipeline(self, trigger: Optional[str] = None) -> dict[str, Any]:
        """M2: guarantee ``sleep.sleep.completed`` is published.

        The pipeline body publishes the normal completed event on success.
        If the body raises, including a transient failure of its own
        completed publish, this wrapper publishes a completed event
        carrying an ``"aborted": True`` flag (content-free: the reason field
        carries only the exception class name). The interoception module treats it identically
        to a normal completion, so ``_in_sleep`` can never wedge and
        faster_decay always stops.

        ``BaseException`` is caught so a cancellation also publishes the
        aborted completed event; the original exception is then re-raised.
        """
        try:
            if trigger is None:
                return await self._run_pipeline_inner()
            return await self._run_pipeline_inner(trigger=trigger)
        except BaseException as exc:
            if isinstance(exc, Exception):
                log.exception("sleep: sleep pipeline aborted")
            else:
                log.warning("sleep: sleep pipeline cancelled (%s)", type(exc).__name__)
            payload: dict[str, Any] = {
                "aborted": True,
                "reason": type(exc).__name__,
                "trigger": trigger,
            }
            if trigger == "developmental_rest":
                payload["rest_seconds"] = self._developmental_rest_s
            publish = asyncio.ensure_future(
                self.publish(
                    "sleep.sleep.completed",
                    payload,
                    salience=self._baseline_salience,
                )
            )
            # Held like the final reset, so a second cancel cannot drop it.
            self._shielded_tasks.add(publish)
            publish.add_done_callback(self._shielded_tasks.discard)
            try:
                await asyncio.shield(publish)
            except Exception:
                log.exception("sleep: aborted-sleep completed publish also failed")
            raise

    async def _fatigue_triggered_enter_sleep(self, trigger: Optional[str] = None) -> None:
        """L3 — wrapper owning the pending-guard bookkeeping.

        Clears ONLY the pending guard here. The trigger is a local value
        passed to ``enter_sleep``, so a losing (SleepBusyError) branch
        cannot change the running sleep's recorded trigger. The task
        reference is held on ``self._sleep_task`` so the sleep is never
        garbage-collected mid-run.
        """
        try:
            await self._fatigue_triggered_enter_sleep_inner(trigger)
        finally:
            self._sleep_pending = False

    async def _interval_triggered_enter_sleep(self) -> None:
        """Interval-based maintenance cycle (M1), recorded as the backstop."""
        try:
            await self.enter_sleep(trigger="backstop")
        except SleepBusyError:
            # A sleep is already in progress — the interval net's job is done
            # for this period; the running sleep covers the maintenance.
            pass
        except Exception:
            log.exception("sleep: interval-triggered sleep failed")
        finally:
            self._sleep_pending = False

    async def _maintenance_poll_loop(self) -> None:
        """M1 — periodic RestScheduler.is_due()/enter_sleep() poll.

        Satisfies the boot.py promise that interval-based rest fires
        without any interoception.fatigue consumer: the scheduler (whose clock is
        the subjective clock) decides due-ness; this loop polls often
        enough to notice and reuses the same non-interruptibility /
        pending-guard path as the fatigue trigger.
        """
        while not self._stopped.is_set():
            try:
                if (
                    self._scheduler.is_due()
                    and not self._sleep_lock.locked()
                    and not self._sleep_pending
                ):
                    log.info(
                        "sleep: rest scheduler reports sleep due — "
                        "triggering interval-based maintenance"
                    )
                    self._sleep_pending = True
                    self._sleep_task = asyncio.create_task(
                        self._interval_triggered_enter_sleep(),
                        name="sleep-interval-sleep",
                    )
                await asyncio.sleep(1.0)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("sleep maintenance poll iteration failed")
                await asyncio.sleep(1.0)
