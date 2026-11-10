# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""ExemplarBuffer: bounded per-modality exemplar storage for identity learning."""

from __future__ import annotations

import math
from typing import Any


def _dot(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def _norm(a: list[float]) -> float:
    return math.sqrt(sum(x * x for x in a))


def _cos_sim(a: list[float], b: list[float]) -> float:
    na = _norm(a)
    nb = _norm(b)
    if na == 0.0 or nb == 0.0:
        return 0.0
    return _dot(a, b) / (na * nb)


def _mean(vecs: list[list[float]]) -> list[float]:
    if not vecs:
        return []
    dim = len(vecs[0])
    out = [0.0] * dim
    for v in vecs:
        for i in range(dim):
            out[i] += v[i]
    n = len(vecs)
    return [x / n for x in out]


def _normalize(v: list[float]) -> list[float]:
    n = _norm(v)
    if n == 0.0:
        return list(v)
    return [x / n for x in v]


class ExemplarBuffer:
    def __init__(
        self,
        dim: int,
        *,
        max_size: int = 20,
        consolidation_threshold: int = 5,
        diversity_floor: float = 0.01,
        ema_decay: float = 0.9,
        reliability_floor: float = 0.3,
    ) -> None:
        self.dim = dim
        self.max_size = max_size
        self.consolidation_threshold = consolidation_threshold
        self.diversity_floor = diversity_floor
        self.ema_decay = ema_decay
        self.reliability_floor = reliability_floor

        self._items: list[tuple[list[float], Any]] = []
        self._consolidated: bool = False
        self._centroid: list[float] | None = None

    # ------------------------------------------------------------------ #
    # core API
    # ------------------------------------------------------------------ #
    def add(self, embedding: list[float], *, timestamp: float | None = None) -> None:
        emb = [float(x) for x in embedding]

        # Evict least-diverse exemplar if buffer is full.
        if len(self._items) >= self.max_size and self.max_size > 0:
            self._evict(emb)

        self._items.append((emb, timestamp))

        if not self._consolidated:
            # Consolidation check.
            if len(self._items) >= self.consolidation_threshold:
                centroid = _mean([e for e, _ in self._items])
                var = self._intra_variance(centroid)
                if var >= self.diversity_floor:
                    self._centroid = centroid
                    self._consolidated = True
        else:
            # EMA update of centroid with re-normalization.
            if self._centroid is not None:
                new_centroid = [
                    self.ema_decay * self._centroid[i] + (1.0 - self.ema_decay) * emb[i]
                    for i in range(self.dim)
                ]
                self._centroid = _normalize(new_centroid)

    def match(self, query: list[float]) -> float:
        q = [float(x) for x in query]
        if self._consolidated and self._centroid is not None:
            return _cos_sim(q, self._centroid)
        if self._items:
            return max(_cos_sim(q, e) for e, _ in self._items)
        return 0.0

    @property
    def consolidated(self) -> bool:
        return self._consolidated

    @property
    def centroid(self) -> list[float] | None:
        if self._centroid is not None:
            return list(self._centroid)
        if self._items:
            return _mean([e for e, _ in self._items])
        return None

    @property
    def count(self) -> int:
        return len(self._items)

    def reliability(self) -> float:
        if len(self._items) < 2:
            return self.reliability_floor
        c = self.centroid
        if c is None:
            return self.reliability_floor
        var = self._intra_variance(c)
        # inverse of variance, normalized to [0, 1]
        if var <= 0.0:
            return 1.0
        val = 1.0 / (1.0 + var)
        if val < 0.0:
            val = 0.0
        if val > 1.0:
            val = 1.0
        return val

    # ------------------------------------------------------------------ #
    # serialization
    # ------------------------------------------------------------------ #
    def to_dict(self) -> dict[str, Any]:
        return {
            "dim": self.dim,
            "max_size": self.max_size,
            "consolidation_threshold": self.consolidation_threshold,
            "diversity_floor": self.diversity_floor,
            "ema_decay": self.ema_decay,
            "reliability_floor": self.reliability_floor,
            "consolidated": self._consolidated,
            "centroid": list(self._centroid) if self._centroid is not None else None,
            "exemplars": [
                {"embedding": list(e), "timestamp": ts} for e, ts in self._items
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ExemplarBuffer":
        buf = cls(
            dim=d["dim"],
            max_size=d.get("max_size", 20),
            consolidation_threshold=d.get("consolidation_threshold", 5),
            diversity_floor=d.get("diversity_floor", 0.01),
            ema_decay=d.get("ema_decay", 0.9),
            reliability_floor=d.get("reliability_floor", 0.3),
        )
        buf._items = [
            (list(item["embedding"]), item.get("timestamp"))
            for item in d.get("exemplars", [])
        ]
        buf._consolidated = bool(d.get("consolidated", False))
        c = d.get("centroid", None)
        buf._centroid = list(c) if c is not None else None
        return buf

    # ------------------------------------------------------------------ #
    # internals
    # ------------------------------------------------------------------ #
    def _intra_variance(self, centroid: list[float]) -> float:
        if not self._items:
            return 0.0
        dists = [1.0 - _cos_sim(e, centroid) for e, _ in self._items]
        return sum(dists) / len(dists)

    def _evict(self, incoming: list[float]) -> None:
        # Determine reference centroid for redundancy scoring.
        if self._consolidated and self._centroid is not None:
            ref = self._centroid
        elif self._items:
            ref = _mean([e for e, _ in self._items])
        else:
            ref = incoming

        if not self._items:
            return

        # Evict exemplar with highest cosine similarity to ref (most redundant).
        sims = [_cos_sim(e, ref) for e, _ in self._items]
        idx = max(range(len(sims)), key=lambda i: sims[i])
        del self._items[idx]
