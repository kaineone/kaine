# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Four drive accumulators for the affect module.

Each drive is a float in [0, 1] with a build rate (scaled by an
external signal), a decay rate, a threshold, a relief gain, and a
hysteresis band that prevents event storms when the value oscillates
near the threshold.

``curiosity`` is heterostatic interest: learning progress lp+ builds it,
it decays with no relief, and its crossing ends are neither the entity's
own success nor a failure (paper A.4).

For ``boredom`` the relief gain is a continuous rate per second
(relieve_rate); for ``social_drive`` and ``restlessness`` it is the
fraction removed per consummatory event (relieve).

Boredom also loses a fraction of its value on each engaging intent (relieve_fraction), the entity's own response (paper A.4).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


_DRIVE_DEFAULTS: dict[str, dict[str, float]] = {
    # Curiosity is heterostatic interest (paper A.4; Oudeyer and Kaplan 2007): learning
    # progress lp+ builds it, nothing relieves it, and it decays at delta_I. delta_I is
    # calibrated so that a sustained lp+ of 0.045, the progress that ended a crossing of
    # the earlier deficit form, holds it at its threshold: beta lp+ / (beta lp+ + delta_I)
    # = 0.7 gives delta_I = 0.05 * 0.045 * 0.3 / 0.7 = 0.00096 per second.
    "curiosity": {
        "build_rate": 0.05,
        "decay_rate": 0.00096,
        "threshold": 0.7,
        "relief_gain": 0.0,
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
    relief_gain: float = 0.5  # rate/s at full strength for boredom (curiosity has none); fraction per event for social/restlessness
    hysteresis_fraction: float = 0.9  # must drop below threshold * this to re-fire
    heterostatic: bool = False  # interest rather than a deficit: crossings re-arm without counting an end (paper A.4)
    _has_fired: bool = field(default=False, init=False, repr=False)
    # How this drive's crossings ended, re-armed below the hysteresis band by
    # the entity's own response (own_ends) or any other way (other_ends), the
    # success and failure counts for coping potential (paper A.4).
    own_ends: int = field(default=0, init=False)
    other_ends: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        if not math.isfinite(self.relief_gain) or not (0.0 <= self.relief_gain <= 1.0):
            raise ValueError("relief_gain must be finite and in [0, 1]")
        if not math.isfinite(self.build_rate) or self.build_rate < 0.0:
            raise ValueError("build_rate must be finite and >= 0")
        if not math.isfinite(self.decay_rate) or self.decay_rate < 0.0:
            raise ValueError("decay_rate must be finite and >= 0")
        if not math.isfinite(self.threshold) or not (0.0 < self.threshold <= 1.0):
            raise ValueError("threshold must be finite and in (0, 1]")

    def _step(self, value: float, u: float, dt: float) -> float:
        r = self.build_rate * u + self.decay_rate
        if r > 0.0:
            eq = self.build_rate * u / r
            return _clamp01(eq + (value - eq) * math.exp(-r * dt))
        return value

    def tick(self, dt: float, signal: float = 0.0, *, no_response_signal: Optional[float] = None) -> None:
        """Advance the drive by `dt` seconds with the given activity signal.

        `signal` ∈ [0, 1] modulates the build rate. The step is the exact
        solution of dD/dt = beta u (1 - D) - delta D, bounded to [0, 1] and
        independent of the update rate.

        `no_response_signal` is the build input the drive would have had without
        the entity's own response; when given and the actual signal is lower, a
        fall back below the band on this step is credited to the response only if
        the counterfactual step would not have fallen back.
        """
        if dt <= 0:
            return
        prev = self.value
        u = _clamp01(signal)
        self.value = self._step(prev, u, dt)
        own = False
        if no_response_signal is not None:
            no_response_u = _clamp01(no_response_signal)
            if u < no_response_u and self._has_fired and self.value < self.threshold * self.hysteresis_fraction:
                cf = self._step(prev, no_response_u, dt)
                if cf >= self.threshold * self.hysteresis_fraction:
                    own = True
        self._check_hysteresis(own=own)

    def relieve(self, strength: float, *, own: bool) -> None:
        """Apply a consummatory event of strength `strength` ∈ [0, 1].

        `own` says whether the entity's own response is the source of the relief.
        """
        c = _clamp01(strength)
        self.value = _clamp01(self.value * (1.0 - self.relief_gain * c))
        self._check_hysteresis(own=own)

    def relieve_fraction(self, fraction: float, *, own: bool) -> None:
        """Remove ``fraction`` of the drive's value in one event: D <- D (1 - fraction).

        ``fraction`` is clamped to [0, 1]. Unlike ``relieve`` it does not use
        ``relief_gain``, so a drive can have a second per-event relief channel with
        its own gain (boredom's engagement relief, paper A.4). `own` says whether
        the entity's own response is the source of the relief.
        """
        c = _clamp01(fraction)
        self.value = _clamp01(self.value * (1.0 - c))
        self._check_hysteresis(own=own)

    def relieve_rate(self, strength: float, dt: float, *, own: bool) -> None:
        """Apply continuous relief at rate ``relief_gain * strength`` per second.

        The exact solution of dD/dt = -relief_gain * strength * D is used,
        so the amount relieved is independent of the update rate.

        `own` says whether the entity's own response is the source of the relief.
        """
        c = _clamp01(strength)
        if dt > 0.0:
            self.value = _clamp01(self.value * math.exp(-self.relief_gain * c * dt))
        self._check_hysteresis(own=own)

    def _check_hysteresis(self, *, own: bool) -> None:
        # Reset hysteresis once below the re-fire band.
        if self._has_fired and self.value < self.threshold * self.hysteresis_fraction:
            self._has_fired = False
            if not self.heterostatic:
                if own:
                    self.own_ends += 1
                else:
                    self.other_ends += 1

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

    def power(self) -> float:
        """The Laplace-smoothed share of ended crossings that the entity's own response ended (paper A.4); 0.5 with no history."""
        return (self.own_ends + 1) / (self.own_ends + self.other_ends + 2)

    def reset(self) -> None:
        self.value = 0.0
        self._has_fired = False


@dataclass
class DriveCrossing:
    name: str
    value: float


class DriveSet:
    """Holds the affect module's four drives and surfaces crossings each tick."""

    def __init__(
        self,
        curiosity: Optional[Drive] = None,
        boredom: Optional[Drive] = None,
        social_drive: Optional[Drive] = None,
        restlessness: Optional[Drive] = None,
    ) -> None:
        self.curiosity = curiosity or Drive(name="curiosity", heterostatic=True, **_DRIVE_DEFAULTS["curiosity"])
        self.boredom = boredom or Drive(name="boredom", **_DRIVE_DEFAULTS["boredom"])
        self.social_drive = social_drive or Drive(name="social_drive", **_DRIVE_DEFAULTS["social_drive"])
        self.restlessness = restlessness or Drive(name="restlessness", **_DRIVE_DEFAULTS["restlessness"])

    def all(self) -> list[Drive]:
        return [self.curiosity, self.boredom, self.social_drive, self.restlessness]

    def deficits(self) -> list[Drive]:
        """The three homeostatic deficits; curiosity is heterostatic interest."""
        return [self.boredom, self.social_drive, self.restlessness]

    @classmethod
    def from_config(cls, section: Mapping[str, Mapping] | None) -> "DriveSet":
        """Build a DriveSet from the [affect.drives.*] nested tables.

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
            if name == "curiosity":
                kwargs["heterostatic"] = True
            drives[name] = Drive(**kwargs)
        return cls(**drives)

    def tick(
        self,
        dt: float,
        *,
        progress_signal: float = 0.0,
        activity_signal: float = 0.0,
        social_signal: float = 0.0,
        action_signal: float = 0.0,
        boredom_no_response_signal: Optional[float] = None,
    ) -> list[DriveCrossing]:
        """Advance every drive. Returns at most one crossing per drive.

        Signals semantics:
        - `progress_signal`: learning progress lp+ in [0, 1], which raises
          curiosity (heterostatic interest).
        - `activity_signal`: 1.0 means neither learning progress nor alert
          excess, which raises boredom.
        - `social_signal`: 1.0 once an operator interaction has been seen.
        - `action_signal`: 1.0 means LOW intent rate, which raises restlessness.
        - `boredom_no_response_signal`: boredom's build input without the
          entity's own learning progress (1 - exc), so a fall that only
          learning progress explains counts as the entity's own.
        - ``restlessness`` receives ``no_response_signal=1.0`` because its
          absence-of-action build input is 1.0 when the entity has not acted
          on its own.
        """
        self.curiosity.tick(dt, progress_signal)
        self.boredom.tick(dt, activity_signal, no_response_signal=boredom_no_response_signal)
        self.social_drive.tick(dt, social_signal)
        self.restlessness.tick(dt, action_signal, no_response_signal=1.0)
        crossings: list[DriveCrossing] = []
        for d in self.all():
            if d.consume_crossing():
                crossings.append(DriveCrossing(name=d.name, value=d.value))
        return crossings

    def relieve(self, name: str, strength: float, *, own: bool) -> None:
        """Relieve a named drive. Unknown names raise KeyError."""
        drive = getattr(self, name, None)
        if drive is None or not isinstance(drive, Drive):
            raise KeyError(name)
        drive.relieve(strength, own=own)

    def relieve_rate(self, name: str, strength: float, dt: float, *, own: bool) -> None:
        """Continuously relieve a named drive over ``dt`` seconds.

        Unknown names raise KeyError.
        """
        drive = getattr(self, name, None)
        if drive is None or not isinstance(drive, Drive):
            raise KeyError(name)
        drive.relieve_rate(strength, dt, own=own)

    def relieve_fraction(self, name: str, fraction: float, *, own: bool) -> None:
        """Relieve a named drive by a fraction of its current value.

        Unknown names raise KeyError.
        """
        drive = getattr(self, name, None)
        if drive is None or not isinstance(drive, Drive):
            raise KeyError(name)
        drive.relieve_fraction(fraction, own=own)

    def reset_all(self) -> None:
        for d in self.all():
            d.reset()

    def reset_deficits(self) -> None:
        """The sleep reset, paper A.4 item 4; interest carries through sleep like the learning-progress bins it reads."""
        for d in self.deficits():
            d.reset()

    def above_to_dict(self) -> dict[str, bool]:
        """Return whether each drive is at or above its threshold, for the welfare records (paper 6.2)."""
        # bool() keeps the payload JSON-serialisable when a value is a numpy float.
        return {d.name: bool(d.value >= d.threshold) for d in self.all()}

    def outcomes_to_dict(self) -> dict[str, dict[str, int]]:
        return {d.name: {"own": d.own_ends, "other": d.other_ends} for d in self.all()}

    def load_outcomes(self, data: Any) -> None:
        """Restore each drive's own and other end counters.

        Unknown drive names, non-dict entries, non-integer values, booleans
        and negative integers are ignored.
        """
        if not isinstance(data, dict):
            return
        for name, entry in data.items():
            if not isinstance(entry, dict):
                continue
            drive = getattr(self, name, None)
            if drive is None or not isinstance(drive, Drive):
                continue
            for key, target in (("own", "own_ends"), ("other", "other_ends")):
                value = entry.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    setattr(drive, target, value)

    def fired_to_dict(self) -> dict[str, bool]:
        """Return the crossing latch state for each drive.

        ``_has_fired`` is the hysteresis latch set by ``consume_crossing()``
        and cleared by ``_check_hysteresis()``; persisting it prevents a
        revived drive from re-firing on its first tick.
        """
        return {d.name: d._has_fired for d in self.all()}

    def load_fired(self, data: Any) -> None:
        """Restore the crossing latches.

        For each drive, a saved bool is used unchanged. For anything else,
        including older state saved before the latch was persisted, the latch
        is inferred from the restored value: a drive at or above its threshold
        must already have fired, because ``consume_crossing()`` fires on every
        tick at which the value is at or above the threshold with the latch
        clear; below the threshold the latch is inferred as clear.
        """
        for d in self.all():
            if isinstance(data, dict):
                value = data.get(d.name)
                if isinstance(value, bool):
                    d._has_fired = value
                    continue
            # Fallback for state saved before the latch was persisted: a drive
            # at or above its threshold must already have fired, because
            # consume_crossing() fires on every tick at which the value is at
            # or above the threshold with the latch clear.
            d._has_fired = d.value >= d.threshold

    def to_dict(self) -> dict[str, float]:
        return {d.name: d.value for d in self.all()}
