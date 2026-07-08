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

        return self._compose(tick_index, scored, scores, metadata)

    def _compose(
        self,
        tick_index: int,
        scored: list[tuple[float, str, Event]],
        scores: dict[str, float],
        metadata: dict[str, Any],
    ) -> WorkspaceSnapshot:
        """Sort the scored candidates, take the top-k, flag inhibition, compose.

        The single canonical tail shared by :meth:`select` and :meth:`select_dual`
        so the two never drift.
        """
        ranked = sorted(scored, key=lambda item: item[0], reverse=True)
        top = ranked[: self._top_k]
        top_score = top[0][0] if top else 0.0
        return WorkspaceSnapshot(
            tick_index=tick_index,
            selected_events=[(entry_id, event) for (_, entry_id, event) in top],
            inhibited=top_score < self._threshold,
            salience_scores=scores,
            metadata=metadata,
        )

    async def select_dual(
        self,
        events: list[tuple[str, Event]],
        context: dict[str, Any],
    ) -> tuple[WorkspaceSnapshot, WorkspaceSnapshot | None]:
        """Return ``(primary, counterfactual)`` for the live oscillatory ablation.

        The primary is the configured selection; the counterfactual is its twin
        with the coherence layer forced off (precision multiplier one). BOTH are
        computed over the SAME events in ONE scoring pass, with phases observed
        exactly once, so the primary is byte-identical to :meth:`select` and the
        counterfactual differs from it only by the layer — the paired,
        same-stimulus contrast the ablation needs, recovered live without replaying
        a stimulus.

        Returns ``(primary, None)`` when the layer is already disabled: there is
        nothing to ablate live, because the entity already IS the baseline.
        """
        if self._coherence is None:
            return await self.select(events, context), None

        tick_index = int(context.get("tick_index", 0))
        if not events:
            # Mirror select()'s empty path: observe once to keep windows aligned,
            # then two empty inhibited snapshots (on == off with no candidates).
            phases = context.get("phases")
            if isinstance(phases, dict):
                self._coherence.observe(phases)
            return (
                WorkspaceSnapshot(
                    tick_index=tick_index,
                    selected_events=[],
                    inhibited=True,
                    salience_scores={},
                ),
                WorkspaceSnapshot(
                    tick_index=tick_index,
                    selected_events=[],
                    inhibited=True,
                    salience_scores={},
                ),
            )

        # Score every candidate ONCE — the shared base for both arms.
        scored_raw: list[tuple[float, str, Event]] = []
        scores_off: dict[str, float] = {}
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
            scored_raw.append((value, entry_id, event))
            scores_off[entry_id] = value

        # Observe phases ONCE, then apply the coherence factor for the ON arm —
        # the identical order select() uses, so the primary matches it exactly.
        phases = context.get("phases")
        if isinstance(phases, dict):
            self._coherence.observe(phases)
        cohort = sorted({event.source for (_, _, event) in scored_raw})
        scored_on: list[tuple[float, str, Event]] = []
        scores_on: dict[str, float] = {}
        for value, entry_id, event in scored_raw:
            new_value = value * self._coherence.factor_for_source(event.source, cohort)
            scored_on.append((new_value, entry_id, event))
            scores_on[entry_id] = new_value

        primary = self._compose(
            tick_index, scored_on, scores_on, {"coherence": self._coherence.plv(cohort)}
        )
        counterfactual = self._compose(tick_index, scored_raw, scores_off, {})
        return primary, counterfactual


def selection_delta(on: WorkspaceSnapshot, off: WorkspaceSnapshot) -> dict[str, Any]:
    """Content-free numeric comparison of a coherence-on vs coherence-off tick.

    Carries only aggregate numbers — membership divergence of the selected
    coalition, mean ranking shift over the items both arms selected, inhibition
    flip, and top-score delta — never event content or ids. This is what the live
    oscillatory ablation logs per experiential tick and pools across records.
    """
    on_ids = [entry_id for entry_id, _ in on.selected_events]
    off_ids = [entry_id for entry_id, _ in off.selected_events]
    on_set, off_set = set(on_ids), set(off_ids)
    union = on_set | off_set
    shared = on_set & off_set
    selection_divergence_fraction = (
        (len(union) - len(shared)) / len(union) if union else 0.0
    )
    on_rank = {entry_id: i for i, entry_id in enumerate(on_ids)}
    off_rank = {entry_id: i for i, entry_id in enumerate(off_ids)}
    k = max(len(on_ids), len(off_ids), 1)
    mean_ranking_divergence = (
        sum(abs(on_rank[e] - off_rank[e]) for e in shared) / (len(shared) * k)
        if shared
        else 0.0
    )
    on_top = max(on.salience_scores.values(), default=0.0)
    off_top = max(off.salience_scores.values(), default=0.0)
    return {
        "selection_divergence_fraction": float(selection_divergence_fraction),
        "mean_ranking_divergence": float(mean_ranking_divergence),
        "inhibited_on": bool(on.inhibited),
        "inhibited_off": bool(off.inhibited),
        "inhibited_flip": bool(on.inhibited) != bool(off.inhibited),
        "top_score_on": float(on_top),
        "top_score_off": float(off_top),
        "top_score_delta": float(on_top - off_top),
        "n_candidates": len(on.salience_scores),
    }
