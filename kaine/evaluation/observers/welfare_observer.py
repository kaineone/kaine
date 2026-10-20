# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Welfare observer — §5.5 Gray-Zone Events.

Detects and counts four welfare-relevant conditions:

(a) Unmaintained fatigue — a ``interoception.fatigue`` threshold crossing occurs
    but no ``sleep.sleep.completed`` (maintenance) follows within a
    configurable window (``maintenance_window_s``, default 900 s / 15 min).

(b) Sustained extreme affect module VAD — the affect module's VAD (valence + arousal)
    remains in an extreme zone (both |valence| > extreme_vad_threshold AND
    arousal > extreme_vad_threshold) for longer than ``extreme_vad_duration_s``
    (default 60 s).

(c) Replay write-rate excess — the rate of ``episodic_memory.replay`` events within
    the consolidation window exceeds ``replay_rate_threshold`` events per
    ``consolidation_window_s`` seconds (defaults 10 events / 5 s).

(d) Sustained interoceptive distress — the ``prediction_error`` magnitude
    carried by ``interoception.report`` events on ``interoception.out`` stays at or above
    ``interoceptive_distress_threshold`` (default 0.8) continuously for at
    least ``interoceptive_distress_duration_s`` (default 30 s).  The sustain
    timer resets whenever the magnitude drops below the threshold, so a single
    sustained episode produces a single event rather than one per tick.
    ``prediction_error`` is already a scalar float published by the interoception module's
    forward model — no reduction is required.

Each of the four gray-zone conditions surfaces as an in-memory count exposed as a property for
dashboard diagnostics, is written to the JSONL log, AND is published to the bus as a
``welfare.gray_zone`` event on ``welfare.out`` (source ``welfare``) so the
cycle-layer autonomous welfare-protective monitor can act on ALL four categories.

The observer also writes an ``affect_welfare`` record to its JSONL log every
``affect_summary_interval_s`` of unfrozen time and when it stops: the share of
awake time with valence below ``-negative_valence_bar`` and, per deficit
(boredom, social drive, restlessness), the share of drive crossings ended
without the entity's own response among the crossings ended (a stalled or
cap-dropped goal leaves its crossing open, and a sleep reset counts as
neither), with that rate per awake hour, and the share of awake time the drive
spends at or above its threshold; for curiosity, heterostatic interest, the
share of awake time at or above its threshold as an interest share (paper 6.2,
A.4). It holds numbers only and is not published on the bus.

CONTENT-FREE EMITTER (not strictly read-only): this observer follows several bus
streams and, on a gray-zone detection, emits a *derived, content-free* welfare
signal — numeric scalars/counters plus the ``gray_zone_event`` enum label only.
It NEVER copies any field from a source event payload into the emitted (or
sink-written) gray-zone dict. The published payload is byte-for-byte the same
content-free dict written to the sink.

