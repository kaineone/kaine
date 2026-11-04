# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The control port between the stimulus effector and the playlist feeds.

The effector hands an accepted command to :class:`StimulusController` in
process, as the shared playlist clock is handed to both feeds (the established
injected-object pattern); only an action name crosses, and the controller turns
it into a pause holder, a seek, a gain in decibels or a channel index. No frame
or sample is written anywhere.

The feeds follow the clock themselves: both read its position and its
``position_epoch()`` together (``locate_with_epoch``), and when the epoch
changes the video source reopens the item and seeks its decoder to the clock's
offset, and the audio producer resyncs at the clock as on a restart. The audio
callback passes through :meth:`StimulusController.wrap_audio_callback`, which
applies the programme gain before the audition module reads the samples.

Pausing is bounded three ways (design D1, the second review's F1). A pause
releases itself after ``P_max`` of entity time; a new pause is refused until
``Delta_sc`` after the previous one ended, whatever other commands came between;
and a pause is refused unless it can run its full ``P_max`` without the
entity's pauses holding the programme for more than ``pause_share_max`` (25 %)
of the trailing awake hour. During a pause the picture holds one frame and the
sound stops, so nothing relieves boredom, and boredom leads more acts: without
the last two bounds the uniform draw held the programme paused for 40-47 % of
three-hour runs, and a scripted sequence for 99.8 %. The first refusal by the
share bound in an episode is logged for the operator.

A poll thread releases the entity pause and accounts awake viewing time (from
the programme's start, excluding sleep and freezes), the paused share, the gain
and the items visited for the welfare record.
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
#: The trailing window of awake time over which the paused share is bounded.
PAUSE_SHARE_WINDOW_S = 3600.0


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
    awake: bool  # neither asleep nor frozen
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
        # Entity time the previous entity pause ended (by resume or release).
        self._entity_pause_ended_at: float | None = None
        # Awake viewing seconds, from the programme's start.
        self._awake_s = 0.0
        # The entity's pauses as [start, end] in awake viewing seconds; the
        # open one ends at None. Older than the trailing window are dropped.
        self._pause_spans: list[list[float | None]] = []
        self._share_episode = False
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

    def reset_gain(self) -> None:
        with self._lock:
            self._gain_db = 0.0

    def state(self) -> StimulusState:
        with self._lock:
            holders = self._clock.holders
            return StimulusState(
                started=self._clock.started,
                holding=TRANSITION_HOLDER in holders,
                ended=self._clock.ended(),
                entity_paused=ENTITY_HOLDER in holders,
                awake=not (holders & NOT_AWAKE_HOLDERS),
                gain_db=self._gain_db,
                channel=self._clock.channel,
                channel_count=self._clock.channel_count,
            )

    def awake_seconds(self) -> float:
        """Awake viewing time since the programme started, the base of the seek cap."""
        with self._lock:
            return self._awake_s

    def is_awake(self) -> bool:
        return not (self._clock.holders & NOT_AWAKE_HOLDERS)

    def paused_share_last_awake_hour(self) -> float:
        """The share of the trailing awake hour the entity's pauses held."""
        with self._lock:
            return self._paused_share_locked()

    def _paused_share_locked(self) -> float:
        lo = self._awake_s - PAUSE_SHARE_WINDOW_S
        held = 0.0
        for start, end in self._pause_spans:
            stop = self._awake_s if end is None else end
            held += max(0.0, stop - max(start, lo))
        return held / PAUSE_SHARE_WINDOW_S

    def _pause_share_refusal_locked(self) -> str | None:
        """A pause is taken only if its full ``P_max`` fits under the share bound."""
        share = self._paused_share_locked()
        room = self._config.pause_share_max - self._config.pause_max_s / PAUSE_SHARE_WINDOW_S
        if share > room + 1e-9:
            return (
                f"the entity's pauses held the programme for {100.0 * share:.1f}% of the last "
                f"awake hour; a pause is taken only while a full one stays within "
                f"{100.0 * self._config.pause_share_max:.0f}%"
            )
        return None

    def refusal(self, action: str) -> str | None:
        """Why the programme cannot take ``action`` now, or None."""
        state = self.state()
        if not state.started or state.holding:
            return "the programme has not started"
        if state.ended:
            return "the programme has ended"
        if not state.awake:
            return "the entity is asleep or frozen"
        if action == PAUSE:
            if state.entity_paused:
                return "the programme is already paused by the entity"
            with self._lock:
                ended_at = self._entity_pause_ended_at
                if ended_at is not None:
                    since = self._now() - ended_at
                    if since < self._config.min_interval_s:
                        return (
                            f"{since:.2f} s after the previous pause ended, "
                            f"{self._config.min_interval_s - since:.3f} s short of the "
                            f"{self._config.min_interval_s:.2f} s between pauses"
                        )
                share_reason = self._pause_share_refusal_locked()
            if share_reason is not None:
                return share_reason
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

    def note_refusal(self, action: str, reason: str) -> None:
        """Record a refused command's bound in the welfare record and log the
        first refusal of a paused-share episode for the operator (numbers only)."""
        if action != PAUSE or "of the last awake hour" not in reason:
            return
        if self._tally is not None:
            self._tally.pause_share_refused()
        with self._lock:
            first = not self._share_episode
            self._share_episode = True
            share = self._paused_share_locked()
        if first:
            log.warning(
                "stimulus control: a pause was refused because the entity's pauses held the "
                "programme for %.1f%% of the last awake hour (bound %.0f%%)",
                100.0 * share,
                100.0 * self._config.pause_share_max,
            )

    # -- commands -----------------------------------------------------------

    def apply(self, action: str) -> dict[str, Any]:
        """Apply one accepted command; raise :class:`StimulusControlError` if it cannot run."""
        with self._lock:
            reason = self.refusal(action)
            if reason is not None:
                raise StimulusControlError(reason)
            if action == PAUSE:
                self._entity_paused_at = self._now()
                self._pause_spans.append([self._awake_s, None])
                self._clock.pause(ENTITY_HOLDER)
            elif action == RESUME:
                self._end_entity_pause_locked()
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

    def _end_entity_pause_locked(self) -> None:
        self._entity_paused_at = None
        self._entity_pause_ended_at = self._now()
        if self._pause_spans and self._pause_spans[-1][1] is None:
            self._pause_spans[-1][1] = self._awake_s
        self._clock.resume(ENTITY_HOLDER)

    # -- feeds --------------------------------------------------------------

    def wrap_audio_callback(self, callback: Callable[[bytes], None]) -> Callable[[bytes], None]:
        """The audio callback with the programme gain applied (0 dB: unchanged)."""

        def _on_pcm(pcm: bytes) -> None:
            callback(apply_gain(pcm, self._gain_db))

        return _on_pcm

    # -- poll ---------------------------------------------------------------

    def poll_once(self) -> None:
        now = self._now()
        with self._lock:
            dt = max(0.0, now - self._last_account)
            self._last_account = now
            holders = self._clock.holders
            viewing = (
                self._clock.started
                and TRANSITION_HOLDER not in holders
                and not self._clock.ended()
            )
            if viewing and not (holders & NOT_AWAKE_HOLDERS):
                self._awake_s += dt
                paused = ENTITY_HOLDER in holders
                if self._tally is not None:
                    self._tally.account(dt, entity_paused=paused, gain_db=self._gain_db)
            release = ENTITY_HOLDER in holders and self._entity_paused_at is not None and (
                now - self._entity_paused_at >= self._config.pause_max_s
                # Defensive: a pause is accepted only if it fits under the share
                # bound, so this second condition should never be what ends it.
                or self._paused_share_locked() >= self._config.pause_share_max
            )
            if release:
                self._end_entity_pause_locked()
                if self._tally is not None:
                    self._tally.auto_released()
            lo = self._awake_s - PAUSE_SHARE_WINDOW_S
            self._pause_spans = [
                s for s in self._pause_spans if s[1] is None or s[1] > lo
            ]
            share = self._paused_share_locked()
            if self._tally is not None:
                self._tally.paused_share(share)
            if self._pause_share_refusal_locked() is None:
                self._share_episode = False
        self._note_visit()

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
    "ENTITY_HOLDER",
    "NOT_AWAKE_HOLDERS",
    "PAUSE_SHARE_WINDOW_S",
    "StimulusController",
    "StimulusState",
    "apply_gain",
]
