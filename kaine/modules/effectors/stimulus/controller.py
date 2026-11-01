# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The control port between the stimulus effector and the playlist feeds.

The effector hands an accepted command to :class:`StimulusController` in
process, as the shared playlist clock is handed to both feeds (the established
injected-object pattern); only an action name crosses, and the controller turns
it into a pause holder, a seek, a gain in decibels or a channel index. No frame
or sample is written anywhere.

The feeds follow the clock themselves: both read its ``position_epoch()``,
and when it changes the video source reopens the item and seeks its decoder to
the clock's offset, and the audio producer resyncs at the clock as on a
restart. The audio callback passes through
:meth:`StimulusController.wrap_audio_callback`, which applies the programme gain
before the audition module reads the samples.

A poll thread releases an entity pause after ``P_max`` of entity time and
accounts awake time, the paused share, the gain and the items visited for the
welfare record. When the entity's pauses hold the programme for more than half
of the last awake hour it logs an operator advisory, once until the share falls
back, and counts it in the record. The advisory blocks nothing: each pause
releases itself and commands are at least ``Delta_sc`` apart.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Callable

from kaine.modules.effectors.stimulus.config import (
    LOUDER,
    NEXT,
    PAUSE,
    PREVIOUS,
    QUIETER,
    RESUME,
    StimulusControlConfig,
    StimulusControlError,
    parse_channel_action,
)
from kaine.modules.effectors.stimulus.programme import Programme, ProgrammeClock
from kaine.modules.effectors.stimulus.records import StimulusTally
from kaine.modules.perception_transition import TRANSITION_HOLDER

log = logging.getLogger(__name__)

ENTITY_HOLDER = "entity"
# Holders under which the entity is not awake: asleep, or frozen by the welfare
# net or the operator. Time under them is not awake time.
NOT_AWAKE_HOLDERS = frozenset({"sleep", "freeze"})
_GAIN_EPS = 1e-9
#: The paused-share advisory: the trailing window of awake time, the share of
#: it held by the entity's pauses past which the operator is told, and the
#: bucket the window is kept in.
ADVISORY_WINDOW_S = 3600.0
ADVISORY_SHARE = 0.5
_ADVISORY_BUCKET_S = 10.0


def apply_gain(pcm: bytes, gain_db: float) -> bytes:
    """Scale int16 little-endian PCM by ``gain_db``; 0 dB returns ``pcm`` itself.

    A raised gain passes through a smooth tanh knee above 0.9 of full scale, so
    a louder programme is never hard-clipped.
    """
    if abs(gain_db) < _GAIN_EPS or not pcm:
        return pcm
    import numpy as np

    from kaine.modules.audition.feed import soft_limit

    x = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
    y = x * float(10.0 ** (gain_db / 20.0))
    if gain_db > 0.0:
        y = soft_limit(y, knee=0.9, ceiling=1.0)
    out = np.clip(np.round(y * 32767.0), -32768, 32767).astype("<i2")
    return out.tobytes()


@dataclass(frozen=True)
class StimulusState:
    started: bool
    holding: bool  # the stimulus-source-to-world crossfade still holds the programme
    ended: bool
    entity_paused: bool
    gain_db: float
    channel: int
    channel_count: int


