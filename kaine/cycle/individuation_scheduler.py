# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Scheduler that decides when the individuation core captures a reference and runs a look.

The scheduler owns lived-time accounting, organ yielding, run deadlines and the
long-inconclusive alert. It is the only writer of the individuation ledger in a
running cycle, besides the core it drives from the same task.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from kaine.cycle.individuation_probe import ProbeFailure
from kaine.lifecycle.individuation_store import (
    IndividuationPaths,
    IndividuationStoreError,
    LedgerUnreadable,
    ReferenceExists,
    ReferenceUnreadable,
    load_ledger,
    load_reference,
    save_ledger,
)
from kaine.lifecycle.lived_time import LivedTimeAccumulator, TickAccumulator

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class SchedulerSettings:
    """Timing and threshold parameters for the individuation scheduler."""

    sleep_settle_s: float = 120.0
    daily_s: float = 86_400.0
    min_look_interval_s: float = 21_600.0
    min_lived_time_s: float = 1_800.0
    min_observations: int = 200
    run_deadline_s: float = 2_700.0
    capture_deadline_s: float = 5_400.0
    blocked_retry_s: float = 300.0
    inconclusive_retry_s: float = 3_600.0
    lived_persist_s: float = 300.0
    inconclusive_alert_s: float = 1_209_600.0
    capture_retry_initial_s: float = 60.0
    capture_retry_max_s: float = 3_600.0
    idle_poll_s: float = 1.0

    def __post_init__(self) -> None:
        float_fields = (
            "sleep_settle_s",
            "daily_s",
            "min_look_interval_s",
            "min_lived_time_s",
            "run_deadline_s",
            "capture_deadline_s",
            "blocked_retry_s",
            "inconclusive_retry_s",
            "lived_persist_s",
            "inconclusive_alert_s",
            "capture_retry_initial_s",
            "capture_retry_max_s",
            "idle_poll_s",
        )
        for name in float_fields:
            value = getattr(self, name)
            if (
                not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(f"{name} must be finite and > 0")
        if self.min_observations < 0:
            raise ValueError("min_observations must be non-negative")
        if self.capture_retry_initial_s > self.capture_retry_max_s:
            raise ValueError(
                "capture_retry_initial_s must not exceed capture_retry_max_s"
            )


@dataclass(frozen=True)
class IndividuationState:
    """In-memory view the divergence monitor reads later."""

    reference_present: bool = False
    reference_kind: str | None = None
    individuated: bool = False
    looks_completed: int = 0
    alpha_spent: float = 0.0
    lived_seconds: float = 0.0
    lived_ticks: int = 0
    last_outcome: str | None = None
    last_reason: str | None = None
    last_attempt_at: str | None = None
    inconclusive_since: str | None = None
    inconclusive_alerted: bool = False
    conditions_alerted_reference: str | None = None
    last_inconclusive_reason: str | None = None
    ledger_readable: bool = True


class IndividuationScheduler:
    """Decide when the individuation core runs."""

    def __init__(
        self,
        *,
        paths: IndividuationPaths,
        settings: SchedulerSettings,
        clock_now: Callable[[], float | None] | None,
        paused_seconds: Callable[[], float] | None,
        tick_index: Callable[[], int | None],
        organ_unloaded: Callable[[], bool],
        paused: Callable[[], bool],
        embedder_ready: Callable[[], bool],
        lingua_idle: Callable[[], bool],
        alert: Callable[[dict], Awaitable[None]],
        adapter_verifiable: Callable[[], bool] | None = None,
        on_capture_kind_change: Callable[[str | None], None] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._paths = paths
        self._settings = settings
        self._clock_now = clock_now
        self._paused_seconds = paused_seconds
        self._tick_index = tick_index
        self._organ_unloaded = organ_unloaded
        self._paused = paused
        self._embedder_ready = embedder_ready
        self._lingua_idle = lingua_idle
        self._alert = alert
        self._adapter_verifiable = adapter_verifiable
        self._monotonic = monotonic
        self._now_dt = now
        self._sleep = sleep

        self._lived = LivedTimeAccumulator(clock_now, paused_seconds)
        self._ticks = TickAccumulator()

        self._core: Any | None = None
        self._asleep = False
        self._look_due_at: float | None = None
        self._next_daily_at: float | None = None
        self._capture_kind: str | None = None
        self._capture_regenerate = False
        self._capture_at: float | None = None
        self._capture_backoff = settings.capture_retry_initial_s
        self._run_deadline_at: float | None = None
        self._pending_s = 0.0
        self._pending_ticks = 0
        self._next_flush_at: float | None = None
        self._started = False
        self._stopped = False
        self._state = IndividuationState()
        self._reference_kind: str | None = None
        self._on_capture_kind_change = on_capture_kind_change
        self._last_skip: str | None = None
        self._alerted_since: str | None = None

    def bind(self, core: Any) -> None:
        """Store the core this scheduler drives."""
        self._core = core

    def _safe(self, fn: Callable[[], Any], default: Any) -> Any:
        try:
            return fn()
        except Exception:
            log.debug(
                "predicate failed, using default %r", default, exc_info=True
            )
            return default

    def abort_reason(self) -> str | None:
        """Return the current abort reason, if any."""
        if self._safe(self._organ_unloaded, True):
            return "organ_unloaded"
        if self._asleep:
            return "asleep"
        if self._safe(self._paused, True):
            return "paused"
        if (
            self._run_deadline_at is not None
            and self._monotonic() >= self._run_deadline_at
        ):
            return "deadline_exceeded"
        return None

    def gate(
        self, sampler: Callable[[str, int], Awaitable[Any]]
    ) -> Callable[[str, int], Awaitable[Any]]:
        """Return a gated sampler that waits for the being's own speech first."""

        async def gated(prompt: str, seed: int) -> Any:
            while True:
                reason = self.abort_reason()
                if reason is not None:
                    return ProbeFailure(reason)
                if self._safe(self._lingua_idle, False):
                    break
                await self._sleep(self._settings.idle_poll_s)
            return await sampler(prompt, seed)

        return gated

    def _notify_capture_kind_change(self, kind: str | None) -> None:
        if self._on_capture_kind_change is None:
            return
        try:
            self._on_capture_kind_change(kind)
        except Exception:
            log.debug(
                "on_capture_kind_change callback failed", exc_info=True
            )

    def notify_sleep_started(self) -> None:
        self._asleep = True

    def notify_sleep_completed(self) -> None:
        self._asleep = False
        if self._capture_kind == "birth":
            self._capture_kind = "capture"
            log.info(
                "individuation birth capture downgraded to capture after sleep"
            )
            self._notify_capture_kind_change("capture")
        self._schedule_look(
            self._monotonic() + self._settings.sleep_settle_s
        )

    def request_capture(self, kind: str, *, regenerate: bool = False) -> None:
        self._capture_kind = kind
        self._capture_regenerate = regenerate
        self._capture_at = self._monotonic()
        self._capture_backoff = self._settings.capture_retry_initial_s

    @property
    def state(self) -> IndividuationState:
        return self._state

    def stop(self) -> None:
        self._stopped = True

    async def run(self) -> None:
        try:
            while not self._stopped:
                try:
                    await self.tick()
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("individuation scheduler tick failed")
                await self._sleep(self._settings.idle_poll_s)
        finally:
            self._flush_lived()

    async def tick(self) -> None:
        m = self._monotonic()

        if not self._started:
            self._started = True
            self._schedule_look(m + self._settings.sleep_settle_s)
            self._next_daily_at = m + self._settings.daily_s
            self._next_flush_at = m + self._settings.lived_persist_s
            self._refresh_state()

        self._pending_s += self._lived.step()
        idx = self._safe(self._tick_index, None)
        if isinstance(idx, int):
            self._pending_ticks += self._ticks.step(idx)

        if self._next_flush_at is not None and m >= self._next_flush_at:
            self._flush_lived()
            self._next_flush_at = m + self._settings.lived_persist_s

        if self._next_daily_at is not None and m >= self._next_daily_at:
            self._schedule_look(m)
            self._next_daily_at = m + self._settings.daily_s

        if self._core is None:
            return

        if (
            self._capture_kind is not None
            and self._capture_at is not None
            and m >= self._capture_at
        ):
            await self._attempt_capture(m)
            return

        if self._look_due_at is not None and m >= self._look_due_at:
            await self._attempt_look(m)

    def _schedule_look(self, at: float) -> None:
        self._look_due_at = (
            at if self._look_due_at is None else min(self._look_due_at, at)
        )

    def _flush_lived(self) -> None:
        try:
            ledger = load_ledger(self._paths)
        except LedgerUnreadable:
            log.warning(
                "individuation ledger unreadable; keeping pending lived time"
            )
            return

        if ledger is None:
            self._pending_s = 0.0
            self._pending_ticks = 0
            return

        if self._pending_s == 0.0 and self._pending_ticks == 0:
            return

        try:
            save_ledger(
                self._paths,
                dataclasses.replace(
                    ledger,
                    lived_seconds=ledger.lived_seconds + self._pending_s,
                    lived_ticks=ledger.lived_ticks + self._pending_ticks,
                ),
            )
        except IndividuationStoreError as exc:
            log.warning("failed to persist lived time: %s", exc)
            return

        self._pending_s = 0.0
        self._pending_ticks = 0
        self._refresh_state()

    def _reanchor_lived(self) -> None:
        self._lived.step()
        idx = self._safe(self._tick_index, None)
        if isinstance(idx, int):
            self._ticks.step(idx)
        self._pending_s = 0.0
        self._pending_ticks = 0

    def _maybe_reanchor_after_failed_capture(self) -> None:
        try:
            ledger = load_ledger(self._paths)
        except Exception:
            return
        if ledger is None:
            self._reanchor_lived()

    def _blocked_reason(self, *, for_look: bool = True) -> str | None:
        if self._safe(self._organ_unloaded, True):
            return "organ_unloaded"
        if self._asleep:
            return "asleep"
        if self._safe(self._paused, True):
            return "paused"
        if self._adapter_verifiable is not None and not self._safe(
            self._adapter_verifiable, False
        ):
            return "adapter_unverifiable"
        if for_look and not self._safe(self._embedder_ready, False):
            return "embedder_not_ready"
        return None

    async def _attempt_capture(self, m: float) -> None:
        reason = self._blocked_reason(for_look=False)
        if reason is not None:
            self._capture_at = m + self._settings.blocked_retry_s
            self._note_skip(reason)
            return

        self._flush_lived()
        self._run_deadline_at = m + self._settings.capture_deadline_s
        try:
            if self._capture_regenerate:
                doc, reason = await self._core.capture_reference(
                    self._capture_kind, regenerate=True
                )
            else:
                doc, reason = await self._core.capture_reference(self._capture_kind)
        except ReferenceExists:
            log.info("individuation capture skipped: reference already exists")
            self._capture_kind = None
            self._capture_regenerate = False
            self._capture_at = None
            self._notify_capture_kind_change(None)
            self._refresh_state()
            return
        except Exception:
            log.exception("individuation capture failed")
            end = self._monotonic()
            self._capture_at = end + self._capture_backoff
            self._capture_backoff = min(
                2 * self._capture_backoff,
                self._settings.capture_retry_max_s,
            )
            self._maybe_reanchor_after_failed_capture()
            return
        else:
            if reason is not None:
                log.info("individuation capture failed: %s", reason)
                end = self._monotonic()
                self._capture_at = end + self._capture_backoff
                self._capture_backoff = min(
                    2 * self._capture_backoff,
                    self._settings.capture_retry_max_s,
                )
                self._maybe_reanchor_after_failed_capture()
                return

            self._reference_kind = doc.reference_kind
            self._capture_kind = None
            self._capture_regenerate = False
            self._capture_at = None
            self._capture_backoff = self._settings.capture_retry_initial_s
            self._notify_capture_kind_change(None)
            self._reanchor_lived()
            self._refresh_state()
        finally:
            self._run_deadline_at = None

    async def _attempt_look(self, m: float) -> None:
        if not self._paths.reference.exists():
            self._look_due_at = None
            self._note_skip("no_reference")
            return

        ledger = None
        try:
            ledger = load_ledger(self._paths)
        except LedgerUnreadable:
            ledger = None

        if ledger is not None:
            lived_s = ledger.lived_seconds + self._pending_s
            lived_t = ledger.lived_ticks + self._pending_ticks
            if (
                lived_s < self._settings.min_lived_time_s
                or lived_t < self._settings.min_observations
            ):
                self._look_due_at = None
                self._note_skip("warming_up")
                return

            if ledger.last_look_at is not None:
                try:
                    last = datetime.fromisoformat(ledger.last_look_at)
                    elapsed = (self._now_dt() - last).total_seconds()
                except Exception:
                    elapsed = self._settings.min_look_interval_s
                if elapsed < self._settings.min_look_interval_s:
                    self._look_due_at = m + (
                        self._settings.min_look_interval_s - elapsed
                    )
                    self._note_skip("interval")
                    return

        reason = self._blocked_reason()
        if reason is not None:
            self._look_due_at = m + self._settings.blocked_retry_s
            self._note_skip(reason)
            if self._core_look_due():
                await self._mark_inconclusive()
            return

        self._flush_lived()

        ledger_lived_s = 0.0
        ledger_lived_t = 0
        before = None
        try:
            re_read = load_ledger(self._paths)
        except LedgerUnreadable:
            re_read = None
        if re_read is not None:
            ledger_lived_s = re_read.lived_seconds
            ledger_lived_t = re_read.lived_ticks
            before = re_read.looks_completed

        self._run_deadline_at = m + self._settings.run_deadline_s
        try:
            outcome = await self._core.look(
                warmed_up=True,
                lived_seconds=ledger_lived_s,
                lived_ticks=ledger_lived_t,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.exception("individuation look failed")
            end = self._monotonic()
            try:
                after = load_ledger(self._paths)
            except LedgerUnreadable:
                after = None
            if (
                after is not None
                and before is not None
                and after.looks_completed > before
            ):
                self._look_due_at = None
                self._refresh_state(
                    last_outcome="error",
                    last_reason=type(exc).__name__,
                )
            else:
                self._look_due_at = end + self._settings.inconclusive_retry_s
                self._state = dataclasses.replace(
                    self._state,
                    last_outcome="error",
                    last_reason=type(exc).__name__,
                )
                await self._mark_inconclusive()
            return
        else:
            if outcome.outcome == "scored":
                self._look_due_at = None
            elif outcome.outcome == "inconclusive":
                end = self._monotonic()
                self._look_due_at = end + self._settings.inconclusive_retry_s
                await self._mark_inconclusive(reason=outcome.reason)
            elif outcome.outcome == "skipped":
                self._look_due_at = None

            self._refresh_state(
                last_outcome=outcome.outcome,
                last_reason=outcome.reason,
                last_attempt_at=self._now_dt().isoformat(),
            )
        finally:
            self._run_deadline_at = None

    def _core_look_due(self) -> bool:
        if self._core is None:
            return True
        try:
            return self._core.look_due()
        except Exception:
            return True

    async def _mark_inconclusive(self, reason: str | None = None) -> None:
        try:
            ledger = load_ledger(self._paths)
        except LedgerUnreadable:
            return
        if ledger is None:
            return

        updates: dict[str, Any] = {}

        if reason is not None:
            updates["last_inconclusive_reason"] = reason

        if ledger.inconclusive_since is None:
            updates["inconclusive_since"] = self._now_dt().isoformat()

        current_since = updates.get("inconclusive_since", ledger.inconclusive_since)

        if (
            reason == "conditions_changed"
            and ledger.conditions_alerted_reference != ledger.reference_id
        ):
            try:
                await self._alert(
                    {
                        "kind": "individuation_conditions_changed",
                        "reference_id": ledger.reference_id,
                    }
                )
            except Exception:
                log.warning("individuation conditions-changed alert failed")
            else:
                updates["conditions_alerted_reference"] = ledger.reference_id

        try:
            since = datetime.fromisoformat(current_since)
            elapsed = (self._now_dt() - since).total_seconds()
        except Exception:
            # An unparseable start must not silence the operator alert.
            elapsed = self._settings.inconclusive_alert_s

        if (
            elapsed >= self._settings.inconclusive_alert_s
            and not ledger.inconclusive_alerted
            and current_since != self._alerted_since
        ):
            last_reason = updates.get(
                "last_inconclusive_reason", ledger.last_inconclusive_reason
            )
            try:
                await self._alert(
                    {
                        "kind": "individuation_inconclusive",
                        "inconclusive_since": current_since,
                        "days": round(elapsed / 86400.0, 1),
                        "last_reason": last_reason,
                    }
                )
            except Exception:
                log.warning("individuation inconclusive alert failed")
            else:
                self._alerted_since = current_since
                updates["inconclusive_alerted"] = True

        if updates:
            try:
                save_ledger(self._paths, dataclasses.replace(ledger, **updates))
            except IndividuationStoreError as exc:
                log.warning("failed to save inconclusive ledger updates: %s", exc)

        self._refresh_state()

    def _note_skip(self, reason: str) -> None:
        if reason != self._last_skip:
            log.info("individuation look skipped: %s", reason)
        self._last_skip = reason
        self._refresh_state(last_outcome="skipped", last_reason=reason)

    def _refresh_state(self, **overrides: Any) -> None:
        ledger = None
        ledger_readable = True
        try:
            ledger = load_ledger(self._paths)
        except LedgerUnreadable:
            ledger_readable = False

        reference_present = self._paths.reference.exists()

        if self._reference_kind is None and reference_present:
            try:
                ref = load_reference(self._paths)
            except ReferenceUnreadable:
                ref = None
            if ref is not None:
                self._reference_kind = ref.reference_kind

        state = self._state

        if not ledger_readable:
            self._state = dataclasses.replace(
                state, ledger_readable=False, **overrides
            )
            return

        state = dataclasses.replace(
            state,
            reference_present=reference_present,
            reference_kind=self._reference_kind,
            ledger_readable=True,
        )

        if ledger is not None:
            state = dataclasses.replace(
                state,
                individuated=ledger.individuated,
                looks_completed=ledger.looks_completed,
                alpha_spent=ledger.alpha_spent,
                lived_seconds=ledger.lived_seconds + self._pending_s,
                lived_ticks=ledger.lived_ticks + self._pending_ticks,
                inconclusive_since=ledger.inconclusive_since,
                inconclusive_alerted=ledger.inconclusive_alerted,
            )

        self._state = dataclasses.replace(state, **overrides)
