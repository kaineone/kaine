# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the continuous input gate (condition 8)."""
from __future__ import annotations

import threading
import time
from typing import Any

from kaine.cycle.input_check import check_input_condition
from kaine.modules.topos.live import PerceptionUnavailableError
from kaine.preboot import CheckResult
from tests.zero_persistence import (
    WriteRecorder,
    leaked_writes,
    redirect_temp,
    scan,
)


def _make_camera_factory(
    *, opened: bool = True, ok: bool = True, frame: Any = None, raise_on_read: bool = False
) -> Any:
    def _factory(device: Any, width: Any = None, height: Any = None) -> Any:
        instance: Any = type("FakeCam", (), {})()
        instance.device = device
        instance.width = width
        instance.height = height
        instance.released = False

        def open() -> bool:
            return opened

        def read() -> tuple[bool, Any]:
            if raise_on_read:
                raise RuntimeError("read boom")
            return ok, frame

        def release() -> None:
            instance.released = True

        instance.open = open
        instance.read = read
        instance.release = release
        return instance

    return _factory


def _make_mic_factory(*, deliver: bool = True, delay: float = 0.0) -> Any:
    def _factory(**kwargs: Any) -> Any:
        callback = kwargs["callback"]
        instance: Any = type("FakeMic", (), {})()
        instance.started = False
        instance.stopped = False
        instance.closed = False
        instance._thread = None

        def start() -> None:
            instance.started = True
            if deliver:

                def _run() -> None:
                    if delay:
                        time.sleep(delay)
                    if not instance.stopped:
                        callback(b"\x00" * 64)

                instance._thread = threading.Thread(target=_run, daemon=True)
                instance._thread.start()

        def stop() -> None:
            instance.stopped = True

        def close() -> None:
            instance.closed = True

        instance.start = start
        instance.stop = stop
        instance.close = close
        return instance

    return _factory


def test_mode_off_refused():
    cond = check_input_condition({"perception_feed": {"mode": "off"}})
    assert not cond.ok
    assert cond.reason == "no input: [perception_feed].mode is off"


def test_mode_playlist_refused():
    cond = check_input_condition({"perception_feed": {"mode": "playlist"}})
    assert not cond.ok
    assert "playlist ends" in cond.reason


def test_mode_unknown_refused():
    cond = check_input_condition({"perception_feed": {"mode": "loop"}})
    assert not cond.ok
    assert "unsupported perception mode" in cond.reason


def test_seeded_no_perceiving_module():
    cond = check_input_condition({"perception_feed": {"mode": "seeded"}, "modules": {}})
    assert not cond.ok
    assert "no perceiving module" in cond.reason
    assert "capture_enabled" not in cond.reason


def test_live_modules_disabled_capture():
    cond = check_input_condition(
        {
            "perception_feed": {"mode": "live"},
            "modules": {"topos": True, "audition": True},
            "topos": {"capture_enabled": False},
            "audition": {"capture_enabled": False},
        }
    )
    assert not cond.ok
    assert "no perceiving module" in cond.reason
    assert "capture_enabled" in cond.reason


def test_live_camera_success():
    cond = check_input_condition(
        {
            "perception_feed": {"mode": "live"},
            "modules": {"topos": True, "audition": True},
            "topos": {"capture_enabled": True},
            "audition": {"capture_enabled": True},
        },
        camera_factory=_make_camera_factory(frame=object()),
        mic_factory=_make_mic_factory(deliver=True, delay=0.01),
        timeout_s=0.5,
    )
    assert cond.ok


def test_camera_open_false():
    cond = check_input_condition(
        {
            "perception_feed": {"mode": "live"},
            "modules": {"topos": True},
            "topos": {"capture_enabled": True},
        },
        camera_factory=_make_camera_factory(opened=False),
    )
    assert not cond.ok
    assert "camera" in cond.reason


def test_camera_read_empty():
    cond = check_input_condition(
        {
            "perception_feed": {"mode": "live"},
            "modules": {"topos": True},
            "topos": {"capture_enabled": True},
        },
        camera_factory=_make_camera_factory(ok=False, frame=None),
    )
    assert not cond.ok
    assert "camera" in cond.reason


def test_microphone_success():
    cond = check_input_condition(
        {
            "perception_feed": {"mode": "live"},
            "modules": {"audition": True},
            "audition": {"capture_enabled": True},
        },
        mic_factory=_make_mic_factory(deliver=True, delay=0.01),
        timeout_s=0.5,
    )
    assert cond.ok


def test_microphone_never_delivers():
    cond = check_input_condition(
        {
            "perception_feed": {"mode": "live"},
            "modules": {"audition": True},
            "audition": {"capture_enabled": True},
        },
        mic_factory=_make_mic_factory(deliver=False),
        timeout_s=0.2,
    )
    assert not cond.ok
    assert "microphone" in cond.reason


