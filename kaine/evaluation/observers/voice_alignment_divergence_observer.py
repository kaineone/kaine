# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Voice-alignment divergence observer.

Subscribes to ``hypnos.out`` for ``hypnos.sleep.completed`` events carrying
voice-alignment phase results.  Extracts the operator-seeded vs.
self-generated preference-pair divergence trajectory (from the
``voice_alignment`` sub-dict of the Hypnos sleep summary) and writes it to
daily-rotated JSONL.

Specifically tracked from the sleep summary:
- ``pairs_processed``      — total pairs considered this cycle
- ``pairs_above_threshold`` — pairs that met the DPO quality threshold
- ``dpo_loss``             — training loss (proxy for preference shift)
- ``adapter_accepted``     — whether the adapter was promoted
- ``capability_score_before`` / ``capability_score_after`` — alignment gate

All values are numeric/boolean metadata only; no raw text content is logged.
When voice alignment is disabled or the phase is skipped, the event's
``voice_alignment`` dict is absent and the observer silently skips it.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)

_HYPNOS_STREAM = "hypnos.out"


class VoiceAlignmentDivergenceObserver(StreamSubscriberObserver):
    """Captures per-sleep voice-alignment divergence metrics."""

    name = "voice_alignment_divergence"
    stream = _HYPNOS_STREAM

    def __init__(self, bus: BusReader, sink: AsyncJsonlSink) -> None:
        super().__init__(bus, poll_interval_s=0.5)
        self._sink = sink

    async def handle(self, entry_id: str, event: Event) -> None:
        if event.type != "hypnos.sleep.completed":
            return
        payload = event.payload or {}
        va = payload.get("voice_alignment")
        if not va or not isinstance(va, dict):
            # Voice alignment disabled or skipped — no-op.
            return
        await self._sink.write(
            {
                "entry_id": entry_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "pairs_processed": va.get("pairs_processed"),
                "pairs_above_threshold": va.get("pairs_above_threshold"),
                "dpo_loss": va.get("dpo_loss"),
                "adapter_accepted": va.get("adapter_accepted"),
                "capability_score_before": va.get("capability_score_before"),
                "capability_score_after": va.get("capability_score_after"),
                "mean_similarity_before": va.get(
                    "mean_intent_expression_similarity_before"
                ),
                "mean_similarity_after": va.get(
                    "mean_intent_expression_similarity_after"
                ),
            }
        )
