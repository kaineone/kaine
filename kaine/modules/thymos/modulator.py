# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""ThymosModulator implementation for Syneidesis.

Syneidesis ships `kaine.workspace.strategies.ThymosModulator` as a
Protocol with a static default. Phase 4 supplies the real implementation
that reads Thymos's current dimensional state and returns a salience
multiplier biased by arousal.
"""
from __future__ import annotations

from typing import Callable

from kaine.bus.schema import Event
from kaine.modules.thymos.state import DimensionalState


class StateModulator:
    """Arousal-weighted salience modulator.

    Higher arousal → broader attention (higher multiplier).
    Lower arousal → narrower attention (lower multiplier).
    Bounded to [0, 1] for Syneidesis's strategy product.
    """

    def __init__(
        self,
        state_getter: Callable[[], DimensionalState],
        *,
        floor: float = 0.2,
        ceiling: float = 1.0,
    ) -> None:
        if not 0.0 <= floor <= ceiling <= 1.0:
            raise ValueError(
                "floor and ceiling must satisfy 0 <= floor <= ceiling <= 1"
            )
        self._state_getter = state_getter
        self._floor = float(floor)
        self._ceiling = float(ceiling)

    async def modulate(self, event: Event) -> float:
        state = self._state_getter()
        # Linear interpolation in [floor, ceiling] across arousal [0, 1].
        span = self._ceiling - self._floor
        return self._floor + span * float(state.arousal)
