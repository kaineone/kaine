# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Cross-platform desktop-audio monitor capture (ffmpeg-backed).

The per-OS input spec is pure; the block/threading path is exercised with a fake
ffmpeg process (no audio device). The Linux/pulse leg is additionally verified
live during development (see the module docstring)."""
from __future__ import annotations

import io
import time

import pytest

from kaine.modules.audition.monitor import (
    AudioCaptureSpec,
    MonitorAudioStream,
    audio_capture_spec,
)


# --------------------------------------------------------------------------- #
# per-OS input spec (pure)
# --------------------------------------------------------------------------- #


def test_specs_per_platform():
    lin = audio_capture_spec("alsa_output.x.monitor", platform="linux")
    assert lin.input_args == ["-f", "pulse", "-i", "alsa_output.x.monitor"]
    win = audio_capture_spec("Stereo Mix", platform="windows")
    assert win.input_args == ["-f", "dshow", "-i", "audio=Stereo Mix"]
    mac = audio_capture_spec("0", platform="darwin")
    assert mac.input_args == ["-f", "avfoundation", "-i", ":0"]


def test_empty_device_raises_with_guidance():
    with pytest.raises(ValueError):
        audio_capture_spec("", platform="linux")


# --------------------------------------------------------------------------- #
# block / lifecycle path (fake ffmpeg process)
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


def test_dispatches_fixed_pcm_blocks_then_stops():
    frames_per_block, channels = 4, 1
    block_bytes = frames_per_block * channels * 2  # int16 => 8 bytes
    n_blocks = 3
    data = b"".join(bytes([i]) * block_bytes for i in (1, 2, 3))
    proc = _FakeProc(data)
    captured: list[bytes] = []

    src = MonitorAudioStream(
        AudioCaptureSpec(["-f", "pulse", "-i", "x.monitor"]),
        sample_rate=16000,
        channels=channels,
        frames_per_block=frames_per_block,
        callback=captured.append,
        open_process=lambda cmd: proc,
    )
    src.start()
    deadline = time.time() + 2.0
    while len(captured) < n_blocks and time.time() < deadline:
        time.sleep(0.01)
    src.stop()

    assert len(captured) == n_blocks
    assert all(len(block) == block_bytes for block in captured)
    assert captured[1][0] == 2  # second block's fill byte
    assert proc.terminated is True


def test_command_emits_s16le_at_target_rate():
    src = MonitorAudioStream(
        AudioCaptureSpec(["-f", "pulse", "-i", "x.monitor"]),
        sample_rate=16000,
        channels=1,
        frames_per_block=160,
        callback=lambda b: None,
        open_process=lambda cmd: _FakeProc(b""),
    )
    cmd = src.command()
    assert cmd[0] == "ffmpeg"
    assert cmd[-3:] == ["-f", "s16le", "-"]
    assert "16000" in cmd and "s16le" in cmd


def test_double_start_is_idempotent():
    src = MonitorAudioStream(
        AudioCaptureSpec(["-i", "x"]),
        sample_rate=16000,
        channels=1,
        frames_per_block=4,
        callback=lambda b: None,
        open_process=lambda cmd: _FakeProc(b""),
    )
    src.start()
    proc1 = src._proc
    src.start()  # no-op while running
    assert src._proc is proc1
    src.stop()
