# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Replay observer — logs mnemos.replay and phantasia.scenario events.

Privacy design (§4.4 / §5)
--------------------------
``redact_content = true`` (default): only memory IDs, affect intensity,
and timestamps are logged.  The ``text`` field from the replay payload is
dropped entirely.  This preserves the zero-raw-content guarantee for
operational logs.

``redact_content = false``: full payload (including ``text``) is logged.
This must be explicitly opted in.

Source streams: ``mnemos.out`` (type ``mnemos.replay``) and
``phantasia.out`` (type ``phantasia.scenario``).  When either stream
produces no events the observer runs silently — it never errors.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)

_REDACTED_DROP = frozenset({"text"})
_MNEMOS_STREAM = "mnemos.out"
_PHANTASIA_STREAM = "phantasia.out"


class _SingleStreamReplayObserver(StreamSubscriberObserver):
    """Internal observer for one stream."""

    def __init__(
        self,
        bus: BusReader,
        sink: AsyncJsonlSink,
        *,
        source_stream: str,
        accepted_types: frozenset[str],
        redact_content: bool,
        name: str,
    ) -> None:
        super().__init__(bus, poll_interval_s=0.5)
        self.stream = source_stream
        self.name = name
        self._sink = sink
        self._accepted_types = accepted_types
        self._redact = redact_content

    async def handle(self, entry_id: str, event: Event) -> None:
        if event.type not in self._accepted_types:
            return
        payload = dict(event.payload or {})
        if self._redact:
            for field in _REDACTED_DROP:
                payload.pop(field, None)
        await self._sink.write(
            {
                "entry_id": entry_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "stream": self.stream,
                "type": event.type,
                "redacted": self._redact,
                "payload": payload,
            }
        )


class ReplayObserver:
    """Composite observer: mnemos.replay + phantasia.scenario streams.

    Exposes the same ``start``/``stop`` lifecycle as BaseObserver so the
    SidecarRegistry can manage it uniformly.
    """

    name = "replay"

    def __init__(
        self,
        bus: BusReader,
        sink: AsyncJsonlSink,
        *,
        redact_content: bool = True,
    ) -> None:
        self._mnemos = _SingleStreamReplayObserver(
            bus,
            sink,
            source_stream=_MNEMOS_STREAM,
            accepted_types=frozenset({"mnemos.replay"}),
            redact_content=redact_content,
            name="replay_mnemos",
        )
        self._phantasia = _SingleStreamReplayObserver(
            bus,
            sink,
            source_stream=_PHANTASIA_STREAM,
            accepted_types=frozenset({"phantasia.scenario"}),
            redact_content=redact_content,
            name="replay_phantasia",
        )

    async def start(self) -> None:
        await self._mnemos.start()
        await self._phantasia.start()

    async def stop(self) -> None:
        await self._mnemos.stop()
        await self._phantasia.stop()
