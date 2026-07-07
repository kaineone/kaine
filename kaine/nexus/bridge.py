# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Protocol, runtime_checkable

from kaine.bus.schema import Event
from kaine.nexus.privacy import PrivacyFilter

log = logging.getLogger(__name__)


@runtime_checkable
class _BusLike(Protocol):
    async def read(
        self, stream: str, *, last_id: str, count: int, block_ms: int
    ) -> list[tuple[str, Event]]:
        ...

    async def current_workspace_id(self) -> str:
        ...


@dataclass
class SSEClient:
    surface: str  # "diagnostics" — the only surface; all surfaces are scrubbed
    queue: asyncio.Queue[tuple[str, Event]] = field(
        default_factory=lambda: asyncio.Queue(maxsize=256)
    )

    async def push(self, entry_id: str, event: Event) -> None:
        try:
            self.queue.put_nowait((entry_id, event))
        except asyncio.QueueFull:
            log.warning("dropping SSE event for surface=%s: queue full", self.surface)


class BusBridge:
    """Reads from Redis streams, applies the privacy filter, fans out to
    per-client SSE queues.

    Every subscriber's events are content-stripped by the privacy filter;
    there is no unfiltered surface.
    """

    def __init__(
        self,
        bus: _BusLike,
        privacy: PrivacyFilter,
        *,
        streams: Iterable[str] = (),
        poll_interval_s: float = 0.2,
        read_count: int = 64,
    ) -> None:
        self._bus = bus
        self._privacy = privacy
        self._streams = list(streams)
        self._poll_interval = float(poll_interval_s)
        self._read_count = int(read_count)
        self._cursors: dict[str, str] = {}
        self._clients: list[SSEClient] = []
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    @property
    def streams(self) -> list[str]:
        return list(self._streams)

    def add_client(self, surface: str) -> SSEClient:
        client = SSEClient(surface=surface)
        self._clients.append(client)
        return client

    def remove_client(self, client: SSEClient) -> None:
        try:
            self._clients.remove(client)
        except ValueError:
            # Already removed (e.g. double-disconnect) — idempotent by design.
            pass

    async def start(self) -> None:
        if self._task is not None:
            return
        for stream in self._streams:
            if stream not in self._cursors:
                self._cursors[stream] = "$"
        self._task = asyncio.create_task(self._run(), name="nexus-bus-bridge")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                # Expected outcome of the cancel() above, not an error.
                pass
            self._task = None

    async def _run(self) -> None:
        try:
            while not self._stopped.is_set():
                await self._tick_once()
                await asyncio.sleep(self._poll_interval)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("nexus bus bridge crashed")

    async def _tick_once(self) -> None:
        for stream in self._streams:
            try:
                entries = await self._bus.read(
                    stream,
                    last_id=self._cursors.get(stream, "$"),
                    count=self._read_count,
                    block_ms=0,
                )
            except Exception:
                log.warning("nexus bridge read failed for %s", stream, exc_info=True)
                continue
            if not entries:
                continue
            self._cursors[stream] = entries[-1][0]
            for entry_id, event in entries:
                await self._dispatch(entry_id, event)

    async def _dispatch(self, entry_id: str, event: Event) -> None:
        # Filter ONCE per event, not once per client. Every client is the same
        # `diagnostics` surface (PrivacyFilter.filter() ignores the `surface`
        # kwarg entirely — see kaine/privacy_filter.py), so filtering per-client
        # recomputed the identical recursive scrub N times for N clients. This
        # reuses the single filtered Event for every client's queue: the output
        # each client receives is byte-identical to the old per-client filter
        # (same input event, same filter, same result — see
        # tests/test_nexus_bridge.py::
        # test_dispatch_output_identical_across_all_clients_and_matches_direct_filter).
        clients = list(self._clients)
        if not clients:
            return
        try:
            filtered = self._privacy.filter(event, surface="diagnostics")
        except Exception:
            log.warning("privacy filter failed", exc_info=True)
            return
        for client in clients:
            await client.push(entry_id, filtered)

    async def publish_synthetic(
        self, *, source: str, type: str, payload: dict[str, Any]
    ) -> None:
        """Inject a server-synthesized (non-bus) event into the SSE stream.

        Used to server-push periodic metrics/health/pacing/module-activity
        snapshots (see ``diagnostics.py``'s snapshot pusher) over the SAME
        single multiplexed stream, rather than the client polling separate
        JSON endpoints. Goes through the identical filter-once + fan-out path
        as bus events for defense-in-depth consistency, even though these
        payloads are already server-composed non-content operational data.
        """
        event = Event(
            source=source,
            type=type,
            payload=payload,
            salience=0.0,
            timestamp=datetime.now(timezone.utc),
            causal_parent=None,
        )
        await self._dispatch(f"synthetic-{time.monotonic()}", event)


def event_to_sse_payload(entry_id: str, event: Event) -> dict[str, Any]:
    return {
        "id": entry_id,
        "source": event.source,
        "type": event.type,
        "payload": event.payload,
        "salience": event.salience,
        "timestamp": event.timestamp.isoformat() if hasattr(event.timestamp, "isoformat") else str(event.timestamp),
        "causal_parent": event.causal_parent,
    }
