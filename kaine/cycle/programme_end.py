# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""End-of-programme watcher for playlist perception feeds.

Polls the shared playlist clock every second. When the programme runs past
its last item while not paused, it requests a single operator-style
preservation with stop. If that preservation fails or does not report within
the timeout, the entity is frozen under the ``programme_end`` holder so it is
not left running without senses.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from kaine.cycle.control_state import push_freeze
from kaine.cycle.preserve_watch import (
    new_request,
    read_result,
    write_request,
)

log = logging.getLogger(__name__)


def _default_freeze(reason: str, source: str = "programme_end") -> None:
    push_freeze(reason=reason, path=None, source=source)


class ProgrammeEndWatcher:
    def __init__(
        self,
        clock: Any,
        item_count: int,
        *,
        write_request: Callable[[Any], None] = write_request,
        read_result: Callable[[], dict | None] = read_result,
        freeze: Callable[[str, str], None] = _default_freeze,
        notify: Callable[[str], Awaitable[None]] | None = None,
        poll_seconds: float = 1.0,
        result_timeout_seconds: float = 600.0,
        clock_fn: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self.clock = clock
        self.item_count = int(item_count)
        self._write_request = write_request
        self._read_result = read_result
        self._freeze = freeze
        self._notify = notify
        self._poll_seconds = float(poll_seconds)
        self._result_timeout_seconds = float(result_timeout_seconds)
        self._clock = clock_fn
        self._sleep = sleep

        self._handled = False

    @staticmethod
    def _programme_ended(clock: Any, item_count: int) -> bool:
        if not getattr(clock, "started", False):
            return False
        if getattr(clock, "paused", False):
            return False
        try:
            index = clock.locate()[0]
        except Exception:
            return False
        return index >= item_count

    async def step(self) -> bool:
        """Return ``True`` once the end-of-programme has been handled."""
        if not self._programme_ended(self.clock, self.item_count):
            return False

        if self._handled:
            return True

        self._handled = True
        end_mono = self._clock()
        end_wall = datetime.now(timezone.utc).isoformat()

        request = new_request("programme end", stop=True)
        request_id = request.request_id

        try:
            self._write_request(request)
        except Exception as exc:
            error = f"could not write preserve request: {type(exc).__name__}: {exc}"
            log.critical(
                "programme end at %s (monotonic %s): %s",
                end_wall,
                end_mono,
                error,
            )
            await self._freeze_and_notify(
                reason=f"programme end: preservation failed ({error})",
                error=error,
            )
            return True

        deadline = self._clock() + self._result_timeout_seconds
        result: dict | None = None
        while self._clock() < deadline:
            candidate = self._read_result()
            if candidate is not None and candidate.get("request_id") == request_id:
                result = candidate
                break
            await self._sleep(self._poll_seconds)

        if result is not None and result.get("ok"):
            log.info(
                "programme end at %s (monotonic %s): preserved and stopped",
                end_wall,
                end_mono,
            )
            return True

        if result is None:
            error = "timed out waiting for preserve result"
        else:
            error = result.get("error") or "preservation reported failure"

        log.critical(
            "programme end at %s (monotonic %s): preservation failed: %s",
            end_wall,
            end_mono,
            error,
        )
        await self._freeze_and_notify(
            reason=f"programme end: preservation failed ({error})",
            error=error,
        )
        return True

    async def _freeze_and_notify(self, reason: str, error: str) -> None:
        try:
            self._freeze(reason=reason, source="programme_end")
        except Exception:
            log.error("programme_end freeze failed: %s", error, exc_info=True)
        if self._notify is not None:
            try:
                await self._notify("programme_end_preserve_failed")
            except Exception:
                log.error("programme_end caretaker notify failed", exc_info=True)

    async def run(self, stop_event: asyncio.Event) -> None:
        """Poll until the programme ends or ``stop_event`` is set."""
        while not stop_event.is_set():
            try:
                finished = await self.step()
            except Exception as exc:
                log.warning(
                    "programme end watcher step failed: %s", exc, exc_info=True
                )
                finished = False
            if finished:
                return
            await self._sleep(self._poll_seconds)
