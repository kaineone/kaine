# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import logging
from typing import Any

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.coherence import CoherenceScorer
from kaine.workspace.strategies import SalienceStrategy

log = logging.getLogger(__name__)


class Syneidesis:
    """Global workspace selection per `docs/kaine-paper.md` §2.3.

    Each tick the cycle hands `select` a list of `(entry_id, Event)` and a
    context dict. `select` scores every event via the configured
    `SalienceStrategy`, picks the top-k by score, composes a
    `WorkspaceSnapshot`, and flags executive inhibition when the top
    score is below `publication_threshold`.
    """

    def __init__(
        self,
        strategy: SalienceStrategy,
        *,
        top_k: int = 5,
        publication_threshold: float = 0.35,
        coherence: CoherenceScorer | None = None,
    ) -> None:
        if top_k <= 0:
            raise ValueError("top_k must be positive")
        if not 0.0 <= publication_threshold <= 1.0:
            raise ValueError("publication_threshold must be in [0, 1]")
        self._strategy = strategy
        self._top_k = top_k
        self._threshold = publication_threshold
        # Oscillatory-binding coherence multiplier. None ⇒ the layer is
        # disabled and selection is bit-for-bit the pre-change behavior; the
        # coherence branch below is never entered.
        self._coherence = coherence

    @property
    def top_k(self) -> int:
        return self._top_k

    @property
    def publication_threshold(self) -> float:
        return self._threshold

    def set_top_k(self, k: int) -> None:
        if k <= 0:
            raise ValueError("top_k must be positive")
        self._top_k = k

    def set_publication_threshold(self, t: float) -> None:
        if not 0.0 <= t <= 1.0:
            raise ValueError("publication_threshold must be in [0, 1]")
        self._threshold = t

    async def select(
        self,
        events: list[tuple[str, Event]],
        context: dict[str, Any],
    ) -> WorkspaceSnapshot:
        tick_index = int(context.get("tick_index", 0))
        if not events:
            # Observe phases even with no events so windows stay aligned, then
            # return the empty inhibited snapshot (no coherence to report).
            if self._coherence is not None:
                phases = context.get("phases")
                if isinstance(phases, dict):
                    self._coherence.observe(phases)
            return WorkspaceSnapshot(
                tick_index=tick_index,
                selected_events=[],
                inhibited=True,
                salience_scores={},
            )

        scored: list[tuple[float, str, Event]] = []
        scores: dict[str, float] = {}
        for entry_id, event in events:
            try:
                value = await self._strategy.score(event, context)
            except Exception as exc:
                log.warning(
                    "salience strategy raised for %s/%s: %s",
                    event.source,
                    event.type,
                    exc,
                )
                value = 0.0
            scored.append((value, entry_id, event))
            scores[entry_id] = value

        # Oscillatory-binding coherence multiplier (additive, flagged). When
        # `self._coherence` is None the layer is disabled: this branch is
        # skipped entirely and selection below is bit-for-bit the pre-change
        # behavior, with no `metadata['coherence']` key written.
        metadata: dict[str, Any] = {}
        if self._coherence is not None and scored:
            phases = context.get("phases")
            if isinstance(phases, dict):
                self._coherence.observe(phases)
            cohort = sorted({event.source for (_, _, event) in scored})
            adjusted: list[tuple[float, str, Event]] = []
            for value, entry_id, event in scored:
                factor = self._coherence.factor_for_source(event.source, cohort)
                new_value = value * factor
                adjusted.append((new_value, entry_id, event))
                scores[entry_id] = new_value
            scored = adjusted
            # Coalition PLV for the selected (post-sort) cohort is written to
            # snapshot metadata so the sidecar coherence_observer can read it.
            metadata["coherence"] = self._coherence.plv(cohort)

        scored.sort(key=lambda item: item[0], reverse=True)
        top = scored[: self._top_k]
        top_score = top[0][0] if top else 0.0
        inhibited = top_score < self._threshold

        return WorkspaceSnapshot(
            tick_index=tick_index,
            selected_events=[(entry_id, event) for (_, entry_id, event) in top],
            inhibited=inhibited,
            salience_scores=scores,
            metadata=metadata,
        )
