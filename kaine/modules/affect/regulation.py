# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Emotion-regulation policies for the affect module.

The process model of emotion regulation (Gross 1998) orders regulatory
processes from attentional deployment early in an emotional episode to
response modulation late. KAINE's monitor implements the three-tier
rule of paper §3.5 and appendix A.5: when affective intensity stays
above theta_E while the appraisal is negative, an episode clock begins.
After Delta_st entity seconds, each further window of Delta_R seconds
emits one activation, escalating through Tier 1 (attentional
deployment), Tier 2 (reappraisal), and Tier 3 (sleep request). The
``PassiveDecay`` off arm leaves regulation to the dimensional state's
homeostatic drift toward baseline and serves as the default policy.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Iterable, Optional, Protocol, runtime_checkable

from kaine.modules.affect.state import DimensionalState

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegulationAdjustment:
    valence: float = 0.0
    arousal: float = 0.0
    dominance: float = 0.0


@runtime_checkable
class RegulationPolicy(Protocol):
    async def suggest(self, state: DimensionalState) -> RegulationAdjustment: ...


class PassiveDecay:
    """No-op regulation: returns zero adjustment every tick.

    The homeostatic drift toward baseline in DimensionalState is the
    sole regulation at this stage. A one-time debug log is emitted on
    first use so the passive policy is visible in traces rather than
    silently doing nothing.
    """

    def __init__(self) -> None:
        self._logged_once = False

    async def suggest(self, state: DimensionalState) -> RegulationAdjustment:
        if not self._logged_once:
            log.debug(
                "affect regulation: PassiveDecay active - "
                "no active regulation policy; homeostatic drift is the sole regulator"
            )
            self._logged_once = True
        return RegulationAdjustment()


@dataclass(frozen=True)
class RegulationConfig:
    """Hyper-parameters for ``ThreeTierRegulation``."""

    set_point: float = 0.5
    reappraisal_fraction: float = 0.5
    selection_bias: float = 0.2
    bias_decay_s: float = 20.0
    sustain_window_s: float = 30.0

    def __post_init__(self) -> None:
        def _require(field: str, ok: bool) -> None:
            if not ok:
                raise ValueError(f"RegulationConfig.{field}")

        _require("set_point", math.isfinite(self.set_point) and self.set_point >= 0)
        _require(
            "reappraisal_fraction",
            math.isfinite(self.reappraisal_fraction)
            and 0 <= self.reappraisal_fraction <= 1,
        )
        _require(
            "selection_bias",
            math.isfinite(self.selection_bias) and 0 <= self.selection_bias <= 1,
        )
        _require("bias_decay_s", math.isfinite(self.bias_decay_s) and self.bias_decay_s > 0)
        _require(
            "sustain_window_s",
            math.isfinite(self.sustain_window_s) and self.sustain_window_s > 0,
        )


@dataclass(frozen=True)
class RegulationActivation:
    """Record emitted by ``ThreeTierRegulation.update`` on a new tier window."""

    tier: int
    episode_s: float
    intensity: float
    target_source: Optional[str]


class ThreeTierRegulation:
    """Three-tier emotion-regulation monitor (paper §3.5 and A.5)."""

    def __init__(self, config: Optional[RegulationConfig] = None) -> None:
        self._config = config if config is not None else RegulationConfig()
        self._episode_start: Optional[float] = None
        self._last_window: int = 0
        self._mass: dict[str, float] = {}
        self._reappraised: bool = False

    @property
    def config(self) -> RegulationConfig:
        return self._config

    @property
    def in_episode(self) -> bool:
        return self._episode_start is not None

    @staticmethod
    def intensity(valence: float, arousal: float, baseline_arousal: float) -> float:
        """Affective intensity as the larger of |v| and a - a0."""
        return max(abs(valence), arousal - baseline_arousal)

    async def suggest(self, state: DimensionalState) -> RegulationAdjustment:
        """The tiers act through ``update``, so this protocol method is a no-op."""
        return RegulationAdjustment()

    def update(
        self, *, now: float, intensity: float, negative: bool
    ) -> Optional[RegulationActivation]:
        """Evaluate the episode rule and emit at most one activation per call."""
        if not (math.isfinite(now) and math.isfinite(intensity)):
            return None

        if intensity >= self._config.set_point and negative:
            if self._episode_start is None:
                self._episode_start = now
                self._last_window = 0
                self._mass.clear()
                self._reappraised = False

            elapsed = now - self._episode_start
            k = math.floor(elapsed / self._config.sustain_window_s)
            if k >= 1 and k > self._last_window:
                self._last_window = k
                tier = min(k, 3)
                target = self.target_source() if tier == 1 else None
                return RegulationActivation(
                    tier=tier,
                    episode_s=elapsed,
                    intensity=intensity,
                    target_source=target,
                )
            return None

        self._end_episode()
        return None

    def observe_coalition(
        self, contributions: Iterable[tuple[str, float]], *, negative: bool
    ) -> None:
        """Accumulate intensity mass from negatively appraised coalitions."""
        if not self.in_episode or not negative:
            return
        for source, value in contributions:
            if math.isfinite(value) and value >= 0:
                self._mass[source] = self._mass.get(source, 0.0) + value

    def target_source(self) -> Optional[str]:
        """Source with the largest accumulated intensity mass."""
        if not self._mass:
            return None
        max_mass = max(self._mass.values())
        if max_mass <= 0:
            return None
        return min(source for source, mass in self._mass.items() if mass == max_mass)

    def take_reappraisal(self) -> bool:
        """Return True once per running episode for the reappraisal tier."""
        if not self.in_episode:
            return False
        if self._reappraised:
            return False
        self._reappraised = True
        return True

    def reset(self) -> None:
        """End any running episode and clear its transient state."""
        self._end_episode()

    def _end_episode(self) -> None:
        self._episode_start = None
        self._last_window = 0
        self._mass.clear()
        self._reappraised = False
