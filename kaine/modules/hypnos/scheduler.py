# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Rest scheduler for Hypnos.

Per `docs/kaine-paper.md` §3.5, rest is "non-interruptible, and the
system can defer rest during active interaction but must rest within a
maximum deferral window." This scheduler tracks when the next sleep is
due and enforces the maximum deferral window — once it expires, sleep
fires regardless of `try_defer()` calls.
"""
from __future__ import annotations

import time
from typing import Callable, Optional


class RestScheduler:
    def __init__(
        self,
        *,
        interval_seconds: float,
        max_deferral_seconds: float,
        per_defer_seconds: float = 60.0,
        clock: Optional[Callable[[], float]] = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        if max_deferral_seconds < 0:
            raise ValueError("max_deferral_seconds must be >= 0")
        if per_defer_seconds <= 0:
            raise ValueError("per_defer_seconds must be positive")
        self._interval = float(interval_seconds)
        self._max_deferral = float(max_deferral_seconds)
        self._per_defer = float(per_defer_seconds)
        self._clock = clock or time.monotonic
        now = self._clock()
        self._original_due_at: float = now + self._interval
        self._effective_due_at: float = self._original_due_at

    def _now(self) -> float:
        return float(self._clock())

    @property
    def original_due_at(self) -> float:
        return self._original_due_at

    @property
    def effective_due_at(self) -> float:
        return self._effective_due_at

    @property
    def total_deferral(self) -> float:
        return max(0.0, self._effective_due_at - self._original_due_at)

    def is_due(self) -> bool:
        now = self._now()
        # Sleep is due if either the effective deadline has passed, or
        # the original deadline + max deferral has — even mid-defer.
        if now >= self._effective_due_at:
            return True
        if now >= self._original_due_at + self._max_deferral:
            return True
        return False

    def try_defer(self) -> bool:
        """Push the next sleep back by `per_defer_seconds`.

        Returns True if the deferral was accepted, False if the max
        deferral window has been exhausted (sleep fires regardless).
        """
        now = self._now()
        # If we're past the deferral window from the ORIGINAL due time,
        # no more deferrals are allowed.
        if now >= self._original_due_at + self._max_deferral:
            return False
        proposed = self._effective_due_at + self._per_defer
        cap = self._original_due_at + self._max_deferral
        if proposed > cap:
            proposed = cap
        # If we'd defer by less than a millisecond, treat as refused so
        # callers don't loop indefinitely on tiny extensions.
        if proposed - self._effective_due_at < 0.001:
            return False
        self._effective_due_at = proposed
        return True

    def mark_completed(self) -> None:
        """Called after a successful sleep — schedule the next one."""
        now = self._now()
        self._original_due_at = now + self._interval
        self._effective_due_at = self._original_due_at
