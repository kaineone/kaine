# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Voice alignment tracker: captures Hypnos cycle stats per sleep."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink
from kaine.evaluation.sleep_snapshots import HYPNOS_STREAM

log = logging.getLogger(__name__)


class VoiceTrackingObserver(StreamSubscriberObserver):
    name = "voice_tracking"
    stream = HYPNOS_STREAM

    def __init__(self, bus: BusReader, sink: AsyncJsonlSink) -> None:
        super().__init__(bus, poll_interval_s=0.5)
        self._sink = sink

    async def handle(self, entry_id: str, event: Event) -> None:
        if event.type != "hypnos.sleep.completed":
            return
        payload = event.payload or {}
        await self._sink.write(
            {
                "entry_id": entry_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "pairs_processed": payload.get("pairs_processed"),
                "pairs_above_threshold": payload.get("pairs_above_threshold"),
                "dpo_loss": payload.get("dpo_loss"),
                "adapter_accepted": payload.get("adapter_accepted"),
                "capability_score_before": payload.get("capability_score_before"),
                "capability_score_after": payload.get("capability_score_after"),
                "mean_similarity_before": payload.get(
                    "mean_intent_expression_similarity_before"
                ),
                "mean_similarity_after": payload.get(
                    "mean_intent_expression_similarity_after"
                ),
            }
        )
