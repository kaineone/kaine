# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Windowed learning progress estimator for a single perceptual source.

This module implements the relative fall of the mean raw prediction error from
the older half to the newer half of a sliding, evenly binned history. It follows
the learning progress formulation described by Oudeyer, Kaplan and Hafner (2007)
and by Baranes and Oudeyer (2013), paper A.4.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any


def _validate_pair(item: object) -> tuple[float, int] | None:
    """Return a validated (sum, count) pair, or None if invalid."""
    if not isinstance(item, (list, tuple)) or len(item) != 2:
        return None
    raw_sum, raw_count = item

    if isinstance(raw_sum, bool) or not isinstance(raw_sum, (int, float)):
        return None
    sum_value = float(raw_sum)
    if not math.isfinite(sum_value) or sum_value < 0.0:
        return None

    if isinstance(raw_count, bool):
        return None
    if isinstance(raw_count, int):
        if raw_count < 0:
            return None
        count_value = raw_count
    elif isinstance(raw_count, float):
        if (
            not math.isfinite(raw_count)
            or raw_count < 0.0
            or not raw_count.is_integer()
        ):
            return None
        count_value = int(raw_count)
    else:
        return None

    return (sum_value, count_value)


class WindowedProgress:
    """Estimate learning progress from binned raw prediction errors."""

    def __init__(self, bin_s: float, max_bins: int) -> None:
        """Create a new estimator with the given bin width and window size."""
        if (
            isinstance(bin_s, bool)
            or not isinstance(bin_s, (int, float))
            or not math.isfinite(bin_s)
            or bin_s <= 0.0
        ):
            raise ValueError("bin_s must be a finite positive number")

        if (
            type(max_bins) is not int
            or isinstance(max_bins, bool)
            or max_bins < 2
            or max_bins % 2 != 0
        ):
            raise ValueError("max_bins must be an even int >= 2")

        self._bin_s = float(bin_s)
        self._max_bins = max_bins
        self._origin: float | None = None
        self._deque: deque[tuple[float, int]] = deque(maxlen=max_bins)
        self._current_idx = 0
        self._current_sum = 0.0
        self._current_count = 0

    @property
    def started(self) -> bool:
        """True once the first positive error has been recorded."""
        return self._origin is not None

    @property
    def bin_s(self) -> float:
        """Width of each time bin in seconds."""
        return self._bin_s

    @property
    def max_bins(self) -> int:
        """Maximum number of completed bins retained."""
        return self._max_bins

    def add(self, t: float, error: float) -> None:
        """Record a raw prediction error at entity time t."""
        if self._origin is None:
            if error <= 0.0:
                return
            self._origin = float(t)
            self._current_idx = 0
            self._current_sum = float(error)
            self._current_count = 1
            return

        self.advance(t)
        self._current_sum += float(error)
        self._current_count += 1

    def advance(self, t: float) -> None:
        """Close bins up to time t without recording a new error."""
        if self._origin is None:
            return

        idx = math.floor((t - self._origin) / self._bin_s)
        if idx <= self._current_idx:
            return

        gap = idx - self._current_idx - 1
        if gap > self._max_bins:
            self._deque.clear()
            self._deque.extend((0.0, 0) for _ in range(self._max_bins))
        else:
            self._deque.append((self._current_sum, self._current_count))
            if gap > 0:
                self._deque.extend((0.0, 0) for _ in range(gap))

        self._current_idx = idx
        self._current_sum = 0.0
        self._current_count = 0

    def value(self, t: float) -> float | None:
        """Return the learning progress at time t, or None if undefined."""
        self.advance(t)

        n = len(self._deque)
        k = (n // 2) * 2
        if k < 2:
            return None

        bins = list(self._deque)[-k:]
        half = k // 2

        older_sum = 0.0
        older_count = 0
        for s, c in bins[:half]:
            older_sum += s
            older_count += c

        newer_sum = 0.0
        newer_count = 0
        for s, c in bins[half:]:
            newer_sum += s
            newer_count += c

        if older_count == 0 or newer_count == 0:
            return None

        older_mean = older_sum / older_count
        newer_mean = newer_sum / newer_count
        if older_mean <= 1e-9:
            return None

        raw = 1.0 - newer_mean / older_mean
        return max(-1.0, min(1.0, raw))

    def to_dict(self, t: float) -> dict[str, Any]:
        """Serialise the started estimator state at time t."""
        if self._origin is None:
            raise ValueError("Estimator has not started yet")

        self.advance(t)
        elapsed = t - (self._origin + self._current_idx * self._bin_s)
        if elapsed < 0.0:
            elapsed = 0.0
        elif elapsed > self._bin_s:
            elapsed = self._bin_s

        return {
            "bin_s": float(self._bin_s),
            "bins": [[float(s), int(c)] for s, c in self._deque],
            "current": [float(self._current_sum), int(self._current_count)],
            "elapsed_s": float(elapsed),
        }

    @classmethod
    def from_dict(
        cls,
        data: object,
        *,
        bin_s: float,
        max_bins: int,
        t: float,
    ) -> WindowedProgress | None:
        """Restore a started estimator from a dict, or return None if invalid."""
        if not isinstance(data, dict):
            return None

        saved_bin_s = data.get("bin_s")
        if (
            isinstance(saved_bin_s, bool)
            or not isinstance(saved_bin_s, (int, float))
            or not math.isfinite(saved_bin_s)
            or abs(float(saved_bin_s) - float(bin_s)) > 1e-9
        ):
            return None

        raw_bins = data.get("bins")
        if not isinstance(raw_bins, list):
            return None

        validated_bins: list[tuple[float, int]] = []
        for item in raw_bins:
            pair = _validate_pair(item)
            if pair is None:
                return None
            validated_bins.append(pair)

        raw_current = data.get("current")
        current = _validate_pair(raw_current)
        if current is None:
            return None

        elapsed = data.get("elapsed_s")
        if (
            isinstance(elapsed, bool)
            or not isinstance(elapsed, (int, float))
            or not math.isfinite(elapsed)
            or elapsed < 0.0
            or elapsed > bin_s
        ):
            return None

        obj = cls(bin_s, max_bins)
        obj._origin = float(t) - float(elapsed)
        obj._current_idx = 0
        obj._current_sum, obj._current_count = current

        if len(validated_bins) > max_bins:
            validated_bins = validated_bins[-max_bins:]
        obj._deque = deque(validated_bins, maxlen=max_bins)

        return obj
