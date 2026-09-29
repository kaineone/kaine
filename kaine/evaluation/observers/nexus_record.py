# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Optional LOCAL-ONLY Nexus diagnostics recorder.

NEVER EXPORT-ELIGIBLE
---------------------
This recorder subscribes to the same diagnostics streams as the Nexus bridge
and writes one record per event to ``data/nexus_record/``.

- The Nexus record NEVER leaves the host.
- The Nexus record is NEVER export-eligible: it writes outside
  ``data/evaluation/`` so the metrics bundle builder cannot reach it.
- Every record contains exactly the payload produced by ``PrivacyFilter`` with
  ``dev_content_override=false`` (the same filter the Nexus bridge applies),
  plus stream name and entry id. A filter failure drops the event and logs a
  warning, mirroring the bridge's behaviour.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from kaine.bus.schema import Event
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.config import NexusRecordConfig
from kaine.evaluation.sink import AsyncJsonlSink
from kaine.evaluation.stream_registry import diagnostics_streams
from kaine.nexus.privacy import PrivacyFilter

log = logging.getLogger(__name__)


class NexusRecord(StreamSubscriberObserver):
    """Local-only recorder of the filtered Nexus diagnostics display."""

    streams = diagnostics_streams()
    name = "nexus_record"

    def __init__(
        self,
        bus: BusReader,
        sink: AsyncJsonlSink,
        config: NexusRecordConfig,
    ) -> None:
        super().__init__(bus, poll_interval_s=0.5)
        self._sink = sink
        self._config = config
        # Same filter construction as the Nexus bridge: diagnostics surface,
        # never a dev-content surface.
        self._privacy = PrivacyFilter(dev_content_override=False)

    async def handle(self, stream: str, entry_id: str, event: Event) -> None:
        try:
            filtered = self._privacy.filter(event, surface="diagnostics")
        except Exception:
            log.warning("privacy filter failed for %s", entry_id, exc_info=True)
            return
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "entry_id": entry_id,
            "stream": stream,
            "source": filtered.source,
            "type": filtered.type,
            "salience": filtered.salience,
            "timestamp": filtered.timestamp.isoformat(),
            "causal_parent": filtered.causal_parent,
            "payload": dict(filtered.payload or {}),
        }
        await self._sink.write(record)
