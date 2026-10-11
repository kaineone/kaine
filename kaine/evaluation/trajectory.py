# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Workspace trajectory recorder: writes every Syneidesis broadcast
as JSONL. Each row records the workspace graph of the broadcast
(members, salience scores, inhibition, metadata), never payloads or module state.
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
    ) -> None:
        super().__init__(bus)
        self._sink = sink

    async def handle(self, entry_id: str, payload: dict[str, Any]) -> None:
        # `payload` is the decoded workspace snapshot dict from
        # subscribe_workspace — tick_index / selected / salience_scores etc.
        payload = payload or {}

        raw_selected = payload.get("selected") or []
        selected: list[dict[str, Any]] = []
        for entry in raw_selected:
            member = _workspace_member(entry)
            if member is not None:
                selected.append(member)

        entry = {
            "entry_id": entry_id,
            "ts": datetime.now(timezone.utc).isoformat(),
            "tick_index": payload.get("tick_index"),
            "is_experiential": payload.get("is_experiential"),
            "inhibited": payload.get("inhibited"),
            "salience_scores": payload.get("salience_scores"),
            "selected": selected,
            "metadata": payload.get("metadata") or {},
        }
        await self._sink.write(entry)


def _workspace_member(entry: Any) -> dict[str, Any] | None:
    """Return the workspace-graph fields for a single selected member.

    Non-dict members are skipped. ``salience`` is converted to float when
    possible; otherwise it is recorded as ``None``. The original member
    timestamp is preserved unchanged. No payload is written.
    """
    if not isinstance(entry, dict):
        return None

    raw_salience = entry.get("salience")
    try:
        salience = float(raw_salience)  # type: ignore[arg-type]
    except Exception:
        salience = None

    return {
        "entry_id": entry.get("entry_id"),
        "source": entry.get("source"),
        "type": entry.get("type"),
        "salience": salience,
        "timestamp": entry.get("timestamp"),
        "causal_parent": entry.get("causal_parent"),
    }
