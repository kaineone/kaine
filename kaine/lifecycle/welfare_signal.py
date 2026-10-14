# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared welfare-signal detection primitives (core-importable).

Both the sidecar welfare observer (``kaine.evaluation.observers.welfare_observer``)
and the cycle-layer autonomous welfare-protective monitor
(``kaine.cycle.preservation_monitor``) must apply the *same* sustained-distress
logic over the same interoception module's signal. This module is the single, core-importable home
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
from typing import NamedTuple


class SustainedThresholdTracker:
    """Detect a value staying at/above a threshold continuously for a duration.

    Rising-edge semantics on the *sustained* condition: ``observe`` returns
    ``True`` exactly once when the magnitude has been continuously at/above
    ``threshold`` for at least ``duration_s``; the sustain timer is then cleared
    so a single sustained episode produces a single fire (not one per sample).
    The timer also resets the instant the magnitude drops below the threshold,
    so a transient spike that dips back down never accumulates to a fire.

    The elapsed duration of an episode is measured as the wall time from its
    onset to the last at/above-threshold sample, plus the unfrozen time since
    that last sample. A sample is evidence the state persisted: while samples
    keep arriving (even during a freeze) the elapsed duration tracks wall time;
    once they stop, frozen time stops counting.

    The caller supplies the clock (``now``) on every ``observe`` call, so the
    tracker introduces no nondeterminism of its own.
    """

    def __init__(self, *, threshold: float, duration_s: float) -> None:
        self.threshold = float(threshold)
        self.duration_s = float(duration_s)
        # Unfrozen time when the current episode began (None = below threshold).
        self._since: float | None = None
        # Wall time when the current episode began.
        self._since_wall: float | None = None
        # Unfrozen time of the most recent at/above-threshold sample.
        self._last_sample: float | None = None
        # Wall time of the most recent at/above-threshold sample.
        self._last_sample_wall: float | None = None
        # Elapsed duration at the moment of the last fire (sample or timeout).
        self.last_fire_elapsed: float = 0.0

    @property
    def active_since(self) -> float | None:
        """Time the current sustained-high episode began, or None if below."""
        return self._since

    def reset(self) -> None:
        self._since = None
        self._since_wall = None
        self._last_sample = None
        self._last_sample_wall = None

    def elapsed(self, now: float) -> float:
        """Unfrozen-aware elapsed duration for the current episode."""
        if self._since is None:
            return 0.0
        if self._last_sample_wall is None or self._last_sample is None:
            return now - self._since
        return (self._last_sample_wall - self._since_wall) + (now - self._last_sample)

    def observe(self, magnitude: float, now: float, *, wall_now: float | None = None) -> bool:
        """Feed one sample. Return True on a rising-edge sustained crossing.

        ``True`` is returned at most once per sustained episode (the timer is
        cleared on fire). A magnitude below the threshold resets the timer.

        ``now`` is the unfrozen time. ``wall_now`` defaults to ``now`` so
        callers that pass one clock behave exactly as before.
        """
        if wall_now is None:
            wall_now = now
        now = float(now)
        wall_now = float(wall_now)
        if float(magnitude) >= self.threshold:
            if self._since is None:
                self._since = now
                self._since_wall = wall_now
            # Every sample is evidence the state persisted up to this wall time.
            self._last_sample = now
            self._last_sample_wall = wall_now
            elapsed = self.elapsed(now)
            if elapsed >= self.duration_s:
                # Sustained long enough — fire once and clear for the next episode.
                self.last_fire_elapsed = elapsed
                self.reset()
                return True
        else:
            self.reset()
        return False

    def check_timeout(self, now: float) -> bool:
        """Fire on elapsed sustain duration WITHOUT a new sample.

        A caller polling on a timer (rather than per-sample) uses this so that a
        sustained episode is detected by the passage of time after the onset,
        even when no further samples arrive while the magnitude stays high. Fires
        once per episode (clears the timer), exactly like :meth:`observe`.
        """
        if self._since is not None:
            elapsed = self.elapsed(now)
            if elapsed >= self.duration_s:
                self.last_fire_elapsed = elapsed
                self.reset()
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


#: Operator advisory published by the welfare observer on ``welfare.out`` when a
#: processor's readings stay undefined, and its clear. Neither is a gray-zone
#: event: the protective monitor reads only ``welfare.gray_zone`` from that stream.
BLIND_SENSOR_TYPE = "welfare.blind_sensor"
BLIND_SENSOR_CLEARED_TYPE = "welfare.blind_sensor_cleared"

#: Operator advisory published when a tracked processor publishes nothing for a
#: sustained stretch, and its clear. Like the blind-sensor advisory, neither is a
#: gray-zone event and the protective monitor never acts on them.
SENSOR_SILENT_TYPE = "welfare.sensor_silent"
SENSOR_SILENT_CLEARED_TYPE = "welfare.sensor_silent_cleared"

#: Report event type -> processor label, for each report that carries a
#: forward-model prediction error.
BLIND_SENSOR_PROCESSORS: dict[str, str] = {
    "interoception.report": "interoception",
    "vision.report": "vision",
    "audition.perception": "audition_acoustic",
    "audition.emotion": "audition_tone",
}

#: Processors that report on a steady cadence, so a long silence means the
#: sensor stopped. ``audition_tone`` is left out: it reports only when speech
#: is heard, so a silent room is a normal reason for it to publish nothing.
SILENCE_TRACKED_PROCESSORS: frozenset[str] = frozenset({"interoception", "vision", "audition_acoustic"})

#: The ``advisory`` label of the rollup line the observer writes when it starts.
#: Readers treat it as clearing every processor's blind and silent state.
ADVISORY_RESET = "reset"