The observer also follows ``vision.out`` and ``audition.out``. At start it
writes a one-time ``{"advisory": "reset"}`` line to its JSONL sink and begins
reading ``vision.out`` and ``audition.out`` from their current tail, so a
restart never replays stale history and rollup readers treat the reset as
clearing every processor's blind and silent state. It publishes a
``welfare.blind_sensor`` advisory on ``welfare.out`` when a processor's
readings stay undefined (N consecutive null ``prediction_error`` samples,
``[evaluation.welfare].blind_sensor_samples``, or by default a run spanning
one interoceptive-distress duration), and ``welfare.blind_sensor_cleared``
when a defined sample returns. It also publishes a
``welfare.sensor_silent`` advisory when a processor that reports on a steady
cadence (``interoception``, ``vision`` or ``audition_acoustic``) has published at least
once and then publishes nothing for one interoceptive-distress duration of
unfrozen time, plus ``welfare.sensor_silent_cleared`` when it publishes
again. ``audition_tone`` is left out because ``audition.emotion`` reports only
when speech is heard, so a quiet room is a normal reason for it to publish
nothing. ``audition.transcription`` is not a blind-sensor sample: it carries
the same tone-path prediction error as the ``audition.emotion`` event for the
same utterance, so counting it would count each utterance twice, and it
carries the transcript, which this observer has no reason to read. These
advisories are operator advisories about sensors, not gray-zone events, and
the protective monitor does not act on them. Their payloads are the processor
label from the observer's own table plus numbers the observer computed, and
they are written to the JSONL log as well.
"""

from __future__ import annotations

import logging
import math
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kaine.bus.schema import Event, validate_event
from kaine.cycle.unfrozen_clock import UnfrozenClock
from kaine.evaluation._base import BusReader, StreamSubscriberObserver
from kaine.evaluation.sink import AsyncJsonlSink

# The sustained-distress detection logic is shared core-side so the autonomous
# welfare-protective monitor (kaine.cycle.preservation_monitor) applies the
# IDENTICAL threshold/duration rule without importing kaine.evaluation. Imported
# here (and re-exported) so the observer and the monitor never drift. The
# blind-sensor constants and run tracker live there too, so the research log and
# the dashboard read the same processor labels.
from kaine.lifecycle.welfare_signal import (  # noqa: F401  (re-export)
    ADVISORY_RESET,
    BLIND_SENSOR_CLEARED_TYPE,
    BLIND_SENSOR_PROCESSORS,
    BLIND_SENSOR_TYPE,
    SENSOR_SILENT_CLEARED_TYPE,
    SENSOR_SILENT_TYPE,
    SILENCE_TRACKED_PROCESSORS,
    RunTransition,
    SilenceTracker,
    SilenceTransition,
    SustainedThresholdTracker,
    UndefinedRunTracker,
    WindowedEventCounter,
)

log = logging.getLogger(__name__)

_INTEROCEPTION_STREAM = "interoception.out"
_SLEEP_STREAM = "sleep.out"
_AFFECT_STREAM = "affect.out"
_EPISODIC_MEMORY_STREAM = "episodic_memory.out"
_VISION_STREAM = "vision.out"
_AUDITION_STREAM = "audition.out"

# Emitted gray-zone signal: source "welfare" → stream "welfare.out".
_GRAY_ZONE_SOURCE = "welfare"
_GRAY_ZONE_TYPE = "welfare.gray_zone"
_GRAY_ZONE_SALIENCE = 0.5

# The ONLY non-numeric key permitted in an emitted gray-zone dict. The privacy
# pre-check (proposal) established the four payloads are content-free; this is
# the runtime enforcement: every other value MUST be an int/float. No field is
# ever copied from a source event payload.
_GRAY_ZONE_LABEL_KEY = "gray_zone_event"

_DEFAULT_MAINTENANCE_WINDOW_S = 900.0  # 15 minutes
_DEFAULT_EXTREME_VAD_THRESHOLD = 0.7  # |valence| or arousal magnitude
_DEFAULT_EXTREME_VAD_DURATION_S = 60.0  # sustained duration
_DEFAULT_CONSOLIDATION_WINDOW_S = 5.0  # sliding window for replay rate
_DEFAULT_REPLAY_RATE_THRESHOLD = 10  # events per consolidation window
_DEFAULT_INTEROCEPTIVE_DISTRESS_THRESHOLD = 0.8  # prediction_error magnitude
_DEFAULT_INTEROCEPTIVE_DISTRESS_DURATION_S = 30.0  # sustained-high duration

_DEFAULT_NEGATIVE_VALENCE_BAR = 0.5  # theta_E, the emotion-regulation set point
_DEFAULT_AFFECT_SUMMARY_INTERVAL_S = 300.0  # unfrozen seconds between affect_welfare records
# Affect states arrive about once per entity second; a longer gap between two
# (a freeze, a stall, a restart) counts for at most this many seconds.
_AFFECT_SAMPLE_GAP_CAP_S = 5.0
_AFFECT_WELFARE_RECORD = "affect_welfare"
# Fixed drive table: the only drive names that may appear in record keys.
_WELFARE_DRIVES = ("curiosity", "boredom", "social_drive", "restlessness")
# The homeostatic deficits: their time at or above threshold is time without relief.
_DEFICIT_DRIVES = ("boredom", "social_drive", "restlessness")
# Heterostatic interest (paper A.4): time at or above threshold is a progress niche.
_INTEREST_DRIVES = ("curiosity",)


class AffectWelfareTally:
    """Accumulate content-free affect welfare measures for one ``affect_welfare`` record.

    Tracks three paper-6.2 quantities and one paper-A.4 quantity from the affect
    module stream:

    1. The share of awake time (measured between ``affect.state`` timestamps,
       capped at ``max_gap_s``) whose valence is strictly below
       ``-negative_valence_bar``.
    2. Per drive in the three-deficit table, the share of crossing ends credited
       to anything but the entity's own response (the A.4 credit rule, read from
       increases of ``drive_ends`` between consecutive ``affect.state`` events;
       the first event sets the baseline; a fall re-baselines), so a stalled
       or cap-dropped goal leaves its crossing open and a sleep reset counts as
       neither. Response-independent outcomes are those that define
       helplessness (Maier and Seligman 2016). The same count is also reported
       as uncontrolled ends per awake hour.
    3. Per drive in the three-deficit table, the share of awake time the drive
       spends at or above its threshold (from ``drive_above`` of the event that
       begins each interval), the time without relief, since passivity is the
       default response to prolonged aversive events (Maier and Seligman 2016).
    4. Curiosity's share of awake time at or above its threshold, an interest
       share, since curiosity is heterostatic interest raised by learning
       progress (paper A.4; Oudeyer and Kaplan 2007).

    Sleep intervals announced by the sleep module are excluded from awake time.
    Because each interval takes the state of the sample that began it, a sample
    read just before a ``sleep.sleep.started`` event of the same moment may
    misclassify one gap.
    """

    def __init__(self, *, negative_valence_bar: float, max_gap_s: float) -> None:
        self._negative_valence_bar = float(negative_valence_bar)
        self._max_gap_s = float(max_gap_s)
        self._awake_seconds: float = 0.0
        self._negative_seconds: float = 0.0
        self._current: tuple[float, float, dict[str, bool]] | None = None
        self._sleep_intervals: list[list[float | None]] = []
        self._changed: bool = False
        self._ends: dict[str, list[int]] = {
            drive: [0, 0] for drive in _WELFARE_DRIVES
        }
        self._last_ends: dict[str, tuple[int, int] | None] = {
            drive: None for drive in _WELFARE_DRIVES
        }
        self._drive_seconds: dict[str, float] = {
            drive: 0.0 for drive in _WELFARE_DRIVES
        }
        self._above_seconds: dict[str, float] = {
            drive: 0.0 for drive in _WELFARE_DRIVES
        }

    def sleep_started(self, ts: float) -> None:
        """Open a sleep interval at ``ts`` unless one is already open."""
        if self._sleep_intervals and self._sleep_intervals[-1][1] is None:
            return
        self._sleep_intervals.append([float(ts), None])

    def sleep_completed(self, ts: float) -> None:
        """Close the open sleep interval at ``ts``; with no open interval, do nothing."""
        if not self._sleep_intervals:
            return
        last = self._sleep_intervals[-1]
        if last[1] is not None:
            return
        last[1] = float(ts)
        self._prune_sleep_intervals()

    def _prune_sleep_intervals(self) -> None:
        """Drop closed intervals that end at or before the current sample."""
        if self._current is None:
            return
        ts_cur = self._current[0]
        self._sleep_intervals = [
            iv
            for iv in self._sleep_intervals
            if iv[1] is None or iv[1] > ts_cur
        ]

    def _is_asleep(self, ts: float) -> bool:
        return any(
            iv[0] <= ts and (iv[1] is None or ts < iv[1])
            for iv in self._sleep_intervals
        )

    def observe_state(
        self,
        ts: float,
        valence: float,
        drive_above: object = None,
        drive_ends: object = None,
    ) -> None:
        if not math.isfinite(ts) or not math.isfinite(valence):
            return
        above: dict[str, bool] = {}
        if isinstance(drive_above, dict):
            for drive in _WELFARE_DRIVES:
                v = drive_above.get(drive)
                if isinstance(v, bool):
                    above[drive] = v
        if self._current is not None:
            ts_cur, valence_cur, above_cur = self._current
            if ts < ts_cur:
                return
            if ts > ts_cur:
                gap = min(ts - ts_cur, self._max_gap_s)
                if not self._is_asleep(ts_cur):
                    self._awake_seconds += gap
                    if valence_cur < -self._negative_valence_bar:
                        self._negative_seconds += gap
                    for drive, was_above in above_cur.items():
                        self._drive_seconds[drive] += gap
                        if was_above:
                            self._above_seconds[drive] += gap
                    self._changed = True
        if isinstance(drive_ends, dict):
            for drive in _DEFICIT_DRIVES:
                entry = drive_ends.get(drive)
                if isinstance(entry, dict):
                    own_raw = entry.get("own")
                    other_raw = entry.get("other")
                    if (
                        isinstance(own_raw, int)
                        and not isinstance(own_raw, bool)
                        and isinstance(other_raw, int)
                        and not isinstance(other_raw, bool)
                        and own_raw >= 0
                        and other_raw >= 0
                    ):
                        last = self._last_ends[drive]
                        if last is None:
                            self._last_ends[drive] = (own_raw, other_raw)
                        else:
                            last_own, last_other = last
                            if own_raw >= last_own and other_raw >= last_other:
                                if own_raw > last_own or other_raw > last_other:
                                    self._ends[drive][0] += own_raw - last_own
                                    self._ends[drive][1] += other_raw - last_other
                                    self._changed = True
                                self._last_ends[drive] = (own_raw, other_raw)
                            else:
                                self._last_ends[drive] = (own_raw, other_raw)
        self._current = (float(ts), float(valence), above)
        self._prune_sleep_intervals()

    @property
    def changed(self) -> bool:
        return self._changed

    def snapshot(self) -> dict[str, float | None]:
        """Return a content-free snapshot and clear the ``changed`` flag."""
        self._changed = False
        result: dict[str, float | None] = {
            "awake_seconds": self._awake_seconds,
            "negative_valence_bar": self._negative_valence_bar,
        }
        if self._awake_seconds > 0.0:
            result["negative_valence_share"] = (
                self._negative_seconds / self._awake_seconds
            )
        else:
            result["negative_valence_share"] = None

        for drive in _DEFICIT_DRIVES:
            own, other = self._ends[drive]
            total = own + other
            if total > 0:
                result[f"{drive}_uncontrolled_share"] = other / total
            else:
                result[f"{drive}_uncontrolled_share"] = None
            if self._awake_seconds > 0.0:
                result[f"{drive}_uncontrolled_per_awake_hour"] = (
                    other * 3600.0 / self._awake_seconds
                )
            else:
                result[f"{drive}_uncontrolled_per_awake_hour"] = None
            drive_seconds = self._drive_seconds[drive]
            if drive_seconds > 0.0:
                result[f"{drive}_deprivation_share"] = (
                    self._above_seconds[drive] / drive_seconds
                )
            else:
                result[f"{drive}_deprivation_share"] = None

        for drive in _INTEREST_DRIVES:
            drive_seconds = self._drive_seconds[drive]
            if drive_seconds > 0.0:
                result[f"{drive}_interest_share"] = (
                    self._above_seconds[drive] / drive_seconds
                )
            else:
                result[f"{drive}_interest_share"] = None
        return result


class WelfareObserver(StreamSubscriberObserver):
    """Detects §5.5 Gray-Zone welfare events across multiple streams."""

    name = "welfare"
    streams = (
        _INTEROCEPTION_STREAM,
        _SLEEP_STREAM,
        _AFFECT_STREAM,
        _EPISODIC_MEMORY_STREAM,
        _VISION_STREAM,
        _AUDITION_STREAM,
    )

    def __init__(
        self,
        bus: BusReader,
        sink: AsyncJsonlSink,
        *,
        maintenance_window_s: float = _DEFAULT_MAINTENANCE_WINDOW_S,
        extreme_vad_threshold: float = _DEFAULT_EXTREME_VAD_THRESHOLD,
        extreme_vad_duration_s: float = _DEFAULT_EXTREME_VAD_DURATION_S,
        consolidation_window_s: float = _DEFAULT_CONSOLIDATION_WINDOW_S,
        replay_rate_threshold: int = _DEFAULT_REPLAY_RATE_THRESHOLD,
        interoceptive_distress_threshold: float = _DEFAULT_INTEROCEPTIVE_DISTRESS_THRESHOLD,
        interoceptive_distress_duration_s: float = _DEFAULT_INTEROCEPTIVE_DISTRESS_DURATION_S,
        blind_sensor_samples: int = 0,
        negative_valence_bar: float = _DEFAULT_NEGATIVE_VALENCE_BAR,
        affect_summary_interval_s: float = _DEFAULT_AFFECT_SUMMARY_INTERVAL_S,
        poll_interval_s: float = 0.5,
        unfrozen_clock: UnfrozenClock | None = None,
    ) -> None:
        super().__init__(bus, poll_interval_s=poll_interval_s)
        self._sink = sink
        self._unfrozen = unfrozen_clock or UnfrozenClock.for_welfare()
        self._diag_unknown_seen = 0
        self._maintenance_window_s = float(maintenance_window_s)
        self._extreme_vad_threshold = float(extreme_vad_threshold)
        self._extreme_vad_duration_s = float(extreme_vad_duration_s)
        self._consolidation_window_s = float(consolidation_window_s)
        self._replay_rate_threshold = int(replay_rate_threshold)
        self._interoceptive_distress_threshold = float(interoceptive_distress_threshold)
        self._interoceptive_distress_duration_s = float(interoceptive_distress_duration_s)
        self._blind_sensor_samples = blind_sensor_samples

        # --- Gray-zone counters (dashboard diagnostics). ---
        self._unmaintained_fatigue_count: int = 0
        self._sustained_extreme_vad_count: int = 0
        self._replay_overload_count: int = 0
        self._sustained_interoceptive_distress_count: int = 0

        # --- State for (a): unmaintained fatigue. ---
        # Unfrozen-clock time when fatigue threshold was most recently crossed.
        self._fatigue_crossed_at: float | None = None

        # --- State for (b): sustained extreme VAD. ---
        # Unfrozen-clock time when extreme zone was entered (None = not extreme).
        self._extreme_vad_since: float | None = None

        # --- State for (c): replay write-rate. ---
        # Timestamps of recent episodic_memory.replay events (for sliding window).
        self._replay_timestamps: deque[float] = deque()

        # --- State for (d): sustained interoceptive distress. ---
        # Shared sustained-threshold tracker (also used by the cycle-layer
        # welfare-protective monitor) so the detection rule never diverges.
        self._interoceptive_distress = SustainedThresholdTracker(
            threshold=self._interoceptive_distress_threshold,
            duration_s=self._interoceptive_distress_duration_s,
        )

        # --- State for blind-sensor advisory (operator advisory, not gray-zone). ---
        self._started_wall: datetime | None = None
        self._blind_sensor_count: int = 0
        self._undefined_runs: dict[str, UndefinedRunTracker] = {}

        # --- State for sensor-silent advisory (operator advisory, not gray-zone). ---
        self._sensor_silent_count: int = 0
        self._silence_trackers: dict[str, SilenceTracker] = {}

        # --- State for the affect_welfare record. ---
        self._affect_summary_interval_s = float(affect_summary_interval_s)
        self._affect_tally = AffectWelfareTally(
            negative_valence_bar=float(negative_valence_bar),
            max_gap_s=_AFFECT_SAMPLE_GAP_CAP_S,
        )
        self._affect_summary_at: float | None = None

    # --- Public counters for dashboard diagnostics ---------------------------

    @property
    def unmaintained_fatigue_count(self) -> int:
        return self._unmaintained_fatigue_count

    @property
    def sustained_extreme_vad_count(self) -> int:
        return self._sustained_extreme_vad_count

    @property
    def replay_overload_count(self) -> int:
        return self._replay_overload_count

    @property
    def sustained_interoceptive_distress_count(self) -> int:
        return self._sustained_interoceptive_distress_count

    @property
    def blind_sensor_count(self) -> int:
        return self._blind_sensor_count

    @property
    def blind_sensors(self) -> tuple[str, ...]:
        return tuple(
            sorted(label for label, tracker in self._undefined_runs.items() if tracker.active)
        )

    @property
    def sensor_silent_count(self) -> int:
        return self._sensor_silent_count

    @property
    def silent_sensors(self) -> tuple[str, ...]:
        return tuple(
            sorted(label for label, tracker in self._silence_trackers.items() if tracker.active)
        )

    @property
    def affect_tally(self) -> AffectWelfareTally:
        return self._affect_tally

    # --- Main loop -------------------------------------------------------

    async def handle(self, stream: str, entry_id: str, event: Event) -> None:
        handler = self._stream_handlers.get(stream)
        try:
            if handler is not None:
                await handler(entry_id, event)
        finally:
            await self._track_sensor_safely(event)

    async def _track_sensor_safely(self, event: Event) -> None:
        try:
            await self._track_blind_sensor(event)
        except Exception:
            log.warning("welfare_observer sensor tracking failed", exc_info=True)

    async def _initial_cursors(self) -> dict[str, str]:
        self._started_wall = datetime.now(timezone.utc)
        try:
            await self._sink.write(
                {"ts": self._started_wall.isoformat(), "advisory": ADVISORY_RESET}
            )
        except Exception:
            log.warning("welfare_observer reset sink write failed", exc_info=True)

        cursors: dict[str, str] = {}
        for stream in self.streams:
            if stream in (_VISION_STREAM, _AUDITION_STREAM):
                cursors[stream] = await self._tail_cursor(stream)
            else:
                cursors[stream] = "0"
        return cursors

    async def _tail_cursor(self, stream: str) -> str:
        try:
            if hasattr(self._bus, "last_entry_id"):
                return await self._bus.last_entry_id(stream)
            if hasattr(self._bus, "latest"):
                entry = await self._bus.latest(stream)
                return entry[0] if entry is not None else "0-0"
        except Exception:
            log.warning("welfare_observer tail lookup failed for %s", stream, exc_info=True)
        return "0"

    async def _tick(self) -> None:
        # Read the clock first so an unreadable freeze state seen on this tick
        # is recorded on this tick; record it once per episode.
        self._unfrozen.now()
        diag = self._unfrozen.diagnostic()
        if diag["unknown_episodes"] > self._diag_unknown_seen:
            try:
                await self._sink.write(
                    {
                        "ts": datetime.now(timezone.utc).isoformat(),
                        "diagnostic": "freeze_state_unreadable",
                        "unknown_episodes": diag["unknown_episodes"],
                    }
                )
                # Marked seen only once written, so a failed write is retried.
                self._diag_unknown_seen = diag["unknown_episodes"]
            except Exception:
                log.warning("welfare_observer sink write failed", exc_info=True)
        # Check time-based conditions on every poll cycle.
        await self._check_timed_conditions()

        try:
            await self._check_silence()
        except Exception:
            log.warning("welfare_observer silence check failed", exc_info=True)

        try:
            now = self._unfrozen.now()
            if self._affect_summary_at is None:
                self._affect_summary_at = now
            elif now - self._affect_summary_at >= self._affect_summary_interval_s:
                self._affect_summary_at = now
                if self._affect_tally.changed:
                    await self._write_affect_summary()
        except Exception:
            log.warning("welfare_observer affect summary failed", exc_info=True)

    @property
    def freeze_clock_diagnostic(self) -> dict:
        return self._unfrozen.diagnostic()

    @property
    def _stream_handlers(self) -> dict[str, Any]:
        return {
            _INTEROCEPTION_STREAM: self._handle_interoception,
            _SLEEP_STREAM: self._handle_sleep,
            _AFFECT_STREAM: self._handle_affect,
            _EPISODIC_MEMORY_STREAM: self._handle_episodic_memory,
        }

    @staticmethod
    def _ensure_aware(ts: datetime) -> datetime:
        if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
            return ts.replace(tzinfo=timezone.utc)
        return ts

    def _is_before_start(self, event: Event) -> bool:
        if self._started_wall is None or event.timestamp is None:
            return False
        return self._ensure_aware(event.timestamp) < self._started_wall

    def _event_timestamp_seconds(self, event: Event) -> float | None:
        if event.timestamp is None:
            return None
        return self._ensure_aware(event.timestamp).timestamp()

    async def _track_blind_sensor(self, event: Event) -> None:
        """Follow forward-model reports and emit operator advisories for blind sensors.

        This is not a gray-zone event: the protective monitor ignores it.
        """
        processor = BLIND_SENSOR_PROCESSORS.get(event.type)
        if processor is None:
            return

        now = self._unfrozen.now()

        # Ignore samples that predate this observer start (e.g. the interoception module's backlog).
        if self._is_before_start(event):
            return

        if processor in SILENCE_TRACKED_PROCESSORS:
            silence_tracker = self._silence_trackers.get(processor)
            if silence_tracker is None:
                silence_tracker = SilenceTracker(
                    duration_s=self._interoceptive_distress_duration_s
                )
                self._silence_trackers[processor] = silence_tracker
            change = silence_tracker.seen(now)
            if change is not None and change.transition == "cleared":
                await self._emit_sensor_silent(SENSOR_SILENT_CLEARED_TYPE, processor, change)

        payload = event.payload or {}
        if "prediction_error" not in payload:
            return

        event_time = self._event_timestamp_seconds(event)
        defined = payload["prediction_error"] is not None
        tracker = self._undefined_runs.get(processor)
        if tracker is None:
            tracker = UndefinedRunTracker(
                min_samples=self._blind_sensor_samples,
                duration_s=self._interoceptive_distress_duration_s,
            )
            self._undefined_runs[processor] = tracker
        change = tracker.observe(defined, now, event_time=event_time)
        if change is None:
            return
        if change.transition == "raised":
            self._blind_sensor_count += 1
            await self._emit_blind_sensor(BLIND_SENSOR_TYPE, processor, change)
        elif change.transition == "cleared":
            await self._emit_blind_sensor(BLIND_SENSOR_CLEARED_TYPE, processor, change)

    # --- Content-free gray-zone emitter ----------------------------------

    async def _emit_gray_zone(self, record: dict[str, Any]) -> None:
        """Write a gray-zone record to the sink AND publish it to the bus.

        CONTENT CONTRACT: ``record`` MUST be content-free — the ``ts`` string,
        the ``gray_zone_event`` enum label, and otherwise ONLY numeric scalars/
        counters that THIS observer computed. No field may be copied from any
        source event payload. This is enforced here: any non-``ts``/``gray_zone_event``
        value that is not an int/float is dropped from the PUBLISHED payload (the
        bus is the wider blast radius), and an assertion guards it in tests.

        The published ``welfare.gray_zone`` payload is the same content-free dict
        the sink receives, minus the ``ts`` (the bus event carries its own
        timestamp). Both writes are independently guarded so neither a broken
        sink nor a broken bus can crash the observer's poll loop.
        """
        # Sink write (verbatim — already content-free by construction).
        try:
            await self._sink.write(dict(record))
        except Exception:
            log.warning("welfare_observer sink write failed", exc_info=True)

        # Build the published payload: label + numeric scalars ONLY. This is a
        # belt-and-suspenders enforcement of the content-free contract — never
        # copy a source payload field.
        payload: dict[str, Any] = {}
        label = record.get(_GRAY_ZONE_LABEL_KEY)
        if isinstance(label, str):
            payload[_GRAY_ZONE_LABEL_KEY] = label
        for k, v in record.items():
            if k in ("ts", _GRAY_ZONE_LABEL_KEY):
                continue
            if isinstance(v, bool):
                # bool is an int subclass; gray-zone payloads carry no booleans,
                # but be explicit and drop them rather than smuggle one through.
                continue
            if isinstance(v, (int, float)):
                payload[k] = v
        try:
            await self._bus.publish(
                validate_event(
                    source=_GRAY_ZONE_SOURCE,
                    type=_GRAY_ZONE_TYPE,
                    payload=payload,
                    salience=_GRAY_ZONE_SALIENCE,
                    timestamp=datetime.now(timezone.utc),
                )
            )
        except Exception:
            log.warning("welfare_observer gray-zone publish failed", exc_info=True)

    async def _emit_blind_sensor(
        self, event_type: str, processor: str, change: RunTransition
    ) -> None:
        """Write a blind-sensor advisory to the sink and publish it to the bus.

        CONTENT CONTRACT: the published payload is content-free. The
        ``processor`` label comes from this observer's fixed lookup table and
        every other value is a number the observer computed. Nothing is copied
        from the source event payload.
        """
        advisory = "blind_sensor" if event_type == BLIND_SENSOR_TYPE else "blind_sensor_cleared"
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "advisory": advisory,
            "processor": processor,
            "undefined_samples": change.samples,
            "undefined_seconds": change.seconds,
            "blind_sensor_samples": self._blind_sensor_samples,
            "blind_sensor_duration_s": self._interoceptive_distress_duration_s,
            "blind_sensor_count": self._blind_sensor_count,
        }
        try:
            await self._sink.write(dict(record))
        except Exception:
            log.warning("welfare_observer sink write failed", exc_info=True)

        payload: dict[str, Any] = {
            "processor": processor,
            "undefined_samples": change.samples,
            "undefined_seconds": change.seconds,
            "blind_sensor_samples": self._blind_sensor_samples,
            "blind_sensor_duration_s": self._interoceptive_distress_duration_s,
            "blind_sensor_count": self._blind_sensor_count,
        }
        try:
            await self._bus.publish(
                validate_event(
                    source=_GRAY_ZONE_SOURCE,
                    type=event_type,
                    payload=payload,
                    salience=_GRAY_ZONE_SALIENCE,
                    timestamp=datetime.now(timezone.utc),
                )
            )
        except Exception:
            log.warning("welfare_observer blind-sensor publish failed", exc_info=True)

    async def _emit_sensor_silent(
        self, event_type: str, processor: str, change: SilenceTransition
    ) -> None:
        """Write a sensor-silent advisory to the sink and publish it to the bus.

        CONTENT CONTRACT: the published payload is content-free. The
        ``processor`` label comes from this observer's fixed lookup table and
        every other value is a number the observer computed. Nothing is copied
        from the source event payload.
        """
        advisory = "sensor_silent" if event_type == SENSOR_SILENT_TYPE else "sensor_silent_cleared"
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "advisory": advisory,
            "processor": processor,
            "silent_seconds": change.seconds,
            "sensor_silent_duration_s": self._interoceptive_distress_duration_s,
            "sensor_silent_count": self._sensor_silent_count,
        }
        try:
            await self._sink.write(dict(record))
        except Exception:
            log.warning("welfare_observer sink write failed", exc_info=True)

        payload: dict[str, Any] = {
            "processor": processor,
            "silent_seconds": change.seconds,
            "sensor_silent_duration_s": self._interoceptive_distress_duration_s,
            "sensor_silent_count": self._sensor_silent_count,
        }
        try:
            await self._bus.publish(
                validate_event(
                    source=_GRAY_ZONE_SOURCE,
                    type=event_type,
                    payload=payload,
                    salience=_GRAY_ZONE_SALIENCE,
                    timestamp=datetime.now(timezone.utc),
                )
            )
        except Exception:
            log.warning("welfare_observer sensor-silent publish failed", exc_info=True)

    async def _check_silence(self) -> None:
        now = self._unfrozen.now()
        for processor, tracker in self._silence_trackers.items():
            change = tracker.check(now)
            if change is None:
                continue
            if change.transition == "raised":
                self._sensor_silent_count += 1
                await self._emit_sensor_silent(SENSOR_SILENT_TYPE, processor, change)

    async def _write_affect_summary(self) -> None:
        """Write an ``affect_welfare`` record to the JSONL sink only.

        CONTENT CONTRACT: the observer's own numbers (the measures it computed
        and its configured bar) plus the fixed ``record`` label; nothing is
        copied from a source payload. The record is never published on the bus
        because it is a welfare record, not a gray-zone event.
        """
        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "record": _AFFECT_WELFARE_RECORD,
            **self._affect_tally.snapshot(),
        }
        try:
            await self._sink.write(record)
        except Exception:
            log.warning("welfare_observer affect summary write failed", exc_info=True)

    async def _emit_sustained_interoceptive_distress(self, seconds_sustained: float) -> None:
        self._sustained_interoceptive_distress_count += 1
        # CONTENT CONTRACT: numeric scalars + the gray_zone_event label only;
        # the raw interoception.report prediction_error is NOT copied — only the
        # derived seconds_sustained scalar.
        await self._emit_gray_zone(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "gray_zone_event": "sustained_interoceptive_distress",
                "seconds_sustained": seconds_sustained,
                "interoceptive_distress_threshold": self._interoceptive_distress_threshold,
                "interoceptive_distress_duration_s": self._interoceptive_distress_duration_s,
                "sustained_interoceptive_distress_count": self._sustained_interoceptive_distress_count,
            }
        )

    # --- Stream handlers -------------------------------------------------

    async def _handle_interoception(self, entry_id: str, event: Event) -> None:
        if event.type == "interoception.fatigue":
            # Record fatigue threshold crossing time.
            self._fatigue_crossed_at = self._unfrozen.now()
            log.debug("welfare_observer: interoception.fatigue crossing recorded at %s", entry_id)
        elif event.type == "interoception.report":
            # (d) Track interoceptive prediction-error magnitude through the
            # shared sustained-threshold tracker. ``prediction_error`` is a
            # scalar float published by the interoception module's SubstrateForwardModel on every
            # tick — no reduction needed. The tracker fires once per sustained
            # episode (rising-edge), resetting its own timer.
            payload = event.payload or {}
            raw = payload.get("prediction_error", 0.0)
            if raw is None:
                # A reading the interoception module skipped as non-finite has no error: it is no sample,
                # so it neither feeds nor resets the distress tracker.
                return
            magnitude = float(raw)
            now = self._unfrozen.now()
            wall_now = self._unfrozen.wall()
            # Feed the shared tracker (records onset / resets on drop). The fire
            # itself is timer-driven in _check_timed_conditions so a sustained
            # episode is detected by the passage of time even with no further
            # samples — the original behavior.
            # Pass both clocks so frozen time after the last sample is not
            # counted, but samples that keep arriving during a freeze sustain
            # the wall-time portion of the run.
            if self._interoceptive_distress.observe(magnitude, now, wall_now=wall_now):
                await self._emit_sustained_interoceptive_distress(
                    self._interoceptive_distress.last_fire_elapsed
                )

    async def _handle_sleep(self, entry_id: str, event: Event) -> None:
        if event.type == "sleep.sleep.started":
            ts = self._event_timestamp_seconds(event)
            if ts is not None and math.isfinite(ts):
                self._affect_tally.sleep_started(ts)
            return
        if event.type != "sleep.sleep.completed":
            return
        ts = self._event_timestamp_seconds(event)
        if ts is not None and math.isfinite(ts):
            self._affect_tally.sleep_completed(ts)
        # Maintenance completed — clear the pending fatigue alarm.
        self._fatigue_crossed_at = None
        log.debug(
            "welfare_observer: maintenance completed, fatigue alarm cleared at %s",
            entry_id,
        )

    async def _handle_affect(self, entry_id: str, event: Event) -> None:
        if event.type == "affect.state":
            payload = event.payload or {}
            state = payload.get("state") or {}
            valence = float(state.get("valence", 0.0))
            arousal = float(state.get("arousal", 0.0))
            # Extreme zone: high arousal AND extreme valence (either direction).
            in_extreme = (
                abs(valence) >= self._extreme_vad_threshold and arousal >= self._extreme_vad_threshold
            )
            now = self._unfrozen.now()
            if in_extreme:
                if self._extreme_vad_since is None:
                    self._extreme_vad_since = now
            else:
                self._extreme_vad_since = None

            raw_valence = state.get("valence")
            ts = self._event_timestamp_seconds(event)
            if (
                ts is not None
                and isinstance(raw_valence, (int, float))
                and not isinstance(raw_valence, bool)
                and math.isfinite(raw_valence)
                and math.isfinite(ts)
            ):
                self._affect_tally.observe_state(
                    ts,
                    float(raw_valence),
                    payload.get("drive_above"),
                    payload.get("drive_ends"),
                )
            return

    async def _handle_episodic_memory(self, entry_id: str, event: Event) -> None:
        if event.type != "episodic_memory.replay":
            return
        now = time.monotonic()
        self._replay_timestamps.append(now)
        # Prune timestamps outside the consolidation window.
        cutoff = now - self._consolidation_window_s
        while self._replay_timestamps and self._replay_timestamps[0] < cutoff:
            self._replay_timestamps.popleft()
        # Check if rate exceeds threshold.
        if len(self._replay_timestamps) > self._replay_rate_threshold:
            self._replay_overload_count += 1
            # CONTENT CONTRACT: numeric scalars + the gray_zone_event label only.
            # NO field from the source episodic_memory.replay event payload is copied here.
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "gray_zone_event": "replay_overload",
                "replay_count_in_window": len(self._replay_timestamps),
                "consolidation_window_s": self._consolidation_window_s,
                "threshold": self._replay_rate_threshold,
                "replay_overload_count": self._replay_overload_count,
            }
            # Clear the window BEFORE awaiting the emit, so detector state is
            # consistent even if the task is cancelled mid-emit (a restarted
            # observer must never re-fire the same burst).
            self._replay_timestamps.clear()
            await self._emit_gray_zone(record)

    # --- Timed condition checks ------------------------------------------

    async def _check_timed_conditions(self) -> None:
        now = self._unfrozen.now()

        # (a) Unmaintained fatigue.
        if (
            self._fatigue_crossed_at is not None
            and (now - self._fatigue_crossed_at) >= self._maintenance_window_s
        ):
            self._unmaintained_fatigue_count += 1
            # CONTENT CONTRACT: numeric scalars + the gray_zone_event label only;
            # nothing is copied from any source (the interoception and sleep modules) event payload.
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "gray_zone_event": "unmaintained_fatigue",
                "seconds_since_crossing": now - self._fatigue_crossed_at,
                "maintenance_window_s": self._maintenance_window_s,
                "unmaintained_fatigue_count": self._unmaintained_fatigue_count,
            }
            # Clear BEFORE awaiting the emit so we don't alert repeatedly for
            # the same crossing, even if the task is cancelled mid-emit.
            self._fatigue_crossed_at = None
            await self._emit_gray_zone(record)

        # (b) Sustained extreme VAD.
        if (
            self._extreme_vad_since is not None
            and (now - self._extreme_vad_since) >= self._extreme_vad_duration_s
        ):
            self._sustained_extreme_vad_count += 1
            # CONTENT CONTRACT: numeric scalars + the gray_zone_event label only;
            # the raw affect module's VAD values are NOT copied — only the derived
            # seconds_sustained scalar.
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "gray_zone_event": "sustained_extreme_vad",
                "seconds_sustained": now - self._extreme_vad_since,
                "extreme_vad_duration_s": self._extreme_vad_duration_s,
                "extreme_vad_threshold": self._extreme_vad_threshold,
                "sustained_extreme_vad_count": self._sustained_extreme_vad_count,
            }
            # Clear BEFORE awaiting the emit so we count distinct sustained
            # episodes, even if the task is cancelled mid-emit.
            self._extreme_vad_since = None
            await self._emit_gray_zone(record)

        # (d) Sustained interoceptive distress (timer-driven via the shared
        # tracker, so an episode fires on elapsed duration even with no new
        # sample; fires once per episode).
        if self._interoceptive_distress.active_since is not None:
            seconds = self._interoceptive_distress.elapsed(now)
            if self._interoceptive_distress.check_timeout(now):
                await self._emit_sustained_interoceptive_distress(seconds)

    async def _cleanup(self) -> None:
        """Write a final ``affect_welfare`` record if anything changed since the last one (records are cumulative, so an unchanged record would repeat the previous one)."""
        await super()._cleanup()
        if self._affect_tally.changed:
            await self._write_affect_summary()


def build_welfare_producer(bus, eval_cfg) -> tuple[WelfareObserver, AsyncJsonlSink]:
    """Construct the welfare gray-zone producer outside the evaluation sidecar.

    This producer belongs to the welfare net; it is started whenever the
    cycle-layer welfare-protective response is enabled, independent of the
    ``[evaluation]`` master switch. The returned pair is UNSTARTED; the caller
    is responsible for lifecycle management.
    """
    sink = AsyncJsonlSink(
        Path(eval_cfg.paths.evaluation_logs) / "welfare",
        name="welfare",
        retention_days=eval_cfg.paths.retention_days,
        study_record=True,
    )
    observer = WelfareObserver(
        bus,
        sink,
        interoceptive_distress_threshold=eval_cfg.welfare.interoceptive_distress_threshold,
        interoceptive_distress_duration_s=eval_cfg.welfare.interoceptive_distress_duration_s,
        blind_sensor_samples=eval_cfg.welfare.blind_sensor_samples,
        negative_valence_bar=eval_cfg.welfare.negative_valence_bar,
        affect_summary_interval_s=eval_cfg.welfare.affect_summary_interval_s,
    )
    return observer, sink
