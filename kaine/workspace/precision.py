# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Precision-weighted selection helpers.

Precision is the inverse variance of a channel's prediction error
(Feldman and Friston, 2010). A source that publishes a habitually
noisy or surprising signal receives a lower precision and therefore
contributes less to salience competition.
"""

from __future__ import annotations

import math


class SourcePrecision:
    """Online per-source precision estimate used to weight salience scores."""

    def __init__(
        self,
        *,
        sample_weight: float = 0.02,
        warmup_samples: int = 20,
        bounds: tuple[float, float] = (0.5, 1.5),
        variance_floor: float = 1e-4,
        min_sources: int = 3,
    ) -> None:
        if not (0.0 < sample_weight <= 1.0):
            raise ValueError("sample_weight must satisfy 0 < sample_weight <= 1")
        if warmup_samples < 1:
            raise ValueError("warmup_samples must be >= 1")
        if not (0.0 < bounds[0] <= 1.0 <= bounds[1]):
            raise ValueError("bounds must satisfy 0 < bounds[0] <= 1 <= bounds[1]")
        if variance_floor <= 0.0:
            raise ValueError("variance_floor must be > 0")
        if min_sources < 1:
            raise ValueError("min_sources must be >= 1")

        self._sample_weight = float(sample_weight)
        self._warmup_samples = int(warmup_samples)
        self._bounds = (float(bounds[0]), float(bounds[1]))
        self._variance_floor = float(variance_floor)
        self._min_sources = int(min_sources)

        self._mean: dict[str, float] = {}
        self._var: dict[str, float] = {}
        self._count: dict[str, int] = {}

    def observe(self, source: str, intensity: float) -> None:
        x = float(intensity)
        count = self._count.get(source, 0)
        if count == 0:
            self._mean[source] = x
            self._var[source] = 0.0
            self._count[source] = 1
            return

        mean = self._mean[source]
        delta = x - mean
        mean += self._sample_weight * delta
        var = self._var[source]
        var = (1.0 - self._sample_weight) * (var + self._sample_weight * delta * delta)
        self._mean[source] = mean
        self._var[source] = var
        self._count[source] = count + 1

    def precision(self, source: str) -> float:
        var = self._var.get(source, 0.0)
        return 1.0 / (var + self._variance_floor)

    def weight(self, source: str) -> float:
        warmed = [src for src in self._count if self._count[src] >= self._warmup_samples]
        if len(warmed) < self._min_sources or source not in warmed:
            return 1.0

        log_precisions = [math.log(self.precision(src)) for src in warmed]
        log_mean = sum(log_precisions) / len(log_precisions)
        pi_ref = math.exp(log_mean)

        w = math.sqrt(self.precision(source) / pi_ref)
        lo, hi = self._bounds
        if w < lo:
            return lo
        if w > hi:
            return hi
        return w