def test_perception_unavailable_error_is_caught():
    cond = check_input_condition(
        {
            "perception_feed": {"mode": "live"},
            "modules": {"topos": True},
            "topos": {"capture_enabled": True},
        },
        camera_factory=lambda _d, width=None, height=None: (_
            for _ in ()
        ).throw(
            PerceptionUnavailableError("opencv-python-headless not installed")
        ),
    )
    assert not cond.ok
    assert "PerceptionUnavailableError" in cond.reason
    assert "opencv-python-headless" in cond.reason


def test_one_surface_failing_still_passes():
    cond = check_input_condition(
        {
            "perception_feed": {"mode": "live"},
            "modules": {"topos": True, "audition": True},
            "topos": {"capture_enabled": True},
            "audition": {"capture_enabled": True},
        },
        camera_factory=_make_camera_factory(frame=object()),
        mic_factory=_make_mic_factory(deliver=False),
        timeout_s=0.2,
    )
    assert cond.ok


def test_seeded_pass():
    def _check(config: dict[str, Any]) -> list[CheckResult]:
        return [
            CheckResult("perception", "video seed", "PASS", ""),
            CheckResult("perception", "audio seed", "PASS", ""),
        ]

    cond = check_input_condition(
        {
            "perception_feed": {"mode": "seeded"},
            "modules": {"topos": True, "audition": True},
        },
        perception_check=_check,
    )
    assert cond.ok



def test_womb_is_continuous_input():
    # The womb never ends (unlike a playlist), so it satisfies condition 8
    # when its sources deliver.
    def _check(config: dict[str, Any]) -> list[CheckResult]:
        return [
            CheckResult("perception", "video womb", "PASS", ""),
            CheckResult("perception", "audio womb", "PASS", ""),
        ]

    cond = check_input_condition(
        {
            "perception_feed": {"mode": "womb"},
            "modules": {"topos": True, "audition": True},
        },
        perception_check=_check,
    )
    assert cond.ok

def test_seeded_fail():
    def _check(config: dict[str, Any]) -> list[CheckResult]:
        return [
            CheckResult("perception", "video seed", "FAIL", "seed video missing"),
            CheckResult("perception", "audio seed", "FAIL", "seed audio missing"),
        ]

    cond = check_input_condition(
        {
            "perception_feed": {"mode": "seeded"},
            "modules": {"topos": True, "audition": True},
        },
        perception_check=_check,
    )
    assert not cond.ok
    assert "video source: seed video missing" in cond.reason
    assert "audio source: seed audio missing" in cond.reason


def test_camera_release_on_read_error():
    factory = _make_camera_factory(raise_on_read=True)
    cond = check_input_condition(
        {
            "perception_feed": {"mode": "live"},
            "modules": {"topos": True},
            "topos": {"capture_enabled": True},
        },
        camera_factory=factory,
    )
    assert not cond.ok
    assert "read boom" in cond.reason


def test_probe_leaves_no_trace(tmp_path, monkeypatch):
    private = redirect_temp(tmp_path, monkeypatch)
    banned = [
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".tiff",
        ".raw",
        ".wav",
        ".pcm",
        ".mp3",
        ".mp4",
        ".avi",
        ".mkv",
    ]

    with WriteRecorder() as recorder:
        cond = check_input_condition(
            {
                "perception_feed": {"mode": "live"},
                "modules": {"topos": True, "audition": True},
                "topos": {"capture_enabled": True},
                "audition": {"capture_enabled": True},
            },
            camera_factory=_make_camera_factory(frame=object()),
            mic_factory=_make_mic_factory(deliver=True, delay=0.01),
            timeout_s=0.5,
        )
        assert cond.ok

    assert not leaked_writes(recorder.writes, banned)
    assert not scan(private, banned)


def test_microphone_probe_uses_the_boot_audio_settings():
    """The probe opens the mic with the same keys and block size as the boot."""
    seen: dict = {}

    class _Stream:
        def __init__(self, callback):
            self._callback = callback

        def start(self):
            self._callback(b"\x00\x00")

        def stop(self):
            pass

        def close(self):
            pass

    def factory(**kwargs):
        seen.update(kwargs)
        return _Stream(kwargs["callback"])

    config = {
        "perception_feed": {"mode": "live"},
        "modules": {"audition": True},
        "audition": {
            "capture_enabled": True,
            "capture_device": "hw:1",
            "capture_sample_rate": 48000,
            "capture_channels": 2,
            "vad_frame_ms": 20,
        },
    }
    result = check_input_condition(config, mic_factory=factory, timeout_s=0.2)
    assert result.ok, result.reason
    assert seen["device"] == "hw:1"
    assert seen["sample_rate"] == 48000
    assert seen["channels"] == 2
    assert seen["frames_per_block"] == 960
