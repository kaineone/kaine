# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the hearing stage surface in runtime.json."""
from __future__ import annotations

import asyncio
import json
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from kaine.bus.schema import Event
from kaine.cycle.__main__ import (
    _phase_development,
    _start_stimulus_source_presence,
    _write_runtime_state,
)
from kaine.cycle.hearing_stage_watch import HearingStageWatch
from kaine.modules.audition.hearing_band import (
    HEARING_BAND_STAGES,
    HearingBandParams,
)
from kaine.modules.vision.feed import StimulusSourceClock


class _FakeBus:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def publish(self, event: Event) -> str:
        self.events.append(event)
        return "1-0"


def test_hearing_stage_watch_current_lifecycle_and_copy() -> None:
    W = 3600.0
    params = HearingBandParams(enabled=True, maturation_seconds=W)
    awake_value = 0.0
    bus = _FakeBus()

    def awake() -> float:
        return awake_value

    watch = HearingStageWatch(bus, awake, params)

    assert watch.current is None

    payload0 = watch.check()
    assert payload0 is not None
    assert watch.current == payload0
    assert watch.check() is None
    assert watch.current == payload0

    returned = watch.current
    returned["stage"] = 99
    assert watch.current == payload0

    awake_value = W / 4.0
    payload1 = watch.check()
    assert payload1 is not None
    assert watch.current == payload1
    assert watch.current["stage"] == 1
    assert watch.current == {
        "stage": 1,
        "previous_stage": 0,
        "low_hz": HEARING_BAND_STAGES[1][0],
        "high_hz": HEARING_BAND_STAGES[1][1],
        "awake_seconds": W / 4.0,
    }


@pytest.mark.asyncio
async def test_write_runtime_state_includes_hearing_stage(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime.json"
    monkeypatch.setattr("kaine.cycle.__main__.RUNTIME_PATH", runtime)

    cycle = MagicMock()
    cycle.tick_index = 0
    cycle.processing_rate_hz = 1.0
    cycle.experiential_rate_hz = 1.0
    cycle.is_paused = False
    cycle.time_scale = 1.0
    cycle.deterministic = False
    cycle.pacing_stats = {}

    registry = MagicMock()
    registry.all_modules.return_value = []

    hearing = {
        "stage": 1,
        "previous_stage": 0,
        "low_hz": 158.1,
        "high_hz": 707.1,
        "awake_seconds": 11000.0,
    }
    await _write_runtime_state(cycle, registry, hearing_stage=hearing)

    raw = json.loads(runtime.read_text())
    assert raw["hearing_stage"] == hearing


@pytest.mark.asyncio
async def test_write_runtime_state_omits_hearing_stage_without_watch(tmp_path, monkeypatch):
    runtime = tmp_path / "runtime.json"
    monkeypatch.setattr("kaine.cycle.__main__.RUNTIME_PATH", runtime)

    cycle = MagicMock()
    cycle.tick_index = 0
    cycle.processing_rate_hz = 1.0
    cycle.experiential_rate_hz = 1.0
    cycle.is_paused = False
    cycle.time_scale = 1.0
    cycle.deterministic = False
    cycle.pacing_stats = {}

    registry = MagicMock()
    registry.all_modules.return_value = []

    await _write_runtime_state(cycle, registry)

    raw = json.loads(runtime.read_text())
    assert "hearing_stage" not in raw


def _stimulus_source_config(clock: StimulusSourceClock, audition: bool) -> dict[str, Any]:
    return {
        "modules": {"audition": audition} if audition else {},
        "perception_feed": {
            "mode": "stimulus_source",
            "_shared_stimulus_source_clock": clock,
            "_stimulus_source_lived_seconds": lambda: 0.0,
            "stimulus_source": {"hearing": {"enabled": True}},
        },
    }


@pytest.mark.asyncio
async def test_start_stimulus_source_presence_calls_on_watch():
    seen: list[Any] = []
    bus = _FakeBus()
    clock = StimulusSourceClock(lived_offset_seconds=0.0)
    clock.mark_delivered("video", 7)
    clock.mark_delivered("audio", 3)
    stop = asyncio.Event()

    task = _start_stimulus_source_presence(
        _stimulus_source_config(clock, audition=True),
        bus,
        stop,
        on_watch=seen.append,
    )
    assert task is not None
    assert len(seen) == 1
    assert isinstance(seen[0], HearingStageWatch)

    stop.set()
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_start_stimulus_source_presence_skips_on_watch_without_audition():
    seen: list[Any] = []
    bus = _FakeBus()
    clock = StimulusSourceClock(lived_offset_seconds=0.0)
    clock.mark_delivered("video", 7)
    clock.mark_delivered("audio", 3)
    stop = asyncio.Event()

    task = _start_stimulus_source_presence(
        _stimulus_source_config(clock, audition=False),
        bus,
        stop,
        on_watch=seen.append,
    )
    assert task is not None
    assert seen == []

    stop.set()
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_start_stimulus_source_presence_omitting_on_watch_still_starts():
    bus = _FakeBus()
    clock = StimulusSourceClock(lived_offset_seconds=0.0)
    clock.mark_delivered("video", 7)
    clock.mark_delivered("audio", 3)
    stop = asyncio.Event()

    task = _start_stimulus_source_presence(
        _stimulus_source_config(clock, audition=True),
        bus,
        stop,
    )
    assert task is not None
    await asyncio.sleep(0.05)

    stop.set()
    await asyncio.wait_for(task, timeout=2.0)


@pytest.mark.asyncio
async def test_phase_development_sets_hearing_stage_watch():
    bus = _FakeBus()
    clock = StimulusSourceClock(lived_offset_seconds=0.0)
    clock.mark_delivered("video", 1)
    clock.mark_delivered("audio", 1)

    ctx = types.SimpleNamespace(
        kaine_config=_stimulus_source_config(clock, audition=True),
        bus=bus,
        stop_event=asyncio.Event(),
        staging_enabled=False,
        stage_state=None,
        hearing_stage_watch=None,
        stimulus_source_presence_task=None,
        development_task=None,
        registry=None,
        cycle=None,
    )

    await _phase_development(ctx)
    assert isinstance(ctx.hearing_stage_watch, HearingStageWatch)
    assert ctx.stimulus_source_presence_task is not None

    ctx.stop_event.set()
    await asyncio.wait_for(ctx.stimulus_source_presence_task, timeout=2.0)
