# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import hashlib
import struct
from collections import Counter, deque
from dataclasses import dataclass
from typing import Iterable, Protocol, runtime_checkable


@dataclass(frozen=True)
class RuminationResult:
    detected: bool
    habituation: float  # in [0, 1]
    dominant_bucket: str | None
    dominant_count: int


@runtime_checkable
class RuminationDetector(Protocol):
    def observe(self, hidden_state: Iterable[float]) -> RuminationResult: ...


class RecurrenceRuminationDetector:
    """Bucket hidden states by quantized fingerprint; flag recurrence.

    A bucket is the blake2b digest of the per-dim-quantized hidden
    state. The detector maintains a deque of recent bucket ids and
    flags rumination when any bucket appears more than `threshold`
    times in the window.

    Habituation is reported as `1 - unique_buckets / window_size` —
    a continuous measure of "how repetitive has recent experience
    been," independent of the threshold.
    """

    def __init__(
        self,
        window: int = 32,
        threshold: int = 4,
        bucket_resolution: float = 0.25,
    ) -> None:
        if window <= 1:
            raise ValueError("window must be >= 2")
        if threshold <= 1:
            raise ValueError("threshold must be >= 2")
        if bucket_resolution <= 0:
            raise ValueError("bucket_resolution must be positive")
        self._buckets: deque[str] = deque(maxlen=window)
        self._threshold = int(threshold)
        self._resolution = float(bucket_resolution)

    @property
    def window(self) -> int:
        return self._buckets.maxlen  # type: ignore[return-value]

    @property
    def threshold(self) -> int:
        return self._threshold

    def _fingerprint(self, hidden_state: Iterable[float]) -> str:
        quantized = [
            int(round(float(v) / self._resolution)) for v in hidden_state
        ]
        packed = struct.pack(f"{len(quantized)}i", *quantized)
        return hashlib.blake2b(packed, digest_size=8).hexdigest()

    def observe(self, hidden_state: Iterable[float]) -> RuminationResult:
        bucket = self._fingerprint(hidden_state)
        self._buckets.append(bucket)
        counts = Counter(self._buckets)
        dominant_bucket, dominant_count = counts.most_common(1)[0]
        unique = len(counts)
        window = max(len(self._buckets), 1)
        habituation = 1.0 - unique / window
        detected = dominant_count >= self._threshold
        return RuminationResult(
            detected=detected,
            habituation=max(0.0, min(1.0, habituation)),
            dominant_bucket=dominant_bucket,
            dominant_count=dominant_count,
        )
