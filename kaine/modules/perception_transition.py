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
  construction. The crossfade advances only while it is perceived: while no
  other holder (``freeze``, ``hypnos``) pauses the clock and the primary
  surface is wanted. The holder is released exactly once, when the perceived
  crossfade time reaches ``transition_seconds``; a timer guarantees the release
  even when no surface reads. Programme time zero is the release;
- :class:`WombWorldTransition`: the per-boot shared state (the womb frame, the
  programme's opening frame, the blend buffers, the controller and the audio
  fade position);
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
# How often the controller re-samples whether the crossfade is perceived while
# it waits for its end (the desired-perception flags have no change events).
TICK_SECONDS = 0.25

# Content-free reasons carried by an ``abandoned`` event.
ABANDON_FIRST_FRAME_UNDECODABLE = "first_frame_undecodable"
ABANDON_FIRST_FRAME_UNBLENDABLE = "first_frame_unblendable"


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
    """The film's weight in the crossfade after ``elapsed`` perceived seconds."""
    seconds = float(transition_seconds)
    if not seconds > 0.0:
        return 1.0
    return smoothstep(float(elapsed) / seconds)


def blend_frames(womb: np.ndarray, film: np.ndarray, alpha: float) -> np.ndarray:
    """Return ``womb + alpha * (film - womb)`` as uint8.

    ``alpha`` is clamped to [0, 1]. Both frames must have the same shape. The
    endpoints are exact: alpha 0 returns the womb frame's values and alpha 1 the
    film frame's. :class:`WombWorldTransition` computes the same arithmetic in
    preallocated buffers.
    """
    import numpy as np

    if womb.shape != film.shape:
        raise ValueError(
            f"blend_frames needs equal shapes, got {womb.shape} and {film.shape}"
        )
    base = womb.astype(np.float32)
    delta = film.astype(np.float32) - base
    return _blend_into(base, delta, np.empty_like(delta), alpha)


