# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Workspace trajectory recorder: writes every Syneidesis broadcast
as JSONL, with salience scores and Thymos state when available.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from kaine.evaluation._base import BusReader, WorkspaceSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink
from kaine.privacy_filter import PrivacyFilter

log = logging.getLogger(__name__)

WORKSPACE_STREAM = "workspace.broadcast"
THYMOS_STREAM = "thymos.out"


class TrajectoryRecorder(WorkspaceSubscriberObserver):
    name = "trajectory"

    def __init__(
        self,
        bus: BusReader,
        sink: AsyncJsonlSink,
        *,
        thymos_state_provider=None,
        privacy_filter: PrivacyFilter | None = None,
    ) -> None:
        super().__init__(bus)
        self._sink = sink
        # thymos_state_provider() returns the latest Thymos state dict, or None.
        self._thymos_provider = thymos_state_provider
        self._privacy = privacy_filter or PrivacyFilter()

    async def handle(self, entry_id: str, payload: dict[str, Any]) -> None:
        # `payload` is the decoded workspace snapshot dict from
        # subscribe_workspace — tick_index / selected / salience_scores etc.
        payload = payload or {}
        thymos_state = None
        if self._thymos_provider is not None:
            try:
                thymos_state = self._thymos_provider()
            except Exception:
                thymos_state = None

        # Strip content-bearing fields from the selected events before
        # persistence. The privacy taxonomy lives in kaine.privacy_filter so
        # the diagnostics surface and the trajectory recorder never drift.
        raw_selected = payload.get("selected") or []
        selected = [self._filter_selected_entry(e) for e in raw_selected]

        entry = {
            "entry_id": entry_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "tick_index": payload.get("tick_index"),
            "is_experiential": payload.get("is_experiential"),
            "inhibited": payload.get("inhibited"),
            "salience_scores": payload.get("salience_scores"),
            "selected": selected,
            "metadata": payload.get("metadata") or {},
            "thymos_state": thymos_state,
        }
        await self._sink.write(entry)

    def _filter_selected_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Return a content-scrubbed copy of a workspace selected entry."""
        if not isinstance(entry, dict):
            return entry
        from kaine.bus.schema import Event

        try:
            event = Event(
                source=str(entry.get("source", "")),
                type=str(entry.get("type", "")),
                payload=dict(entry.get("payload", {})),
                salience=float(entry.get("salience", 0.5)),
                timestamp=datetime.now(timezone.utc),
                causal_parent=entry.get("causal_parent"),
            )
            filtered = self._privacy.filter_for_diagnostics(event)
            return {
                "source": filtered.source,
                "type": filtered.type,
                "salience": filtered.salience,
                "causal_parent": filtered.causal_parent,
                "payload": filtered.payload,
            }
        except Exception:
            # If the entry cannot be decoded as an Event, drop the payload
            # entirely rather than risk persisting raw content.
            return {
                "source": str(entry.get("source", "")),
                "type": str(entry.get("type", "")),
                "salience": float(entry.get("salience", 0.5)),
                "causal_parent": entry.get("causal_parent"),
                "payload": {},
            }
