# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Dimensional affective state for Thymos.

Three floats — valence, arousal, dominance — with homeostatic drift
toward a configurable baseline. Pure data; no I/O.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional


def _clamp(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


@dataclass(frozen=True)
class DimensionalState:
    valence: float = 0.0       # [-1, 1]
    arousal: float = 0.3       # [0, 1]
    dominance: float = 0.0     # [-1, 1]

    def clamped(self) -> "DimensionalState":
        return DimensionalState(
            valence=_clamp(self.valence, -1.0, 1.0),
            arousal=_clamp(self.arousal, 0.0, 1.0),
            dominance=_clamp(self.dominance, -1.0, 1.0),
        )

    def drift_toward(
        self,
        baseline: "DimensionalState",
        rate_per_s: float,
        dt: float,
    ) -> "DimensionalState":
        """Move every dimension toward `baseline` by `rate_per_s * dt`."""
        if dt <= 0 or rate_per_s <= 0:
            return self.clamped()
        # Damped first-order step: clamp the fraction so we can't overshoot.
        frac = min(1.0, float(rate_per_s) * float(dt))
        return DimensionalState(
            valence=self.valence + (baseline.valence - self.valence) * frac,
            arousal=self.arousal + (baseline.arousal - self.arousal) * frac,
            dominance=self.dominance + (baseline.dominance - self.dominance) * frac,
        ).clamped()

    def nudged(
        self,
        *,
        valence: float = 0.0,
        arousal: float = 0.0,
        dominance: float = 0.0,
    ) -> "DimensionalState":
        return replace(
            self,
            valence=_clamp(self.valence + valence, -1.0, 1.0),
            arousal=_clamp(self.arousal + arousal, 0.0, 1.0),
            dominance=_clamp(self.dominance + dominance, -1.0, 1.0),
        )

    def to_dict(self) -> dict[str, float]:
        return {
            "valence": float(self.valence),
            "arousal": float(self.arousal),
            "dominance": float(self.dominance),
        }