class RunTransition(NamedTuple):
    """A blind-sensor state change: ``"raised"`` or ``"cleared"``, with the run's size."""

    transition: str
    samples: int
    seconds: float


class SilenceTransition(NamedTuple):
    """A silence-advisory state change: ``"raised"`` or ``"cleared"``, with elapsed seconds."""

    transition: str
    seconds: float


class SilenceTracker:
    """Track one processor's silence after it has been seen at least once.

    ``duration_s`` is the unfrozen-time silence that raises the advisory.
    ``seen`` records a publication and clears a raised advisory. ``check``
    raises the advisory when ``now - last_seen`` reaches the duration. A
    processor that has never been seen is never silent; it may simply be
    disabled.
    """

    def __init__(self, *, duration_s: float) -> None:
        if duration_s <= 0:
            raise ValueError("duration_s must be positive")
        self._duration_s = float(duration_s)
        self._seen: bool = False
        self._last_seen: float = 0.0
        self._raised: bool = False

    @property
    def active(self) -> bool:
        return self._raised

    def seen(self, now: float) -> SilenceTransition | None:
        """Record a publication at unfrozen time ``now`` and lower any advisory."""
        transition: SilenceTransition | None = None
        if self._raised:
            transition = SilenceTransition("cleared", now - self._last_seen)
            self._raised = False
        self._seen = True
        self._last_seen = float(now)
        return transition

    def check(self, now: float) -> SilenceTransition | None:
        """Raise the advisory if ``now - last_seen`` has reached the duration."""
        if not self._seen or self._raised:
            return None
        elapsed = now - self._last_seen
        if elapsed >= self._duration_s:
            self._raised = True
            return SilenceTransition("raised", elapsed)
        return None


class UndefinedRunTracker:
    """Track one processor's current run of consecutive undefined samples.

    ``min_samples`` is the configured N; 0 means derive N from the duration.
    A run begins on the first undefined sample and ends on the first defined
    sample. With ``min_samples > 0`` the threshold is met when the run holds
    that many samples. With 0 it is met when the run spans ``duration_s`` from
    its first sample, which is the number of samples that duration holds at
    the processor's own rate. The advisory is raised once per run when the
    threshold is met, and a cleared transition is returned when a defined
    sample follows a raised advisory.

    ``now`` is the observer's unfrozen read time. It excludes frozen time,
    but it stretches when the observer lags and then reads a backlog. The
    optional ``event_time`` is the event's own wall-clock timestamp; it does
    not stretch with lag, but it includes frozen time. With ``min_samples == 0``
    the span threshold requires both ``now - start >= duration_s`` and, when
    both the first and current sample carry an event time, ``event_time -
    first_event_time >= duration_s``. Requiring both means neither a lagging
    observer nor a freeze can raise the advisory early. The reported
    ``seconds`` of a transition is the smaller of the two spans when both
    exist, otherwise the read-time span. When ``event_time`` is None the
    behaviour is unchanged from before.
    """

    def __init__(self, *, min_samples: int, duration_s: float) -> None:
        if min_samples < 0:
            raise ValueError("min_samples must be non-negative")
        if duration_s <= 0:
            raise ValueError("duration_s must be positive")
        self.min_samples = int(min_samples)
        self.duration_s = float(duration_s)
        self._samples: int = 0
        self._start: float | None = None
        self._first_event_time: float | None = None
        self._raised: bool = False

    @property
    def samples(self) -> int:
        return self._samples

    @property
    def active(self) -> bool:
        return self._raised

    def observe(
        self, defined: bool, now: float, event_time: float | None = None
    ) -> RunTransition | None:
        """Record one sample and return a transition if the run changes state."""
        if not defined:
            if self._samples == 0:
                self._start = float(now)
                self._first_event_time = event_time
            self._samples += 1
            if not self._raised and self._threshold_met(now, event_time):
                self._raised = True
                return RunTransition(
                    "raised",
                    self._samples,
                    self._effective_seconds(now, event_time),
                )
            return None
        if self._raised:
            transition = RunTransition(
                transition="cleared",
                samples=self._samples,
                seconds=self._effective_seconds(now, event_time),
            )
        else:
            transition = None
        self._reset()
        return transition

    def _effective_seconds(self, now: float, event_time: float | None) -> float:
        """Return the run span, preferring the smaller of the two clocks when both exist."""
        if self._start is None:
            return 0.0
        read_span = now - self._start
        if self._first_event_time is not None and event_time is not None:
            return min(read_span, event_time - self._first_event_time)
        return read_span

    def _threshold_met(self, now: float, event_time: float | None) -> bool:
        if self.min_samples > 0:
            return self._samples >= self.min_samples
        if self._start is None:
            return False
        if (now - self._start) < self.duration_s:
            return False
        if self._first_event_time is not None and event_time is not None:
            return (event_time - self._first_event_time) >= self.duration_s
        return True

    def _reset(self) -> None:
        self._samples = 0
        self._start = None
        self._first_event_time = None
        self._raised = False


__all__ = [
    "SustainedThresholdTracker",
    "WindowedEventCounter",
    "ADVISORY_RESET",
    "BLIND_SENSOR_CLEARED_TYPE",
    "BLIND_SENSOR_PROCESSORS",
    "BLIND_SENSOR_TYPE",
    "RunTransition",
    "SENSOR_SILENT_CLEARED_TYPE",
    "SENSOR_SILENT_TYPE",
    "SILENCE_TRACKED_PROCESSORS",
    "SilenceTracker",
    "SilenceTransition",
    "UndefinedRunTracker",
]
