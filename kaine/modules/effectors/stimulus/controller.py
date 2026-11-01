# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The control port between the stimulus effector and the playlist feeds.

The effector hands an accepted command to :class:`StimulusController` in
process, as the shared playlist clock is handed to both feeds (the established
injected-object pattern); only an action name crosses, and the controller turns
it into a pause holder, a seek, a gain in decibels or a channel index. No frame
or sample is written anywhere.

The feeds stay as they are and are wrapped:

- :class:`SeekAwareVideoSource` reopens the video decoder at the clock's
  presented item whenever the presented position jumps;
- :class:`ControlledAudioStream` serialises the audio stream's start, stop and
  producer restart, and the controller restarts the producer at the clock's
  position after a jump;
- the audio callback passes through :meth:`StimulusController.wrap_audio_callback`,
  which applies the programme gain before the audition module reads the samples
  and keeps any block from before a jump silent until the producer has moved.

A poll thread releases an entity pause after ``P_max`` of entity time, restarts
the audio producer after a jump and accounts awake time, the paused share, the
gain and the items visited for the welfare record.
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
        self._audio_streams: list[ControlledAudioStream] = []
        self._audio_epoch = clock.position_epoch()
        self._awake_s = 0.0
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

    def wrap_video(self, source: Any) -> "SeekAwareVideoSource":
        return SeekAwareVideoSource(source, self._clock)

    def wrap_audio(self, stream: Any) -> "ControlledAudioStream":
        controlled = ControlledAudioStream(stream)
        with self._lock:
            self._audio_streams = [s for s in self._audio_streams if not s.closed]
            self._audio_streams.append(controlled)
        return controlled

    def audio_is_stale(self) -> bool:
        """True while the presented position has jumped and the producer has not moved yet."""
        return self._clock.position_epoch() != self._audio_epoch

    def wrap_audio_callback(self, callback: Callable[[bytes], None]) -> Callable[[bytes], None]:
        def _on_pcm(pcm: bytes) -> None:
            if self.audio_is_stale():
                callback(b"\x00" * len(pcm))
                return
            callback(apply_gain(pcm, self._gain_db))

        return _on_pcm

    # -- poll ---------------------------------------------------------------

    def poll_once(self) -> None:
        now = self._now()
        with self._lock:
            dt = max(0.0, now - self._last_account)
            self._last_account = now
            holders = self._clock.holders
            if not (holders & NOT_AWAKE_HOLDERS):
                self._awake_s += dt
                if self._tally is not None:
                    self._tally.account(
                        dt, entity_paused=ENTITY_HOLDER in holders, gain_db=self._gain_db
                    )
            if (
                ENTITY_HOLDER in holders
                and self._entity_paused_at is not None
                and now - self._entity_paused_at >= self._config.pause_max_s
            ):
                self._entity_paused_at = None
                self._clock.resume(ENTITY_HOLDER)
                if self._tally is not None:
                    self._tally.auto_released()
            streams = list(self._audio_streams)
        epoch = self._clock.position_epoch()
        if epoch != self._audio_epoch:
            moved = True
            for stream in streams:
                if not stream.reposition():
                    moved = False
            if moved:
                self._audio_epoch = epoch
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


class SeekAwareVideoSource:
    """A ``_VideoSource`` over a ``PlaylistSource`` that follows the clock's jumps."""

    def __init__(self, inner: Any, clock: ProgrammeClock) -> None:
        self._inner = inner
        self._clock = clock
        self._epoch: tuple[int, int] | None = None

    @property
    def manifest(self) -> Any:
        return self._inner.manifest

    @property
    def clock(self) -> Any:
        return self._inner.clock

    @property
    def current_item(self) -> Any:
        return self._inner.current_item

    def first_frame(self) -> Any:
        return self._inner.first_frame()

    def open(self) -> bool:
        self._epoch = None
        return bool(self._inner.open())

    def read(self) -> tuple[bool, Any]:
        epoch = self._clock.position_epoch()
        if epoch != self._epoch:
            first = self._epoch is None
            self._epoch = epoch
            if self._clock.started:
                idx, _offset = self._clock.locate()
                if idx < self._clock.item_count and (
                    not first or idx != self._inner.open_item_index
                ):
                    self._inner.reopen_item(idx)
        return self._inner.read()

    def release(self) -> None:
        self._inner.release()


class ControlledAudioStream:
    """An ``_AudioStream`` whose start, stop and producer restart never interleave."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self._lock = threading.Lock()
        self.closed = False

    @property
    def manifest(self) -> Any:
        return self._inner.manifest

    @property
    def clock(self) -> Any:
        return self._inner.clock

    @property
    def current_item(self) -> Any:
        return self._inner.current_item

    @property
    def delivered_position(self) -> Any:
        return self._inner.delivered_position

    def start(self) -> None:
        with self._lock:
            self.closed = False
            self._inner.start()

    def stop(self) -> None:
        with self._lock:
            self._inner.stop()

    def close(self) -> None:
        with self._lock:
            self.closed = True
            self._inner.close()

    def reposition(self) -> bool:
        """Restart a running producer at the clock's position; True when moved or idle."""
        with self._lock:
            if self.closed:
                return True
            return self._inner.restart_producer() is not False


__all__ = [
    "ENTITY_HOLDER",
    "NOT_AWAKE_HOLDERS",
    "ControlledAudioStream",
    "SeekAwareVideoSource",
    "StimulusController",
    "StimulusState",
    "apply_gain",
]
