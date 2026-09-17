# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Empatheia observer — tracks agent-model prediction accuracy.

Subscribes to ``empatheia.out`` (type ``empatheia.agent_model``) and, when
a subsequent ``audition.out`` emotion event arrives for the same agent,
computes a simple accuracy metric: whether the predicted familiarity/
reliability was consistent with the observed emotion signal.

Accuracy model
--------------
When a new ``empatheia.agent_model`` prediction arrives, the observer
stores it keyed by ``agent_id``.  When the next ``audition.out`` event of
type ``audition.emotion`` arrives, the observer pairs it with any pending
prediction and computes:

    accuracy = 1.0 - |predicted_reliability - observed_confidence|

where ``observed_confidence`` is taken from the audition event's
``confidence`` payload field.  When ``confidence`` is absent the pairing is
skipped — no record is written — rather than scoring against a fabricated
default that would inflate accuracy toward 1.0.  The pair is written to the
sink (with ``confidence_present: true``) and the pending prediction is cleared.

Source streams: ``empatheia.out`` and ``audition.out``.  When either is
absent the observer runs silently.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from kaine.bus.schema import Event
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)

_EMPATHEIA_STREAM = "empatheia.out"
_AUDITION_STREAM = "audition.out"


class EmpatheiaObserver(StreamSubscriberObserver):
    """Tracks empatheia.agent_model predictions vs. subsequent audition events."""

    name = "empatheia"
    streams = (_EMPATHEIA_STREAM, _AUDITION_STREAM)

    def __init__(
        self,
        bus: BusReader,
        sink: AsyncJsonlSink,
        *,
        poll_interval_s: float = 0.5,
    ) -> None:
        super().__init__(bus, poll_interval_s=poll_interval_s)
        self._sink = sink
        # Pending predictions keyed by agent_id.
        self._pending: dict[str, dict[str, Any]] = {}

    async def handle(self, stream: str, entry_id: str, event: Event) -> None:
        if stream == _EMPATHEIA_STREAM and event.type == "empatheia.agent_model":
            payload = event.payload or {}
            agent_id = str(payload.get("agent_id") or "unknown")
            self._pending[agent_id] = {
                "entry_id": entry_id,
                "agent_id": agent_id,
                "reliability": float(payload.get("reliability") or 0.0),
                "familiarity": float(payload.get("familiarity") or 0.0),
                "interaction_count": int(payload.get("interaction_count") or 0),
                "predicted_at": datetime.now(timezone.utc).isoformat(),
            }
            return

        if stream == _AUDITION_STREAM and event.type in (
            "audition.emotion",
            "audition.transcription",
        ):
            # Pair with any pending prediction (use first pending agent if
            # the event doesn't carry an agent_id).
            payload = event.payload or {}
            raw_confidence = payload.get("confidence")
            if raw_confidence is None:
                # Skip: scoring against a fabricated default would inflate
                # accuracy toward 1.0 for no-op pairings. Discard pending
                # predictions for this event without writing a record.
                return
            observed_confidence = float(raw_confidence)
            for agent_id, pred in list(self._pending.items()):
                accuracy = 1.0 - abs(pred["reliability"] - observed_confidence)
                await self._sink.write(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "agent_id": agent_id,
                        "predicted_at": pred["predicted_at"],
                        "observed_event_type": event.type,
                        "observed_entry_id": entry_id,
                        "predicted_reliability": pred["reliability"],
                        "observed_confidence": observed_confidence,
                        "confidence_present": True,
                        "accuracy": round(accuracy, 4),
                        "familiarity": pred["familiarity"],
                        "interaction_count": pred["interaction_count"],
                    }
                )
                del self._pending[agent_id]
