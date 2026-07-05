# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import math
from collections import deque
from typing import Protocol, runtime_checkable


@runtime_checkable
class SceneHabituator(Protocol):
    def observe(self, embedding: list[float]) -> float: ...
    def reset(self) -> None: ...


class RollingMeanHabituator:
    """Habituation rises as recent frames stabilize around a mean.

    Maintains a rolling window of recent embeddings. Score is
    `1 / (1 + mean_pairwise_l2)`, where the L2 distance is averaged
    against the running mean of the window. Static scene → distances
    collapse to 0 → habituation → 1. Highly varied scene → distances
    rise → habituation → 0.
    """

    def __init__(self, window: int = 16) -> None:
        if window <= 1:
            raise ValueError("window must be >= 2")
        self._window = int(window)
        self._frames: deque[list[float]] = deque(maxlen=window)

    @property
    def window(self) -> int:
        return self._window

    def observe(self, embedding: list[float]) -> float:
        vec = [float(v) for v in embedding]
        self._frames.append(vec)
        if len(self._frames) < 2:
            return 1.0  # nothing to compare against — call it fully habituated
        dim = len(vec)
        mean = [0.0] * dim
        for f in self._frames:
            for i in range(dim):
                mean[i] += f[i]
        for i in range(dim):
            mean[i] /= len(self._frames)
        total = 0.0
        for f in self._frames:
            total += math.sqrt(sum((f[i] - mean[i]) ** 2 for i in range(dim)))
        avg_distance = total / len(self._frames)
        habituation = 1.0 / (1.0 + avg_distance)
        return max(0.0, min(1.0, habituation))

    def reset(self) -> None:
        self._frames.clear()
