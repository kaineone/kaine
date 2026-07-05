# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import math
from typing import Iterable, Optional, Protocol, runtime_checkable


def _dot(a: Iterable[float], b: Iterable[float]) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b))


def _norm(v: Iterable[float]) -> float:
    return math.sqrt(sum(float(x) * float(x) for x in v))


def cosine_similarity(a: Iterable[float], b: Iterable[float]) -> float:
    """Cosine similarity in [-1, 1]; returns 0 when either is zero-vector."""
    a_list = list(a)
    b_list = list(b)
    na, nb = _norm(a_list), _norm(b_list)
    if na == 0 or nb == 0:
        return 0.0
    return _dot(a_list, b_list) / (na * nb)


@runtime_checkable
class ChangeDetector(Protocol):
    def observe(self, embedding: list[float]) -> float: ...
    def reset(self) -> None: ...


class CosineChangeDetector:
    """change_score = 1 - cosine_similarity(previous, current).

    First call returns 0.0 (no previous frame). Identical consecutive
    frames return 0.0. Orthogonal frames return 1.0. Anti-correlated
    frames return 2.0.
    """

    def __init__(self) -> None:
        self._previous: Optional[list[float]] = None

    def observe(self, embedding: list[float]) -> float:
        current = [float(v) for v in embedding]
        if self._previous is None:
            self._previous = current
            return 0.0
        sim = cosine_similarity(self._previous, current)
        self._previous = current
        # cosine_similarity returns in [-1, 1]; change in [0, 2]
        return max(0.0, 1.0 - sim)

    def reset(self) -> None:
        self._previous = None