def _blend_into(base: Any, delta: Any, buf: Any, alpha: float) -> np.ndarray:
    """``rint(base + alpha * delta)`` in ``buf``; returns a fresh uint8 frame."""
    import numpy as np

    a = np.float32(min(1.0, max(0.0, float(alpha))))
    np.multiply(delta, a, out=buf)
    np.add(buf, base, out=buf)
    np.rint(buf, out=buf)
    np.clip(buf, 0.0, 255.0, out=buf)
    return buf.astype(np.uint8)


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
    programme is born paused. :meth:`start` begins the transition: the video
    surface starts it whenever it is present; the audio surface only when it is
    the only surface.

    The crossfade advances only while it is perceived: while no other holder
    (``freeze``, ``hypnos``, ...) pauses the clock, and while
    ``perceiving(video_present)`` is true (the boot wiring checks the desired
    perception flags and the freeze control). Holder changes are applied the
    moment they happen; ``perceiving`` is re-sampled on every video read and on
    every timer tick. The holder is released exactly once, by whichever of
    :meth:`poll` or the timer first sees ``transition_seconds`` of perceived
    crossfade; programme time zero is that release.

    ``on_event(phase, payload)`` receives the content-free outcome: ``started``
    (the crossfade first advanced), ``completed`` and ``abandoned`` (with a
    ``reason`` code), each with ``transition_seconds``.
    """

    def __init__(
        self,
        playlist_clock: PlaylistClock,
        transition_seconds: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        timer_factory: Callable[[float, Callable[[], None]], Any] = _daemon_timer,
        perceiving: Callable[[bool], bool] | None = None,
        video_present: bool = True,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        tick_seconds: float = TICK_SECONDS,
    ) -> None:
        seconds = float(transition_seconds)
        if not math.isfinite(seconds) or seconds <= 0.0:
            raise ValueError("transition_seconds must be finite and above zero")
        self._pclock = playlist_clock
        self._seconds = seconds
        self._clock = clock
        self._timer_factory = timer_factory
        self._perceiving = perceiving
        self._video_present = bool(video_present)
        self._on_event = on_event
        self._tick = max(0.001, float(tick_seconds))
        self._lock = threading.RLock()
        self._started = False
        self._released = False
        self._announced = False
        self._perceived = True
        self._progress = 0.0
        self._segment_start: float | None = None
        self._timer: Any = None
        self._pending: list[tuple[str, dict[str, Any]]] = []
        playlist_clock.pause(TRANSITION_HOLDER)
        playlist_clock.add_holder_listener(self._on_holders)

    # --- state ------------------------------------------------------------

    @property
    def transition_seconds(self) -> float:
        return self._seconds

    @property
    def started(self) -> bool:
        with self._lock:
            return self._started

    @property
    def released(self) -> bool:
        with self._lock:
            return self._released

    @property
    def video_present(self) -> bool:
        with self._lock:
            return self._video_present

    def set_video_present(self, present: bool) -> None:
        """Record whether a video surface exists. Without one, the audio
        surface starts the transition and ``perceiving`` judges audio."""
        with self._lock:
            self._video_present = bool(present)

    def progress(self) -> float:
        """Seconds of perceived crossfade so far."""
        with self._lock:
            total = self._progress
            if self._segment_start is not None:
                total += max(0.0, self._clock() - self._segment_start)
            return total

    def alpha(self) -> float:
        """The film's weight in the crossfade now (1.0 once released)."""
        if self.released:
            return 1.0
        return transition_alpha(self.progress(), self._seconds)

    # --- transitions ------------------------------------------------------

    def start(self, surface: str = "video") -> None:
        """Begin the transition (idempotent). An audio start is ignored while
        a video surface is present."""
        with self._lock:
            if self._started or self._released:
                return
            if surface != "video" and self._video_present:
                return
        perceived = self._sample()
        with self._lock:
            if self._started or self._released:
                return
            self._started = True
            # Fix the programme origin now; the clock is held under
            # ``transition``, so programme time stays at zero until release.
            self._pclock.start()
            self._update_locked(perceived, None)
            self._arm_locked()
        log.info(
            "womb-to-world transition started by the %s surface (%.1f s of "
            "perceived crossfade); the programme waits",
            surface,
            self._seconds,
        )
        self._flush()

    def poll(self) -> bool:
        """Account perceived time and release the holder when it is up.

        Returns True once the transition has been released.
        """
        with self._lock:
            if self._released:
                return True
            if not self._started:
                return False
        perceived = self._sample()
        with self._lock:
            if self._released:
                return True
            self._update_locked(perceived, None)
            done = self._progress >= self._seconds
            if done:
                self._finish_locked("completed", {})
        if done:
            self._pclock.resume(TRANSITION_HOLDER)
            log.info("womb-to-world transition complete; programme time starts")
        self._flush()
        return done

    def abort(self, reason: str, detail: str = "") -> None:
        """Release the holder now, so the programme starts as it would without
        a transition. Used when the transition cannot be rendered."""
        with self._lock:
            if self._released:
                return
            if self._segment_start is not None:
                self._progress += max(0.0, self._clock() - self._segment_start)
                self._segment_start = None
            self._finish_locked("abandoned", {"reason": str(reason)})
        self._pclock.resume(TRANSITION_HOLDER)
        log.warning(
            "womb-to-world transition abandoned (%s%s); the programme starts now",
            reason,
            f": {detail}" if detail else "",
        )
        self._flush()

    # --- internals --------------------------------------------------------

    def _sample(self) -> bool | None:
        """Whether the crossfade is perceived now (None keeps the last value)."""
        if self._perceiving is None:
            return True
        try:
            return bool(self._perceiving(self.video_present))
        except Exception:
            log.debug("transition perceiving check raised", exc_info=True)
            return None

    def _update_locked(
        self, perceived: bool | None, holders: frozenset[str] | None
    ) -> None:
        now = self._clock()
        if self._segment_start is not None:
            self._progress += max(0.0, now - self._segment_start)
            self._segment_start = None
        if perceived is not None:
            self._perceived = perceived
        if holders is None:
            holders = self._pclock.holders
        others = holders - {TRANSITION_HOLDER}
        if self._started and not self._released and self._perceived and not others:
            self._segment_start = now
            if not self._announced:
                self._announced = True
                self._pending.append(("started", {}))

    def _finish_locked(self, phase: str, extra: dict[str, Any]) -> None:
        self._released = True
        self._segment_start = None
        timer, self._timer = self._timer, None
        if timer is not None:
            timer.cancel()
        self._pending.append((phase, extra))

    def _arm_locked(self) -> None:
        if self._released:
            return
        delay = self._tick
        if self._segment_start is not None:
            remaining = self._seconds - (
                self._progress + max(0.0, self._clock() - self._segment_start)
            )
            delay = min(delay, max(remaining, 0.001))
        timer = self._timer_factory(delay, self._on_timer)
        self._timer = timer
        timer.start()

    def _on_timer(self) -> None:
        if self.poll():
            return
        with self._lock:
            if not self._released:
                self._arm_locked()

    def _on_holders(self, holders: frozenset[str]) -> None:
        with self._lock:
            if not self._started or self._released:
                return
            self._update_locked(None, holders)
        self._flush()

    def _flush(self) -> None:
        with self._lock:
            pending, self._pending = self._pending, []
        if self._on_event is None:
            return
        for phase, extra in pending:
            payload = {"phase": phase, "transition_seconds": self._seconds, **extra}
            try:
                self._on_event(phase, payload)
            except Exception:
                log.warning("transition event handler raised", exc_info=True)


