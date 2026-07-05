# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Fatigue observer — records soma.fatigue and soma.report history.

Subscribes to ``soma.out`` and logs:
- Every ``soma.fatigue`` event (threshold crossing) with the current
  value and threshold.
- Every ``soma.report`` event's fatigue fields (fatigue_value,
  fatigue_threshold) at low priority (written but no alert).

This provides a continuous fatigue trajectory plus explicit threshold
crossings for the welfare assessment pipeline.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)

_SOMA_STREAM = "soma.out"


class FatigueObserver(StreamSubscriberObserver):
    """Logs soma.fatigue threshold crossings and periodic fatigue reports."""

    name = "fatigue"
    stream = _SOMA_STREAM

    def __init__(self, bus: BusReader, sink: AsyncJsonlSink) -> None:
        super().__init__(bus, poll_interval_s=0.5)
        self._sink = sink

    async def handle(self, entry_id: str, event: Event) -> None:
        if event.type == "soma.fatigue":
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
        elif event.type == "soma.report":
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
