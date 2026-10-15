# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Replay observer — logs episodic_memory.replay and world_model.scenario events.

Privacy design (§4.4 / §5)
--------------------------
``redact_content = true`` (default): only memory IDs, affect intensity,
and timestamps are logged.  The ``text`` field from the replay payload is
dropped entirely.  This preserves the zero-raw-content guarantee for
operational logs.

``redact_content = false``: full payload (including ``text``) is logged.
This must be explicitly opted in.

Source streams: ``episodic_memory.out`` (type ``episodic_memory.replay``) and
``world_model.out`` (type ``world_model.scenario``).  When either stream
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
_EPISODIC_MEMORY_STREAM = "episodic_memory.out"
_WORLD_MODEL_STREAM = "world_model.out"


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
        self.streams = (source_stream,)
        self.name = name
        self._sink = sink
        self._accepted_types = accepted_types
        self._redact = redact_content

    async def handle(self, stream: str, entry_id: str, event: Event) -> None:
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
                "stream": stream,
                "type": event.type,
                "redacted": self._redact,
                "payload": payload,
            }
        )


class ReplayObserver:
    """Composite observer: episodic_memory.replay + world_model.scenario streams.

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
        self._episodic_memory = _SingleStreamReplayObserver(
            bus,
            sink,
            source_stream=_EPISODIC_MEMORY_STREAM,
            accepted_types=frozenset({"episodic_memory.replay"}),
            redact_content=redact_content,
            name="replay_episodic_memory",
        )
        self._world_model = _SingleStreamReplayObserver(
            bus,
            sink,
            source_stream=_WORLD_MODEL_STREAM,
            accepted_types=frozenset({"world_model.scenario"}),
            redact_content=redact_content,
            name="replay_world_model",
        )

    async def start(self) -> None:
        await self._episodic_memory.start()
        await self._world_model.start()

    async def stop(self) -> None:
        await self._episodic_memory.stop()
        await self._world_model.stop()
