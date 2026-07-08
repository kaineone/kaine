# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Live oscillatory-ablation recorder.

Unlike the bus-subscribing observers, this one is driven directly by the cycle:
on each experiential tick the cognitive cycle runs the dual-path selection and
hands ``(primary, counterfactual)`` to this recorder's :meth:`record` (the
callable wired in as the cycle's ``ablation_recorder``). The primary is
byte-identical to the entity's actual selection; the counterfactual is its
coherence-off twin over the same tick. The recorder computes the content-free
``selection_delta`` — membership divergence, ranking shift, inhibition flip, and
top-score delta, never event content — and enqueues it to a daily-rotated JSONL
sink for the cross-record field-tier analysis (paper §6.4).

The recorder never raises into the cycle: a delta failure is logged and skipped,
and the cycle also wraps the call defensively.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from kaine.cycle.types import WorkspaceSnapshot
from kaine.evaluation.sink import AsyncJsonlSink
from kaine.workspace.syneidesis import selection_delta

log = logging.getLogger(__name__)


class AblationObserver:
    """Records the live oscillatory-ablation paired delta per experiential tick."""

    name = "ablation"

    def __init__(self, sink: AsyncJsonlSink) -> None:
        self._sink = sink

    def record(
        self, primary: WorkspaceSnapshot, counterfactual: WorkspaceSnapshot
    ) -> None:
        """Compute the content-free coherence-on vs coherence-off delta for one
        experiential tick and enqueue it. Called synchronously by the cycle."""
        try:
            delta = selection_delta(primary, counterfactual)
        except Exception:
            log.warning("ablation selection_delta failed; skipping tick", exc_info=True)
            return
        delta["ts"] = datetime.now(timezone.utc).isoformat()
        delta["tick_index"] = primary.tick_index
        self._sink.enqueue(delta)
