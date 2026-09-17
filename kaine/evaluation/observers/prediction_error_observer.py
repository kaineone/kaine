# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Prediction-error observer — sliding-window statistics across predictive modules.

Subscribes to five predictive-module output streams:

    soma.out       → soma.report         → ``prediction_error``
    chronos.out    → chronos.report      → ``temporal_prediction_error``
    topos.out      → topos.report        → ``prediction_error``
    audition.out   → audition.*          → ``prediction_error``
    phantasia.out  → phantasia.world_error → ``world_error``

Maintains an in-memory sliding window per source and computes mean / p95 /
p99 statistics on each flush interval.  Statistics are written to
daily-rotated JSONL and exposed as in-memory counters for Nexus diagnostics.

When a source module is absent its stream produces no events and that slot
contributes nothing — the observer remains fully operational for the streams
that do exist.

READ-ONLY: never publishes to the bus.
"""

from __future__ import annotations

import logging
import statistics
import time as _time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from kaine.bus.schema import Event
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)


# (stream, accepted_types, error_field)
_SOURCES: list[tuple[str, frozenset[str], str]] = [
    (
        "soma.out",
        frozenset({"soma.report"}),
        "prediction_error",
    ),
    (
        "chronos.out",
        frozenset({"chronos.report"}),
        "temporal_prediction_error",
    ),
    (
        "topos.out",
        frozenset({"topos.report"}),
        "prediction_error",
    ),
    (
        "audition.out",
        frozenset({"audition.transcription", "audition.emotion"}),
        "prediction_error",
    ),
    (
        "phantasia.out",
        frozenset({"phantasia.world_error"}),
        "world_error",
    ),
]
_SOURCE_MAP: dict[str, tuple[frozenset[str], str]] = {
    stream: (accepted, field) for stream, accepted, field in _SOURCES
}

_DEFAULT_WINDOW_SIZE = 64
_DEFAULT_FLUSH_INTERVAL_S = 30.0


def _percentile(values: list[float], pct: float) -> float:
    """Simple percentile (linear interpolation on sorted values)."""
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    k = (n - 1) * pct / 100.0
    lo = int(k)
    hi = lo + 1
    if hi >= n:
        return sorted_vals[-1]
    frac = k - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


class PredictionErrorObserver(StreamSubscriberObserver):
    """Multi-stream prediction-error statistics observer."""

    name = "prediction_error"
    streams = tuple(stream for stream, _, _ in _SOURCES)

    def __init__(
        self,
        bus: BusReader,
        sink: AsyncJsonlSink,
        *,
        window_size: int = _DEFAULT_WINDOW_SIZE,
        flush_interval_s: float = _DEFAULT_FLUSH_INTERVAL_S,
        poll_interval_s: float = 0.5,
    ) -> None:
        super().__init__(bus, poll_interval_s=poll_interval_s)
        self._sink = sink
        self._window_size = max(2, int(window_size))
        self._flush_interval_s = float(flush_interval_s)
        # Per-source windows.
        self._windows: dict[str, deque[float]] = {
            stream: deque(maxlen=self._window_size) for stream, _, _ in _SOURCES
        }
        # In-memory diagnostics counters (total events ingested per source).
        self._event_counts: dict[str, int] = {stream: 0 for stream, _, _ in _SOURCES}
        self._last_flush_at: float = 0.0

    @property
    def event_counts(self) -> dict[str, int]:
        return dict(self._event_counts)

    def _stats_for_source(self, stream: str) -> dict[str, Any]:
        window = list(self._windows[stream])
        if not window:
            return {"n": 0, "mean": None, "p95": None, "p99": None}
        return {
            "n": len(window),
            "mean": round(statistics.fmean(window), 6),
            "p95": round(_percentile(window, 95), 6),
            "p99": round(_percentile(window, 99), 6),
        }

    async def _initial_cursors(self) -> dict[str, str]:
        self._last_flush_at = _time.monotonic()
        return await super()._initial_cursors()

    async def handle(self, stream: str, entry_id: str, event: Event) -> None:
        accepted_types, error_field = _SOURCE_MAP[stream]
        if event.type in accepted_types:
            payload = event.payload or {}
            val = payload.get(error_field)
            if isinstance(val, (int, float)):
                self._windows[stream].append(float(val))
                self._event_counts[stream] += 1

    async def _tick(self) -> None:
        now = _time.monotonic()
        if now - self._last_flush_at >= self._flush_interval_s:
            await self._flush()
            self._last_flush_at = now

    async def _cleanup(self) -> None:
        await self._flush()

    async def _flush(self) -> None:
        stats = {stream: self._stats_for_source(stream) for stream, _, _ in _SOURCES}
        # Only write if at least one source has data.
        if all(s["n"] == 0 for s in stats.values()):
            return
        await self._sink.write(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "sources": stats,
                "event_counts": dict(self._event_counts),
            }
        )
