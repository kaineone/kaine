# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

from kaine.bus.client import AsyncBus
from kaine.bus.schema import Event
from kaine.entity_clock import EntityClock
from kaine.cycle.protocols import (
    CycleHook,
    ModuleRegistryProtocol,
    SyneidesisProtocol,
)
from kaine.cycle.types import TickResult, WorkspaceSnapshot
from kaine.workspace.volition import Volition

log = logging.getLogger(__name__)


def _real_utc_now() -> datetime:
    """Default wall-clock seam: real UTC time."""
    return datetime.now(timezone.utc)


# Fixed epoch for deterministic-mode logical timestamps. A run's tick `k`
# stamps every event at BASE_EPOCH + k * target_tick_period, so timestamps are
# identical across two runs with the same seed and input (no real-clock leak).
# 1970-01-01T00:00:00Z is an arbitrary, documented fixed point — its only role
# is to be stable and run-independent.
BASE_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


class CycleHooks:
    def __init__(self) -> None:
        self._on_pause: list[CycleHook] = []
        self._on_resume: list[CycleHook] = []
        self._on_shutdown: list[CycleHook] = []

    def register(self, event: str, hook: CycleHook) -> None:
        bucket = self._bucket(event)
        bucket.append(hook)

    async def fire(self, event: str) -> None:
        for hook in self._bucket(event):
            try:
                await hook()
            except Exception:
                log.warning("cycle hook for %s raised; continuing", event, exc_info=True)

    def _bucket(self, event: str) -> list[CycleHook]:
        if event == "pause":
            return self._on_pause
        if event == "resume":
            return self._on_resume
        if event == "shutdown":
            return self._on_shutdown
        raise ValueError(f"unknown hook event {event!r}")


