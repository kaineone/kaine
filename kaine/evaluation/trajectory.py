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
    ) -> None:
        super().__init__(bus)
        self._sink = sink
        # thymos_state_provider() returns the latest Thymos state dict, or None.
        self._thymos_provider = thymos_state_provider

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
        entry = {
            "entry_id": entry_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "tick_index": payload.get("tick_index"),
            "is_experiential": payload.get("is_experiential"),
            "inhibited": payload.get("inhibited"),
            "salience_scores": payload.get("salience_scores"),
            "selected": payload.get("selected") or [],
            "metadata": payload.get("metadata") or {},
            "thymos_state": thymos_state,
        }
        await self._sink.write(entry)
