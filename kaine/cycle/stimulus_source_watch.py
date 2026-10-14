# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Stimulus-source-loss watcher and pre-spawn hold for entities in their developmental phase.

An entity in its developmental phase depends on a developmental stimulus.  Before spawn,
:func:`hold_until_stimulus_source_ready` blocks module initialisation until the stimulus source
is ready or shutdown is requested.  While running, :class:`StimulusSourceLossWatcher`
monitors stimulus source liveness and freezes the cycle (under the ``development``
freeze source) when the stimulus is lost for too long.  Because perception
is left on during a developmental-phase-only freeze, a local stimulus source can prove its return
through real sensory deliveries.

Before it judges loss, :class:`StimulusSourceLossWatcher` arms itself on the first
live observation of the stimulus source, so a slow-starting stimulus source is not condemned
while it is still coming online.  If the stimulus source never becomes live within
``arm_timeout_seconds`` the watcher treats it as lost immediately.
"""

from __future__ import annotations

import asyncio
import logging
import math
from pathlib import Path
from time import monotonic
from typing import Any, Awaitable, Callable

from kaine.cycle.control_state import pop_freeze, push_freeze, read_control
from kaine.lifecycle.stimulus_source_liveness import (
    DEFAULT_PRESENCE_WINDOW_S,
    StimulusSourceLiveness,
    check_stimulus_source_live,
    check_stimulus_source_ready,
)

log = logging.getLogger(__name__)

DEVELOPMENT_FREEZE_SOURCE = "development"
STAGE_DEVELOPMENT_STIMULUS_SOURCE_LOST = "stage.development.stimulus_source_lost"
STAGE_DEVELOPMENT_STIMULUS_SOURCE_RETURNED = "stage.development.stimulus_source_returned"


def _validate_positive(name: str, value: float) -> None:
    try:
        value = float(value)
    except Exception:
        raise ValueError(f"{name} must be a finite positive number, got {value!r}")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number, got {value}")


async def hold_until_stimulus_source_ready(
    config: dict[str, Any],
    bus: Any,
    stop_event: asyncio.Event,
    *,
    publish: Callable[[str, dict[str, Any], float], Awaitable[None]],
    ready_check: Callable[..., Awaitable[StimulusSourceLiveness]] = check_stimulus_source_ready,
    retry_seconds: float = 5.0,
) -> bool:
    """Block until the stimulus source is ready for spawn, or until shutdown is requested.

    While held, publish ``stage.development.no_stimulus`` after each failed
    check so the developmental state is visible on ``lifecycle.out``.
    """
    _validate_positive("retry_seconds", retry_seconds)
    while not stop_event.is_set():
        try:
            result = await ready_check(config, bus)
        except Exception as exc:
            result = StimulusSourceLiveness(
                live=False,
                provider="unknown",
                reason=f"{type(exc).__name__}: {exc}",
            )
        if result.live:
            log.info("stimulus source is ready for spawn (%s)", result.provider)
            return True
        log.warning("stimulus source not ready: %s", result.reason)
        try:
            await publish(
                "stage.development.no_stimulus",
                {
                    "stage": "development",
                    "reason": "stimulus_source_not_ready",
                    "detail": result.reason,
                    "provider": result.provider,
                },
                0.7,
            )
        except Exception:
            log.warning("publish stage.development.no_stimulus failed", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=retry_seconds)
            return False
        except asyncio.TimeoutError:
            continue
    return False


class StimulusSourceLossWatcher:
    """Cycle-layer watcher that freezes a developing entity when the stimulus source is lost.

    The watcher arms itself on the first live observation of the stimulus source and
    does not judge transient quiet periods while the stimulus source is still starting.
    If no live observation occurs within ``arm_timeout_seconds``, the stimulus source is
    declared lost immediately.  Once armed, hysteresis prevents a single
    missed event from freezing the entity, and a developmental-phase-only freeze leaves
    perception on so a local stimulus source can prove its return.  Arming survives a
    stimulus source return.
    """

    def __init__(
        self,
        config: dict[str, Any],
        bus: Any,
        *,
        publish: Callable[[str, dict[str, Any], float], Awaitable[None]],
        is_developing: Callable[[], bool],
        notify: Callable[[str], Awaitable[Any]] | None = None,
        live_check: Callable[..., Awaitable[StimulusSourceLiveness]] = check_stimulus_source_live,
        control_path: Path | None = None,
        check_seconds: float = 1.0,
        loss_after_seconds: float = 5.0,
        window_s: float = DEFAULT_PRESENCE_WINDOW_S,
        arm_timeout_seconds: float = 120.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        _validate_positive("check_seconds", check_seconds)
        _validate_positive("loss_after_seconds", loss_after_seconds)
        _validate_positive("window_s", window_s)
        _validate_positive("arm_timeout_seconds", arm_timeout_seconds)
        self._config = config
        self._bus = bus
        self._publish = publish
        self._is_developing = is_developing
        self._notify = notify
        self._live_check = live_check
        self._control_path = control_path
        self._check_seconds = check_seconds
        self._loss_after_seconds = loss_after_seconds
        self._window_s = window_s
        self._arm_timeout_seconds = arm_timeout_seconds
        self._clock = clock
        self._started_at: float = clock()
        self._armed: bool = False
        self._grace_until: float = clock() + window_s + 2 * check_seconds
        self._not_live_since: float | None = None
        self._live_streak: int = 0
        self._lost: bool = False

    @property
    def stimulus_source_lost(self) -> bool:
        return self._lost

    async def _declare_loss(self, result: StimulusSourceLiveness) -> None:
        """Freeze the developing entity and publish/notify that the stimulus source is lost."""
        try:
            push_freeze(
                reason="stimulus source lost",
                path=self._control_path,
                source=DEVELOPMENT_FREEZE_SOURCE,
            )
        except Exception:
            log.warning("push_freeze on stimulus source loss failed", exc_info=True)
        self._lost = True
        self._live_streak = 0
        log.critical(
            "stimulus source lost for %s seconds; freezing developing entity",
            self._loss_after_seconds,
        )
        try:
            await self._publish(
                STAGE_DEVELOPMENT_STIMULUS_SOURCE_LOST,
                {
                    "stage": "development",
                    "reason": result.reason,
                    "provider": result.provider,
                },
                0.9,
            )
        except Exception:
            log.warning("publish stage.development.stimulus_source_lost failed", exc_info=True)
        if self._notify is not None:
            try:
                await self._notify("stimulus_source_lost")
            except Exception:
                log.warning("notify stimulus_source_lost failed", exc_info=True)

    async def step(self) -> None:
        """Perform a single stimulus-source-liveness check and update freeze state."""
        if not self._is_developing():
            if self._lost:
                try:
                    pop_freeze(self._control_path, source=DEVELOPMENT_FREEZE_SOURCE)
                except Exception:
                    log.warning("pop_freeze on development end failed", exc_info=True)
                self._lost = False
            return

        now = self._clock()

        if not self._armed:
            try:
                result = await self._live_check(
                    self._config, self._bus, window_s=self._window_s
                )
            except Exception as exc:
                result = StimulusSourceLiveness(
                    live=False,
                    provider="unknown",
                    reason=f"{type(exc).__name__}: {exc}",
                )

            if result.live:
                self._armed = True
                self._grace_until = now + self._window_s + 2 * self._check_seconds
                log.info("stimulus source live; loss watch armed")
                return

            if now - self._started_at < self._arm_timeout_seconds:
                return

            self._armed = True
            await self._declare_loss(result)
            return

        if now < self._grace_until:
            return

        try:
            result = await self._live_check(
                self._config, self._bus, window_s=self._window_s
            )
        except Exception as exc:
            result = StimulusSourceLiveness(
                live=False,
                provider="unknown",
                reason=f"{type(exc).__name__}: {exc}",
            )

        if not self._lost:
            if result.live:
                self._not_live_since = None
            else:
                if self._not_live_since is None:
                    self._not_live_since = now
                if now - self._not_live_since >= self._loss_after_seconds:
                    await self._declare_loss(result)

        if self._lost:
            control = read_control(self._control_path)
            stack = list(control.stack)
            if not stack and control.source == DEVELOPMENT_FREEZE_SOURCE:
                stack = [{"source": DEVELOPMENT_FREEZE_SOURCE}]
            development_present = any(
                entry.get("source") == DEVELOPMENT_FREEZE_SOURCE for entry in stack
            )
            if not development_present and not result.live:
                try:
                    push_freeze(
                        reason="stimulus source lost",
                        path=self._control_path,
                        source=DEVELOPMENT_FREEZE_SOURCE,
                    )
                    log.warning(
                        "stimulus source still lost after an unfreeze; "
                        "freezing the developing entity again"
                    )
                except Exception:
                    log.warning(
                        "re-push development freeze after unfreeze failed",
                        exc_info=True,
                    )
            if result.live:
                self._live_streak += 1
                if self._live_streak >= 2:
                    try:
                        pop_freeze(self._control_path, source=DEVELOPMENT_FREEZE_SOURCE)
                    except Exception:
                        log.warning(
                            "pop_freeze on stimulus source return failed",
                            exc_info=True,
                        )
                    self._lost = False
                    self._not_live_since = None
                    self._live_streak = 0
                    self._grace_until = now + self._window_s + 2 * self._check_seconds
                    log.info("stimulus source returned; resuming development")
                    try:
                        await self._publish(
                            STAGE_DEVELOPMENT_STIMULUS_SOURCE_RETURNED,
                            {
                                "stage": "development",
                                "provider": result.provider,
                            },
                            0.6,
                        )
                    except Exception:
                        log.warning(
                            "publish stage.development.stimulus_source_returned failed",
                            exc_info=True,
                        )
            else:
                self._live_streak = 0

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run the watcher until ``stop_event`` is set.

        A step failure is logged and absorbed; the watcher does not clear its
        own freeze at shutdown because a crashed stimulus source must not silently resume.
        """
        while not stop_event.is_set():
            try:
                await self.step()
            except Exception:
                log.warning("stimulus source watcher step failed", exc_info=True)
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self._check_seconds
                )
            except asyncio.TimeoutError:
                continue
