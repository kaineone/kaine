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
    reference_count: int = 0


@runtime_checkable
class DriftDetector(Protocol):
    def observe(self, sources: Iterable[str]) -> DriftResult: ...
    def reset(self) -> None: ...


class SourceDistributionDrift:
    """v2 drift detector: symmetric KL divergence between recent and
    historical reference source-name distributions.

    "Sources" here are the `source` fields of selected events in a
    workspace broadcast. Eidolon feeds them in batches (one batch per
    broadcast). The detector keeps a deque-of-batches as the recent
    window. The reference distribution is formed from batches that
    have left the recent window, so the reference and recent
    distributions are disjoint. The score is kept at 0.0 until the
    reference has accumulated at least `window` evicted broadcasts.
    """

    def __init__(self, window: int = 100, epsilon: float = 1e-3) -> None:
        if window <= 0:
            raise ValueError("window must be positive")
        if epsilon <= 0:
            raise ValueError("epsilon must be positive")
        self._window = int(window)
        self._epsilon = float(epsilon)
        self._recent: deque[Counter[str]] = deque(maxlen=window)
        self._reference: Counter[str] = Counter()
        self._reference_batches: int = 0
        self._total_events: int = 0

    @property
    def recent_count(self) -> int:
        return sum(sum(c.values()) for c in self._recent)

    @property
    def historical_count(self) -> int:
        return self._total_events

    @property
    def reference_count(self) -> int:
        return sum(self._reference.values())

    def reset(self) -> None:
        self._recent.clear()
        self._reference.clear()
        self._reference_batches = 0
        self._total_events = 0

    def observe(self, sources: Iterable[str]) -> DriftResult:
        batch: Counter[str] = Counter()
        for src in sources:
            batch[str(src)] += 1

        self._total_events += sum(batch.values())

        if len(self._recent) == self._window:
            oldest = self._recent[0]
            self._reference.update(oldest)
            self._reference_batches += 1

        self._recent.append(batch)
        return self._compute()

    def _compute(self) -> DriftResult:
        recent_total = Counter()
        for c in self._recent:
            recent_total.update(c)

        rec_total = sum(recent_total.values())
        ref_total = sum(self._reference.values())

        if (
            not recent_total
            or self._reference_batches < self._window
            or not self._reference
        ):
            return DriftResult(
                score=0.0,
                recent_count=rec_total,
                historical_count=self._total_events,
                reference_count=ref_total,
            )

        all_keys = set(recent_total) | set(self._reference)
        n_keys = len(all_keys)
        eps = self._epsilon

        score = 0.0
        per_key: dict[str, float] = {}
        for key in all_keys:
            p = (recent_total.get(key, 0) + eps) / (rec_total + eps * n_keys)
            q = (self._reference.get(key, 0) + eps) / (ref_total + eps * n_keys)
            contribution = p * math.log(p / q) + q * math.log(q / p)
            score += contribution
            per_key[key] = abs(contribution)

        top = tuple(
            k for k, _ in sorted(per_key.items(), key=lambda t: t[1], reverse=True)[:5]
        )

        return DriftResult(
            score=score,
            recent_count=rec_total,
            historical_count=self._total_events,
            reference_count=ref_total,
            top_drifted_sources=top,
        )