class CognitiveCycle:
    # Tick-rate bounds for soma.regulation reduce_rate advisory.
    _MIN_PROCESSING_RATE_HZ: float = 0.5   # floor: never slower than 0.5 Hz
    _MAX_PROCESSING_RATE_HZ: float = 20.0  # ceiling: never faster than 20 Hz
    # Factor by which reduce_rate lowers the current processing rate.
    _REDUCE_RATE_FACTOR: float = 0.8
    # Window (in ticks) over which the achieved-rate / slip stats are averaged
    # for the honest pacing report. Small so the report tracks recent reality
    # (a sustained overrun shows quickly) without per-tick noise.
    _PACING_WINDOW_TICKS: int = 32

    def __init__(
        self,
        bus: AsyncBus,
        syneidesis: SyneidesisProtocol,
        registry: ModuleRegistryProtocol,
        processing_rate_hz: float = 10.0,
        experiential_rate_hz: Optional[float] = None,
        read_count: int = 100,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Any] = asyncio.sleep,
        volition: Optional[Volition] = None,
        collect_phases: bool = False,
        wall_clock: Callable[[], datetime] = _real_utc_now,
        deterministic: bool = False,
        time_scale: float = 1.0,
        entity_clock: Optional[EntityClock] = None,
        affect_observer: Optional[
            Callable[[list[tuple[str, Event]]], None]
        ] = None,
        ablation_recorder: Optional[
            Callable[[WorkspaceSnapshot, WorkspaceSnapshot], None]
        ] = None,
    ) -> None:
        if processing_rate_hz <= 0:
            raise ValueError("processing_rate_hz must be positive")
        if experiential_rate_hz is not None and experiential_rate_hz <= 0:
            raise ValueError("experiential_rate_hz must be positive")
        self._bus = bus
        self._syneidesis = syneidesis
        self._registry = registry
        self._volition = volition
        self._processing_rate = float(processing_rate_hz)
        # Cached target tick period in SUBJECTIVE seconds (inverse of the
        # processing rate). The processing rate is a subjective-Hz rate, so this
        # period is invariant under time_scale — it is the felt tick period, and
        # the logical clock stamps in subjective time, so timestamps are
        # byte-identical across any scale (only the REAL pacing budget changes,
        # via EntityClock.period below). Recomputed on EVERY rate change through
        # the single _apply_processing_rate setter, so the pacing period and the
        # logical period can never diverge.
        self._target_tick_period = 1.0 / self._processing_rate
        self._experiential_rate = float(experiential_rate_hz or processing_rate_hz)
        self._read_count = int(read_count)
        self._clock = clock
        self._sleep = sleep
        # The shared subjective clock. The engine paces in subjective time: the
        # injectable `clock`/`_sleep` seam (the single global-pacing point) is
        # wired through the EntityClock so one `time_scale` dilates the whole
        # mind. When no clock is injected (the common case in tests) one is
        # constructed from the same injected real-clock/real-sleep + time_scale,
        # so the existing FakeClock seam keeps working unchanged. At
        # time_scale == 1.0 the real pacing budget equals the pre-change target,
        # so behavior is byte-identical.
        self._entity_clock = entity_clock or EntityClock(
            scale=float(time_scale),
            monotonic=clock,
            real_sleep=sleep,
        )
        # Event-timestamp seam. `_clock` (monotonic float) measures elapsed time
        # for slip/latency; `_wall_clock` (datetime) stamps published events.
        # The two are deliberately distinct and never conflated. In deterministic
        # mode `_now()` returns a logical timestamp derived from the tick index
        # instead of calling `_wall_clock`, so a run is reproducible.
        self._wall_clock = wall_clock
        self._deterministic = bool(deterministic)
        # When the oscillatory-layer is enabled, collect per-module phases each
        # tick and hand them to Syneidesis via context['phases']. Off by
        # default ⇒ zero per-tick cost and selection is unchanged.
        self._collect_phases = bool(collect_phases)
        # DI seam for the live four-factor salience (wire-salience-goal-thymos).
        # When the workspace's real Thymos/goal factors are active, the cycle
        # refreshes this callback each tick with the events it already collected
        # so the affect/drive snapshot the salience factors read stays current —
        # without the workspace importing kaine.modules. None (both factors on
        # the static negative control) ⇒ this is never called and the tick is
        # byte-identical to the pre-change behavior. Pure: reads collected events
        # only, no clock / RNG / bus I/O, so determinism is preserved.
        self._affect_observer = affect_observer
        # Live oscillatory-ablation recorder. When set, experiential ticks run the
        # dual-path selection and hand (primary, counterfactual) here read-only —
        # the coherence-off counterfactual scored over the SAME tick. None ⇒ no
        # dual-path pass and select() is called exactly as before, so the entity's
        # behaviour is unchanged whether or not the ablation is being recorded.
        self._ablation_recorder = ablation_recorder

        self._tick_index = 0
        self._cursors: dict[str, str] = {}
        self._error_counts: dict[str, int] = {}
        self._experience_acc = 0.0
        self._control_cursor: str = "0"
        self._paused = asyncio.Event()
        self._paused.set()
        self._stopped = False
        self.hooks = CycleHooks()

        # Honest pacing report (Phase 3 of biological-timing-and-dilation).
        # A rolling window of the most recent ticks' real wall duration + target
        # budget, so we can surface the ACHIEVED processing rate vs the TARGET
        # rate and the recent slip. This makes a `time_scale > 1` (or any rate)
        # overrun *visible* — the cycle attempts the faster target and, when the
        # hardware cannot hold it, the shortfall is reported (and Soma's
        # reduce_rate throttles), never silently capped or faked.
        self._recent_wall_ms: deque[float] = deque(maxlen=self._PACING_WINDOW_TICKS)
        self._recent_target_ms: deque[float] = deque(maxlen=self._PACING_WINDOW_TICKS)
        self._recent_slip_ms: deque[float] = deque(maxlen=self._PACING_WINDOW_TICKS)
        self._overrun_ticks: int = 0

        # soma.regulation consumer state.
        self._soma_out_cursor: str = "0"
        # Advisory / diagnostic latch only. The early-maintenance trigger is
        # event-driven: Hypnos observes the soma.regulation/request_maintenance
        # event on soma.out directly. Nothing reads this flag to drive behaviour.
        self.maintenance_requested: bool = False

    def set_ablation_recorder(
        self,
        recorder: Optional[Callable[[WorkspaceSnapshot, WorkspaceSnapshot], None]],
    ) -> None:
        """Attach or clear the live oscillatory-ablation recorder after
        construction. The composition root uses this once the sidecar's ablation
        observer exists (the registry is built after the cycle). ``None`` clears
        it, restoring plain single-path selection."""
        self._ablation_recorder = recorder

    @property
    def tick_index(self) -> int:
        return self._tick_index

    @property
    def deterministic(self) -> bool:
        return self._deterministic

    @property
    def _target_tick_period_s(self) -> float:
        """The SUBJECTIVE tick period in seconds (inverse of the processing rate).

        Used by the logical clock so each tick's events get a stable,
        run-independent timestamp in subjective time. This is the *felt* tick
        period and is invariant under ``time_scale`` (only the real pacing budget,
        ``EntityClock.period``, changes with scale) — so deterministic-mode
        timestamps are byte-identical across any scale, and identical at scale 1.0
        to the pre-change formula. Returns the cached value, recomputed on EVERY
        rate change through the single ``_apply_processing_rate`` setter (so the
        pacing period and the logical period can never diverge), without a
        per-call division.
        """
        return self._target_tick_period

    def _logical_now(self) -> datetime:
        """Deterministic logical timestamp for the current tick."""
        return BASE_EPOCH + timedelta(
            seconds=self._tick_index * self._target_tick_period_s
        )

    def _now(self) -> datetime:
        """Single source for event timestamps.

        Logical (reproducible) in deterministic mode; the injected/real wall
        clock otherwise. The two clocks are distinct from the monotonic
        ``_clock`` used for slip/latency durations.
        """
        if self._deterministic:
            return self._logical_now()
        return self._wall_clock()

    @property
    def processing_rate_hz(self) -> float:
        return self._processing_rate

    @property
    def experiential_rate_hz(self) -> float:
        return self._experiential_rate

    @property
    def time_scale(self) -> float:
        """The global time_scale (0 = frozen, 1.0 = real-time, >1 = dilated)."""
        return self._entity_clock.scale

    @property
    def entity_clock(self) -> EntityClock:
        """The shared subjective clock the cycle paces against."""
        return self._entity_clock

    @property
    def error_counts(self) -> dict[str, int]:
        return dict(self._error_counts)

    @property
    def pacing_stats(self) -> dict[str, Any]:
        """The honest pacing report: TARGET vs ACHIEVED processing rate + slip.

        The target rate is ``processing_rate_hz * time_scale`` (the REAL
        ticks-per-real-second the cycle is aiming for — a ``time_scale > 1``
        raises it above the subjective rate). The achieved rate is derived from
        the mean real per-tick wall time over the recent window: a tick that
        overruns its budget pushes the achieved rate below target, and that
        shortfall is what is surfaced here (and in Nexus) so a ``>1`` dilation is
        attempted and then *honestly* throttled, never silently capped.

        Returns ``None``-valued fields (achieved_rate_hz=None) until at least one
        tick has run. ``overrunning`` is True when recent ticks slipped past
        their budget on average — the signal an operator/Nexus reads to see the
        mind could not hold the requested speed.
        """
        scale = self._entity_clock.scale
        target_rate = self._processing_rate * scale if scale > 0 else 0.0
        n = len(self._recent_wall_ms)
        if n == 0:
            return {
                "target_rate_hz": target_rate,
                "achieved_rate_hz": None,
                "mean_tick_ms": None,
                "mean_target_ms": None,
                "mean_slip_ms": None,
                "max_slip_ms": None,
                "overrunning": False,
                "overrun_ticks": self._overrun_ticks,
                "window_ticks": 0,
                "time_scale": scale,
            }
        mean_wall = sum(self._recent_wall_ms) / n
        mean_target = sum(self._recent_target_ms) / n
        mean_slip = sum(self._recent_slip_ms) / n
        max_slip = max(self._recent_slip_ms)
        # Achieved rate: a tick really takes max(wall, target) real seconds (the
        # cycle sleeps the remaining budget when under, and overruns when over),
        # so the sustainable rate is 1 / mean(max(wall, target)).
        eff_period_ms = sum(
            max(w, t) for w, t in zip(self._recent_wall_ms, self._recent_target_ms)
        ) / n
        achieved_rate = 1000.0 / eff_period_ms if eff_period_ms > 0 else None
        # Overrunning when the average tick slipped past its budget — i.e. the
        # achieved rate is materially below the target (1% tolerance for noise).
        overrunning = (
            achieved_rate is not None
            and target_rate > 0
            and achieved_rate < target_rate * 0.99
        )
        return {
            "target_rate_hz": target_rate,
            "achieved_rate_hz": achieved_rate,
            "mean_tick_ms": mean_wall,
            "mean_target_ms": mean_target,
            "mean_slip_ms": mean_slip,
            "max_slip_ms": max_slip,
            "overrunning": overrunning,
            "overrun_ticks": self._overrun_ticks,
            "window_ticks": n,
            "time_scale": scale,
        }

    def _apply_processing_rate(self, hz: float) -> None:
        """THE single processing-rate setter.

        EVERY path that changes the processing rate — the public
        ``set_processing_rate``, the runtime ``cycle.set_rates`` control event,
        and the Soma ``reduce_rate`` advisory throttle — routes through here, so
        the cached subjective tick period (used by the logical clock and the
        pacing budget) is recomputed on EVERY change and can never diverge from
        the live rate. (The earlier bug: ``reduce_rate`` mutated
        ``_processing_rate`` directly without recomputing ``_target_tick_period``,
        so the logical clock kept stamping at the stale period.)
        """
        self._processing_rate = float(hz)
        self._target_tick_period = 1.0 / self._processing_rate

    def set_processing_rate(self, hz: float) -> None:
        if hz <= 0:
            raise ValueError("must be positive")
        self._apply_processing_rate(hz)

    def set_experiential_rate(self, hz: float) -> None:
        if hz <= 0:
            raise ValueError("must be positive")
        self._experiential_rate = float(hz)

    @property
    def is_paused(self) -> bool:
        """True when the experiential loop is suspended (frozen) — `run_forever`
        is blocked on `_paused.wait()`, so no ticks fire."""
        return not self._paused.is_set()

    async def pause(self) -> None:
        if not self._paused.is_set():
            return
        await self.hooks.fire("pause")
        self._paused.clear()

    async def resume(self) -> None:
        if self._paused.is_set():
            return
        self._paused.set()
        await self.hooks.fire("resume")

    async def shutdown(self) -> None:
        self._stopped = True
        self._paused.set()
        await self.hooks.fire("shutdown")

    async def tick(self) -> TickResult:
        # REAL target budget for this tick. The processing rate is subjective-Hz;
        # the real seconds the tick may take before it overruns is the
        # EntityClock period = 1 / (rate * time_scale). At time_scale == 1.0 this
        # is exactly 1000/rate ms (byte-identical to the pre-change target); at
        # 0.5 it is 2× (slower wall pacing); at 2.0 it is 0.5× (the faster target
        # the cycle attempts, with overrun honestly recorded as slip). At
        # time_scale == 0 the entity is frozen via the pause path and tick() is
        # not paced; period() would be undefined, so fall back to the subjective
        # period for the (unused) frozen-tick target rather than dividing by zero.
        if self._entity_clock.scale > 0:
            target_ms = self._entity_clock.period(self._processing_rate) * 1000.0
        else:
            target_ms = self._target_tick_period * 1000.0
        start = self._entity_clock.wall()

        events: list[tuple[str, Event]] = []
        modules_seen = 0
        error = False
        error_message: Optional[str] = None

        streams = list(self._registry.active_streams())
        if streams:
            tasks = [
                self._safe_read(stream, self._cursors.get(stream, "0"))
                for stream in streams
            ]
            results = await asyncio.gather(*tasks)
            for stream, entries in zip(streams, results):
                if not entries:
                    continue
                modules_seen += 1
                events.extend(entries)
                self._cursors[stream] = entries[-1][0]

        # Canonical within-tick event ordering. Sort the gathered events by a
        # total deterministic key (source, type, entry_id) before selection so
        # tie-breaks resolve identically regardless of async gather / stream
        # declaration order. Applied unconditionally (not gated to deterministic
        # mode): production and deterministic runs share one ordering rule, so
        # the oscillatory ablation's "only the layer differs" claim is airtight.
        # The selection score sort is stable, so this only pins the equal-score
        # tie-break input; for the already-ordered common case it is a no-op.
        # entry_id is the unique bus stream id (the first tuple element). A 0- or
        # 1-event tick is already ordered, so skip the sort call entirely.
        if len(events) > 1:
            events.sort(key=lambda item: (item[1].source, item[1].type, item[0]))

        # Refresh the affect/drive snapshot the live salience factors read, from
        # the canonically-ordered batch above (so which thymos.state "wins" a
        # multi-event tick is deterministic). No-op when no real factor is wired.
        if self._affect_observer is not None:
            try:
                self._affect_observer(events)
            except Exception:
                log.warning(
                    "affect observer raised on tick %d; continuing",
                    self._tick_index,
                    exc_info=True,
                )

        is_experiential = self._advance_experiential()

        snapshot: Optional[WorkspaceSnapshot] = None
        counterfactual: Optional[WorkspaceSnapshot] = None
        try:
            select_context: dict[str, Any] = {
                "tick_index": self._tick_index,
                "is_experiential": is_experiential,
            }
            if self._collect_phases:
                select_context["phases"] = self._collect_module_phases()
            # On an experiential tick, when the live ablation is recording, take
            # the dual-path selection: the primary is byte-identical to select()
            # (the entity is unaffected) and the counterfactual is the coherence-off
            # twin over the same events. Otherwise select() exactly as before.
            if self._ablation_recorder is not None and is_experiential:
                snapshot, counterfactual = await self._syneidesis.select_dual(
                    events,
                    context=select_context,
                )
            else:
                snapshot = await self._syneidesis.select(
                    events,
                    context=select_context,
                )
        except Exception as exc:
            error = True
            error_message = str(exc)
            log.exception("syneidesis raised on tick %d", self._tick_index)

        if snapshot is not None and is_experiential:
            broadcast_ok = False
            try:
                payload = self._snapshot_to_payload(snapshot, is_experiential)
                await self._bus.publish_workspace(payload)
                broadcast_ok = True
            except Exception:
                log.exception("workspace broadcast failed on tick %d", self._tick_index)
            # Executive action selection runs immediately after a successful
            # experiential broadcast. Volition is the ONLY source of effector
            # activation; it returns no intents when the snapshot is inhibited,
            # structurally enforcing executive inhibition (§37/§147).
            if broadcast_ok and self._volition is not None:
                await self._run_volition(snapshot)

        # Live oscillatory ablation: hand the paired (primary, counterfactual) to
        # the recorder read-only. Present only on experiential ticks with the layer
        # enabled; a recorder fault never disturbs the cycle.
        if (
            counterfactual is not None
            and snapshot is not None
            and self._ablation_recorder is not None
        ):
            try:
                self._ablation_recorder(snapshot, counterfactual)
            except Exception:
                log.warning(
                    "ablation recorder raised on tick %d; continuing",
                    self._tick_index,
                    exc_info=True,
                )

        end = self._entity_clock.wall()
        wall_ms = (end - start) * 1000.0
        slip_ms = max(0.0, wall_ms - target_ms)

        # Record the tick into the rolling pacing window for the honest report.
        # An overrun (slip > 0) means the cycle could not hold the target rate
        # this tick — counted so the shortfall is visible and never silent.
        self._recent_wall_ms.append(wall_ms)
        self._recent_target_ms.append(target_ms)
        self._recent_slip_ms.append(slip_ms)
        if slip_ms > 0.0:
            self._overrun_ticks += 1

        await self._publish_latency(
            wall_ms=wall_ms,
            target_ms=target_ms,
            slip_ms=slip_ms,
            is_experiential=is_experiential,
            error=error,
        )

        result = TickResult(
            tick_index=self._tick_index,
            wall_duration_ms=wall_ms,
            target_duration_ms=target_ms,
            slip_ms=slip_ms,
            is_experiential=is_experiential,
            modules_seen=modules_seen,
            events_collected=len(events),
            error=error,
            error_message=error_message,
        )
        self._tick_index += 1
        return result

    async def _run_volition(self, snapshot: WorkspaceSnapshot) -> None:
        """Invoke action selection and publish produced intents.

        The cycle never calls effectors directly: it publishes intents to
        ``volition.out`` and effectors realize them off the bus. An inhibited
        snapshot yields no intents (Volition's gate), so nothing is published.
        """
        from kaine.workspace.volition import INTENT_TYPES, VOLITION_SOURCE

        try:
            intents = self._volition.select(snapshot)
        except Exception:
            log.exception("volition raised on tick %d", self._tick_index)
            return
        for intent in intents:
            event_type = INTENT_TYPES.get(intent.kind)
            if event_type is None:
                log.warning("dropping intent with unknown kind %r", intent.kind)
                continue
            try:
                event = Event(
                    source=VOLITION_SOURCE,
                    type=event_type,
                    payload=intent.to_event_payload(),
                    salience=0.5,
                    timestamp=self._now(),
                )
                await self._bus.publish(event)
            except Exception:
                log.exception("failed to publish %s intent", intent.kind)

    async def apply_rate_control_event(self, payload: dict[str, Any]) -> bool:
        """Apply a `cycle.set_rates` payload. Returns True on success."""
        updated = False
        try:
            if "processing_rate_hz" in payload:
                new_proc = float(payload["processing_rate_hz"])
                if new_proc <= 0:
                    log.warning(
                        "rejecting cycle.set_rates: processing_rate_hz must be positive (got %s)",
                        new_proc,
                    )
                    return False
                self._apply_processing_rate(new_proc)
                updated = True
            if "experiential_rate_hz" in payload:
                new_exp = float(payload["experiential_rate_hz"])
                if new_exp <= 0:
                    log.warning(
                        "rejecting cycle.set_rates: experiential_rate_hz must be positive (got %s)",
                        new_exp,
                    )
                    return False
                self._experiential_rate = new_exp
                updated = True
        except (TypeError, ValueError) as exc:
            log.warning("rejecting cycle.set_rates: %s", exc)
            return False
        if updated:
            try:
                await self._publish_rates_event()
            except Exception:
                log.exception("failed to publish cycle.rates event")
        return updated

    async def _publish_rates_event(self) -> None:
        from kaine.bus.schema import Event

        event = Event(
            source="cycle",
            type="cycle.rates",
            payload={
                "processing_rate_hz": self._processing_rate,
                "experiential_rate_hz": self._experiential_rate,
            },
            salience=0.1,
            timestamp=self._now(),
        )
        await self._bus.publish(event)

    async def consume_control_events(self, control_stream: str = "cycle.control") -> None:
        """Drain pending events from `control_stream`. Idempotent — safe to
        call repeatedly. Phase 7's runtime API surfaces; the
        first-boot script will spawn a background task that calls this
        once per tick to keep the cycle responsive to rate changes.
        """
        cursor = self._control_cursor
        try:
            entries = await self._bus.read(
                control_stream, last_id=cursor, count=32, block_ms=0
            )
        except Exception:
            return
        if not entries:
            return
        for entry_id, event in entries:
            self._control_cursor = entry_id
            if event.type == "cycle.set_rates":
                await self.apply_rate_control_event(event.payload)

    async def consume_soma_regulation(self, soma_stream: str = "soma.out") -> None:
        """Drain pending ``soma.regulation`` events from the soma stream.

        Actions are advisory only: the cycle acts on them within safe
        bounds and logs each one.  Unknown ``action`` values are ignored
        gracefully — Soma may be extended in future without breaking the
        engine.

        Actuation map
        -------------
        ``reduce_rate``
            Lower the processing rate by ``_REDUCE_RATE_FACTOR``, clamped
            to ``[_MIN_PROCESSING_RATE_HZ, _MAX_PROCESSING_RATE_HZ]``.
        ``shed_module``
            Request that the module registry suspend the lowest-priority
            module (via ``request_shed_low_priority`` if present — the
            registry may ignore it if no shedding target exists).
        ``request_maintenance``
            Latch ``self.maintenance_requested = True`` as an advisory /
            diagnostic signal.  This flag is NOT what schedules maintenance:
            the actual early-maintenance trigger is event-driven — Hypnos
            observes the ``soma.regulation`` / ``request_maintenance`` event
            directly on ``soma.out`` and fires an earlier offline cycle.  The
            flag is retained purely as a latched advisory for diagnostics and
            introspection; nothing reads it to drive behaviour.
        """
        cursor = self._soma_out_cursor
        try:
            entries = await self._bus.read(
                soma_stream, last_id=cursor, count=32, block_ms=0
            )
        except Exception:
            return
        if not entries:
            return
        for entry_id, event in entries:
            self._soma_out_cursor = entry_id
            if event.type != "soma.regulation":
                continue
            action = event.payload.get("action")
            reason = event.payload.get("reason", "")
            severity = event.payload.get("severity", 0)
            if action == "reduce_rate":
                new_rate = max(
                    self._MIN_PROCESSING_RATE_HZ,
                    min(
                        self._MAX_PROCESSING_RATE_HZ,
                        self._processing_rate * self._REDUCE_RATE_FACTOR,
                    ),
                )
                log.info(
                    "soma.regulation advisory reduce_rate "
                    "(severity=%s, reason=%r): processing_rate %.3f → %.3f Hz",
                    severity,
                    reason,
                    self._processing_rate,
                    new_rate,
                )
                # Route through the single setter so the cached subjective tick
                # period is recomputed too (the logical clock and the pacing
                # budget stay consistent with the throttled rate).
                self._apply_processing_rate(new_rate)
            elif action == "shed_module":
                log.info(
                    "soma.regulation advisory shed_module "
                    "(severity=%s, reason=%r): requesting low-priority suspension",
                    severity,
                    reason,
                )
                if hasattr(self._registry, "request_shed_low_priority"):
                    try:
                        self._registry.request_shed_low_priority()
                    except Exception:
                        log.warning(
                            "registry.request_shed_low_priority raised", exc_info=True
                        )
            elif action == "request_maintenance":
                log.info(
                    "soma.regulation advisory request_maintenance "
                    "(severity=%s, reason=%r): flagging for Hypnos",
                    severity,
                    reason,
                )
                self.maintenance_requested = True
            elif action is None:
                log.warning(
                    "soma.regulation event missing 'action' field; ignoring"
                )
            else:
                log.debug(
                    "soma.regulation: unknown action %r; ignoring gracefully",
                    action,
                )

    async def run_forever(self, max_ticks: Optional[int] = None) -> None:
        while not self._stopped:
            await self._paused.wait()
            if self._stopped:
                break
            await self.consume_control_events()
            await self.consume_soma_regulation()
            result = await self.tick()
            if max_ticks is not None and self._tick_index >= max_ticks:
                break
            # `target_duration_ms` is the REAL per-tick budget (the EntityClock
            # period at the current time_scale), so `remaining_s` is the real
            # time to wait before the next subjective tick. At time_scale 1.0
            # this is identical to the pre-change pacing; at 0.5 it waits ~2× real
            # per subjective tick; at >1 the (smaller) budget targets a faster
            # rate and an overrun is honestly recorded as slip. Slept via the
            # same real_sleep the EntityClock wraps.
            remaining_s = max(
                0.0,
                (result.target_duration_ms - result.wall_duration_ms) / 1000.0,
            )
            if remaining_s > 0:
                await self._sleep(remaining_s)

    def _collect_module_phases(self) -> dict[str, float]:
        """Per-module oscillator phase, keyed by module name.

        Only invoked when the oscillatory-layer is enabled. Modules without an
        oscillator report the neutral phase. Degrades to an empty dict if the
        registry does not expose module instances.
        """
        all_modules = getattr(self._registry, "all_modules", None)
        if all_modules is None:
            return {}
        phases: dict[str, float] = {}
        try:
            for module in all_modules():
                try:
                    phases[module.name] = float(module.phase())
                except Exception:
                    log.debug("phase() failed for a module", exc_info=True)
        except Exception:
            log.debug("phase collection failed", exc_info=True)
            return {}
        return phases

    async def _safe_read(self, stream: str, last_id: str) -> list[tuple[str, Event]]:
        try:
            return await self._bus.read(
                stream, last_id=last_id, count=self._read_count, block_ms=0
            )
        except Exception as exc:
            self._error_counts[stream] = self._error_counts.get(stream, 0) + 1
            log.warning("read failed for %s: %s", stream, exc)
            return []

    def _advance_experiential(self) -> bool:
        ratio = self._experiential_rate / self._processing_rate
        self._experience_acc += ratio
        if self._experience_acc >= 1.0:
            self._experience_acc -= 1.0
            return True
        return False

    def _snapshot_to_payload(
        self, snapshot: WorkspaceSnapshot, is_experiential: bool
    ) -> dict[str, Any]:
        return {
            "tick_index": snapshot.tick_index,
            "inhibited": snapshot.inhibited,
            "is_experiential": is_experiential,
            "salience_scores": dict(snapshot.salience_scores),
            "metadata": dict(snapshot.metadata),
            "selected": [
                {
                    "entry_id": entry_id,
                    "source": ev.source,
                    "type": ev.type,
                    "salience": ev.salience,
                    "payload": ev.payload,
                    "timestamp": ev.timestamp.isoformat(),
                    "causal_parent": ev.causal_parent,
                }
                for entry_id, ev in snapshot.selected_events
            ],
        }

    async def _publish_latency(
        self,
        wall_ms: float,
        target_ms: float,
        slip_ms: float,
        is_experiential: bool,
        error: bool,
    ) -> None:
        try:
            event = Event(
                source="cycle",
                type="cycle.tick",
                payload={
                    "tick_index": self._tick_index,
                    "wall_duration_ms": wall_ms,
                    "target_duration_ms": target_ms,
                    "slip_ms": slip_ms,
                    "is_experiential": is_experiential,
                    "error": error,
                },
                salience=0.5 if error else 0.05,
                timestamp=self._now(),
            )
            await self._bus.publish(event)
        except Exception:
            log.exception("failed to publish cycle latency event")
