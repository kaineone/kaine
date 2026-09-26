# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Womb-loss watcher and pre-spawn hold for gestating entities.

A gestating entity depends on a womb stimulus.  Before spawn,
:func:`hold_until_womb_ready` blocks module initialisation until the womb
is ready or shutdown is requested.  While running, :class:`WombLossWatcher`
monitors womb liveness and freezes the cycle (under the ``gestation``
freeze source) when the stimulus is lost for too long.  Because perception
is left on during a gestation-only freeze, a local womb can prove its return
through real sensory deliveries.

Before it judges loss, :class:`WombLossWatcher` arms itself on the first
live observation of the womb, so a slow-starting womb is not condemned
while it is still coming online.  If the womb never becomes live within
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
from kaine.lifecycle.womb_liveness import (
    DEFAULT_PRESENCE_WINDOW_S,
    WombLiveness,
    check_womb_live,
    check_womb_ready,
)

log = logging.getLogger(__name__)

GESTATION_FREEZE_SOURCE = "gestation"
STAGE_GESTATION_WOMB_LOST = "stage.gestation.womb_lost"
STAGE_GESTATION_WOMB_RETURNED = "stage.gestation.womb_returned"


def _validate_positive(name: str, value: float) -> None:
    try:
        value = float(value)
    except Exception:
        raise ValueError(f"{name} must be a finite positive number, got {value!r}")
    if not math.isfinite(value) or value <= 0:
        raise ValueError(f"{name} must be a finite positive number, got {value}")


async def hold_until_womb_ready(
    config: dict[str, Any],
    bus: Any,
    stop_event: asyncio.Event,
    *,
    publish: Callable[[str, dict[str, Any], float], Awaitable[None]],
    ready_check: Callable[..., Awaitable[WombLiveness]] = check_womb_ready,
    retry_seconds: float = 5.0,
) -> bool:
    """Block until the womb is ready for spawn, or until shutdown is requested.

    While held, publish ``stage.gestation.no_stimulus`` after each failed
    check so the gestation state is visible on ``lifecycle.out``.
    """
    _validate_positive("retry_seconds", retry_seconds)
    while not stop_event.is_set():
        try:
            result = await ready_check(config, bus)
        except Exception as exc:
            result = WombLiveness(
                live=False,
                provider="unknown",
                reason=f"{type(exc).__name__}: {exc}",
            )
        if result.live:
            log.info("womb is ready for spawn (%s)", result.provider)
            return True
        log.warning("womb not ready: %s", result.reason)
        try:
            await publish(
                "stage.gestation.no_stimulus",
                {
                    "stage": "gestation",
                    "reason": "womb_not_ready",
                    "detail": result.reason,
                    "provider": result.provider,
                },
                0.7,
            )
        except Exception:
            log.warning("publish stage.gestation.no_stimulus failed", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=retry_seconds)
            return False
        except asyncio.TimeoutError:
            continue
    return False


