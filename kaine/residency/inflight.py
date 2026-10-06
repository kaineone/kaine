# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Inflight gate: count worker-thread work so unload waits for threads."""

import asyncio
import threading
from typing import Any, Callable, Optional


class InflightTicket:
    """A single admission ticket. Releasing it more than once is a no-op."""

    __slots__ = ("_gate", "_loop", "_released")

    def __init__(
        self, gate: "InflightGate", loop: asyncio.AbstractEventLoop
    ) -> None:
        self._gate = gate
        self._loop = loop
        self._released = False

    def release(self) -> None:
        """Release this ticket once. Idempotent and non-blocking."""
        if self._released:
            return
        self._released = True
        self._gate._release()


class InflightGate:
    """Counts work running in worker threads.

    Idle only when every admitted job has finished or has been provably
    abandoned before its worker thread ever started it.
    """

    __slots__ = ("_count", "_lock", "_idle_event", "_idle_event_loop")

    def __init__(self) -> None:
        self._count: int = 0
        self._lock = threading.Lock()
        self._idle_event: Optional[asyncio.Event] = None
        self._idle_event_loop: Optional[asyncio.AbstractEventLoop] = None

    def _ensure_event(self) -> None:
        """Create or replace the idle event bound to the running loop."""
        loop = asyncio.get_running_loop()
        with self._lock:
            if self._idle_event is None or self._idle_event_loop is not loop:
                if self._count != 0:
                    raise RuntimeError(
                        "InflightGate used from a different event loop while work is in flight"
                    )
                self._idle_event_loop = loop
                self._idle_event = asyncio.Event()
                self._idle_event.set()

    def admit(self) -> InflightTicket:
        """Increment the in-flight count and return a ticket to release."""
        self._ensure_event()
        loop = asyncio.get_running_loop()
        with self._lock:
            self._count += 1
            self._idle_event.clear()
        return InflightTicket(self, loop)

    def _release(self) -> None:
        """Decrement the count and signal idleness at zero."""
        with self._lock:
            self._count -= 1
            if self._count <= 0:
                self._idle_event.set()

    @property
    def inflight(self) -> int:
        with self._lock:
            return self._count

    async def wait_idle(self) -> None:
        """Return once the in-flight count reaches zero."""
        self._ensure_event()
        await self._idle_event.wait()

    async def run(
        self,
        ticket: InflightTicket,
        executor: Optional[Any],
        fn: Callable[..., Any],
        /,
        *args: Any,
    ) -> Any:
        """Run ``fn(*args)`` in ``executor`` while keeping the gate accurate.

        The ticket must have been obtained from ``admit()``. Cancellation is
        handled so that work which has already started in a worker thread runs
        to completion (and releases the ticket from that thread), while work
        that never started is marked abandoned and released immediately.
        """
        loop = ticket._loop
        if loop is None:
            raise RuntimeError("admit() must be called before run()")
        if asyncio.get_running_loop() is not loop:
            raise RuntimeError(
                "InflightGate.run() must be called on the loop that admitted the ticket"
            )

        state = {"started": False, "abandoned": False}
        lock = threading.Lock()

        def wrapper() -> Any:
            with lock:
                if state["abandoned"]:
                    return
                state["started"] = True
            try:
                return fn(*args)
            finally:
                try:
                    loop.call_soon_threadsafe(ticket.release)
                except RuntimeError:
                    # The loop has been closed; there is nothing left to notify.
                    pass

        try:
            return await loop.run_in_executor(executor, wrapper)
        except BaseException:
            with lock:
                if not state["started"]:
                    state["abandoned"] = True
                    ticket.release()
            raise
