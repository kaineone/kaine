# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Cross-platform screen / window capture as a Topos ``_VideoSource``.

A shared desktop or a single window is the most flexible live-stimulus source:
whatever the operator plays there — a browser, a media player with a playlist, a
game — the entity sees, with nothing stream-specific to wire up. Because KAINE
runs on Windows, macOS, and X11 Linux, capture goes through the **system ffmpeg
binary** rather than a Python library: ffmpeg is the one tool that carries every
platform's capture input device (``gdigrab`` on Windows, ``avfoundation`` on
macOS, ``x11grab`` on X11) and desktop-audio capture, whereas the PyAV pip wheels
ship without those input devices. Only the per-OS *input spec* differs; it is a
pure function (:func:`screen_capture_spec`), unit-tested per platform.

The source spawns one ffmpeg that scales the capture to Topos's configured
geometry and emits raw ``bgr24`` frames on stdout, which the source reads a frame
at a time and hands to Topos as a BGR ``ndarray`` — the same shape the webcam
source yields, so nothing downstream of ``Topos.process_frame`` changes. The
process spawner is injected so the framing/lifecycle logic is testable without a
display; the real one runs ffmpeg. As with all perception, raw frames are held in
memory and released, never written to disk.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from kaine.modules.topos.live import PerceptionUnavailableError

log = logging.getLogger(__name__)


def current_platform() -> str:
    """Coarse platform key for capture-spec selection: 'windows' | 'darwin' | 'linux'."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


@dataclass(frozen=True)
class ScreenTarget:
    """What to capture. ``kind`` is 'fullscreen', 'region', or 'window'.

    ``region`` is ``(x, y, width, height)`` for a region, or the resolved window
    geometry on platforms that grab a window as a screen region (X11, macOS).
    ``window_title`` names a window where the OS grabs by title directly
    (Windows/gdigrab). ``display`` is the X11 display (e.g. ``:0.0``); ignored off
    X11. ``framerate`` is the capture rate in frames per second; ``cursor`` draws
    the mouse pointer into the frame.
    """

    kind: str = "fullscreen"
    region: tuple[int, int, int, int] | None = None
    window_title: str | None = None
    display: str = ":0.0"
    framerate: int = 10
    cursor: bool = True


@dataclass(frozen=True)
class CaptureSpec:
    """The ffmpeg *input* arguments for one OS — the ``-f <indev> [opts] -i <dev>``
    portion of the command. The source appends the output (scale + rawvideo)."""

    input_args: list[str] = field(default_factory=list)


def _mouse(cursor: bool) -> str:
    return "1" if cursor else "0"


def screen_capture_spec(
    target: ScreenTarget, *, platform: str | None = None
) -> CaptureSpec:
    """Pure per-OS mapping from a :class:`ScreenTarget` to ffmpeg input arguments.

    Windows uses ``gdigrab`` (full desktop, a region, or a window by title). macOS
    uses ``avfoundation`` (full screen; window/region need a pre-crop ffmpeg cannot
    do on that indev, so those raise). Linux uses ``x11grab`` (full display or a
    region, including a resolved window geometry). A native-Wayland session must
    run capture through XWayland (the runtime builder detects and reports).
    """
    platform = platform or current_platform()
    fps = str(int(target.framerate))

    if platform == "windows":
        args = [
            "-f",
            "gdigrab",
            "-framerate",
            fps,
            "-draw_mouse",
            _mouse(target.cursor),
        ]
        if target.kind == "window":
            if not target.window_title:
                raise ValueError("window capture on Windows requires window_title")
            return CaptureSpec([*args, "-i", f"title={target.window_title}"])
        if target.kind == "region":
            x, y, w, h = _require_region(target)
            args += [
                "-offset_x",
                str(x),
                "-offset_y",
                str(y),
                "-video_size",
                f"{w}x{h}",
            ]
        return CaptureSpec([*args, "-i", "desktop"])

    if platform == "darwin":
        if target.kind != "fullscreen":
            raise ValueError(
                "macOS (avfoundation) captures a whole screen only; window/region "
                "capture is not supported on this backend"
            )
        return CaptureSpec(
            [
                "-f",
                "avfoundation",
                "-framerate",
                fps,
                "-capture_cursor",
                _mouse(target.cursor),
                "-i",
                "1:none",
            ]
        )

    # linux / x11grab (also covers XWayland sessions)
    args = ["-f", "x11grab", "-framerate", fps, "-draw_mouse", _mouse(target.cursor)]
    if target.kind in ("window", "region"):
        x, y, w, h = _require_region(target)
        args += ["-video_size", f"{w}x{h}", "-i", f"{target.display}+{x},{y}"]
        return CaptureSpec(args)
    return CaptureSpec([*args, "-i", target.display])


def _require_region(target: ScreenTarget) -> tuple[int, int, int, int]:
    if not target.region:
        raise ValueError(
            f"{target.kind} capture requires a resolved region=(x, y, w, h)"
        )
    return target.region


def _default_run_command(cmd: list[str]) -> str:
    """Run a short probe command and return its stdout (empty string on failure)."""
    try:
        out = subprocess.run(  # noqa: S603 — cmd is a fixed probe (xrandr)
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=3,
            check=False,
        )
        return out.stdout.decode("utf-8", "replace")
    except Exception:
        return ""


def detect_screen_size(
    target: ScreenTarget,
    *,
    platform: str | None = None,
    run_command: Callable[[list[str]], str] | None = None,
) -> tuple[int, int] | None:
    """Best-effort native pixel size of the capture target, for the native grab.

    A region or window target already carries its own resolved geometry, so its
    size is returned directly. For a fullscreen target the display resolution is
    probed — on X11 via ``xrandr`` (the current mode, marked ``*``). Returns
    ``None`` when the size cannot be determined (e.g. no probe on this platform);
    the caller then falls back to the configured capture geometry rather than
    guessing. The command runner is injected so the parsing is unit-testable
    without a display.
    """
    if target.kind in ("region", "window") and target.region:
        _, _, w, h = target.region
        return (int(w), int(h))
    platform = platform or current_platform()
    if platform != "linux":
        # No portable fullscreen probe wired for gdigrab/avfoundation yet; the
        # operator sets capture_width/height to the panel resolution instead.
        return None
    run = run_command or _default_run_command
    out = run(["xrandr", "--display", target.display, "--current"])
    return _parse_xrandr_current(out)


def _parse_xrandr_current(text: str) -> tuple[int, int] | None:
    """Parse the current (``*``-marked) mode's ``WxH`` from ``xrandr`` output."""
    for line in text.splitlines():
        if "*" not in line:
            continue
        for token in line.split():
            if "x" in token:
                w, _, h = token.partition("x")
                # A mode token is 'WIDTHxHEIGHT' possibly with a trailing '+'.
                h = h.split("+")[0]
                if w.isdigit() and h.isdigit():
                    return (int(w), int(h))
    return None


