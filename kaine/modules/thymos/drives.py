# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Four drive accumulators for Thymos.

Each drive is a float in [0, 1] with a build rate (scaled by an
external signal), a decay rate, a threshold, and a hysteresis band
that prevents event storms when the value oscillates near the
threshold.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


@dataclass
class Drive:
    name: str
    value: float = 0.0
    build_rate: float = 0.05        # per second when signal = 1.0
    decay_rate: float = 0.02        # per second
    threshold: float = 0.7
    hysteresis_fraction: float = 0.9  # must drop below threshold * this to re-fire
    _has_fired: bool = field(default=False, init=False, repr=False)

    def tick(self, dt: float, signal: float = 0.0) -> None:
        """Advance the drive by `dt` seconds with the given activity signal.

        `signal` ∈ [0, 1] modulates the build rate. A signal of 1.0
        applies the full build rate; 0.0 means the drive only decays.
        """
        if dt <= 0:
            return
        s = _clamp01(signal)
        delta_up = self.build_rate * s * dt
        delta_down = self.decay_rate * dt
        self.value = _clamp01(self.value + delta_up - delta_down)
        # Reset hysteresis once below the re-fire band.
        if self._has_fired and self.value < self.threshold * self.hysteresis_fraction:
            self._has_fired = False

    def consume_crossing(self) -> bool:
        """Return True at most once per crossing of `threshold`.

        Hysteresis is enforced via `_has_fired` — once the drive fires,
        it must drop below `threshold * hysteresis_fraction` before
        firing again.
        """
        if self.value >= self.threshold and not self._has_fired:
            self._has_fired = True
            return True
        return False

    def reset(self) -> None:
        self.value = 0.0
        self._has_fired = False


@dataclass
class DriveCrossing:
    name: str
    value: float


class DriveSet:
    """Holds Thymos's four drives and surfaces crossings each tick."""

    def __init__(
        self,
        curiosity: Optional[Drive] = None,
        boredom: Optional[Drive] = None,
        social_drive: Optional[Drive] = None,
        restlessness: Optional[Drive] = None,
    ) -> None:
        self.curiosity = curiosity or Drive(name="curiosity")
        self.boredom = boredom or Drive(name="boredom")
        self.social_drive = social_drive or Drive(name="social_drive")
        self.restlessness = restlessness or Drive(name="restlessness")

    def all(self) -> list[Drive]:
        return [self.curiosity, self.boredom, self.social_drive, self.restlessness]

    def tick(
        self,
        dt: float,
        *,
        novelty_signal: float = 0.0,
        activity_signal: float = 0.0,
        social_signal: float = 0.0,
        action_signal: float = 0.0,
    ) -> list[DriveCrossing]:
        """Advance every drive. Returns at most one crossing per drive.

        Signals semantics:
        - `novelty_signal`: 1.0 means LOW novelty in recent broadcasts,
          which RAISES curiosity. The caller computes this as
          `1 - recent_novelty`.
        - `activity_signal`: 1.0 means LOW activity, which raises boredom.
          Caller computes as `1 - recent_activity`.
        - `social_signal`: rises with `time_since_last_interaction_s`,
          mapped to [0, 1] elsewhere by the caller.
        - `action_signal`: 1.0 means actions per minute below baseline,
          which raises restlessness.
        """
        self.curiosity.tick(dt, novelty_signal)
        self.boredom.tick(dt, activity_signal)
        self.social_drive.tick(dt, social_signal)
        self.restlessness.tick(dt, action_signal)
        crossings: list[DriveCrossing] = []
        for d in self.all():
            if d.consume_crossing():
                crossings.append(DriveCrossing(name=d.name, value=d.value))
        return crossings

    def reset_all(self) -> None:
        for d in self.all():
            d.reset()

    def to_dict(self) -> dict[str, float]:
        return {d.name: d.value for d in self.all()}
