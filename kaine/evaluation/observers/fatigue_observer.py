# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Fatigue observer — records interoception.fatigue and interoception.report history.

Subscribes to ``interoception.out`` and logs:
- Every ``interoception.fatigue`` event (threshold crossing) with the current
  value and threshold.
- Every ``interoception.report`` event's fatigue fields (fatigue_value,
  fatigue_threshold) at low priority (written but no alert).

This provides a continuous fatigue trajectory plus explicit threshold
crossings for the welfare assessment pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.bus.streams import INTEROCEPTION_STREAM
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)

_INTEROCEPTION_STREAM = INTEROCEPTION_STREAM


class FatigueObserver(StreamSubscriberObserver):
    """Logs interoception.fatigue threshold crossings and periodic fatigue reports."""

    name = "fatigue"
    streams = (_INTEROCEPTION_STREAM,)

    def __init__(self, bus: BusReader, sink: AsyncJsonlSink) -> None:
        super().__init__(bus, poll_interval_s=0.5)
        self._sink = sink

    async def handle(self, stream: str, entry_id: str, event: Event) -> None:
        if event.type == "interoception.fatigue":
            payload = event.payload or {}
            await self._sink.write(
                {
                    "entry_id": entry_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "event": "threshold_crossing",
                    "fatigue_value": payload.get("value"),
                    "fatigue_threshold": payload.get("threshold"),
                    "crossed": payload.get("crossed", True),
                }
            )
        elif event.type == "interoception.report":
            payload = event.payload or {}
            await self._sink.write(
                {
                    "entry_id": entry_id,
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "event": "report",
                    "fatigue_value": payload.get("fatigue_value"),
                    "fatigue_threshold": payload.get("fatigue_threshold"),
                    "prediction_error": payload.get("prediction_error"),
                }
            )
