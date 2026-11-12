# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Bounded in-memory queue for audio segments arriving while STT is not resident.

When the residency manager has unloaded the STT engine, incoming audio segments
are buffered here instead of being dropped.  When STT loads again, the queue is
drained and the buffered segments are processed.  Segments that exceed the count
or age bounds are evicted oldest-first.  Every drop fires a content-free
queue_drop residency event.

Zero persistence: all data lives only in process memory.  No file is ever opened
for writing.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class QueuedSegment:
    audio_bytes: bytes
    sample_rate: int
    source_label: str
    enqueued_at: float
    item: Any = None


class BoundedAudioQueue:
    """Thread-safe bounded queue for audio during STT unload.

    Bounded by count (``max_count``) and age (``max_age_s``).  When the count
    limit is reached the oldest segment is dropped.  Segments older than
    ``max_age_s`` are evicted on every enqueue and drain.  Drops are counted
    and each fires a ``queue_drop`` residency event.
    """

    def __init__(self, max_count: int = 32, max_age_s: float = 10.0) -> None:
        if max_count < 1:
            raise ValueError("max_count must be >= 1")
        if max_age_s <= 0:
            raise ValueError("max_age_s must be > 0")
        self._max_count = int(max_count)
        self._max_age_s = float(max_age_s)
        self._buf: deque[QueuedSegment] = deque()
        self._total_drops = 0
        self._lock = threading.Lock()

    def _fire_drop(self, reason: str) -> None:
        from kaine.residency.events import record_queue_drop

        record_queue_drop(name="perception_queue", reason=reason)

    def _evict_stale(self, now: float) -> int:
        dropped = 0
        while self._buf and (now - self._buf[0].enqueued_at) > self._max_age_s:
            self._buf.popleft()
            self._total_drops += 1
            dropped += 1
            self._fire_drop("age_limit")
        return dropped

    def enqueue(
        self,
        audio_bytes: bytes,
        sample_rate: int,
        source_label: str,
        *,
        item: Any = None,
    ) -> bool:
        with self._lock:
            now = time.monotonic()
            self._evict_stale(now)
            while len(self._buf) >= self._max_count:
                self._buf.popleft()
                self._total_drops += 1
                self._fire_drop("count_limit")
            self._buf.append(
                QueuedSegment(
                    audio_bytes=audio_bytes,
                    sample_rate=sample_rate,
                    source_label=source_label,
                    enqueued_at=now,
                    item=item,
                )
            )
            return True

    def drain(self) -> list[QueuedSegment]:
        with self._lock:
            self._evict_stale(time.monotonic())
            segments = list(self._buf)
            self._buf.clear()
            return segments

    @property
    def total_drops(self) -> int:
        with self._lock:
            return self._total_drops

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._buf)

    def clear(self) -> None:
        with self._lock:
            self._buf.clear()
