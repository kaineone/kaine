# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import math
from collections import deque
from typing import Iterable, Protocol, runtime_checkable


@runtime_checkable
class AnomalyDetector(Protocol):
    def observe(self, hidden_state: Iterable[float]) -> float: ...


class RollingZScoreAnomaly:
    """Anomaly score = z-score of the current hidden state's L2 norm.

    Maintains a deque of recent norms and reports
    `|current - mean| / max(std, eps)`. Returns 0 until at least two
    samples have been observed (the first sample establishes the
    window, the second establishes a baseline std).
    """

    def __init__(self, window: int = 64, eps: float = 1e-6) -> None:
        if window <= 1:
            raise ValueError("window must be >= 2")
        if eps <= 0:
            raise ValueError("eps must be positive")
        self._norms: deque[float] = deque(maxlen=window)
        self._eps = float(eps)

    @property
    def window(self) -> int:
        return self._norms.maxlen  # type: ignore[return-value]

    def observe(self, hidden_state: Iterable[float]) -> float:
        values = list(hidden_state)
        norm = math.sqrt(sum(v * v for v in values))
        prior = list(self._norms)
        self._norms.append(norm)
        if len(prior) < 1:
            return 0.0
        mean = sum(prior) / len(prior)
        if len(prior) < 2:
            return 0.0
        variance = sum((x - mean) ** 2 for x in prior) / (len(prior) - 1)
        std = math.sqrt(variance)
        return abs(norm - mean) / max(std, self._eps)
