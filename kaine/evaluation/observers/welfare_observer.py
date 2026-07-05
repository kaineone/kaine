# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Welfare observer — §5.5 Gray-Zone Events.

Detects and counts four welfare-relevant conditions:

(a) Unmaintained fatigue — a ``soma.fatigue`` threshold crossing occurs
    but no ``hypnos.sleep.completed`` (maintenance) follows within a
    configurable window (``maintenance_window_s``, default 900 s / 15 min).

(b) Sustained extreme Thymos VAD — the Thymos VAD (valence + arousal)
    remains in an extreme zone (both |valence| > extreme_vad_threshold AND
    arousal > extreme_vad_threshold) for longer than ``extreme_vad_duration_s``
    (default 60 s).

(c) Replay write-rate excess — the rate of ``mnemos.replay`` events within
    the consolidation window exceeds ``replay_rate_threshold`` events per
    ``consolidation_window_s`` seconds (defaults 10 events / 5 s).

(d) Sustained interoceptive distress — the ``prediction_error`` magnitude
    carried by ``soma.report`` events on ``soma.out`` stays at or above
    ``interoceptive_distress_threshold`` (default 0.8) continuously for at
    least ``interoceptive_distress_duration_s`` (default 30 s).  The sustain
    timer resets whenever the magnitude drops below the threshold, so a single
    sustained episode produces a single event rather than one per tick.
    ``prediction_error`` is already a scalar float published by Soma's
    forward model — no reduction is required.

Each event type surfaces as an in-memory count exposed as a property for
Nexus diagnostics, is written to the JSONL log, AND is published to the bus as a
``welfare.gray_zone`` event on ``welfare.out`` (source ``welfare``) so the
cycle-layer autonomous welfare-protective monitor can act on ALL four categories.

CONTENT-FREE EMITTER (not strictly read-only): this observer follows several bus
streams and, on a gray-zone detection, emits a *derived, content-free* welfare
signal — numeric scalars/counters plus the ``gray_zone_event`` enum label only.
It NEVER copies any field from a source event payload into the emitted (or
sink-written) gray-zone dict. The published payload is byte-for-byte the same
content-free dict written to the sink.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any

from kaine.bus.schema import Event, validate_event
from kaine.evaluation._base import BaseObserver, BusReader
from kaine.evaluation.sink import AsyncJsonlSink

# The sustained-distress detection logic is shared core-side so the autonomous
# welfare-protective monitor (kaine.cycle.preservation_monitor) applies the
# IDENTICAL threshold/duration rule without importing kaine.evaluation. Imported
# here (and re-exported) so the observer and the monitor never drift.
from kaine.lifecycle.welfare_signal import (  # noqa: F401  (re-export)
    SustainedThresholdTracker,
    WindowedEventCounter,
)

log = logging.getLogger(__name__)

_SOMA_STREAM = "soma.out"
_HYPNOS_STREAM = "hypnos.out"
_THYMOS_STREAM = "thymos.out"
_MNEMOS_STREAM = "mnemos.out"

# Emitted gray-zone signal: source "welfare" → stream "welfare.out".
_GRAY_ZONE_SOURCE = "welfare"
_GRAY_ZONE_TYPE = "welfare.gray_zone"
_GRAY_ZONE_SALIENCE = 0.5

# The ONLY non-numeric key permitted in an emitted gray-zone dict. The privacy
# pre-check (proposal) established the four payloads are content-free; this is
# the runtime enforcement: every other value MUST be an int/float. No field is
# ever copied from a source event payload.
_GRAY_ZONE_LABEL_KEY = "gray_zone_event"

_DEFAULT_MAINTENANCE_WINDOW_S = 900.0      # 15 minutes
_DEFAULT_EXTREME_VAD_THRESHOLD = 0.7       # |valence| or arousal magnitude
_DEFAULT_EXTREME_VAD_DURATION_S = 60.0     # sustained duration
_DEFAULT_CONSOLIDATION_WINDOW_S = 5.0      # sliding window for replay rate
_DEFAULT_REPLAY_RATE_THRESHOLD = 10        # events per consolidation window
_DEFAULT_INTEROCEPTIVE_DISTRESS_THRESHOLD = 0.8   # prediction_error magnitude
_DEFAULT_INTEROCEPTIVE_DISTRESS_DURATION_S = 30.0  # sustained-high duration


