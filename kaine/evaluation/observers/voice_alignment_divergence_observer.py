# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Voice-alignment divergence observer.

Subscribes to ``hypnos.out`` for ``hypnos.sleep.completed`` events and writes
one JSONL record per sleep summarising the voice-alignment phase.

Record fields and their source in the ``hypnos.sleep.completed`` payload:

- ``adapter_accepted`` — from ``voice_alignment.accepted``
- ``capability_loss`` — from ``voice_alignment.capability_loss``
- ``outcome`` — category derived from ``voice_alignment.accepted`` and
  ``voice_alignment.reason``
- ``samples_used`` — from ``voice_alignment.samples_used``
- ``pairs_processed`` — from the top-level ``pairs_processed``
- ``pairs_above_threshold`` — from the top-level ``pairs_above_threshold``
- ``dpo_loss`` — from the top-level ``dpo_loss``
- ``capability_score_before`` — from the top-level ``capability_score_before``
- ``capability_score_after`` — from the top-level ``capability_score_after``
- ``mean_similarity_before`` — from the top-level ``mean_intent_expression_similarity_before``
- ``mean_similarity_after`` — from the top-level ``mean_intent_expression_similarity_after``

The free-text reason is never recorded because these records are eligible for
the metrics-only research bundle.

If the event type is not ``hypnos.sleep.completed``, the payload has no
``voice_alignment`` dict, or the voice-alignment phase result in ``phases``
carries ``metadata.skipped``, the observer writes nothing.  A missing
voice-alignment phase (older producers) does not prevent recording.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)

_HYPNOS_STREAM = "hypnos.out"


def outcome_category(accepted: object, reason: object, samples_used: object) -> str:
    """Return the fixed outcome category for a voice-alignment result."""
    if accepted is True:
        return "accepted"
    text = str(reason or "").lower()
    if "dpo pairs" in text:
        return "no_pairs"
    if "abliteration veto" in text:
        return "vetoed_abliteration"
    if "capability" in text:
        return "vetoed_capability"
    return "failed"


class VoiceAlignmentDivergenceObserver(StreamSubscriberObserver):
    """Captures per-sleep voice-alignment divergence metrics."""

    name = "voice_alignment_divergence"
    streams = (_HYPNOS_STREAM,)

    def __init__(self, bus: BusReader, sink: AsyncJsonlSink) -> None:
        super().__init__(bus, poll_interval_s=0.5)
        self._sink = sink

    async def handle(self, stream: str, entry_id: str, event: Event) -> None:
        if event.type != "hypnos.sleep.completed":
            return
        payload = event.payload or {}
        va = payload.get("voice_alignment")
        if not isinstance(va, dict):
            return
        for phase in payload.get("phases") or []:
            if isinstance(phase, dict) and phase.get("phase") == "voice_alignment":
                metadata = phase.get("metadata") or {}
                if isinstance(metadata, dict) and "skipped" in metadata:
                    return
                break
        await self._sink.write(
            {
                "entry_id": entry_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "adapter_accepted": va.get("accepted"),
                "capability_loss": va.get("capability_loss"),
                "outcome": outcome_category(
                    va.get("accepted"), va.get("reason"), va.get("samples_used")
                ),
                "samples_used": va.get("samples_used"),
                "pairs_processed": payload.get("pairs_processed"),
                "pairs_above_threshold": payload.get("pairs_above_threshold"),
                "dpo_loss": payload.get("dpo_loss"),
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
