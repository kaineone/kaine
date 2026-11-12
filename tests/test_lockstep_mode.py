# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
from typing import Any, ClassVar

import pytest

from kaine.bus.schema import Event
from kaine.modules.base import BaseModule, _current_tick

# ---------------------------------------------------------------------------
# Minimal fakes — language module tracking
# ---------------------------------------------------------------------------


class FakeBus:
    """Minimal AsyncBus-compatible mock for unit tests."""

    def __init__(self) -> None:
        self.published: list[Event] = []
        self._broadcasts: list[tuple[str, dict[str, Any]]] = []

    async def publish(self, event: Event) -> str:
        self.published.append(event)
        return f"fake-{len(self.published)}"

    async def current_workspace_id(self) -> str:
        return "$"


class TrackingModule(BaseModule):
    name: ClassVar[str] = "tracker"

    def __init__(self, bus: FakeBus) -> None:
        super().__init__(bus)  # type: ignore[arg-type]

    async def on_workspace(self, snapshot: Any) -> None:
        pass


# ---------------------------------------------------------------------------
# 1. Language module: _dispatch_intent tracks generation tasks with tick context
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_track_registers_task() -> None:
    bus = FakeBus()
    mod = TrackingModule(bus)
    token = _current_tick.set(7)
    try:
        task = asyncio.create_task(asyncio.sleep(0))
        mod.track(task)
    finally:
        _current_tick.reset(token)
    assert 7 in mod._tracked_tasks
    assert task in mod._tracked_tasks[7]
    await task


@pytest.mark.asyncio
async def test_current_tick_context_var_set_and_reset() -> None:
    bus = FakeBus()
    mod = TrackingModule(bus)
    token = _current_tick.set(5)
    try:
        await mod.publish("tracker.ping", {"v": 1}, salience=0.2)
    finally:
        _current_tick.reset(token)
    assert len(bus.published) == 1
    assert bus.published[0].tick == 5
    assert _current_tick.get(None) is None


# ---------------------------------------------------------------------------
# Minimal fakes — interoception
# ---------------------------------------------------------------------------


class FakeMetricsReader:
    def __init__(self, metrics: dict[str, float] | None = None) -> None:
        self._metrics = metrics or {"cpu_percent": 10.0, "ram_percent": 20.0}
        self.latencies: list[float] = []
        self.initialized = False
        self.shutdown_called = False

    async def initialize(self) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        self.shutdown_called = True

    async def read_metrics(self) -> dict[str, float]:
        out = dict(self._metrics)
        if self.latencies:
            out["cycle_latency_avg_ms"] = sum(self.latencies) / len(self.latencies)
        return out

    def update_cycle_latency_sample(self, wall_duration_ms: float) -> None:
        self.latencies.append(float(wall_duration_ms))


@pytest.fixture
async def intero_bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig

    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


# ---------------------------------------------------------------------------
# 2. Interoception: lockstep flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_interoception_lockstep_defaults_false(intero_bus: Any) -> None:
    from kaine.modules.interoception import Interoception

    intero = Interoception(intero_bus, reader=FakeMetricsReader())
    assert intero._lockstep is False


@pytest.mark.asyncio
async def test_interoception_lockstep_stored_when_true(intero_bus: Any) -> None:
    from kaine.modules.interoception import Interoception

    intero = Interoception(intero_bus, reader=FakeMetricsReader(), lockstep=True)
    assert intero._lockstep is True


@pytest.mark.asyncio
async def test_produce_loop_dispatches_to_lockstep(intero_bus: Any) -> None:
    from kaine.modules.interoception import Interoception

    intero = Interoception(intero_bus, reader=FakeMetricsReader(), lockstep=True)
    called = False

    async def fake_lockstep() -> None:
        nonlocal called
        called = True

    intero._produce_loop_lockstep = fake_lockstep  # type: ignore[assignment]
    await intero._produce_loop()
    assert called


