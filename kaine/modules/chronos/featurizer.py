# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Deterministic, pure-Python featurization of WorkspaceSnapshots.

Produces a fixed 24-dim float vector per snapshot under a numbered layout:

- Layout 1 (legacy): eight known source bins; unknown sources, including
  Audition, overflow into the last source bin (dim 11). Dim 23 is always
  0.0.
- Layout 2: events whose ``source == "audition"`` add their salience to
  dim 23 instead of any source bin. Everything else is identical to
  layout 1, including the hash projection and salience statistics. The
  vector length stays 24.

The dimensions break down as:

    [0]      : log1p(num_selected_events), clamped to 8
    [1..3]   : mean / max / std of salience scores in the snapshot
    [4..11]  : top-source one-hots for the eight known sources (each
               event contributes 1.0 weighted by salience to its source
               bin if known; unknown sources are absorbed in [11], except
               that under layout 2 Audition has its own slot, [23])
    [12..19] : eight-bin hash projection of (source, type) pairs,
               weighted by salience (blake2b → 8 buckets)
    [20]     : log1p(delta_t_seconds) since previous snapshot
    [21]     : 1.0 if inhibited else 0.0
    [22]     : 1.0 if is_experiential else 0.0
    [23]     : Audition salience bin in layout 2; reserved / permanently
               zero in layout 1. Trained beings keep layout 1 through the
               versioned restore, so a trained network never sees the
               meaning of this slot change.

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

AUDITION_SOURCE: str = "audition"
FEATURIZER_LAYOUTS: tuple[int, ...] = (1, 2)
LATEST_LAYOUT: int = 2

_NUM_SOURCE_BINS = 8  # must match len(known_sources); last bin doubles as overflow
_NUM_HASH_BINS = 8


class SnapshotFeaturizer:
    def __init__(
        self,
        known_sources: Iterable[str] = DEFAULT_KNOWN_SOURCES,
        clock: Optional[callable] = None,
        layout: int = LATEST_LAYOUT,
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
        self._layout = self._validate_layout(layout)
        self._last_seen_ts: Optional[float] = None
        self._clock = clock or time.time

    @property
    def feature_dim(self) -> int:
        return DEFAULT_FEATURE_DIM

    @property
    def layout(self) -> int:
        return self._layout

    def set_layout(self, layout: int) -> None:
        self._layout = self._validate_layout(layout)

    def _validate_layout(self, layout: int) -> int:
        layout = int(layout)
        if layout not in FEATURIZER_LAYOUTS:
            raise ValueError(f"unsupported featurizer layout {layout}")
        return layout

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
            if self._layout == 2 and event.source == AUDITION_SOURCE:
                # Audition has its own reserved slot in layout 2.
                continue
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
        # [23] Audition bin in layout 2; reserved zero in layout 1.
        if self._layout == 2:
            for _, event in events:
                if event.source == AUDITION_SOURCE:
                    vec[23] += float(event.salience)
        else:
            vec[23] = 0.0

        return vec
