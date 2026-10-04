# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Subjective-lived-time accumulators anchored per boot."""

from __future__ import annotations

import math
from typing import Callable


class LivedTimeAccumulator:
    """Accumulate subjective lived time since the previous step."""

    def __init__(
        self,
        clock_now: Callable[[], float | None] | None,
        paused_seconds: Callable[[], float] | None = None,
    ) -> None:
        self._clock_now = clock_now
        self._paused_seconds = paused_seconds
        self.clock_baseline: float | None = None
        self.paused_baseline: float | None = None

    def set_paused_source(self, paused_seconds: Callable[[], float] | None) -> None:
        """Replace the paused-time source and reset its baseline."""
        self._paused_seconds = paused_seconds
        self.paused_baseline = None

    def step(self) -> float:
        """Return the positive finite lived delta since the previous step.

        The first tick of an instance anchors the baseline and returns
        nothing, so downtime between boots never counts. A frozen clock
        (scale 0) produces no positive delta. Frozen (paused) time is
        measured by the cycle and subtracted exactly so a suspended span does
        not count toward maturation.
        """
        if self._clock_now is None:
            return 0.0

        try:
            now = self._clock_now()
            if now is None:
                return 0.0
            now = float(now)
        except Exception:
            return 0.0

        paused: float | None = None
        if self._paused_seconds is not None:
            try:
                paused = float(self._paused_seconds())
                if not math.isfinite(paused):
                    raise ValueError("non-finite paused time")
            except Exception:
                # Source failed: drop both baselines so the next good tick
                # re-anchors and adds nothing. The pauses inside this span are
                # unknown, so it must not count; this fails toward counting less.
                self.clock_baseline = None
                self.paused_baseline = None
                return 0.0

        if self.clock_baseline is None:
            self.clock_baseline = now
            self.paused_baseline = paused if paused is not None else 0.0
            return 0.0

        if paused is None:
            delta = now - self.clock_baseline
        else:
            if self.paused_baseline is None:
                self.paused_baseline = paused
            delta = (now - self.clock_baseline) - (paused - self.paused_baseline)

        self.clock_baseline = now
        if paused is not None:
            self.paused_baseline = paused

        if delta > 0 and math.isfinite(delta):
            return delta
        return 0.0


class TickAccumulator:
    """Accumulate lived ticks anchored per boot."""

    def __init__(self) -> None:
        self.baseline: int | None = None

    def step(self, tick_index: int) -> int:
        """Return the lived tick delta since the previous step."""
        if not isinstance(tick_index, int) or tick_index < 0:
            return 0

        if self.baseline is None or tick_index < self.baseline:
            self.baseline = tick_index
            return 0

        delta = tick_index - self.baseline
        self.baseline = tick_index
        return delta
