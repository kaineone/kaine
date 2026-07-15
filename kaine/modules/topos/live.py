# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Live camera stream — eyes for the topos surface.

LiveCamera runs as a sibling task launched from Topos.initialize() when
[topos].capture_enabled = true. It opens cv2.VideoCapture(device) in a
background thread, polls a frame every capture_interval_s, converts
BGR→RGB to an in-memory PIL.Image, and hands it to Topos.process_frame().

ZERO PERSISTENCE INVARIANT: raw frames live only in process memory.
The capture path never writes to disk — see the load-bearing test at
tests/test_zero_persistence_invariant.py for the static grep that
fails the build if a frame-writing call sneaks in. Each frame is
released after the sink call returns. Topos's own CosineChangeDetector
+ RollingMeanHabituator handle throttling at the process_frame level.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass, replace
from typing import Any, Awaitable, Callable, Protocol, runtime_checkable

from kaine.entity_clock import EntityClock

log = logging.getLogger(__name__)


class PerceptionUnavailableError(RuntimeError):
    """Raised when capture is enabled but the required extras aren't installed."""


SinkFn = Callable[[Any], Awaitable[Any]]
StateWriter = Callable[[bool], Any]
DesiredReader = Callable[[], bool]
OnStateChange = Callable[[str, dict], None]


@runtime_checkable
class _VideoSource(Protocol):
    def open(self) -> bool: ...
    def read(self) -> tuple[bool, Any]: ...
    def release(self) -> None: ...


@dataclass(frozen=True)
class LiveCameraConfig:
    # ``capture_interval_s`` is the entity's SUBJECTIVE vision-sampling cadence:
    # one frame is sampled every ``capture_interval_s`` *subjective* seconds, and
    # the shared EntityClock translates that to real seconds at the current
    # ``time_scale`` (Phase 2). It is a first-class *subjective rate* decoupled
    # from the workspace tick — the eyes sample at their own rhythm, faster than
    # conscious access (see ``vision_sample_hz``). The class default is 1.0 s
    # (1 Hz) so that direct construction without config arguments stays safe;
    # the shipped config/kaine.toml sets vision_sample_hz = 10.0 (benchmarked-
    # cleared, operator-approved on this host) and that wins at boot.
    device: int | str = 0
    capture_interval_s: float = 1.0
    width: int | None = 640
    height: int | None = 480
    warmup_frames: int = 3
    desired_state_poll_ms: int = 250

    @property
    def vision_sample_hz(self) -> float:
        """The subjective vision-sampling rate in Hz (1 / ``capture_interval_s``).

        The clean, biologically-framed expression of the capture cadence: how
        many frames per *subjective* second the eyes sample. Decoupled from the
        workspace tick (conscious access) — senses run fast underneath a slow
        tick. The class default is 1.0 Hz (no config); the shipped config sets
        10 Hz (benchmarked-cleared, operator-approved on this host).
        """
        if self.capture_interval_s <= 0:
            raise ValueError("capture_interval_s must be positive")
        return 1.0 / self.capture_interval_s

    @staticmethod
    def interval_from_hz(vision_sample_hz: float) -> float:
        """Convert a subjective ``vision_sample_hz`` to a ``capture_interval_s``.

        Lets config/operators express the sense cadence as a rate (the natural
        biological unit) and store it as the interval the supervisor sleeps on.
        """
        if vision_sample_hz <= 0:
            raise ValueError("vision_sample_hz must be positive")
        return 1.0 / vision_sample_hz


class _CV2VideoSource:
    """Wraps cv2.VideoCapture so the LiveCamera doesn't import cv2 at
    module-load time. Constructed only when capture is enabled."""

    def __init__(
        self, device: int | str, *, width: int | None, height: int | None
    ) -> None:
        try:
            import cv2  # type: ignore[import-untyped]
        except ImportError as exc:
            raise PerceptionUnavailableError(
                "opencv-python-headless not installed — install with: pip install -e .[vision]"
            ) from exc
        self._cv2 = cv2
        self._device = device
        self._width = width
        self._height = height
        self._cap: Any = None

    def open(self) -> bool:
        self._cap = self._cv2.VideoCapture(self._device)
        if not self._cap.isOpened():
            return False
        if self._width:
            self._cap.set(self._cv2.CAP_PROP_FRAME_WIDTH, int(self._width))
        if self._height:
            self._cap.set(self._cv2.CAP_PROP_FRAME_HEIGHT, int(self._height))
        return True

    def read(self) -> tuple[bool, Any]:
        if self._cap is None:
            return False, None
        return self._cap.read()

    def release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                log.debug("VideoCapture.release raised", exc_info=True)
            self._cap = None