class StimulusController:
    """Applies accepted stimulus commands to the shared programme."""

    def __init__(
        self,
        clock: ProgrammeClock,
        programme: Programme,
        config: StimulusControlConfig,
        *,
        now: Callable[[], float],
        tally: StimulusTally | None = None,
        poll_seconds: float = 0.05,
    ) -> None:
        self._clock = clock
        self._programme = programme
        self._config = config
        self._now = now
        self._tally = tally
        self._poll_seconds = float(poll_seconds)
        self._lock = threading.RLock()
        # The gain returns to zero at the start of every viewing; a boot is a viewing.
        self._gain_db = 0.0
        self._entity_paused_at: float | None = None
        self._awake_s = 0.0
        # Paused seconds per bucket of awake time, oldest first, for the
        # trailing-hour paused share; the last bucket is the one filling.
        self._paused_buckets: list[float] = [0.0]
        self._bucket_awake = 0.0
        self._advisory_active = False
        self._last_account = now()
        self._last_visit: tuple[int, int] | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ----------------------------------------------------------

    @property
    def clock(self) -> ProgrammeClock:
        return self._clock

    @property
    def programme(self) -> Programme:
        return self._programme

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="stimulus-control", daemon=True
        )
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                log.warning("stimulus control poll failed", exc_info=True)
            self._stop.wait(self._poll_seconds)

    # -- state --------------------------------------------------------------

    @property
    def gain_db(self) -> float:
        return self._gain_db

    def state(self) -> StimulusState:
        with self._lock:
            holders = self._clock.holders
            return StimulusState(
                started=self._clock.started,
                holding=TRANSITION_HOLDER in holders,
                ended=self._clock.ended(),
                entity_paused=ENTITY_HOLDER in holders,
                gain_db=self._gain_db,
                channel=self._clock.channel,
                channel_count=self._clock.channel_count,
            )

    def awake_seconds(self) -> float:
        """Awake entity time since boot, the base of the per-awake-hour seek cap."""
        with self._lock:
            return self._awake_s

    def is_awake(self) -> bool:
        return not (self._clock.holders & NOT_AWAKE_HOLDERS)

    def refusal(self, action: str) -> str | None:
        """Why the programme cannot take ``action`` now, or None."""
        state = self.state()
        if not state.started or state.holding:
            return "the programme has not started"
        if state.ended:
            return "the programme has ended"
        if action == PAUSE and state.entity_paused:
            return "the programme is already paused by the entity"
        if action == RESUME and not state.entity_paused:
            return "the programme is not paused by the entity"
        step = self._config.gain_step_db
        if action == LOUDER and state.gain_db + step > self._config.gain_max_db + _GAIN_EPS:
            return "the gain is at its upper bound"
        if action == QUIETER and state.gain_db - step < -self._config.gain_max_db - _GAIN_EPS:
            return "the gain is at its lower bound"
        channel = parse_channel_action(action)
        if channel is not None:
            if not 0 <= channel < state.channel_count:
                return "no such programme channel"
            if channel == state.channel:
                return "already on that channel"
        return None

    # -- commands -----------------------------------------------------------

    def apply(self, action: str) -> dict[str, Any]:
        """Apply one accepted command; raise :class:`StimulusControlError` if it cannot run."""
        with self._lock:
            reason = self.refusal(action)
            if reason is not None:
                raise StimulusControlError(reason)
            if action == PAUSE:
                self._entity_paused_at = self._now()
                self._clock.pause(ENTITY_HOLDER)
            elif action == RESUME:
                self._entity_paused_at = None
                self._clock.resume(ENTITY_HOLDER)
            elif action == NEXT:
                self._clock.seek(+1)
            elif action == PREVIOUS:
                self._clock.seek(-1)
            elif action == LOUDER:
                self._gain_db = min(
                    self._config.gain_max_db, self._gain_db + self._config.gain_step_db
                )
            elif action == QUIETER:
                self._gain_db = max(
                    -self._config.gain_max_db, self._gain_db - self._config.gain_step_db
                )
            else:
                channel = parse_channel_action(action)
                if channel is None:
                    raise StimulusControlError("not a stimulus action")
                self._clock.switch_channel(channel)
            # A jump between two polls is still a visit.
            self._note_visit()
            return {"gain_db": self._gain_db, "channel": self._clock.channel}

    # -- feeds --------------------------------------------------------------

    def wrap_audio_callback(self, callback: Callable[[bytes], None]) -> Callable[[bytes], None]:
        """The audio callback with the programme gain applied (0 dB: unchanged)."""

        def _on_pcm(pcm: bytes) -> None:
            callback(apply_gain(pcm, self._gain_db))

        return _on_pcm

    # -- poll ---------------------------------------------------------------

    def poll_once(self) -> None:
        now = self._now()
        advisory: float | None = None
        with self._lock:
            dt = max(0.0, now - self._last_account)
            self._last_account = now
            holders = self._clock.holders
            if not (holders & NOT_AWAKE_HOLDERS):
                self._awake_s += dt
                paused = ENTITY_HOLDER in holders
                if self._tally is not None:
                    self._tally.account(dt, entity_paused=paused, gain_db=self._gain_db)
                advisory = self._advance_paused_window(dt, paused)
            if (
                ENTITY_HOLDER in holders
                and self._entity_paused_at is not None
                and now - self._entity_paused_at >= self._config.pause_max_s
            ):
                self._entity_paused_at = None
                self._clock.resume(ENTITY_HOLDER)
                if self._tally is not None:
                    self._tally.auto_released()
        if advisory is not None:
            # An operator advisory, not a block: numbers only.
            log.warning(
                "stimulus control advisory: the entity's pauses held the programme "
                "for %.0f%% of the last awake hour (more than %.0f%%); nothing is "
                "blocked, each pause releases itself after %.0f s",
                100.0 * advisory,
                100.0 * ADVISORY_SHARE,
                self._config.pause_max_s,
            )
        self._note_visit()

    def paused_share_last_awake_hour(self) -> float:
        """The share of the trailing awake hour held by the entity's pauses."""
        with self._lock:
            return sum(self._paused_buckets) / ADVISORY_WINDOW_S

    def _advance_paused_window(self, dt: float, paused: bool) -> float | None:
        """Account ``dt`` awake seconds; return the share when an advisory is due."""
        remaining = dt
        keep = int(ADVISORY_WINDOW_S / _ADVISORY_BUCKET_S)
        while remaining > 0.0:
            step = min(_ADVISORY_BUCKET_S - self._bucket_awake, remaining)
            if paused:
                self._paused_buckets[-1] += step
            self._bucket_awake += step
            remaining -= step
            if self._bucket_awake >= _ADVISORY_BUCKET_S - 1e-9:
                self._paused_buckets.append(0.0)
                self._bucket_awake = 0.0
                if len(self._paused_buckets) > keep:
                    del self._paused_buckets[: len(self._paused_buckets) - keep]
        share = sum(self._paused_buckets) / ADVISORY_WINDOW_S
        if self._tally is not None:
            self._tally.paused_share(share)
        if share > ADVISORY_SHARE and not self._advisory_active:
            self._advisory_active = True
            if self._tally is not None:
                self._tally.paused_advisory()
            return share
        if share <= ADVISORY_SHARE:
            self._advisory_active = False
        return None

    def _note_visit(self) -> None:
        if self._tally is None:
            return
        with self._lock:
            if not self._clock.started or self._clock.ended():
                return
            if TRANSITION_HOLDER in self._clock.holders:
                return
            channel, idx, _local = self._clock.current_position()
            key = (channel, idx)
            if key == self._last_visit:
                return
            self._last_visit = key
            items = self._programme.manifest.items
            if 0 <= idx < len(items):
                self._tally.visit(channel, items[idx].order)


__all__ = [
    "ADVISORY_SHARE",
    "ADVISORY_WINDOW_S",
    "ENTITY_HOLDER",
    "NOT_AWAKE_HOLDERS",
    "StimulusController",
    "StimulusState",
    "apply_gain",
]
