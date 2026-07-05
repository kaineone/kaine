# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Sleep cycle before/after snapshot recorder.

Watches hypnos.out for the sleep lifecycle events. On hypnos.sleep.started,
captures the current registry state via the provided `state_provider`. On
hypnos.sleep.completed, captures again and writes the pair.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable

from kaine.bus.schema import Event
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)


HYPNOS_STREAM = "hypnos.out"


class SleepSnapshotRecorder(StreamSubscriberObserver):
    name = "sleep_snapshots"
    stream = HYPNOS_STREAM

    def __init__(
        self,
        bus: BusReader,
        sink: AsyncJsonlSink,
        *,
        state_provider: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        super().__init__(bus, poll_interval_s=0.5)
        self._sink = sink
        self._state_provider = state_provider
        self._pending_before: dict[str, Any] | None = None
        self._pending_started_ts: str | None = None

    async def handle(self, entry_id: str, event: Event) -> None:
        if event.type == "hypnos.sleep.started":
            self._pending_before = self._capture_state()
            self._pending_started_ts = datetime.now(timezone.utc).isoformat()
            return
        if event.type == "hypnos.sleep.completed":
            if self._pending_before is None:
                # We missed the hypnos.sleep.started — record the after-only.
                await self._sink.write(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "before": None,
                        "after": self._capture_state(),
                        "warning": "no matching hypnos.sleep.started",
                    }
                )
                return
            await self._sink.write(
                {
                    "began_ts": self._pending_started_ts,
                    "ended_ts": datetime.now(timezone.utc).isoformat(),
                    "before": self._pending_before,
                    "after": self._capture_state(),
                    "hypnos_payload": event.payload or {},
                }
            )
            self._pending_before = None
            self._pending_started_ts = None

    def _capture_state(self) -> dict[str, Any]:
        if self._state_provider is None:
            return {}
        try:
            return dict(self._state_provider())
        except Exception:
            log.warning("sleep snapshot state_provider raised", exc_info=True)
            return {}