# ---------------------------------------------------------------------------
# Minimal fakes — vision LiveCamera
# ---------------------------------------------------------------------------


class FakeVideoSource:
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


def fake_bgr_to_rgb(frame: Any) -> Any:
    return ("rgb", frame)


# ---------------------------------------------------------------------------
# 3. Vision LiveCamera: lockstep_trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_camera_lockstep_trigger_stored() -> None:
    from kaine.modules.vision.live import LiveCamera

    sentinel = object()

    async def noop_sink(image: Any) -> None:
        pass

    cam = LiveCamera(noop_sink, lockstep_trigger=sentinel)
    assert cam._lockstep_trigger is sentinel


@pytest.mark.asyncio
async def test_live_camera_lockstep_trigger_default_none() -> None:
    from kaine.modules.vision.live import LiveCamera

    async def noop_sink(image: Any) -> None:
        pass

    cam = LiveCamera(noop_sink)
    assert cam._lockstep_trigger is None


@pytest.mark.asyncio
async def test_live_camera_supervise_dispatches_to_lockstep() -> None:
    from kaine.modules.vision.live import LiveCamera

    sentinel = object()

    async def noop_sink(image: Any) -> None:
        pass

    cam = LiveCamera(noop_sink, lockstep_trigger=sentinel)
    called = False

    async def fake_lockstep() -> None:
        nonlocal called
        called = True

    cam._supervise_lockstep = fake_lockstep  # type: ignore[assignment]
    await cam._supervise()
    assert called


@pytest.mark.asyncio
async def test_live_camera_lockstep_captures_per_yield() -> None:
    from kaine.modules.vision.live import LiveCamera, LiveCameraConfig

    async def trigger():  # type: ignore[no-untyped-def]
        for i in range(3):
            yield i

    frames = [f"frame-{i}" for i in range(20)]
    captured: list[Any] = []

    async def sink(image: Any) -> None:
        captured.append(image)

    def factory(
        device: int | str, *, width: int | None = None, height: int | None = None
    ) -> FakeVideoSource:
        return FakeVideoSource(frames, device=device, width=width, height=height)

    cfg = LiveCameraConfig(
        capture_interval_s=0.02,
        warmup_frames=3,
        desired_state_poll_ms=20,
    )
    cam = LiveCamera(
        sink,
        config=cfg,
        source_factory=factory,
        bgr_to_rgb=fake_bgr_to_rgb,
        lockstep_trigger=trigger(),
    )
    await cam.initialize()
    await asyncio.sleep(0.3)
    await cam.shutdown()
    assert len(captured) == 3


# ---------------------------------------------------------------------------
# 4. Audition LiveMicrophone: lockstep_trigger
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_live_mic_lockstep_trigger_stored() -> None:
    from kaine.modules.audition.live import LiveMicrophone

    sentinel = object()

    async def noop_sink(data: bytes, sr: int, label: str) -> None:
        pass

    mic = LiveMicrophone(noop_sink, lockstep_trigger=sentinel)
    assert mic._lockstep_trigger is sentinel


@pytest.mark.asyncio
async def test_live_mic_lockstep_trigger_default_none() -> None:
    from kaine.modules.audition.live import LiveMicrophone

    async def noop_sink(data: bytes, sr: int, label: str) -> None:
        pass

    mic = LiveMicrophone(noop_sink)
    assert mic._lockstep_trigger is None


@pytest.mark.asyncio
async def test_live_mic_supervise_dispatches_to_lockstep() -> None:
    from kaine.modules.audition.live import LiveMicrophone

    sentinel = object()

    async def noop_sink(data: bytes, sr: int, label: str) -> None:
        pass

    mic = LiveMicrophone(noop_sink, lockstep_trigger=sentinel)
    called = False

    async def fake_lockstep() -> None:
        nonlocal called
        called = True

    mic._supervise_lockstep = fake_lockstep  # type: ignore[assignment]
    await mic._supervise()
    assert called
