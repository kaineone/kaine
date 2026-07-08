# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Cross-platform screen/window capture source (ffmpeg-backed).

The per-OS input spec is a pure function; the frame path is exercised with a fake
ffmpeg process so these run with no display. The X11 leg is additionally verified
live against a real capture during development (see the module docstring)."""
from __future__ import annotations

import io

import numpy as np
import pytest

from kaine.modules.topos.screen import (
    CaptureSpec,
    ScreenCaptureSource,
    ScreenTarget,
    screen_capture_spec,
)


# --------------------------------------------------------------------------- #
# per-OS input spec (pure)
# --------------------------------------------------------------------------- #


def test_linux_fullscreen_and_region_specs():
    full = screen_capture_spec(ScreenTarget(display=":0.0"), platform="linux")
    assert full.input_args[:2] == ["-f", "x11grab"]
    assert full.input_args[-2:] == ["-i", ":0.0"]

    region = screen_capture_spec(
        ScreenTarget(kind="region", region=(10, 20, 640, 480), display=":0.0"),
        platform="linux",
    )
    assert "-video_size" in region.input_args
    assert "640x480" in region.input_args
    assert region.input_args[-1] == ":0.0+10,20"


def test_linux_window_requires_region():
    with pytest.raises(ValueError):
        screen_capture_spec(
            ScreenTarget(kind="window", window_title="Firefox"), platform="linux"
        )


def test_windows_specs():
    win = screen_capture_spec(
        ScreenTarget(kind="window", window_title="VLC"), platform="windows"
    )
    assert win.input_args[:2] == ["-f", "gdigrab"]
    assert win.input_args[-1] == "title=VLC"

    full = screen_capture_spec(ScreenTarget(), platform="windows")
    assert full.input_args[-1] == "desktop"


def test_macos_fullscreen_only():
    mac = screen_capture_spec(ScreenTarget(), platform="darwin")
    assert mac.input_args[:2] == ["-f", "avfoundation"]
    with pytest.raises(ValueError):
        screen_capture_spec(
            ScreenTarget(kind="region", region=(0, 0, 8, 8)), platform="darwin"
        )


def test_cursor_flag_maps_through():
    on = screen_capture_spec(ScreenTarget(cursor=True), platform="linux")
    off = screen_capture_spec(ScreenTarget(cursor=False), platform="linux")
    assert on.input_args[on.input_args.index("-draw_mouse") + 1] == "1"
    assert off.input_args[off.input_args.index("-draw_mouse") + 1] == "0"


# --------------------------------------------------------------------------- #
# frame path (fake ffmpeg process)
# --------------------------------------------------------------------------- #


class _FakeProc:
    def __init__(self, data: bytes) -> None:
        self.stdout = io.BytesIO(data)
        self.terminated = False
        self.killed = False

    def terminate(self) -> None:
        self.terminated = True

    def wait(self, timeout=None):  # noqa: ANN001
        return 0

    def kill(self) -> None:
        self.killed = True


def _source(width: int, height: int, n_frames: int):
    frame_bytes = width * height * 3
    # n_frames distinct frames so we can tell them apart
    data = b"".join(
        bytes([i % 256]) * frame_bytes for i in range(1, n_frames + 1)
    )
    proc = _FakeProc(data)
    src = ScreenCaptureSource(
        CaptureSpec(["-f", "x11grab", "-i", ":0.0"]),
        width=width,
        height=height,
        open_process=lambda cmd: proc,
    )
    return src, proc


def test_reads_frames_then_reports_eof():
    src, proc = _source(4, 2, 2)
    opened = src.open()
    assert opened is True
    ok, f0 = src.read()
    assert ok and f0.shape == (2, 4, 3) and f0.dtype == np.uint8
    ok, f1 = src.read()
    assert ok and int(f1[0, 0, 0]) == 2  # second frame's fill byte
    ok, f2 = src.read()
    assert ok is False and f2 is None  # EOF -> clean stop
    src.release()
    assert proc.terminated is True


def test_short_read_is_a_clean_failure():
    # one byte short of a full frame -> read() returns (False, None), never a crash
    frame_bytes = 4 * 2 * 3
    proc = _FakeProc(b"\x01" * (frame_bytes - 1))
    src = ScreenCaptureSource(
        CaptureSpec(["-i", ":0.0"]), width=4, height=2, open_process=lambda cmd: proc
    )
    opened = src.open()
    assert opened is True
    ok, frame = src.read()
    assert ok is False and frame is None


def test_command_composition_scales_and_emits_rawvideo():
    src = ScreenCaptureSource(
        CaptureSpec(["-f", "x11grab", "-i", ":0.0"]),
        width=320,
        height=240,
        open_process=lambda cmd: _FakeProc(b""),
    )
    cmd = src.command()
    assert cmd[0] == "ffmpeg"
    assert "scale=320:240" in cmd
    assert cmd[-3:] == ["-f", "rawvideo", "-"]
    assert "bgr24" in cmd


def test_read_before_open_is_false():
    src = ScreenCaptureSource(CaptureSpec(["-i", ":0.0"]), width=4, height=2)
    ok, frame = src.read()
    assert ok is False and frame is None
