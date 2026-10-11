# SPDX-License-Identifier: LicenseRef-CAL-0.4
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

    The level factor rises linearly with arousal, and the contrast gain
    sharpens the competition above baseline (adaptive gain;
    arousal-biased competition, Mather and Sutherland 2011).
    """

    def __init__(
        self,
        state_getter: Callable[[], DimensionalState],
        *,
        floor: float = 0.2,
        ceiling: float = 1.0,
        contrast_gain_max: float = 0.0,
        baseline_arousal: float = 0.3,
    ) -> None:
        if not 0.0 <= floor <= ceiling <= 1.0:
            raise ValueError(
                "floor and ceiling must satisfy 0 <= floor <= ceiling <= 1"
            )
        if contrast_gain_max < 0.0:
            raise ValueError("contrast_gain_max must be >= 0")
        if not 0.0 <= baseline_arousal < 1.0:
            raise ValueError(
                "baseline_arousal must satisfy 0 <= baseline_arousal < 1"
            )
        self._state_getter = state_getter
        self._floor = float(floor)
        self._ceiling = float(ceiling)
        self._contrast_gain_max = float(contrast_gain_max)
        self._baseline_arousal = float(baseline_arousal)

    def contrast_gain(self) -> float:
        a = float(self._state_getter().arousal)
        denom = 1.0 - self._baseline_arousal
        t = (a - self._baseline_arousal) / denom
        if t < 0.0:
            t = 0.0
        elif t > 1.0:
            t = 1.0
        return self._contrast_gain_max * t

    async def modulate(self, event: Event) -> float:
        state = self._state_getter()
        # Linear interpolation in [floor, ceiling] across arousal [0, 1].
        span = self._ceiling - self._floor
        return self._floor + span * float(state.arousal)
