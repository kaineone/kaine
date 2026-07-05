# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Nous policy observer — logs nous.policy events to daily-rotated JSONL.

Subscribes to ``nous.out`` and records every ``nous.policy`` event:
- ``expected_free_energy`` (EFE value)
- ``horizon``              (planning horizon)
- ``policy``               (selected action ID string)

These are numeric/string metadata only — no raw content.

When Nous is absent or disabled the stream produces no events and the
observer runs silently.

READ-ONLY: never publishes to the bus.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)

_NOUS_STREAM = "nous.out"


class NousPolicyObserver(StreamSubscriberObserver):
    """Records Nous policy events (EFE, horizon, action) to JSONL."""

    name = "nous_policy"
    stream = _NOUS_STREAM

    def __init__(self, bus: BusReader, sink: AsyncJsonlSink) -> None:
        super().__init__(bus, poll_interval_s=0.5)
        self._sink = sink

    async def handle(self, entry_id: str, event: Event) -> None:
        if event.type != "nous.policy":
            return
        payload = event.payload or {}
        await self._sink.write(
            {
                "entry_id": entry_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "expected_free_energy": payload.get("expected_free_energy"),
                "horizon": payload.get("horizon"),
                "policy": payload.get("policy"),
            }
        )
