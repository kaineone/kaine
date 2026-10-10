# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Broadcast context computation.

A context is a 24-dimensional featurization of the accessed members of the
latest adopted broadcast, weighted by salience and aged by the time since
reception. It implements the paper's Appendix A.1 featurization Phi_I and the
context adoption rule, and Appendix A.8's null context construction.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Callable, Collection, Sequence
from typing import Optional

from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.chronos.featurizer import AUDITION_SOURCE, DEFAULT_KNOWN_SOURCES

CONTEXT_DIM: int = 24
ADDITIVE_INDICES: tuple[int, ...] = tuple(range(4, 20)) + (23,)

_NUM_SOURCE_BINS = len(DEFAULT_KNOWN_SOURCES)
_NUM_HASH_BINS = 8


def event_contribution(source: str, event_type: str, weight: float) -> list[float]:
    """Return a 24-vector holding only one event's additive contributions."""
    vec = [0.0] * CONTEXT_DIM
    if not math.isfinite(weight) or weight < 0.0:
        return vec

    # [4..11] source mass; unknown non-audition sources share the praxis/overflow bin.
    if source != AUDITION_SOURCE:
        try:
            idx = DEFAULT_KNOWN_SOURCES.index(source)
        except ValueError:
            idx = _NUM_SOURCE_BINS - 1
        vec[4 + idx] = weight
    # [23] audition mass
    else:
        vec[23] = weight

    # [12..19] hash projection of (source, type)
    key = f"{source}::{event_type}".encode("utf-8")
    digest = hashlib.blake2b(key, digest_size=8).digest()
    bucket = int.from_bytes(digest, "big") % _NUM_HASH_BINS
    vec[12 + bucket] = weight

    return vec


def featurize_events(events: Sequence[tuple[str, str, float]], age_s: float) -> list[float]:
    """Compute the 24-dimensional context featurization Phi for the events."""
    vec = [0.0] * CONTEXT_DIM
    n = len(events)

    # [0] count
    vec[0] = min(8.0, math.log1p(n))

    # Effective weights drive both statistics and additive bins.
    effective_weights: list[float] = []
    for source, event_type, weight in events:
        effective = weight if math.isfinite(weight) and weight >= 0.0 else 0.0
        effective_weights.append(effective)
        if effective == 0.0:
            continue
        contrib = event_contribution(source, event_type, effective)
        for i in ADDITIVE_INDICES:
            vec[i] += contrib[i]

    # [1..3] weight statistics
    if n > 0:
        mean = sum(effective_weights) / n
        vec[1] = mean
        vec[2] = max(effective_weights)
        if n > 1:
            variance = sum((w - mean) ** 2 for w in effective_weights) / (n - 1)
            vec[3] = math.sqrt(variance)

    # [20] age
    vec[20] = math.log1p(max(float(age_s), 0.0))
    # [21] inhibition flag (a context is never inhibited)
    vec[21] = 0.0
    # [22] broadcast indicator
    vec[22] = 1.0

    return vec


class BroadcastContext:
    """Adopted broadcast context with running statistics for null contexts."""

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._members: list[tuple[str, str, float]] = []
        self._received_at: Optional[float] = None
        self._n = 0
        self._running_sum_components_0_3: list[float] = [0.0] * 4
        self._source_running_sums: dict[str, list[float]] = {}

    @property
    def has_context(self) -> bool:
        """True once a broadcast has been adopted."""
        return self._received_at is not None

    def observe(self, snapshot: WorkspaceSnapshot) -> bool:
        """Adopt an accessed broadcast if possible; return whether adoption occurred."""
        if snapshot.inhibited:
            return False

        threshold = snapshot.metadata.get("access_threshold")
        accessed: list[tuple[str, str, float]] = []
        for entry_id, event in snapshot.selected_events or []:
            score = (snapshot.salience_scores or {}).get(entry_id, event.salience)
            if threshold is None or score >= threshold:
                accessed.append((event.source, event.type, float(event.salience)))

        if not accessed:
            return False

        # Adopt the new context (age is effectively zero at the moment of receipt).
        self._members = accessed
        self._received_at = self._clock()
        vec = featurize_events(self._members, 0.0)

        # Update running statistics over adopted contexts.
        self._n += 1
        for i in range(4):
            self._running_sum_components_0_3[i] += vec[i]

        current_shares: dict[str, list[float]] = {}
        for source, event_type, weight in self._members:
            contrib = event_contribution(source, event_type, weight)
            share = current_shares.setdefault(source, [0.0] * CONTEXT_DIM)
            for i in ADDITIVE_INDICES:
                share[i] += contrib[i]

        for source, share in current_shares.items():
            running = self._source_running_sums.setdefault(source, [0.0] * CONTEXT_DIM)
            for i in ADDITIVE_INDICES:
                running[i] += share[i]

        return True

    def vector(self) -> Optional[list[float]]:
        """Current context vector, or None before first adoption."""
        if not self.has_context:
            return None
        return featurize_events(self._members, self._clock() - self._received_at)

    def null_vector(self, kept_sources: Collection[str]) -> Optional[list[float]]:
        """Null-context estimate keeping selected source shares."""
        if not self.has_context:
            return None

        vec = self.vector()
        if vec is None:
            return None

        # [0..3] running means over adopted contexts.
        for i in range(4):
            vec[i] = self._running_sum_components_0_3[i] / self._n

        # Per-source additive shares in the current context.
        current_shares: dict[str, list[float]] = {}
        for source, event_type, weight in self._members:
            contrib = event_contribution(source, event_type, weight)
            share = current_shares.setdefault(source, [0.0] * CONTEXT_DIM)
            for i in ADDITIVE_INDICES:
                share[i] += contrib[i]

        # Additive indices: kept current share plus running mean of the rest.
        for i in ADDITIVE_INDICES:
            total_running = sum(running[i] for running in self._source_running_sums.values())
            kept_running = sum(
                self._source_running_sums.get(source, [0.0] * CONTEXT_DIM)[i]
                for source in kept_sources
            )
            kept_current = sum(
                current_shares.get(source, [0.0] * CONTEXT_DIM)[i]
                for source in kept_sources
            )
            not_kept_running_mean = (total_running - kept_running) / self._n
            vec[i] = kept_current + not_kept_running_mean

        # Components 20, 21, 22 remain from vector().

        return vec

    def age_s(self) -> Optional[float]:
        """Seconds since the adopted broadcast was received."""
        if not self.has_context:
            return None
        return self._clock() - self._received_at