def _default_source_factory(
    device: int | str, *, width: int | None, height: int | None
) -> _VideoSource:
    return _CV2VideoSource(device, width=width, height=height)


def _bgr_to_pil_rgb(frame: Any) -> Any:
    """Convert a cv2 BGR ndarray to a PIL.Image (RGB). Both libraries
    are imported lazily so the unit tests can pass without them, but at
    runtime when capture is on, OpenCV must be installed (and Pillow is
    already a core dep)."""
    try:
        import cv2  # type: ignore[import-untyped]
        from PIL import Image
    except ImportError as exc:
        raise PerceptionUnavailableError(
            "opencv-python-headless or Pillow missing"
        ) from exc
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


class LiveCamera:
    """Eyes-only camera stream. Constructed by Topos when
    [topos].capture_enabled is true. Lifecycle owned by the parent.

    `sink` is `Topos.process_frame`. The camera hands frames to it and
    never touches the result. Static-scene throttling happens inside
    Topos via change-detection + habituation; nothing here.
    """

    def __init__(
        self,
        sink: SinkFn,
        *,
        config: LiveCameraConfig | None = None,
        state_writer: StateWriter | None = None,
        desired_state_reader: DesiredReader | None = None,
        on_state_change: OnStateChange | None = None,
        source_factory: Callable[..., _VideoSource] | None = None,
        bgr_to_rgb: Callable[[Any], Any] | None = None,
        # Shared subjective clock (injected by Topos at boot). The capture
        # interval is the entity's perception SAMPLING rhythm, so it runs in
        # subjective time — at time_scale != 1.0 the eyes sample at the dilated
        # rate, coherent with the rest of the mind. The desired-state poll
        # (operator on/off flag) stays on REAL time (infrastructural). Defaults
        # to a real-time clock → behavior-identical.
        entity_clock: EntityClock | None = None,
    ) -> None:
        self._sink = sink
        self._cfg = config or LiveCameraConfig()
        self._state_writer = state_writer
        self._desired_reader = desired_state_reader
        self._on_state_change = on_state_change
        self._source_factory = source_factory or _default_source_factory
        self._bgr_to_rgb = bgr_to_rgb or _bgr_to_pil_rgb
        self._clock = entity_clock or EntityClock()
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._active = False
        self._source: _VideoSource | None = None
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._active

    @property
    def config(self) -> LiveCameraConfig:
        return self._cfg

    @property
    def current_item(self) -> Any:
        """Content-free provenance of the item the underlying source is
        presenting, or ``None``. Only the playlist source exposes this (via the
        shared ``PlaylistClock``); the real camera and seeded feeds return
        ``None``. Read by Topos to stamp the playing item onto ``topos.report``
        so the media is legible off the bus rather than inferred from file
        descriptors."""
        return getattr(self._source, "current_item", None)

    def set_vision_sample_hz(self, vision_sample_hz: float) -> None:
        """Retune the subjective vision-sampling rate on a running camera.

        The supervisor reads ``self._cfg.capture_interval_s`` live each loop, so
        swapping in a new frozen config (only the interval changed) takes effect
        on the next capture sleep without restarting the source. This is the
        runtime seam the per-fork timing profile applies a ``vision_sample_hz``
        override through (Phase 4). ``capture_interval_s`` remains a *subjective*
        cadence — the shared clock still translates it to real seconds at the
        current ``time_scale`` — so this only changes the per-second frame count,
        not the dilation handling.
        """
        interval = LiveCameraConfig.interval_from_hz(vision_sample_hz)
        self._cfg = replace(self._cfg, capture_interval_s=interval)
        log.info(
            "live camera vision_sample_hz retuned to %.3f Hz (interval %.4f s)",
            vision_sample_hz,
            interval,
        )

    async def initialize(self) -> None:
        if self._task is not None:
            return
        self._stopped.clear()
        self._task = asyncio.create_task(
            self._supervise(), name="live-camera-supervisor"
        )

    async def shutdown(self) -> None:
        self._stopped.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
        await self._close_source()
        if self._active:
            self._set_active(False)

    async def _supervise(self) -> None:
        try:
            while not self._stopped.is_set():
                desired = self._read_desired()
                if desired and not self._active:
                    if not await self._open_source():
                        # Couldn't open — sleep and retry on next desired-poll.
                        await self._sleep_poll_interval()
                        continue
                elif not desired and self._active:
                    await self._close_source()
                    self._set_active(False)
                    log.info("live camera capture_stopped")
                if self._active:
                    await self._capture_one_frame()
                    await self._sleep_capture_interval()
                else:
                    await self._sleep_poll_interval()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("live camera supervisor crashed")
        finally:
            await self._close_source()
            if self._active:
                self._set_active(False)

    def _read_desired(self) -> bool:
        if self._desired_reader is None:
            return True
        try:
            return bool(self._desired_reader())
        except Exception:
            log.warning("desired_state_reader raised", exc_info=True)
            return self._active

    async def _open_source(self) -> bool:
        try:
            source = await asyncio.to_thread(
                self._source_factory,
                self._cfg.device,
                width=self._cfg.width,
                height=self._cfg.height,
            )
            opened = await asyncio.to_thread(source.open)
        except PerceptionUnavailableError:
            raise
        except Exception:
            log.exception("failed to open camera source")
            return False
        if not opened:
            log.warning("camera device %s could not be opened", self._cfg.device)
            try:
                source.release()
            except Exception:
                # Best-effort teardown of a source that never finished opening;
                # `source` is a pluggable _VideoSource (cv2 or a seeded feed) so
                # its release() failure modes aren't known here, and the open
                # already failed so there's nothing left to protect.
                pass
            return False
        self._source = source
        # Discard the first few frames (auto-exposure / WB settle).
        for _ in range(max(0, self._cfg.warmup_frames)):
            try:
                ok, _ = await asyncio.to_thread(source.read)
                if not ok:
                    break
            except Exception:
                break
        self._set_active(True)
        log.info(
            "live camera capture_started device=%s width=%s height=%s interval_s=%.3f",
            self._cfg.device,
            self._cfg.width,
            self._cfg.height,
            self._cfg.capture_interval_s,
        )
        return True

    async def _close_source(self) -> None:
        source = self._source
        self._source = None
        if source is None:
            return
        try:
            await asyncio.to_thread(source.release)
        except Exception:
            log.debug("source.release raised", exc_info=True)

    async def _capture_one_frame(self) -> None:
        source = self._source
        if source is None:
            return
        try:
            ok, frame = await asyncio.to_thread(source.read)
        except Exception:
            log.warning("frame_capture_failed read error", exc_info=True)
            return
        if not ok or frame is None:
            log.warning("frame_capture_failed empty read from %s", self._cfg.device)
            return
        try:
            image = await asyncio.to_thread(self._bgr_to_rgb, frame)
        except Exception:
            log.warning("frame_capture_failed BGR→RGB conversion", exc_info=True)
            return
        # Drop the raw BGR ndarray immediately. PIL.Image holds the RGB
        # copy and gets handed off; the input ndarray is GC'd here.
        frame = None  # noqa: F841
        try:
            await self._sink(image)
        except Exception:
            log.exception("live camera sink raised")

    async def _sleep_capture_interval(self) -> None:
        # Perception sampling cadence — cognitive. The SUBJECTIVE
        # capture_interval_s maps to capture_interval_s / scale real seconds
        # (the clock's translation); at scale 1.0 it is unchanged. The wait_for
        # keeps the prompt-shutdown race.
        scale = self._clock.scale
        timeout = (
            self._cfg.capture_interval_s
            if scale <= 0  # frozen: pause path holds the loop; don't div-by-zero
            else self._cfg.capture_interval_s / scale
        )
        try:
            await asyncio.wait_for(self._stopped.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            return

    async def _sleep_poll_interval(self) -> None:
        # Desired-state poll: how often we re-check the operator's on/off flag.
        # Infrastructure housekeeping, not cognition — stays on real wall time
        # so the camera reacts to the operator at a fixed cadence regardless of
        # the entity's time_scale.
        # infrastructural: real time, not subjective
        try:
            await asyncio.wait_for(
                self._stopped.wait(),
                timeout=self._cfg.desired_state_poll_ms / 1000.0,
            )
        except asyncio.TimeoutError:
            return

    def _set_active(self, active: bool) -> None:
        with self._lock:
            if self._active == active:
                return
            self._active = active
        if self._state_writer is not None:
            try:
                self._state_writer(active)
            except Exception:
                log.warning("perception state_writer raised", exc_info=True)
        if self._on_state_change is not None:
            try:
                self._on_state_change(
                    "capture_started" if active else "capture_stopped",
                    {"surface": "video", "device": self._cfg.device},
                )
            except Exception:
                log.debug("on_state_change raised", exc_info=True)
