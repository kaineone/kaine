# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The workspace-off (fan-in prompt-assembler) conditioning path.

The ablation's control arm gives the language organ the SAME underlying
information as the workspace-on arm — all current module outputs — but without
competitive selection, threshold gating, or broadcast-as-shared-state. This
module builds that flat control snapshot.

A ``WorkspaceSnapshot`` is the object the language organ's ``ContextAssembler``
renders (``lingua/context.py``); the on-arm hands it the competitively-selected
coalition, the off-arm hands it the flat snapshot built here. Because the SAME
``ContextAssembler`` and the SAME rendering budget (``max_events``,
``char_budget``) apply to both arms, the contrast is selection-structure, not
information-quantity — the fair-null discipline the experiment requires.

Fairness details:
* ``selected_events`` carries every candidate event (no top-k truncation), so the
  control is not starved relative to the on-arm coalition.
* ``salience_scores`` carries each event's RAW published salience, not a
  competitively-computed score, so the flat arm ranks by the module's own signal
  strength rather than by the workspace's precision-weighted competition.
* ``inhibited`` is always ``False``: the control has no threshold gate. (Whether
  the on-arm inhibits is part of what the ablation measures.)
"""
from __future__ import annotations

from typing import Sequence

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot


def flat_fan_in_snapshot(
    tick_index: int,
    candidates: Sequence[tuple[str, Event]],
    *,
    is_experiential: bool = True,
) -> WorkspaceSnapshot:
    """Build the flat control snapshot from all of a tick's candidate events.

    ``candidates`` is the same ``(entry_id, Event)`` batch the workspace-on arm
    hands to Syneidesis for competitive selection; here every one is retained,
    with the event's own ``salience`` as its score, so the language organ sees
    all module outputs ranked by raw signal strength rather than by competition.
    No scoring, no top-k, no inhibition, no broadcast.
    """
    events = list(candidates)
    salience_scores = {entry_id: float(ev.salience) for entry_id, ev in events}
    return WorkspaceSnapshot(
        tick_index=tick_index,
        selected_events=events,
        inhibited=False,
        is_experiential=is_experiential,
        salience_scores=salience_scores,
        metadata={"conditioning": "flat_fan_in", "candidate_count": len(events)},
    )
