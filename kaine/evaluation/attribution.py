# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Module contribution attribution: which modules win seats in
workspace broadcasts? Maintains a running histogram and flushes
per-hour rollups.
"""
from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from kaine.evaluation._base import BusReader, WorkspaceSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)


class AttributionRecorder(WorkspaceSubscriberObserver):
    name = "attribution"

    def __init__(self, bus: BusReader, sink: AsyncJsonlSink) -> None:
        super().__init__(bus)
        self._sink = sink
        self._running_total: Counter[str] = Counter()
        self._current_hour_key: str | None = None
        self._current_hour_counts: Counter[str] = Counter()

    @property
    def running_total(self) -> dict[str, int]:
        return dict(self._running_total)

    @property
    def current_hour_counts(self) -> dict[str, int]:
        return dict(self._current_hour_counts)

    async def handle(self, entry_id: str, payload: dict[str, Any]) -> None:
        # `payload` is the decoded workspace snapshot dict.
        payload = payload or {}
        sources = {item.get("source") for item in (payload.get("selected") or []) if isinstance(item, dict)}
        sources.discard(None)
        for src in sources:
            self._running_total[src] += 1
        await self._maybe_flush_hour(sources)

    async def _maybe_flush_hour(self, sources: set[str]) -> None:
        now = datetime.now(timezone.utc)
        hour_key = now.strftime("%Y-%m-%dT%H")
        if self._current_hour_key is None:
            self._current_hour_key = hour_key
        if hour_key != self._current_hour_key:
            # Flush the closing hour.
            await self._sink.write(
                {
                    "hour": self._current_hour_key,
                    "ts": now.isoformat(),
                    "counts": dict(self._current_hour_counts),
                }
            )
            self._current_hour_key = hour_key
            self._current_hour_counts = Counter()
        for src in sources:
            self._current_hour_counts[src] += 1

    async def stop(self) -> None:
        # Flush whatever's in the current hour before shutting down.
        if self._current_hour_key is not None and self._current_hour_counts:
            try:
                await self._sink.write(
                    {
                        "hour": self._current_hour_key,
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "counts": dict(self._current_hour_counts),
                        "partial": True,
                    }
                )
            except Exception:
                log.warning("final attribution flush failed", exc_info=True)
        await super().stop()
