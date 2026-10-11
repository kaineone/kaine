# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Engine-level tests for slip-driven automatic time dilation."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from kaine.cycle.engine import CognitiveCycle
from kaine.cycle.time_scale_controller import TimeScaleController, TimeScaleSettings
from kaine.cycle.types import WorkspaceSnapshot
from kaine.entity_clock import EntityClock
from tests._fakes import FakeRegistry


class MonotonicSource:
    """Manual monotonic clock for deterministic wall-time control."""

    def __init__(self) -> None:
        self._t = 0.0

    def __call__(self) -> float:
        return self._t

    def advance(self, dt: float) -> None:
        self._t += dt


class RecordingBus:
    """In-memory bus that records every publish/workspace broadcast."""

    def __init__(self) -> None:
        self.workspace_broadcasts: list[dict[str, Any]] = []
        self.published: dict[str, list[Any]] = {}

    async def read_entries(
        self,
        stream: str,
        last_id: str = "0",
        count: int = 100,
        block_ms: int = 0,
    ) -> tuple[list[tuple[str, Any]], str | None]:
        return [], "0"

    async def publish_workspace(self, payload: dict[str, Any]) -> str:
        self.workspace_broadcasts.append(payload)
        return "ws-1"

    async def publish(self, event: Any) -> str:
        self.published.setdefault(event.type, []).append(event)
        return "id-1"


class SlowSyneidesis:
    """A syneidesis stand-in that spends wall time inside select()."""

    def __init__(self, monotonic: MonotonicSource, delay_s: float = 0.15) -> None:
        self._monotonic = monotonic
        self._delay = delay_s
        self._tick = 0

    async def select(
        self,
        events: list[tuple[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> WorkspaceSnapshot:
        self._monotonic.advance(self._delay)
        self._tick += 1
        return WorkspaceSnapshot(
            tick_index=context.get("tick_index", self._tick) if context else self._tick,
            inhibited=False,
            salience_scores={},
            metadata={},
            selected_events=[],
        )


@pytest.fixture
def monotonic_source() -> MonotonicSource:
    return MonotonicSource()


@pytest.fixture
def dilation_cycle(monotonic_source: MonotonicSource):
    settings = TimeScaleSettings(
        ceiling=1.0,
        floor=0.1,
        target=0.5,
        high=0.95,
        low=0.3,
        dwell_s=0.05,
        window_s=0.05,
    )
    controller = TimeScaleController(settings, initial_scale=1.0)
    entity_clock = EntityClock(
        scale=1.0,
        monotonic=monotonic_source,
        real_sleep=asyncio.sleep,
    )
    bus = RecordingBus()
    registry = FakeRegistry([])
    syneidesis = SlowSyneidesis(monotonic_source, delay_s=0.15)

    cycle = CognitiveCycle(
        bus=bus,
        syneidesis=syneidesis,
        registry=registry,
        processing_rate_hz=10.0,
        entity_clock=entity_clock,
        time_scale_controller=controller,
        time_scale=1.0,
    )
    return cycle, bus, monotonic_source


@pytest.mark.asyncio
async def test_slow_ticks_drive_scale_down_and_publish_event(
    dilation_cycle: tuple[CognitiveCycle, RecordingBus, MonotonicSource],
):
    cycle, bus, _ = dilation_cycle

    assert cycle.time_scale == 1.0
    await cycle.run_forever(max_ticks=40)

    assert cycle.time_scale < 1.0
    stats = cycle.pacing_stats
    assert stats["time_scale_changes"] >= 1
    assert stats["auto_time_scale"] is True

    ts_events = bus.published.get("cycle.time_scale", [])
    assert ts_events, "expected a cycle.time_scale event"
    payload = ts_events[-1].payload
    assert "from" in payload
    assert "to" in payload
    assert payload["to"] < payload["from"]
    assert payload["reason"] in ("overload", "headroom")
    assert "utilization" in payload
    assert payload["window_s"] == pytest.approx(0.05)

    assert bus.workspace_broadcasts
    assert "time_scale" in bus.workspace_broadcasts[-1]

    tick_events = bus.published.get("cycle.tick", [])
    assert tick_events
    assert tick_events[-1].payload["time_scale"] == cycle.time_scale


@pytest.mark.asyncio
async def test_scale_change_keeps_subjective_now_continuous(
    monotonic_source: MonotonicSource,
):
    settings = TimeScaleSettings(
        ceiling=1.0,
        floor=0.1,
        target=0.5,
        high=0.95,
        low=0.3,
        dwell_s=0.01,
        window_s=0.01,
    )
    controller = TimeScaleController(settings, initial_scale=1.0)

    for _ in range(20):
        controller.observe(150.0, 100.0, monotonic_source(), current_scale=1.0)
        monotonic_source.advance(0.01)

    change = controller.observe(150.0, 100.0, monotonic_source(), current_scale=1.0)
    assert change is not None

    clock = EntityClock(
        scale=1.0,
        monotonic=monotonic_source,
        real_sleep=asyncio.sleep,
    )
    now_before = clock.now()
    clock.scale = change.new
    now_after = clock.now()

    assert now_after == pytest.approx(now_before, abs=1e-9)


@pytest.mark.asyncio
async def test_deterministic_mode_drops_controller(
    monotonic_source: MonotonicSource,
    caplog: pytest.LogCaptureFixture,
):
    caplog.set_level(logging.INFO)
    settings = TimeScaleSettings(
        ceiling=1.0,
        floor=0.1,
        target=0.5,
        high=0.95,
        low=0.3,
        dwell_s=0.05,
        window_s=0.05,
    )
    controller = TimeScaleController(settings, initial_scale=1.0)

    cycle = CognitiveCycle(
        bus=RecordingBus(),
        syneidesis=SlowSyneidesis(monotonic_source, delay_s=0.01),
        registry=FakeRegistry([]),
        entity_clock=EntityClock(
            scale=1.0,
            monotonic=monotonic_source,
            real_sleep=asyncio.sleep,
        ),
        deterministic=True,
        time_scale_controller=controller,
    )

    assert cycle._time_scale_controller is None
    assert "automatic time dilation is disabled" in caplog.text


@pytest.mark.asyncio
async def test_cycle_tick_payload_carries_time_scale(
    monotonic_source: MonotonicSource,
):
    cycle = CognitiveCycle(
        bus=RecordingBus(),
        syneidesis=SlowSyneidesis(monotonic_source, delay_s=0.001),
        registry=FakeRegistry([]),
        entity_clock=EntityClock(
            scale=0.75,
            monotonic=monotonic_source,
            real_sleep=asyncio.sleep,
        ),
        processing_rate_hz=10.0,
        time_scale=0.75,
    )

    await cycle.tick()
    tick_events = cycle._bus.published.get("cycle.tick", [])
    assert tick_events
    assert tick_events[-1].payload["time_scale"] == 0.75
