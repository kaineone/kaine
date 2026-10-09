# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Four drive accumulators for Thymos.

Each drive is a float in [0, 1] with a build rate (scaled by an
external signal), a decay rate, a threshold, a relief gain, and a
hysteresis band that prevents event storms when the value oscillates
near the threshold.

For ``curiosity`` and ``boredom`` the relief gain is a continuous rate
per second at full strength (relieve_rate); for ``social_drive`` and
``restlessness`` it is the fraction removed per consummatory event
(relieve).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Mapping, Optional


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


_DRIVE_DEFAULTS: dict[str, dict[str, float]] = {
    "curiosity": {
        "build_rate": 0.05,
        "decay_rate": 0.0055,
        "threshold": 0.7,
        "relief_gain": 0.5,
    },
    "boredom": {
        "build_rate": 0.04,
        "decay_rate": 0.0045,
        "threshold": 0.7,
        "relief_gain": 0.3,
    },
    "social_drive": {
        "build_rate": 0.01,
        "decay_rate": 0.0011,
        "threshold": 0.7,
        "relief_gain": 0.8,
    },
    "restlessness": {
        "build_rate": 0.03,
        "decay_rate": 0.0033,
        "threshold": 0.7,
        "relief_gain": 0.5,
    },
}


@dataclass
class Drive:
    name: str
    value: float = 0.0
    build_rate: float = 0.05        # per second when signal = 1.0
    decay_rate: float = 0.0055      # per second
    threshold: float = 0.7
    relief_gain: float = 0.5  # rate/s at full strength for curiosity/boredom; fraction per event for social/restlessness
    hysteresis_fraction: float = 0.9  # must drop below threshold * this to re-fire
    _has_fired: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        if not (0.0 <= self.relief_gain <= 1.0):
            raise ValueError("relief_gain must be in [0, 1]")
        if self.build_rate < 0.0:
            raise ValueError("build_rate must be >= 0")
        if self.decay_rate < 0.0:
            raise ValueError("decay_rate must be >= 0")
        if not (0.0 < self.threshold <= 1.0):
            raise ValueError("threshold must be in (0, 1]")

    def tick(self, dt: float, signal: float = 0.0) -> None:
        """Advance the drive by `dt` seconds with the given activity signal.

        `signal` ∈ [0, 1] modulates the build rate. The step is the exact
        solution of dD/dt = beta u (1 - D) - delta D, bounded to [0, 1] and
        independent of the update rate.
        """
        if dt <= 0:
            return
        u = _clamp01(signal)
        r = self.build_rate * u + self.decay_rate
        if r > 0.0:
            eq = self.build_rate * u / r
            self.value = _clamp01(eq + (self.value - eq) * math.exp(-r * dt))
        self._check_hysteresis()

    def relieve(self, strength: float) -> None:
        """Apply a consummatory event of strength `strength` ∈ [0, 1]."""
        c = _clamp01(strength)
        self.value = _clamp01(self.value * (1.0 - self.relief_gain * c))
        self._check_hysteresis()

    def relieve_rate(self, strength: float, dt: float) -> None:
        """Apply continuous relief at rate ``relief_gain * strength`` per second.

        The exact solution of dD/dt = -relief_gain * strength * D is used,
        so the amount relieved is independent of the update rate.
        """
        c = _clamp01(strength)
        if dt > 0.0:
            self.value = _clamp01(self.value * math.exp(-self.relief_gain * c * dt))
        self._check_hysteresis()

    def _check_hysteresis(self) -> None:
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
        self.curiosity = curiosity or Drive(name="curiosity", **_DRIVE_DEFAULTS["curiosity"])
        self.boredom = boredom or Drive(name="boredom", **_DRIVE_DEFAULTS["boredom"])
        self.social_drive = social_drive or Drive(name="social_drive", **_DRIVE_DEFAULTS["social_drive"])
        self.restlessness = restlessness or Drive(name="restlessness", **_DRIVE_DEFAULTS["restlessness"])

    def all(self) -> list[Drive]:
        return [self.curiosity, self.boredom, self.social_drive, self.restlessness]

    @classmethod
    def from_config(cls, section: Mapping[str, Mapping] | None) -> "DriveSet":
        """Build a DriveSet from the [thymos.drives.*] nested tables.

        Missing keys keep the per-drive defaults; unknown keys raise ValueError.
        """
        if section is None:
            section = {}
        defaults: dict[str, dict[str, float]] = _DRIVE_DEFAULTS
        for name in section.keys():
            if name not in defaults:
                raise ValueError(f"Unknown drive {name!r}")
        known = {"build_rate", "decay_rate", "threshold", "relief_gain"}
        drives: dict[str, Drive] = {}
        for name, params in defaults.items():
            sub = section.get(name, {})
            for key in sub.keys():
                if key not in known:
                    raise ValueError(f"Unknown drive config key {key!r} for {name}")
            kwargs = {
                "name": name,
                "build_rate": float(sub.get("build_rate", params["build_rate"])),
                "decay_rate": float(sub.get("decay_rate", params["decay_rate"])),
                "threshold": float(sub.get("threshold", params["threshold"])),
                "relief_gain": float(sub.get("relief_gain", params["relief_gain"])),
            }
            drives[name] = Drive(**kwargs)
        return cls(**drives)

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
        - `novelty_signal`: 1.0 means LOW learning progress, which RAISES curiosity.
        - `activity_signal`: 1.0 means LOW alert rate, which raises boredom.
        - `social_signal`: 1.0 once an operator interaction has been seen.
        - `action_signal`: 1.0 means LOW intent rate, which raises restlessness.
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

    def relieve(self, name: str, strength: float) -> None:
        """Relieve a named drive. Unknown names raise KeyError."""
        drive = getattr(self, name, None)
        if drive is None or not isinstance(drive, Drive):
            raise KeyError(name)
        drive.relieve(strength)

    def relieve_rate(self, name: str, strength: float, dt: float) -> None:
        """Continuously relieve a named drive over ``dt`` seconds.

        Unknown names raise KeyError.
        """
        drive = getattr(self, name, None)
        if drive is None or not isinstance(drive, Drive):
            raise KeyError(name)
        drive.relieve_rate(strength, dt)

    def reset_all(self) -> None:
        for d in self.all():
            d.reset()

    def to_dict(self) -> dict[str, float]:
        return {d.name: d.value for d in self.all()}