def _default_open_process(cmd: list[str]) -> Any:
    """Spawn ffmpeg; raise a perception error if the binary is absent."""
    try:
        return subprocess.Popen(  # noqa: S603 — cmd is built from a fixed spec
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
        )
    except FileNotFoundError as exc:
        raise PerceptionUnavailableError(
            "ffmpeg not found on PATH — screen capture requires the system ffmpeg "
            "binary (Debian/Ubuntu: apt install ffmpeg)"
        ) from exc


def _read_exact(stream: Any, n: int) -> bytes | None:
    """Read exactly ``n`` bytes from ``stream``, or None at EOF/short read."""
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)


class ScreenCaptureSource:
    """A Topos ``_VideoSource`` backed by a system-ffmpeg screen/window capture.

    ``open()`` spawns ffmpeg scaling the capture to ``(width, height)`` and
    emitting raw ``bgr24`` frames; ``read()`` returns the next frame as a
    ``(height, width, 3)`` BGR ``ndarray`` (the webcam source's shape);
    ``release()`` stops ffmpeg. The process spawner is injected so the framing and
    lifecycle are testable without a display.
    """

    def __init__(
        self,
        spec: CaptureSpec,
        *,
        width: int,
        height: int,
        ffmpeg_path: str = "ffmpeg",
        native: bool = False,
        open_process: Callable[[list[str]], Any] | None = None,
    ) -> None:
        self._spec = spec
        self._width = int(width)
        self._height = int(height)
        self._ffmpeg_path = ffmpeg_path
        # Native passthrough (topos-foveation): emit frames at the capture's own
        # resolution with no scale filter, so the foveal crop carries true native
        # detail. (width, height) must then be the actual capture resolution — the
        # builder detects it — because they size the raw-frame reshape.
        self._native = bool(native)
        self._open_process = open_process or _default_open_process
        self._frame_bytes = self._width * self._height * 3
        self._proc: Any = None

    def command(self) -> list[str]:
        """The full ffmpeg command: the OS input spec, emitted as raw bgr24 on
        stdout. Scaled to Topos geometry unless native passthrough is set."""
        scale_args = (
            [] if self._native else ["-vf", f"scale={self._width}:{self._height}"]
        )
        return [
            self._ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            *self._spec.input_args,
            *scale_args,
            "-pix_fmt",
            "bgr24",
            "-f",
            "rawvideo",
            "-",
        ]

    def open(self) -> bool:
        try:
            self._proc = self._open_process(self.command())
        except PerceptionUnavailableError:
            raise
        except Exception:
            log.warning("screen capture failed to start ffmpeg", exc_info=True)
            self._proc = None
            return False
        return self._proc is not None and self._proc.stdout is not None

    def read(self) -> tuple[bool, Any]:
        if self._proc is None or self._proc.stdout is None:
            return False, None
        data = _read_exact(self._proc.stdout, self._frame_bytes)
        if data is None:
            return False, None
        frame = np.frombuffer(data, dtype=np.uint8).reshape(
            self._height, self._width, 3
        )
        return True, frame

    def release(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            if proc.stdout is not None:
                proc.stdout.close()
        except Exception:
            log.debug("screen capture stdout close raised", exc_info=True)
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                log.debug("screen capture kill raised", exc_info=True)
