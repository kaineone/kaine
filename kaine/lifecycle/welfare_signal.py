# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared welfare-signal detection primitives (core-importable).

Both the sidecar welfare observer (``kaine.evaluation.observers.welfare_observer``)
and the cycle-layer autonomous welfare-protective monitor
(``kaine.cycle.preservation_monitor``) must apply the *same* sustained-distress
logic over the same Soma signal. This module is the single, core-importable home
for that logic so neither copy drifts from the other — mirroring how
``AsyncJsonlSink`` / ``PrivacyFilter`` were extracted to shared homes.

It lives under ``kaine.lifecycle`` (NOT ``kaine.evaluation``) precisely so the
core cycle-layer monitor can import it WITHOUT importing ``kaine.evaluation`` —
the sidecar boundary forbids any core module from importing the evaluation
package. The welfare observer re-imports the same tracker for back-compat.

The primitives here are pure (no I/O, no bus, no clock of their own — the caller
passes ``now``), so they are deterministic over the logged state: a given
sequence of (magnitude, timestamp) inputs always produces the same crossings.
"""
from __future__ import annotations

from collections import deque


class SustainedThresholdTracker:
    """Detect a value staying at/above a threshold continuously for a duration.

    Rising-edge semantics on the *sustained* condition: ``observe`` returns
    ``True`` exactly once when the magnitude has been continuously at/above
    ``threshold`` for at least ``duration_s``; the sustain timer is then cleared
    so a single sustained episode produces a single fire (not one per sample).
    The timer also resets the instant the magnitude drops below the threshold,
    so a transient spike that dips back down never accumulates to a fire.

    The caller supplies the clock (``now``) on every ``observe`` call, so the
    tracker introduces no nondeterminism of its own.
    """

    def __init__(self, *, threshold: float, duration_s: float) -> None:
        self.threshold = float(threshold)
        self.duration_s = float(duration_s)
        # Wall/monotonic time when the magnitude first crossed the threshold
        # (None = currently below threshold).
        self._since: float | None = None

    @property
    def active_since(self) -> float | None:
        """Time the current sustained-high episode began, or None if below."""
        return self._since

    def reset(self) -> None:
        self._since = None

    def observe(self, magnitude: float, now: float) -> bool:
        """Feed one sample. Return True on a rising-edge sustained crossing.

        ``True`` is returned at most once per sustained episode (the timer is
        cleared on fire). A magnitude below the threshold resets the timer.
        """
        if float(magnitude) >= self.threshold:
            if self._since is None:
                self._since = now
            elif (now - self._since) >= self.duration_s:
                # Sustained long enough — fire once and clear for the next episode.
                self._since = None
                return True
        else:
            self._since = None
        return False

    def check_timeout(self, now: float) -> bool:
        """Fire on elapsed sustain duration WITHOUT a new sample.

        A caller polling on a timer (rather than per-sample) uses this so that a
        sustained episode is detected by the passage of time after the onset,
        even when no further samples arrive while the magnitude stays high. Fires
        once per episode (clears the timer), exactly like :meth:`observe`.
        """
        if self._since is not None and (now - self._since) >= self.duration_s:
            self._since = None
            return True
        return False


class WindowedEventCounter:
    """Count discrete events within a sliding time window; fire on overflow.

    Used for the "repeated gray-zone / distress events within a window"
    condition: each ``record`` appends an event timestamp, prunes timestamps
    older than ``window_s``, and returns ``True`` once the count within the
    window reaches ``threshold`` (then clears the window so one burst fires
    once, not on every subsequent event in the same burst).
    """

    def __init__(self, *, window_s: float, threshold: int) -> None:
        self.window_s = float(window_s)
        self.threshold = int(threshold)
        self._timestamps: deque[float] = deque()

    @property
    def count(self) -> int:
        return len(self._timestamps)

    def reset(self) -> None:
        self._timestamps.clear()

    def record(self, now: float) -> bool:
        """Record one event at ``now``. Return True on a windowed-rate crossing."""
        self._timestamps.append(now)
        cutoff = now - self.window_s
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        if self.threshold > 0 and len(self._timestamps) >= self.threshold:
            self._timestamps.clear()
            return True
        return False


__all__ = ["SustainedThresholdTracker", "WindowedEventCounter"]
