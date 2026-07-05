# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import math
from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Iterable, Protocol, runtime_checkable


@dataclass(frozen=True)
class DriftResult:
    score: float
    recent_count: int
    historical_count: int
    top_drifted_sources: tuple[str, ...] = field(default_factory=tuple)


@runtime_checkable
class DriftDetector(Protocol):
    def observe(self, sources: Iterable[str]) -> DriftResult: ...
    def reset(self) -> None: ...


class SourceDistributionDrift:
    """v1 drift detector: symmetric KL divergence between recent and
    cumulative source-name distributions.

    "Sources" here are the `source` fields of selected events in a
    workspace broadcast. Eidolon feeds them in batches (one batch per
    broadcast). The detector keeps a deque-of-batches as the recent
    window (so one batch is one snapshot of "what was salient this
    cycle"), and a single Counter for all-time.
    """

    def __init__(self, window: int = 100, epsilon: float = 1e-3) -> None:
        if window <= 0:
            raise ValueError("window must be positive")
        if epsilon <= 0:
            raise ValueError("epsilon must be positive")
        self._window = int(window)
        self._epsilon = float(epsilon)
        self._recent: deque[Counter[str]] = deque(maxlen=window)
        self._cumulative: Counter[str] = Counter()

    @property
    def recent_count(self) -> int:
        return sum(sum(c.values()) for c in self._recent)

    @property
    def historical_count(self) -> int:
        return sum(self._cumulative.values())

    def reset(self) -> None:
        self._recent.clear()
        self._cumulative.clear()

    def observe(self, sources: Iterable[str]) -> DriftResult:
        batch: Counter[str] = Counter()
        for src in sources:
            s = str(src)
            batch[s] += 1
            self._cumulative[s] += 1
        self._recent.append(batch)
        return self._compute()

    def _compute(self) -> DriftResult:
        recent_total = Counter()
        for c in self._recent:
            recent_total.update(c)
        # Need both distributions to compare.
        if not recent_total or not self._cumulative:
            return DriftResult(
                score=0.0,
                recent_count=self.recent_count,
                historical_count=self.historical_count,
            )
        all_keys = set(recent_total) | set(self._cumulative)
        rec_total = sum(recent_total.values())
        cum_total = sum(self._cumulative.values())
        eps = self._epsilon
        score = 0.0
        per_key: dict[str, float] = {}
        for key in all_keys:
            p = (recent_total.get(key, 0) + eps) / (rec_total + eps * len(all_keys))
            q = (self._cumulative.get(key, 0) + eps) / (cum_total + eps * len(all_keys))
            contribution = p * math.log(p / q) + q * math.log(q / p)
            score += contribution
            per_key[key] = abs(contribution)
        top = tuple(
            k for k, _ in sorted(per_key.items(), key=lambda t: t[1], reverse=True)[:5]
        )
        return DriftResult(
            score=score,
            recent_count=rec_total,
            historical_count=cum_total,
            top_drifted_sources=top,
        )
