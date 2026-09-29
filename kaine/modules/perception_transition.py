# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The womb-to-world transition that opens a viewing after birth.

A born being's first playlist viewing of a boot opens with a crossfade from the
field it last perceived in the womb (the bloom peak at ``womb_t_at_birth``) to
the programme's opening frame, held still. The programme's sound is silent
during the crossfade, as the bloom ended in silence, and fades in once
programme time starts.

The pieces:

- pure functions: the fade curve (:func:`smoothstep`,
  :func:`transition_alpha`), the video blend (:func:`blend_frames`), a
  deterministic resize (:func:`resize_bilinear`) and the audio fade-in
  (:func:`audio_fade_gain`, :func:`apply_audio_fade`);
- :func:`render_birth_field`: the womb generator's bloom-peak frame, a pure
  function of the recorded seed, womb time, lived time and parameters;
- :class:`TransitionController`: one per boot, shared by both surfaces. It holds
  the shared ``PlaylistClock`` paused under the holder ``transition`` from
  construction, starts on the first read of either surface, and releases the
  holder exactly once when ``transition_seconds`` have elapsed. A timer
  guarantees the release, so a quiet surface never leaves the programme paused.
  Programme time zero is the release;
- :class:`WombWorldTransition`: the per-boot shared state (the womb frame, the
  programme's opening frame, the controller and the audio fade position);
- :class:`TransitionVideoSource` and :class:`TransitionAudioStream`: wrappers
  around the playlist sources that present the transition.

ZERO PERSISTENCE INVARIANT (eyes-and-ears): every frame and sample here lives
only in process memory. Nothing in this module opens a file.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    import numpy as np

    from kaine.modules.topos.feed import PlaylistClock, PlaylistPosition
    from kaine.modules.womb_signal import WombParams

log = logging.getLogger(__name__)

TRANSITION_HOLDER = "transition"


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------


def smoothstep(x: float) -> float:
    """The fade curve: ``3x^2 - 2x^3`` on ``x`` clamped to [0, 1].

    Monotonic non-decreasing, with exact endpoints ``smoothstep(0) == 0`` and
    ``smoothstep(1) == 1`` and zero slope at both, so the fade starts and ends
    without a visible step.
    """
    x = float(x)
    if not x > 0.0:  # also maps NaN to the start
        return 0.0
    if x >= 1.0:
        return 1.0
    return x * x * (3.0 - 2.0 * x)


def transition_alpha(elapsed: float, transition_seconds: float) -> float:
    """The film's weight in the crossfade after ``elapsed`` seconds."""
    seconds = float(transition_seconds)
    if not seconds > 0.0:
        return 1.0
    return smoothstep(float(elapsed) / seconds)


def blend_frames(womb: np.ndarray, film: np.ndarray, alpha: float) -> np.ndarray:
    """Return ``(1 - alpha) * womb + alpha * film`` as uint8.

    ``alpha`` is clamped to [0, 1]. Both frames must have the same shape. The
    endpoints are exact: alpha 0 returns the womb frame's values and alpha 1 the
    film frame's.
    """
    import numpy as np

    if womb.shape != film.shape:
        raise ValueError(
            f"blend_frames needs equal shapes, got {womb.shape} and {film.shape}"
        )
    a = min(1.0, max(0.0, float(alpha)))
    out = womb.astype(np.float32) * np.float32(1.0 - a) + film.astype(
        np.float32
    ) * np.float32(a)
    return np.clip(np.rint(out), 0.0, 255.0).astype(np.uint8)


def resize_bilinear(image: np.ndarray, height: int, width: int) -> np.ndarray:
    """Resize an ``(h, w, c)`` uint8 image to ``(height, width, c)``.

    Bilinear interpolation on pixel centres, computed in numpy only, so the
    result is the same on every run.
    """
    import numpy as np

    height = int(height)
    width = int(width)
    if height <= 0 or width <= 0:
        raise ValueError("resize_bilinear needs a positive target size")
    src_h, src_w = int(image.shape[0]), int(image.shape[1])
    if (src_h, src_w) == (height, width):
        return image.copy()

    def _axis(n_out: int, n_in: int) -> tuple[Any, Any, Any]:
        pos = (np.arange(n_out, dtype=np.float64) + 0.5) * (n_in / n_out) - 0.5
        pos = np.clip(pos, 0.0, n_in - 1)
        lo = np.floor(pos).astype(np.int64)
        hi = np.minimum(lo + 1, n_in - 1)
        return lo, hi, (pos - lo).astype(np.float32)

    y0, y1, wy = _axis(height, src_h)
    x0, x1, wx = _axis(width, src_w)
    src = image.astype(np.float32)
    if src.ndim == 2:
        src = src[:, :, None]
    wx = wx[None, :, None]
    wy = wy[:, None, None]
    top = src[y0][:, x0] * (1.0 - wx) + src[y0][:, x1] * wx
    bottom = src[y1][:, x0] * (1.0 - wx) + src[y1][:, x1] * wx
    out = top * (1.0 - wy) + bottom * wy
    if image.ndim == 2:
        out = out[:, :, 0]
    return np.clip(np.rint(out), 0.0, 255.0).astype(np.uint8)


def audio_fade_gain(frame_index: int, fade_frames: int) -> float:
    """The linear fade-in gain for the ``frame_index``-th sample frame heard
    since programme time started: ``frame_index / fade_frames`` clamped to
    [0, 1]. ``fade_frames <= 0`` means no fade."""
    if fade_frames <= 0:
        return 1.0
    return min(1.0, max(0.0, float(frame_index) / float(fade_frames)))


def apply_audio_fade(
    pcm: bytes, *, start_frame: int, channels: int, fade_frames: int
) -> bytes:
    """Apply the fade-in to an int16 little-endian PCM block.

    ``start_frame`` is the index, counted since programme time started, of the
    block's first sample frame. Every channel of a frame gets the same gain.
    Blocks past the end of the fade are returned unchanged.
    """
    import numpy as np

    channels = max(1, int(channels))
    if fade_frames <= 0 or start_frame >= fade_frames:
        return pcm
    frame_bytes = 2 * channels
    n_frames = len(pcm) // frame_bytes
    body = len(pcm) - n_frames * frame_bytes
    samples = np.frombuffer(pcm, dtype="<i2", count=n_frames * channels)
    idx = np.arange(start_frame, start_frame + n_frames, dtype=np.float64)
    gain = np.clip(idx / float(fade_frames), 0.0, 1.0)
    scaled = samples.reshape(n_frames, channels).astype(np.float64) * gain[:, None]
    out = np.clip(np.rint(scaled), -32768, 32767).astype("<i2").tobytes()
    if body:
        # A trailing partial frame is outside the frame grid; keep it silent.
        out += b"\x00" * body
    return out


def render_birth_field(
    *,
    seed: int,
    womb_t_at_birth: float,
    lived_seconds: float,
    params: WombParams,
    width: int,
    height: int,
) -> np.ndarray:
    """Render the womb's bloom-peak field at ``womb_t_at_birth``.

    The womb generator's own pure function (``WombProceduralSource.frame_at``
    at ``birth_progress = 1.0``: bright, pulse-free, full colour) at frame index
    ``floor(womb_t_at_birth * frame_rate_hz)``, with the recorded seed and the
    being's lived gestation time.
    """
    from kaine.modules.topos.feed import (
        WombClock,
        WombProceduralSource,
        WombSchedule,
    )

    lived = float(lived_seconds)
    if not math.isfinite(lived) or lived < 0.0:
        lived = 0.0
    schedule = WombSchedule(seed=int(seed), width=int(width), height=int(height))
    source = WombProceduralSource(
        schedule,
        params=params,
        clock=WombClock(lived_offset_seconds=lived),
        lived_seconds=lambda: lived,
    )
    index = int(math.floor(float(womb_t_at_birth) * float(schedule.frame_rate_hz)))
    return source.frame_at(index, birth_progress=1.0)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------


def _daemon_timer(interval: float, fn: Callable[[], None]) -> Any:
    timer = threading.Timer(interval, fn)
    timer.daemon = True
    return timer


class TransitionController:
    """Owns the ``transition`` pause holder on the shared playlist clock.

    Construction pauses the clock under ``transition`` (before any read), so the
    programme is born paused. :meth:`start` (called on the first read or
    produce of either surface) fixes the transition's start, anchors the
    programme origin and arms a timer. The holder is released exactly once, by
    whichever of :meth:`poll` (the video read) or the timer first sees
    ``transition_seconds`` elapsed; programme time zero is that release.
    """

    def __init__(
        self,
        playlist_clock: PlaylistClock,
        transition_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        timer_factory: Callable[[float, Callable[[], None]], Any] = _daemon_timer,
    ) -> None:
        seconds = float(transition_seconds)
        if not math.isfinite(seconds) or seconds <= 0.0:
            raise ValueError("transition_seconds must be finite and above zero")
        self._pclock = playlist_clock
        self._seconds = seconds
        self._clock = clock
        self._timer_factory = timer_factory
        self._lock = threading.Lock()
        self._started_at: float | None = None
        self._released = False
        self._timer: Any = None
        playlist_clock.pause(TRANSITION_HOLDER)

    @property
    def transition_seconds(self) -> float:
        return self._seconds

    @property
    def started(self) -> bool:
        with self._lock:
            return self._started_at is not None

    @property
    def released(self) -> bool:
        with self._lock:
            return self._released

    def start(self) -> None:
        """Begin the transition (idempotent)."""
        with self._lock:
            if self._started_at is not None or self._released:
                return
            self._started_at = self._clock()
            # Fix the programme origin now; the clock is held under
            # ``transition``, so programme time stays at zero until release.
            self._pclock.start()
            self._arm_locked(self._seconds)
        log.info(
            "womb-to-world transition started (%.1f s); the programme waits",
            self._seconds,
        )

    def elapsed(self) -> float:
        """Seconds since :meth:`start`, or 0.0 before it."""
        with self._lock:
            if self._started_at is None:
                return 0.0
            return max(0.0, self._clock() - self._started_at)

    def alpha(self) -> float:
        """The film's weight in the crossfade now (1.0 once released)."""
        if self.released:
            return 1.0
        return transition_alpha(self.elapsed(), self._seconds)

    def poll(self) -> bool:
        """Release the holder when the transition's time is up.

        Returns True once the transition has been released.
        """
        with self._lock:
            if self._released:
                return True
            if self._started_at is None:
                return False
            if self._clock() - self._started_at < self._seconds:
                return False
            self._release_locked()
        log.info("womb-to-world transition complete; programme time starts")
        return True

    def abort(self, reason: str) -> None:
        """Release the holder now, so the programme starts as it would without
        a transition. Used when the transition cannot be rendered."""
        with self._lock:
            if self._released:
                return
            self._release_locked()
        log.warning(
            "womb-to-world transition abandoned (%s); the programme starts now",
            reason,
        )

    def _release_locked(self) -> None:
        self._released = True
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()
        self._pclock.resume(TRANSITION_HOLDER)

    def _arm_locked(self, delay: float) -> None:
        timer = self._timer_factory(max(0.0, float(delay)), self._on_timer)
        self._timer = timer
        timer.start()

    def _on_timer(self) -> None:
        if self.poll():
            return
        # The timer fired before the controller's clock reached the end (timer
        # and clock can disagree slightly): re-arm for the remainder.
        with self._lock:
            if self._released or self._started_at is None:
                return
            remaining = self._seconds - (self._clock() - self._started_at)
            self._arm_locked(max(remaining, 0.001))


# ---------------------------------------------------------------------------
# Shared per-boot state
# ---------------------------------------------------------------------------


class WombWorldTransition:
    """The per-boot womb-to-world transition shared by both surfaces.

    Holds the womb's bloom-peak frame (rendered once, at construction), the
    programme's opening frame (decoded once, by the video surface), the
    controller and the number of sample frames heard since programme time
    started (for the audio fade-in).
    """

    def __init__(
        self,
        *,
        womb_frame: np.ndarray,
        controller: TransitionController,
        audio_fade_seconds: float,
    ) -> None:
        fade = float(audio_fade_seconds)
        if not math.isfinite(fade) or fade < 0.0:
            raise ValueError("audio_fade_seconds must be finite and non-negative")
        self._womb_source = womb_frame
        self._controller = controller
        self._audio_fade_seconds = fade
        self._lock = threading.Lock()
        self._prepared = False
        self._womb: Any = None
        self._film: Any = None
        self._audio_frames_heard = 0

    @property
    def controller(self) -> TransitionController:
        return self._controller

    @property
    def transition_seconds(self) -> float:
        return self._controller.transition_seconds

    @property
    def audio_fade_seconds(self) -> float:
        return self._audio_fade_seconds

    @property
    def released(self) -> bool:
        return self._controller.released

    @property
    def womb_frame(self) -> np.ndarray:
        """The bloom-peak frame as rendered (before any resize)."""
        return self._womb_source

    @property
    def prepared(self) -> bool:
        with self._lock:
            return self._prepared

    def prepare(self, first_frame: Callable[[], Any]) -> bool:
        """Obtain the programme's opening frame once and size the womb frame to
        it. On failure the transition is abandoned (the programme starts now).
        Returns True when the transition frames are ready."""
        with self._lock:
            if self._prepared:
                return self._film is not None
            self._prepared = True
            reason = None
            try:
                film = first_frame()
            except Exception as exc:
                film = None
                reason = f"the programme's first frame could not be decoded: {exc}"
            if film is None and reason is None:
                reason = "the programme's first frame could not be decoded"
            if film is not None:
                film_shape = getattr(film, "shape", None)
                womb_shape = self._womb_source.shape
                if (
                    film_shape is None
                    or len(film_shape) != len(womb_shape)
                    or tuple(film_shape[2:]) != tuple(womb_shape[2:])
                    or str(getattr(film, "dtype", "")) != "uint8"
                ):
                    reason = (
                        f"the programme's first frame has shape {film_shape}, "
                        f"which cannot be blended with the womb's {womb_shape}"
                    )
                    film = None
            if film is not None:
                self._womb = resize_bilinear(
                    self._womb_source, int(film.shape[0]), int(film.shape[1])
                )
                self._film = film.copy()
        if reason is not None:
            self._controller.abort(reason)
            return False
        return True

    def frame_at(self, alpha: float) -> np.ndarray | None:
        """The crossfade frame at film weight ``alpha`` (None until prepared)."""
        with self._lock:
            womb, film = self._womb, self._film
        if womb is None or film is None:
            return None
        return blend_frames(womb, film, alpha)

    def fade_block(self, pcm: bytes, *, sample_rate: int, channels: int) -> bytes:
        """Fade one programme PCM block in; silence it before release."""
        channels = max(1, int(channels))
        if not self._controller.released:
            # The programme is held during the crossfade; any block reaching
            # here early is kept silent, as the bloom ended in silence.
            return b"\x00" * len(pcm)
        n_frames = len(pcm) // (2 * channels)
        fade_frames = int(round(self._audio_fade_seconds * float(sample_rate)))
        with self._lock:
            start = self._audio_frames_heard
            self._audio_frames_heard += n_frames
        return apply_audio_fade(
            pcm, start_frame=start, channels=channels, fade_frames=fade_frames
        )


# ---------------------------------------------------------------------------
# Surface wrappers
# ---------------------------------------------------------------------------


class TransitionVideoSource:
    """A ``_VideoSource`` presenting the crossfade, then the playlist.

    Wraps a ``PlaylistSource``. While the transition runs, ``read()`` returns
    the crossfade from the womb's bloom-peak field to the programme's opening
    frame; once released, it reads the playlist as usual.
    """

    def __init__(self, inner: Any, transition: WombWorldTransition) -> None:
        self._inner = inner
        self._t = transition

    @property
    def manifest(self) -> Any:
        return self._inner.manifest

    @property
    def clock(self) -> Any:
        return self._inner.clock

    @property
    def current_item(self) -> PlaylistPosition | None:
        """``None`` during the transition: no programme item is shown yet."""
        if not self._t.released:
            return None
        return self._inner.current_item

    def open(self) -> bool:
        opened = bool(self._inner.open())
        if opened and not self._t.released:
            self._t.prepare(self._inner.first_frame)
        return opened

    def read(self) -> tuple[bool, Any]:
        if not self._t.released:
            controller = self._t.controller
            controller.start()
            if not controller.poll():
                frame = self._t.frame_at(controller.alpha())
                if frame is not None:
                    return True, frame
        return self._inner.read()

    def release(self) -> None:
        self._inner.release()


class TransitionAudioStream:
    """An ``_AudioStream`` whose programme sound fades in after the crossfade.

    Wraps a ``PlaylistAudioStream`` built by ``make_inner(callback)`` around a
    callback that applies the fade. During the crossfade the shared clock is
    held, so the playlist stream parks and nothing is heard.
    """

    def __init__(
        self,
        make_inner: Callable[[Callable[[bytes], None]], Any],
        *,
        callback: Callable[[bytes], None],
        transition: WombWorldTransition,
        sample_rate: int,
        channels: int,
    ) -> None:
        self._callback = callback
        self._t = transition
        self._sample_rate = int(sample_rate)
        self._channels = int(channels)
        self._inner = make_inner(self._on_pcm)

    @property
    def manifest(self) -> Any:
        return self._inner.manifest

    @property
    def clock(self) -> Any:
        return self._inner.clock

    @property
    def current_item(self) -> PlaylistPosition | None:
        """``None`` during the transition: no programme item is heard yet."""
        if not self._t.released:
            return None
        return self._inner.current_item

    @property
    def delivered_position(self) -> tuple[int, float] | None:
        return self._inner.delivered_position

    def _on_pcm(self, pcm: bytes) -> None:
        self._callback(
            self._t.fade_block(
                pcm, sample_rate=self._sample_rate, channels=self._channels
            )
        )

    def start(self) -> None:
        self._inner.start()
        self._t.controller.start()

    def stop(self) -> None:
        self._inner.stop()

    def close(self) -> None:
        self._inner.close()


__all__ = [
    "TRANSITION_HOLDER",
    "TransitionAudioStream",
    "TransitionController",
    "TransitionVideoSource",
    "WombWorldTransition",
    "apply_audio_fade",
    "audio_fade_gain",
    "blend_frames",
    "render_birth_field",
    "resize_bilinear",
    "smoothstep",
    "transition_alpha",
]
