# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Wall-clock accumulator that discounts time spent under operator freeze."""
from __future__ import annotations

import logging
import time
from typing import Callable

import kaine.cycle.control_state as control_state

log = logging.getLogger(__name__)


class UnfrozenClock:
    """Accumulate wall seconds only while the cycle is not frozen.

    A span counts only if both its start and end observations are unfrozen
    (or unknown treated as unfrozen per policy). Unknown/corrupt freeze-state
    observations fail toward the caller's safe side: welfare timers keep
    counting so a broken control file never hides distress.
    """

    def __init__(
        self,
        read_frozen: Callable[[], bool | None],
        *,
        unknown_counts_as: str,
        monotonic: Callable[[], float] = time.monotonic,
        poll_s: float = 0.25,
    ) -> None:
        if unknown_counts_as not in ("unfrozen", "frozen"):
            raise ValueError(
                f"unknown_counts_as must be 'unfrozen' or 'frozen', got {unknown_counts_as!r}"
            )
        self._read_frozen = read_frozen
        self._unknown_counts_as = unknown_counts_as
        self._monotonic = monotonic
        self._poll_s = float(poll_s)

        self._total = 0.0
        self._last_t: float | None = None
        self._last_counting = False
        self._last_state: bool | None = None
        self._seen_state = False
        self._unknown_episodes = 0
        self._cached_state: bool | None = None
        self._cached_at: float | None = None

    @property
    def unknown_counts_as(self) -> str:
        return self._unknown_counts_as

    def _read(self) -> bool | None:
        now = self._monotonic()
        if self._cached_at is not None and (now - self._cached_at) < self._poll_s:
            return self._cached_state
        try:
            state = self._read_frozen()
        except Exception:
            state = None
        self._cached_state = state
        self._cached_at = now
        return state

    def wall(self) -> float:
        """The wall (monotonic) time this clock is measured against."""
        return self._monotonic()

    def now(self) -> float:
        t = self._monotonic()
        state = self._read()

        if state is None:
            if not self._seen_state or self._last_state is not None:
                self._unknown_episodes += 1
                if self._unknown_counts_as == "unfrozen":
                    log.warning("freeze state unreadable; welfare timers keep counting")
                else:
                    log.warning("freeze state unreadable; counting as frozen")

        self._last_state = state
        self._seen_state = True

        counting = (state is False) or (
            state is None and self._unknown_counts_as == "unfrozen"
        )

        if self._last_t is not None and self._last_counting and counting:
            delta = t - self._last_t
            if delta > 0.0:
                self._total += delta

        self._last_t = t
        self._last_counting = counting
        return self._total

    def frozen(self) -> bool | None:
        return self._last_state

    def diagnostic(self) -> dict:
        return {
            "unknown_counts_as": self._unknown_counts_as,
            "unknown_episodes": self._unknown_episodes,
            "in_unknown_episode": self._last_state is None and self._seen_state,
        }

    @classmethod
    def for_welfare(
        cls, *, monotonic: Callable[[], float] = time.monotonic
    ) -> "UnfrozenClock":
        """Build a welfare clock that counts unknown spans as unfrozen."""
        return cls(
            control_state.read_frozen_state,
            unknown_counts_as="unfrozen",
            monotonic=monotonic,
        )
