# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import logging
from typing import Any, Sequence

from kaine.bus.schema import Event
from kaine.workspace.novelty import NoveltyTracker
from kaine.workspace.strategies import GoalScorer, ThymosModulator

log = logging.getLogger(__name__)


def _clamp(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


class RuleBasedSalience:
    """v1 product-form salience: intensity * novelty * goal * thymos.

    Each term lives in [0, 1]; the product is clamped to [0, 1] to guard
    against floating-point overshoot.

    A degraded-mode warning is emitted at construction ONLY for factors named in
    ``downgraded_factors`` — the factors the operator deliberately set to the
    dev-only static fallback *when that factor ships real by default*. The cycle
    assembly (``make_salience_factors``) computes this by comparing the selected
    source against each factor's shipped default, so a factor sitting on its
    shipped static baseline (e.g. the STAGED goal factor) does NOT warn — only a
    genuine downgrade does. Passing nothing (the common/test case) is silent.
    """

    def __init__(
        self,
        novelty: NoveltyTracker,
        goal_scorer: GoalScorer,
        thymos_modulator: ThymosModulator,
        *,
        downgraded_factors: Sequence[str] = (),
    ) -> None:
        self._novelty = novelty
        self._goal = goal_scorer
        self._thymos = thymos_modulator
        # Announce a deliberate downgrade (a factor that ships REAL by default but
        # was set to the static negative control) so it is visible in operator
        # logs rather than silent. Shipped defaults (thymos=real, goal=staged
        # static) pass an empty list here, so a normal boot stays quiet.
        downgraded = list(downgraded_factors)
        if downgraded:
            log.warning(
                "RuleBasedSalience: %d salience factor(s) deliberately downgraded "
                "to the dev-only static fallback (negative control) — live salience "
                "is degraded toward intensity × novelty. Downgraded: %s",
                len(downgraded),
                "; ".join(downgraded),
            )

    async def score(self, event: Event, context: dict[str, Any]) -> float:
        intensity = _clamp(event.salience)
        novelty = _clamp(self._novelty.observe(event))
        goal = _clamp(await self._goal.relevance(event))
        thymos = _clamp(await self._thymos.modulate(event))
        return _clamp(intensity * novelty * goal * thymos)
