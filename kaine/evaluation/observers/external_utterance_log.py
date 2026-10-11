# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Optional LOCAL-ONLY external-utterance recorder.

NEVER EXPORT-ELIGIBLE
---------------------
This recorder subscribes ONLY to ``lingua.external`` and writes one record
per ``external_speech`` event to ``state/research/external_utterances/``.

- The external-utterance log NEVER leaves the host.
- The external-utterance log is NEVER export-eligible: it writes to
  ``state/research/...``, which is structurally OUTSIDE ``data/evaluation/``.
- It captures only the ``text`` field of ``external_speech`` events. Bystander
  ``user_input`` and every other payload field are dropped.
- It NEVER subscribes to any other speech stream, so inner speech is never
  recorded.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from kaine.bus.schema import Event
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.config import ExternalUtterancesConfig
from kaine.evaluation.sink import AsyncJsonlSink

log = logging.getLogger(__name__)


class ExternalUtteranceLog(StreamSubscriberObserver):
    """Local-only recorder for the entity's external speech stream."""

    streams = ("lingua.external",)
    name = "external_utterance_log"

    def __init__(
        self,
        bus: BusReader,
        sink: AsyncJsonlSink,
        config: ExternalUtterancesConfig,
    ) -> None:
        super().__init__(bus, poll_interval_s=0.5)
        self._sink = sink
        self._config = config

    async def handle(self, stream: str, entry_id: str, event: Event) -> None:
        if event.type != "external_speech":
            return
        payload = event.payload or {}
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_id": entry_id,
            "type": event.type,
            "text": payload.get("text"),
        }
        if "run_id" in payload:
            record["run_id"] = payload["run_id"]
        await self._sink.write(record)
