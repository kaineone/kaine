# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Deterministic, pure-Python featurization of WorkspaceSnapshots.

Produces a fixed 24-dim float vector per snapshot. The dimensions break
down as:

    [0]      : log1p(num_selected_events), clamped to 8
    [1..3]   : mean / max / std of salience scores in the snapshot
    [4..11]  : top-source one-hots for the eight known sources (each
               event contributes 1.0 weighted by salience to its source
               bin if known; unknown sources are absorbed in [11])
    [12..19] : eight-bin hash projection of (source, type) pairs,
               weighted by salience (blake2b → 8 buckets)
    [20]     : log1p(delta_t_seconds) since previous snapshot
    [21]     : 1.0 if inhibited else 0.0
    [22]     : 1.0 if is_experiential else 0.0
    [23]     : reserved padding for future features (always 0.0)

The vector is independent of torch — the network module is the only
place torch is imported, so tests of the featurizer stay fast.
"""
from __future__ import annotations

import hashlib
import math
import time
from typing import Iterable, Optional

from kaine.cycle.types import WorkspaceSnapshot

DEFAULT_FEATURE_DIM: int = 24
DEFAULT_KNOWN_SOURCES: tuple[str, ...] = (
    "soma",
    "chronos",
    "topos",
    "nous",
    "mnemos",
    "thymos",
    "lingua",
    "praxis",
)

_NUM_SOURCE_BINS = 8  # must match len(known_sources); last bin doubles as overflow
_NUM_HASH_BINS = 8


class SnapshotFeaturizer:
    def __init__(
        self,
        known_sources: Iterable[str] = DEFAULT_KNOWN_SOURCES,
        clock: Optional[callable] = None,
    ) -> None:
        sources = tuple(known_sources)
        if len(sources) != _NUM_SOURCE_BINS:
            raise ValueError(
                f"known_sources must have exactly {_NUM_SOURCE_BINS} entries; "
                f"got {len(sources)}. Future configs that need more bins must "
                "also change DEFAULT_FEATURE_DIM."
            )
        self._known_sources = sources
        self._source_index = {name: i for i, name in enumerate(sources)}
        self._last_seen_ts: Optional[float] = None
        self._clock = clock or time.time

    @property
    def feature_dim(self) -> int:
        return DEFAULT_FEATURE_DIM

    def featurize(self, snapshot: WorkspaceSnapshot) -> list[float]:
        vec = [0.0] * DEFAULT_FEATURE_DIM
        events = list(snapshot.selected_events or [])

        # [0] count
        vec[0] = min(8.0, math.log1p(len(events)))

        # [1..3] salience statistics
        if events:
            sals = [float(ev.salience) for _, ev in events]
            mean = sum(sals) / len(sals)
            vec[1] = mean
            vec[2] = max(sals)
            if len(sals) > 1:
                variance = sum((s - mean) ** 2 for s in sals) / (len(sals) - 1)
                vec[3] = math.sqrt(variance)

        # [4..11] source one-hot weighted by salience
        for _, event in events:
            idx = self._source_index.get(event.source)
            if idx is None:
                idx = _NUM_SOURCE_BINS - 1  # overflow bucket = last bin
            vec[4 + idx] += float(event.salience)

        # [12..19] hash projection of (source, type) pairs
        for _, event in events:
            key = f"{event.source}::{event.type}".encode("utf-8")
            digest = hashlib.blake2b(key, digest_size=8).digest()
            bucket = int.from_bytes(digest, "big") % _NUM_HASH_BINS
            vec[12 + bucket] += float(event.salience)

        # [20] delta time
        now = float(self._clock())
        if self._last_seen_ts is None:
            vec[20] = 0.0
        else:
            vec[20] = math.log1p(max(now - self._last_seen_ts, 0.0))
        self._last_seen_ts = now

        # [21] inhibited
        vec[21] = 1.0 if snapshot.inhibited else 0.0
        # [22] is_experiential
        vec[22] = 1.0 if snapshot.is_experiential else 0.0
        # [23] reserved — permanently zero in the shipped model.
        # WARNING: this slot has been zero for every observation the CfC and
        # forward-prediction models have ever seen. Introducing a real feature
        # here later would require a full model-weight reset (the trained
        # network will have adapted its weights to a constant-zero input at
        # this position; a non-zero signal would be interpreted against those
        # adapted weights, producing unreliable outputs until retrained from
        # scratch). Do NOT populate this slot without a coordinated retrain.
        vec[23] = 0.0

        return vec