class WombLossWatcher:
    """Cycle-layer watcher that freezes a gestating entity when the womb is lost.

    The watcher arms itself on the first live observation of the womb and
    does not judge transient quiet periods while the womb is still starting.
    If no live observation occurs within ``arm_timeout_seconds``, the womb is
    declared lost immediately.  Once armed, hysteresis prevents a single
    missed event from freezing the entity, and a gestation-only freeze leaves
    perception on so a local womb can prove its return.  Arming survives a
    womb return.
    """

    def __init__(
        self,
        config: dict[str, Any],
        bus: Any,
        *,
        publish: Callable[[str, dict[str, Any], float], Awaitable[None]],
        is_gestating: Callable[[], bool],
        notify: Callable[[str], Awaitable[Any]] | None = None,
        live_check: Callable[..., Awaitable[WombLiveness]] = check_womb_live,
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
        self._is_gestating = is_gestating
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
    def womb_lost(self) -> bool:
        return self._lost

    async def _declare_loss(self, result: WombLiveness) -> None:
        """Freeze the gestating entity and publish/notify that the womb is lost."""
        try:
            push_freeze(
                reason="womb lost",
                path=self._control_path,
                source=GESTATION_FREEZE_SOURCE,
            )
        except Exception:
            log.warning("push_freeze on womb loss failed", exc_info=True)
        self._lost = True
        self._live_streak = 0
        log.critical(
            "womb lost for %s seconds; freezing gestating entity",
            self._loss_after_seconds,
        )
        try:
            await self._publish(
                STAGE_GESTATION_WOMB_LOST,
                {
                    "stage": "gestation",
                    "reason": result.reason,
                    "provider": result.provider,
                },
                0.9,
            )
        except Exception:
            log.warning("publish stage.gestation.womb_lost failed", exc_info=True)
        if self._notify is not None:
            try:
                await self._notify("womb_lost")
            except Exception:
                log.warning("notify womb_lost failed", exc_info=True)

    async def step(self) -> None:
        """Perform a single womb-liveness check and update freeze state."""
        if not self._is_gestating():
            if self._lost:
                try:
                    pop_freeze(self._control_path, source=GESTATION_FREEZE_SOURCE)
                except Exception:
                    log.warning("pop_freeze on gestation end failed", exc_info=True)
                self._lost = False
            return

        now = self._clock()

        if not self._armed:
            try:
                result = await self._live_check(
                    self._config, self._bus, window_s=self._window_s
                )
            except Exception as exc:
                result = WombLiveness(
                    live=False,
                    provider="unknown",
                    reason=f"{type(exc).__name__}: {exc}",
                )

            if result.live:
                self._armed = True
                self._grace_until = now + self._window_s + 2 * self._check_seconds
                log.info("womb live; loss watch armed")
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
            result = WombLiveness(
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
            if not stack and control.source == GESTATION_FREEZE_SOURCE:
                stack = [{"source": GESTATION_FREEZE_SOURCE}]
            gestation_present = any(
                entry.get("source") == GESTATION_FREEZE_SOURCE for entry in stack
            )
            if not gestation_present and not result.live:
                try:
                    push_freeze(
                        reason="womb lost",
                        path=self._control_path,
                        source=GESTATION_FREEZE_SOURCE,
                    )
                    log.warning(
                        "womb still lost after an unfreeze; "
                        "freezing the gestating entity again"
                    )
                except Exception:
                    log.warning(
                        "re-push gestation freeze after unfreeze failed",
                        exc_info=True,
                    )
            if result.live:
                self._live_streak += 1
                if self._live_streak >= 2:
                    try:
                        pop_freeze(self._control_path, source=GESTATION_FREEZE_SOURCE)
                    except Exception:
                        log.warning(
                            "pop_freeze on womb return failed",
                            exc_info=True,
                        )
                    self._lost = False
                    self._not_live_since = None
                    self._live_streak = 0
                    self._grace_until = now + self._window_s + 2 * self._check_seconds
                    log.info("womb returned; resuming gestation")
                    try:
                        await self._publish(
                            STAGE_GESTATION_WOMB_RETURNED,
                            {
                                "stage": "gestation",
                                "provider": result.provider,
                            },
                            0.6,
                        )
                    except Exception:
                        log.warning(
                            "publish stage.gestation.womb_returned failed",
                            exc_info=True,
                        )
            else:
                self._live_streak = 0

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run the watcher until ``stop_event`` is set.

        A step failure is logged and absorbed; the watcher does not clear its
        own freeze at shutdown because a crashed womb must not silently resume.
        """
        while not stop_event.is_set():
            try:
                await self.step()
            except Exception:
                log.warning("womb watcher step failed", exc_info=True)
            try:
                await asyncio.wait_for(
                    stop_event.wait(), timeout=self._check_seconds
                )
            except asyncio.TimeoutError:
                continue
