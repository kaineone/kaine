# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import logging
import math
from typing import Any, Sequence

from kaine.bus.schema import Event
from kaine.workspace.novelty import NoveltyTracker
from kaine.workspace.precision import SourcePrecision
from kaine.workspace.strategies import GoalScorer, ThymosModulator

log = logging.getLogger(__name__)


def _clamp(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _sigmoid(x: float) -> float:
    if x >= 0.0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    z = math.exp(x)
    return z / (1.0 + z)


def arousal_contrast(p: float, gain: float) -> float:
    """Adaptive gain logistic contrast.

    Adaptive gain (Aston-Jones and Cohen 2005; Eldar, Cohen and Niv 2013):
    a steeper logistic amplifies high priorities and suppresses low ones.
    The function is monotone, so it changes contrast, not ranking.
    At gain 0 it is the identity.
    """
    p = _clamp(float(p))
    if gain <= 1e-9:
        return p
    lo = _sigmoid(-0.5 * gain)
    hi = _sigmoid(0.5 * gain)
    return _clamp((_sigmoid(gain * (p - 0.5)) - lo) / (hi - lo))


class RuleBasedSalience:
    """Product-form salience with precision weighting and arousal contrast.

    priority = intensity * novelty * goal * precision weight;
    score = thymos level factor times the arousal contrast of the priority.

    With no precision tracker and contrast gain 0 this reduces to the original
    four-factor product.

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
        precision: SourcePrecision | None = None,
        downgraded_factors: Sequence[str] = (),
    ) -> None:
        self._novelty = novelty
        self._goal = goal_scorer
        self._thymos = thymos_modulator
        self._precision = precision
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

        weight = 1.0
        if self._precision is not None:
            weight = self._precision.weight(event.source)

        priority = _clamp(intensity * novelty * goal * weight)

        if self._precision is not None:
            self._precision.observe(event.source, intensity)

        getter = getattr(self._thymos, "contrast_gain", None)
        gain = float(getter()) if callable(getter) else 0.0

        return _clamp(thymos * arousal_contrast(priority, gain))
