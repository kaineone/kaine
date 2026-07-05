# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Coherence observer — reads WorkspaceSnapshot.metadata['coherence'] (PLV)
from broadcasts and writes per-module-pair PLV time series to daily-rotated
JSONL.

The PLV values are produced by the oscillatory-layer change and are stored
as a nested dict in the workspace broadcast's metadata field, keyed as
``"coherence"``.  Each entry maps a pair label (e.g. ``"soma|thymos"``) to
a float PLV in [0, 1].

When the oscillatory layer is disabled or no coherence metadata is present
the observer runs silently and writes nothing — it never errors on absence.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from kaine.evaluation._base import BusReader, WorkspaceSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)


class CoherenceObserver(WorkspaceSubscriberObserver):
    """Records PLV coherence entries from workspace broadcast metadata."""

    name = "coherence"

    def __init__(self, bus: BusReader, sink: AsyncJsonlSink) -> None:
        super().__init__(bus)
        self._sink = sink

    async def handle(self, entry_id: str, payload: dict[str, Any]) -> None:
        metadata = payload.get("metadata") or {}
        coherence = metadata.get("coherence")
        if not coherence or not isinstance(coherence, dict):
            # Oscillatory layer absent or disabled — no-op.
            return
        await self._sink.write(
            {
                "entry_id": entry_id,
                "ts": datetime.now(timezone.utc).isoformat(),
                "tick_index": payload.get("tick_index"),
                "coherence": coherence,
            }
        )