# ---------------------------------------------------------------------------
# Shared per-boot state
# ---------------------------------------------------------------------------


class WombWorldTransition:
    """The per-boot womb-to-world transition shared by both surfaces.

    Holds the womb's bloom-peak frame (rendered once, at construction), the
    programme's opening frame (decoded once, by the video surface) with the
    float32 buffers the per-read blend reuses, the controller and the number of
    sample frames heard since programme time started (for the audio fade-in).
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
        self._blend_lock = threading.Lock()
        self._prepared = False
        self._base: Any = None
        self._delta: Any = None
        self._buf: Any = None
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
        it, at the film's native resolution. The frame is decoded before the
        lock is taken; the lock only publishes the result. On failure the
        transition is abandoned (the programme starts now). Returns True when
        the transition frames are ready."""
        import numpy as np

        with self._lock:
            if self._prepared:
                return self._delta is not None
        reason = detail = None
        base = delta = None
        try:
            film = first_frame()
        except Exception as exc:
            film = None
            reason, detail = ABANDON_FIRST_FRAME_UNDECODABLE, str(exc)
        if film is None and reason is None:
            reason = ABANDON_FIRST_FRAME_UNDECODABLE
        if film is not None:
            film_shape = getattr(film, "shape", None)
            womb_shape = self._womb_source.shape
            if (
                film_shape is None
                or len(film_shape) != len(womb_shape)
                or tuple(film_shape[2:]) != tuple(womb_shape[2:])
                or str(getattr(film, "dtype", "")) != "uint8"
            ):
                reason = ABANDON_FIRST_FRAME_UNBLENDABLE
                detail = f"shape {film_shape} against the womb's {womb_shape}"
            else:
                womb = resize_bilinear(
                    self._womb_source, int(film_shape[0]), int(film_shape[1])
                )
                base = womb.astype(np.float32)
                delta = film.astype(np.float32)
                np.subtract(delta, base, out=delta)
        with self._lock:
            if self._prepared:  # another surface prepared first
                return self._delta is not None
            self._prepared = True
            if delta is not None:
                self._base = base
                self._delta = delta
                self._buf = np.empty_like(delta)
        if delta is None:
            self._controller.abort(reason or ABANDON_FIRST_FRAME_UNDECODABLE, detail or "")
            return False
        return True

    def frame_at(self, alpha: float) -> np.ndarray | None:
        """The crossfade frame at film weight ``alpha`` (None until prepared).

        Reuses one float32 buffer; the returned uint8 frame is fresh."""
        with self._lock:
            base, delta, buf = self._base, self._delta, self._buf
        if delta is None:
            return None
        with self._blend_lock:
            return _blend_into(base, delta, buf, alpha)

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
            controller.start("video")
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
    held, so the playlist stream parks and nothing is heard. The audio surface
    starts the transition only when there is no video surface.
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
        self._t.controller.start("audio")

    def stop(self) -> None:
        self._inner.stop()

    def close(self) -> None:
        self._inner.close()


__all__ = [
    "ABANDON_FIRST_FRAME_UNBLENDABLE",
    "ABANDON_FIRST_FRAME_UNDECODABLE",
    "TICK_SECONDS",
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
