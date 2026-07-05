# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""LiveCamera unit tests with FakeVideoSource.

No real camera. No disk writes. Verifies the polling cadence, BGR→RGB
conversion path, warmup-frame discarding, and on/off lifecycle.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from kaine.modules.topos.live import (
    LiveCamera,
    LiveCameraConfig,
)


class FakeVideoSource:
    """Implements the _VideoSource protocol. Yields scripted frames."""

    def __init__(
        self,
        frames: list[Any],
        *,
        device: int | str,
        width: int | None,
        height: int | None,
        open_succeeds: bool = True,
    ) -> None:
        self._frames = list(frames)
        self.device = device
        self.width = width
        self.height = height
        self._open_succeeds = open_succeeds
        self.read_count = 0
        self.released = False
        self._idx = 0

    def open(self) -> bool:
        return self._open_succeeds

    def read(self) -> tuple[bool, Any]:
        if self._idx >= len(self._frames):
            return False, None
        frame = self._frames[self._idx]
        self._idx += 1
        self.read_count += 1
        return True, frame

    def release(self) -> None:
        self.released = True


def fake_bgr_to_rgb(frame):
    # Identity — the fake "frame" is just a tag object; conversion is
    # tested as a separate concern.
    return ("rgb", frame)


@pytest.mark.asyncio
async def test_live_camera_calls_sink_with_pil_image_per_interval():
    frames = [f"frame-{i}" for i in range(10)]
    captured: list[Any] = []

    async def sink(image):
        captured.append(image)

    cfg = LiveCameraConfig(
        capture_interval_s=0.02,
        warmup_frames=0,
        desired_state_poll_ms=20,
    )
    sources: list[FakeVideoSource] = []

    def factory(device, *, width, height):
        s = FakeVideoSource(frames, device=device, width=width, height=height)
        sources.append(s)
        return s

    cam = LiveCamera(
        sink,
        config=cfg,
        state_writer=lambda active: None,
        desired_state_reader=lambda: True,
        source_factory=factory,
        bgr_to_rgb=fake_bgr_to_rgb,
    )
    await cam.initialize()
    try:
        for _ in range(40):
            if len(captured) >= 3:
                break
            await asyncio.sleep(0.03)
    finally:
        await cam.shutdown()
    assert len(captured) >= 3
    assert all(item[0] == "rgb" for item in captured[:3])
    assert sources and sources[0].released is True


@pytest.mark.asyncio
async def test_live_camera_discards_warmup_frames():
    frames = [f"frame-{i}" for i in range(10)]
    captured: list[Any] = []

    async def sink(image):
        captured.append(image)

    cfg = LiveCameraConfig(
        capture_interval_s=0.02,
        warmup_frames=3,
        desired_state_poll_ms=20,
    )

    def factory(device, *, width, height):
        return FakeVideoSource(frames, device=device, width=width, height=height)

    cam = LiveCamera(
        sink,
        config=cfg,
        state_writer=lambda active: None,
        desired_state_reader=lambda: True,
        source_factory=factory,
        bgr_to_rgb=fake_bgr_to_rgb,
    )
    await cam.initialize()
    try:
        for _ in range(40):
            if len(captured) >= 1:
                break
            await asyncio.sleep(0.03)
    finally:
        await cam.shutdown()
    # First sink call must be at least the warmup-th frame.
    assert captured
    first = captured[0][1]
    # frame-0..2 are warmup, frame-3 is first delivered.
    assert first == "frame-3"


@pytest.mark.asyncio
async def test_live_camera_respects_desired_off():
    factory_calls = []

    def factory(device, *, width, height):
        factory_calls.append((device, width, height))
        return FakeVideoSource([], device=device, width=width, height=height)

    cam = LiveCamera(
        sink=lambda image: asyncio.sleep(0),
        config=LiveCameraConfig(
            capture_interval_s=0.02, desired_state_poll_ms=20
        ),
        state_writer=lambda active: None,
        desired_state_reader=lambda: False,
        source_factory=factory,
        bgr_to_rgb=fake_bgr_to_rgb,
    )
    await cam.initialize()
    await asyncio.sleep(0.2)
    await cam.shutdown()
    assert factory_calls == []


@pytest.mark.asyncio
async def test_live_camera_emits_state_changes():
    states: list[bool] = []
    cam = LiveCamera(
        sink=lambda image: asyncio.sleep(0),
        config=LiveCameraConfig(
            capture_interval_s=0.05,
            warmup_frames=0,
            desired_state_poll_ms=20,
        ),
        state_writer=lambda active: states.append(bool(active)),
        desired_state_reader=lambda: True,
        source_factory=lambda device, *, width, height: FakeVideoSource(
            [f"f-{i}" for i in range(3)],
            device=device, width=width, height=height,
        ),
        bgr_to_rgb=fake_bgr_to_rgb,
    )
    await cam.initialize()
    for _ in range(20):
        if True in states:
            break
        await asyncio.sleep(0.05)
    await cam.shutdown()
    assert True in states
    assert False in states


@pytest.mark.asyncio
async def test_live_camera_open_failure_retries_quietly():
    cam = LiveCamera(
        sink=lambda image: asyncio.sleep(0),
        config=LiveCameraConfig(
            capture_interval_s=0.05, desired_state_poll_ms=20
        ),
        state_writer=lambda active: None,
        desired_state_reader=lambda: True,
        source_factory=lambda device, *, width, height: FakeVideoSource(
            [], device=device, width=width, height=height,
            open_succeeds=False,
        ),
        bgr_to_rgb=fake_bgr_to_rgb,
    )
    await cam.initialize()
    await asyncio.sleep(0.2)
    await cam.shutdown()
    # The test passes if no exception propagated. Camera stays inactive.
    assert cam.active is False
