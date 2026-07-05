# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Proactive output audit: log every Lingua external speech whose
causal chain doesn't include a recent user input event.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from kaine.bus.schema import Event
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)


LINGUA_EXTERNAL_STREAM = "lingua.external"
USER_INPUT_STREAMS = frozenset({"audition.out"})


class ProactiveAuditObserver(StreamSubscriberObserver):
    name = "proactive_audit"
    stream = LINGUA_EXTERNAL_STREAM

    def __init__(
        self,
        bus: BusReader,
        sink: AsyncJsonlSink,
        *,
        thymos_state_provider=None,
        last_user_input_provider=None,
        proactive_threshold_seconds: float = 30.0,
    ) -> None:
        super().__init__(bus, poll_interval_s=0.3)
        self._sink = sink
        self._thymos = thymos_state_provider
        self._last_input = last_user_input_provider
        self._threshold = float(proactive_threshold_seconds)

    async def handle(self, entry_id: str, event: Event) -> None:
        if event.type != "external_speech":
            return
        now = datetime.now(timezone.utc)
        last_input_ts = None
        if self._last_input is not None:
            try:
                last_input_ts = self._last_input()
            except Exception:
                last_input_ts = None
        seconds_since_input = None
        if last_input_ts is not None:
            seconds_since_input = (now - last_input_ts).total_seconds()
        is_proactive = (
            seconds_since_input is None or seconds_since_input > self._threshold
        )
        if not is_proactive:
            return
        payload = event.payload or {}
        thymos_state = None
        if self._thymos is not None:
            try:
                thymos_state = self._thymos()
            except Exception:
                thymos_state = None
        await self._sink.write(
            {
                "entry_id": entry_id,
                "ts": now.isoformat(),
                "trigger_module": payload.get("trigger_module"),
                "trigger_salience": payload.get("trigger_salience"),
                "tick_index": payload.get("tick_index"),
                "seconds_since_user_input": seconds_since_input,
                "thymos_state": thymos_state,
            }
        )
