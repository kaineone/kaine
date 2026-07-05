# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Base observer pattern for sidecar components.

Each observer is an async task. The SidecarRegistry constructs all
enabled observers, calls `start()` on each, and `stop()` on shutdown.
Observers never publish to the bus (read-only on the cognitive loop).
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Protocol, runtime_checkable

from kaine.bus.schema import Event

log = logging.getLogger(__name__)


@runtime_checkable
class BusReader(Protocol):
    async def read(
        self, stream: str, *, last_id: str = "0", count: int = 100, block_ms: int = 0
    ) -> list[tuple[str, Event]]: ...

    async def read_entries(
        self, stream: str, last_id: str = "0", count: int = 100, block_ms: int = 0
    ) -> tuple[list[tuple[str, Event]], str | None]: ...

    def subscribe_workspace(
        self, last_id: str = "$", count: int = 32, poll_interval_s: float = 0.05
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]: ...

    async def current_workspace_id(self) -> str: ...


class BaseObserver(ABC):
    """Common observer lifecycle. Subclasses implement `_run`."""

    name: str = "observer"

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stopped.clear()
        self._task = asyncio.create_task(self._safe_run(), name=f"sidecar-{self.name}")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None

    async def _safe_run(self) -> None:
        try:
            await self._run()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("observer %s crashed", self.name)

    @abstractmethod
    async def _run(self) -> None: ...


class StreamSubscriberObserver(BaseObserver):
    """Observer that follows one bus stream and dispatches events."""

    stream: str = ""

    def __init__(self, bus: BusReader, *, poll_interval_s: float = 0.5) -> None:
        super().__init__()
        self._bus = bus
        self._poll_interval_s = float(poll_interval_s)
        self._cursor = "0"  # default: pick up backlog on first read

    async def _run(self) -> None:
        try:
            self._cursor = await self._initial_cursor()
        except Exception:
            self._cursor = "0"
        while not self._stopped.is_set():
            last_scanned: str | None = None
            try:
                entries, last_scanned = await self._bus.read_entries(
                    self.stream, last_id=self._cursor, count=64, block_ms=0
                )
            except Exception:
                entries = []
                log.warning("observer %s read failed", self.name, exc_info=True)
            for entry_id, event in entries:
                self._cursor = entry_id
                try:
                    await self.handle(entry_id, event)
                except Exception:
                    log.warning(
                        "observer %s handler raised on %s", self.name, entry_id,
                        exc_info=True,
                    )
            # Advance past entries that were scanned but skipped as undecodable,
            # so a batch of all-malformed legacy entries can't wedge the cursor.
            if last_scanned is not None:
                self._cursor = last_scanned
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=self._poll_interval_s)
            except asyncio.TimeoutError:
                continue

    async def _initial_cursor(self) -> str:
        # Default: start from "0" so observers see the backlog. Subclasses
        # that want to skip backlog can override.
        return "0"

    @abstractmethod
    async def handle(self, entry_id: str, event: Event) -> None: ...


class WorkspaceSubscriberObserver(BaseObserver):
    """Observer that follows ``workspace.broadcast`` via the canonical
    ``bus.subscribe_workspace`` path — the same door every module uses.

    Unlike :class:`StreamSubscriberObserver`, this does NOT decode entries
    through the standard ``Event`` schema. The broadcast is published as a
    ``{snapshot: <json>, timestamp, source}`` entry, which the Event decoder
    rejects (no ``salience``/``type``/``payload``); an observer using that path
    silently receives nothing. ``subscribe_workspace`` yields the *decoded
    snapshot dict*, which is what :meth:`handle` receives.

    Default start position is ``"$"`` (only broadcasts after the observer
    starts), so a long-lived persisted stream isn't replayed on every boot.
    """

    def __init__(self, bus: BusReader, *, start_id: str = "$") -> None:
        super().__init__()
        self._bus = bus
        self._start_id = start_id

    async def _run(self) -> None:
        # Race each broadcast against the stop signal so shutdown is immediate.
        # `subscribe_workspace` blocks (polls) when idle and never yields, so a
        # plain `async for` could only be torn down by task cancellation; racing
        # the stop event keeps `stop()` responsive (and never cancels a pending
        # __anext__ on a timeout, which would close the generator mid-stream).
        agen = self._bus.subscribe_workspace(last_id=self._start_id)
        stop_wait = asyncio.ensure_future(self._stopped.wait())
        try:
            while not self._stopped.is_set():
                nxt = asyncio.ensure_future(agen.__anext__())
                done, _ = await asyncio.wait(
                    {nxt, stop_wait}, return_when=asyncio.FIRST_COMPLETED
                )
                if nxt not in done:
                    nxt.cancel()
                    with contextlib.suppress(asyncio.CancelledError, StopAsyncIteration):
                        await nxt
                    break
                try:
                    entry_id, payload = nxt.result()
                except StopAsyncIteration:
                    break
                try:
                    await self.handle(entry_id, payload)
                except Exception:
                    log.warning(
                        "observer %s handler raised on %s", self.name, entry_id,
                        exc_info=True,
                    )
        finally:
            if not stop_wait.done():
                stop_wait.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await stop_wait
            aclose = getattr(agen, "aclose", None)
            if aclose is not None:
                with contextlib.suppress(Exception):
                    await aclose()

    @abstractmethod
    async def handle(self, entry_id: str, payload: dict[str, Any]) -> None: ...
