# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The pooled arm of the workspace-mediation development harness.

Every candidate event enters the broadcast context weighted by its own
salience. There is no scoring, no top-k selection, no access gate, and no
inhibition. The arm differs from workspace-on only in how the context is
formed; the same candidate set is delivered to both arms.
"""
from __future__ import annotations

from typing import Sequence

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot


def pooled_snapshot(
    tick_index: int,
    candidates: Sequence[tuple[str, Event]],
) -> WorkspaceSnapshot:
    """Build the pooled control snapshot from all candidates at one tick.

    Each candidate is retained, its score is its own published salience, and
    the snapshot is never inhibited. Metadata records the arm name and the
    candidate count; it does not contain an access threshold, so
    BroadcastContext adopts every member.
    """
    events = list(candidates)
    salience_scores = {entry_id: float(ev.salience) for entry_id, ev in events}
    return WorkspaceSnapshot(
        tick_index=tick_index,
        selected_events=events,
        inhibited=False,
        is_experiential=True,
        salience_scores=salience_scores,
        metadata={"arm": "pooled", "candidate_count": len(events)},
    )