class WelfareObserver(BaseObserver):
    """Detects §5.5 Gray-Zone welfare events across multiple streams."""

    name = "welfare"

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
        poll_interval_s: float = 0.5,
    ) -> None:
        super().__init__()
        self._bus = bus
        self._sink = sink
        self._maintenance_window_s = float(maintenance_window_s)
        self._extreme_vad_threshold = float(extreme_vad_threshold)
        self._extreme_vad_duration_s = float(extreme_vad_duration_s)
        self._consolidation_window_s = float(consolidation_window_s)
        self._replay_rate_threshold = int(replay_rate_threshold)
        self._interoceptive_distress_threshold = float(interoceptive_distress_threshold)
        self._interoceptive_distress_duration_s = float(interoceptive_distress_duration_s)
        self._poll_interval_s = float(poll_interval_s)

        # Cursors per stream.
        self._cursors: dict[str, str] = {
            _SOMA_STREAM: "0",
            _HYPNOS_STREAM: "0",
            _THYMOS_STREAM: "0",
            _MNEMOS_STREAM: "0",
        }

        # --- Gray-zone counters (Nexus diagnostics). ---
        self._unmaintained_fatigue_count: int = 0
        self._sustained_extreme_vad_count: int = 0
        self._replay_overload_count: int = 0
        self._sustained_interoceptive_distress_count: int = 0

        # --- State for (a): unmaintained fatigue. ---
        # Wall-clock time when fatigue threshold was most recently crossed.
        self._fatigue_crossed_at: float | None = None

        # --- State for (b): sustained extreme VAD. ---
        # Wall-clock time when extreme zone was entered (None = not extreme).
        self._extreme_vad_since: float | None = None

        # --- State for (c): replay write-rate. ---
        # Timestamps of recent mnemos.replay events (for sliding window).
        self._replay_timestamps: deque[float] = deque()

        # --- State for (d): sustained interoceptive distress. ---
        # Shared sustained-threshold tracker (also used by the cycle-layer
        # welfare-protective monitor) so the detection rule never diverges.
        self._interoceptive_distress = SustainedThresholdTracker(
            threshold=self._interoceptive_distress_threshold,
            duration_s=self._interoceptive_distress_duration_s,
        )

    # --- Public counters for Nexus diagnostics ---------------------------

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

    # --- Main loop -------------------------------------------------------

    async def _run(self) -> None:
        streams = [
            (_SOMA_STREAM, self._handle_soma),
            (_HYPNOS_STREAM, self._handle_hypnos),
            (_THYMOS_STREAM, self._handle_thymos),
            (_MNEMOS_STREAM, self._handle_mnemos),
        ]
        while not self._stopped.is_set():
            for stream, handler in streams:
                try:
                    entries, last_scanned = await self._bus.read_entries(
                        stream,
                        last_id=self._cursors[stream],
                        count=64,
                        block_ms=0,
                    )
                except Exception:
                    log.warning(
                        "welfare_observer read failed for %s", stream, exc_info=True
                    )
                    entries = []
                    last_scanned = None
                for entry_id, event in entries:
                    self._cursors[stream] = entry_id
                    try:
                        await handler(entry_id, event)
                    except Exception:
                        log.warning(
                            "welfare_observer handler raised on %s / %s",
                            stream,
                            entry_id,
                            exc_info=True,
                        )
                if last_scanned is not None:
                    self._cursors[stream] = last_scanned

            # Check time-based conditions on every poll.
            await self._check_timed_conditions()

            try:
                await asyncio.wait_for(
                    self._stopped.wait(), timeout=self._poll_interval_s
                )
            except asyncio.TimeoutError:
                continue

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

    # --- Stream handlers -------------------------------------------------

    async def _handle_soma(self, entry_id: str, event: Event) -> None:
        if event.type == "soma.fatigue":
            # Record fatigue threshold crossing time.
            self._fatigue_crossed_at = time.monotonic()
            log.debug(
                "welfare_observer: soma.fatigue crossing recorded at %s", entry_id
            )
        elif event.type == "soma.report":
            # (d) Track interoceptive prediction-error magnitude through the
            # shared sustained-threshold tracker. ``prediction_error`` is a
            # scalar float published by Soma's SubstrateForwardModel on every
            # tick — no reduction needed. The tracker fires once per sustained
            # episode (rising-edge), resetting its own timer.
            payload = event.payload or {}
            magnitude = float(payload.get("prediction_error", 0.0))
            now = time.monotonic()
            # Feed the shared tracker (records onset / resets on drop). The fire
            # itself is timer-driven in _check_timed_conditions so a sustained
            # episode is detected by the passage of time even with no further
            # samples — the original behavior.
            self._interoceptive_distress.observe(magnitude, now)

    async def _handle_hypnos(self, entry_id: str, event: Event) -> None:
        if event.type != "hypnos.sleep.completed":
            return
        # Maintenance completed — clear the pending fatigue alarm.
        self._fatigue_crossed_at = None
        log.debug(
            "welfare_observer: maintenance completed, fatigue alarm cleared at %s",
            entry_id,
        )

    async def _handle_thymos(self, entry_id: str, event: Event) -> None:
        if event.type != "thymos.state":
            return
        payload = event.payload or {}
        state = payload.get("state") or {}
        valence = float(state.get("valence", 0.0))
        arousal = float(state.get("arousal", 0.0))
        # Extreme zone: high arousal AND extreme valence (either direction).
        in_extreme = (
            abs(valence) >= self._extreme_vad_threshold
            and arousal >= self._extreme_vad_threshold
        )
        now = time.monotonic()
        if in_extreme:
            if self._extreme_vad_since is None:
                self._extreme_vad_since = now
        else:
            self._extreme_vad_since = None

    async def _handle_mnemos(self, entry_id: str, event: Event) -> None:
        if event.type != "mnemos.replay":
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
            # NO field from the source mnemos.replay event payload is copied here.
            await self._emit_gray_zone(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "gray_zone_event": "replay_overload",
                    "replay_count_in_window": len(self._replay_timestamps),
                    "consolidation_window_s": self._consolidation_window_s,
                    "threshold": self._replay_rate_threshold,
                    "replay_overload_count": self._replay_overload_count,
                }
            )
            # Clear window to avoid repeated alerts in same burst.
            self._replay_timestamps.clear()

    # --- Timed condition checks ------------------------------------------

    async def _check_timed_conditions(self) -> None:
        now = time.monotonic()

        # (a) Unmaintained fatigue.
        if (
            self._fatigue_crossed_at is not None
            and (now - self._fatigue_crossed_at) >= self._maintenance_window_s
        ):
            self._unmaintained_fatigue_count += 1
            # CONTENT CONTRACT: numeric scalars + the gray_zone_event label only;
            # nothing is copied from any source (soma/hypnos) event payload.
            await self._emit_gray_zone(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "gray_zone_event": "unmaintained_fatigue",
                    "seconds_since_crossing": now - self._fatigue_crossed_at,
                    "maintenance_window_s": self._maintenance_window_s,
                    "unmaintained_fatigue_count": self._unmaintained_fatigue_count,
                }
            )
            # Clear so we don't alert repeatedly for the same crossing.
            self._fatigue_crossed_at = None

        # (b) Sustained extreme VAD.
        if (
            self._extreme_vad_since is not None
            and (now - self._extreme_vad_since) >= self._extreme_vad_duration_s
        ):
            self._sustained_extreme_vad_count += 1
            # CONTENT CONTRACT: numeric scalars + the gray_zone_event label only;
            # the raw thymos VAD values are NOT copied — only the derived
            # seconds_sustained scalar.
            await self._emit_gray_zone(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "gray_zone_event": "sustained_extreme_vad",
                    "seconds_sustained": now - self._extreme_vad_since,
                    "extreme_vad_duration_s": self._extreme_vad_duration_s,
                    "extreme_vad_threshold": self._extreme_vad_threshold,
                    "sustained_extreme_vad_count": self._sustained_extreme_vad_count,
                }
            )
            # Clear so we count distinct sustained episodes.
            self._extreme_vad_since = None

        # (d) Sustained interoceptive distress (timer-driven via the shared
        # tracker, so an episode fires on elapsed duration even with no new
        # sample; fires once per episode).
        since = self._interoceptive_distress.active_since
        if since is not None and self._interoceptive_distress.check_timeout(now):
            self._sustained_interoceptive_distress_count += 1
            # CONTENT CONTRACT: numeric scalars + the gray_zone_event label only;
            # the raw soma.report prediction_error is NOT copied — only the
            # derived seconds_sustained scalar.
            await self._emit_gray_zone(
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "gray_zone_event": "sustained_interoceptive_distress",
                    "seconds_sustained": now - since,
                    "interoceptive_distress_threshold": self._interoceptive_distress_threshold,
                    "interoceptive_distress_duration_s": self._interoceptive_distress_duration_s,
                    "sustained_interoceptive_distress_count": self._sustained_interoceptive_distress_count,
                }
            )
