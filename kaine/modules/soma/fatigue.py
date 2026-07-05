# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Fatigue accumulator for Soma.

Integrates prediction error over waking time with continuous decay.
Crossing the maintenance threshold triggers a ``soma.fatigue`` event
that ``hypnos-restructure`` uses as its emergent sleep-pressure signal
instead of a wall-clock timer.

Design constraints
------------------
- Zero raw-sense-data persistence: only the scalar fatigue value is
  persisted; no raw metric buffers.
- The accumulator is purely arithmetic — no torch dependency.
- Welfare-critical: represents KAINE's "right to offline maintenance".
"""
from __future__ import annotations

import logging
import time
from typing import Optional

log = logging.getLogger(__name__)


class FatigueAccumulator:
    """Continuous fatigue integrator with decay.

    Dynamics
    --------
    At each update with elapsed time ``dt`` (seconds) and current prediction
    error ``e``:

        F(t + dt) = max(0, F(t) + e * dt - decay * dt)

    During Hypnos sleep (``faster_decay`` flag), the decay rate is
    multiplied by ``faster_decay_factor`` so fatigue drops during
    rest.

    Threshold crossing
    ------------------
    When ``F`` crosses ``maintenance_threshold`` from below, the
    accumulator sets ``threshold_crossed = True`` and records that a
    ``soma.fatigue`` event should be published.  The flag is cleared
    on ``reset()``.  Repeated crossings (if fatigue is not reset
    promptly) do not re-raise the flag; the caller must publish once
    per crossing.
    """

    def __init__(
        self,
        *,
        decay_per_s: float = 0.01,
        maintenance_threshold: float = 100.0,
        faster_decay_factor: float = 3.0,
    ) -> None:
        if decay_per_s < 0:
            raise ValueError("decay_per_s must be >= 0")
        if maintenance_threshold <= 0:
            raise ValueError("maintenance_threshold must be positive")
        if faster_decay_factor < 1.0:
            raise ValueError("faster_decay_factor must be >= 1.0")

        self._decay_per_s = float(decay_per_s)
        self._threshold = float(maintenance_threshold)
        self._faster_decay_factor = float(faster_decay_factor)

        self._value: float = 0.0
        self._threshold_crossed: bool = False
        self._faster_decay: bool = False
        self._last_time: Optional[float] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def value(self) -> float:
        return self._value

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def threshold_crossed(self) -> bool:
        """True from the tick that value first exceeds threshold until reset()."""
        return self._threshold_crossed

    @property
    def faster_decay(self) -> bool:
        return self._faster_decay

    @faster_decay.setter
    def faster_decay(self, flag: bool) -> None:
        self._faster_decay = bool(flag)

    # ------------------------------------------------------------------
    # Core interface
    # ------------------------------------------------------------------

    def update(self, prediction_error: float, *, now: Optional[float] = None) -> bool:
        """Integrate one observation.

        Parameters
        ----------
        prediction_error:
            The current tick's L2 prediction error (≥ 0).
        now:
            Current monotonic time (seconds).  Defaults to
            ``time.monotonic()``.  Exposed for testing.

        Returns
        -------
        bool
            True on the tick that *value* first crosses *threshold*
            (i.e. a ``soma.fatigue`` event should be published).
        """
        if now is None:
            now = time.monotonic()

        if self._last_time is None:
            self._last_time = now
            return False

        dt = max(0.0, now - self._last_time)
        self._last_time = now

        e = max(0.0, float(prediction_error))
        decay_rate = self._decay_per_s
        if self._faster_decay:
            decay_rate *= self._faster_decay_factor

        new_value = max(0.0, self._value + e * dt - decay_rate * dt)
        was_below = self._value < self._threshold
        self._value = new_value

        newly_crossed = was_below and self._value >= self._threshold
        if newly_crossed:
            self._threshold_crossed = True
            log.info(
                "FatigueAccumulator: threshold %.2f crossed (value=%.4f)",
                self._threshold,
                self._value,
            )
        return newly_crossed

    def would_cross(self, prediction_error: float, *, now: Optional[float] = None) -> bool:
        """Non-mutating: would ``update(prediction_error, now)`` newly cross?

        Used by the developmental warm-up to log a single INFO line when the
        accumulator *would have* crossed the maintenance threshold on cold-start
        error alone but the dampened input held it below. Leaves all internal
        state untouched.
        """
        if now is None:
            now = time.monotonic()
        if self._last_time is None:
            return False
        dt = max(0.0, now - self._last_time)
        e = max(0.0, float(prediction_error))
        decay_rate = self._decay_per_s
        if self._faster_decay:
            decay_rate *= self._faster_decay_factor
        new_value = max(0.0, self._value + e * dt - decay_rate * dt)
        return self._value < self._threshold and new_value >= self._threshold

    def reset(self) -> None:
        """Reset fatigue to baseline at the end of a Hypnos offline cycle."""
        self._value = 0.0
        self._threshold_crossed = False
        self._last_time = None
        log.info("FatigueAccumulator: reset to baseline")

    # ------------------------------------------------------------------
    # Serialisation — scalar value only.
    # ------------------------------------------------------------------

    def state_dict(self) -> dict[str, float]:
        """Return the serialisable scalar state."""
        return {"value": self._value}

    def load_state_dict(self, state: dict) -> None:
        """Restore scalar state from a ``state_dict()`` snapshot."""
        if "value" in state:
            self._value = float(state["value"])
