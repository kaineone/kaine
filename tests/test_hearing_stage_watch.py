# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the hearing stage watch publisher."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from kaine.bus.schema import Event
from kaine.bus.streams import DEVELOPMENT_SOURCE
from kaine.cycle.__main__ import _start_stimulus_source_presence
from kaine.cycle.hearing_stage_watch import HEARING_STAGE_TYPE, HearingStageWatch
from kaine.modules.audition.hearing_band import (
    HEARING_BAND_STAGES,
    HearingBandParams,
    hearing_stage,
)
from kaine.modules.vision.feed import StimulusSourceClock


class _FakeBus:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def publish(self, event: Event) -> str:
        self.events.append(event)
        return "1-0"


def test_check_reports_initial_stage_and_transitions() -> None:
    W = 3600.0
    params = HearingBandParams(enabled=True, maturation_seconds=W)
    awake_value = 0.0
    bus = _FakeBus()

    def awake() -> float:
        return awake_value

    watch = HearingStageWatch(bus, awake, params)

    payload0 = watch.check()
    assert payload0 == {
        "stage": 0,
        "previous_stage": None,
        "low_hz": HEARING_BAND_STAGES[0][0],
        "high_hz": HEARING_BAND_STAGES[0][1],
        "awake_seconds": 0.0,
    }
    assert watch.check() is None

    awake_value = W / 4.0
    payload1 = watch.check()
    assert payload1 == {
        "stage": 1,
        "previous_stage": 0,
        "low_hz": HEARING_BAND_STAGES[1][0],
        "high_hz": HEARING_BAND_STAGES[1][1],
        "awake_seconds": W / 4.0,
    }

    awake_value = W
    payload4 = watch.check()
    assert payload4 == {
        "stage": 4,
        "previous_stage": 1,
        "low_hz": None,
        "high_hz": None,
        "awake_seconds": W,
    }


def test_check_stage_matches_hearing_stage_for_sweep() -> None:
    W = 3600.0
    params = HearingBandParams(enabled=True, maturation_seconds=W)
    bus = _FakeBus()
    awake_value = 0.0

    def awake() -> float:
        return awake_value

    watch = HearingStageWatch(bus, awake, params)

    for step in range(0, 13):
        t = step * W / 10.0
        awake_value = t
        payload = watch.check()
        if payload is not None:
            assert payload["stage"] == hearing_stage(t, params)


def test_check_logs_stage_transition(caplog: pytest.LogCaptureFixture) -> None:
    W = 3600.0
    params = HearingBandParams(enabled=True, maturation_seconds=W)
    bus = _FakeBus()
    watch = HearingStageWatch(bus, lambda: 0.0, params)

    with caplog.at_level("INFO"):
        watch.check()

    assert "stimulus source: hearing stage 0 of 4 (353.6 to 707.1 Hz) at 0 s awake" in caplog.text


@pytest.mark.asyncio
async def test_run_publishes_events_and_returns_after_stage_4() -> None:
    W = 3600.0
    params = HearingBandParams(enabled=True, maturation_seconds=W)
    bus = _FakeBus()
    values = iter([0.0, W / 4.0, W / 2.0, 3.0 * W / 4.0, W])

    def awake() -> float:
        return next(values)

    watch = HearingStageWatch(bus, awake, params, period_s=0.01)
    task = asyncio.create_task(watch.run(asyncio.Event()))
    await asyncio.wait_for(task, timeout=2.0)

    assert bus.events
    assert {event.type for event in bus.events} == {HEARING_STAGE_TYPE}
    assert {event.source for event in bus.events} == {DEVELOPMENT_SOURCE}
    stages = [event.payload["stage"] for event in bus.events]
    assert stages == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_run_survives_awake_exception_and_publishes_later(
    caplog: pytest.LogCaptureFixture,
) -> None:
    W = 3600.0
    params = HearingBandParams(enabled=True, maturation_seconds=W)
    bus = _FakeBus()
    values: list[Any] = [
        0.0,
        RuntimeError("awake failed once"),
        W / 4.0,
        W / 2.0,
        3.0 * W / 4.0,
        W,
    ]
    iterator = iter(values)

    def awake() -> float:
        val = next(iterator)
        if isinstance(val, Exception):
            raise val
        return val

    watch = HearingStageWatch(bus, awake, params, period_s=0.01)
    with caplog.at_level("WARNING"):
        task = asyncio.create_task(watch.run(asyncio.Event()))
        await asyncio.wait_for(task, timeout=2.0)

    assert "hearing stage check failed" in caplog.text
    stages = [event.payload["stage"] for event in bus.events]
    assert stages == [0, 1, 2, 3, 4]


def test_from_config_returns_none_when_audition_off() -> None:
    config = {
        "modules": {"audition": False},
        "perception_feed": {"_stimulus_source_lived_seconds": lambda: 0.0},
    }
    assert HearingStageWatch.from_config(config, _FakeBus()) is None


def test_from_config_returns_none_when_hearing_disabled() -> None:
    config = {
        "modules": {"audition": True},
        "perception_feed": {
            "_stimulus_source_lived_seconds": lambda: 0.0,
            "stimulus_source": {"hearing": {"enabled": False}},
        },
    }
    assert HearingStageWatch.from_config(config, _FakeBus()) is None


def test_from_config_returns_none_without_lived_seconds() -> None:
    config = {"modules": {"audition": True}, "perception_feed": {}}
    assert HearingStageWatch.from_config(config, _FakeBus()) is None


def test_from_config_returns_watch_otherwise() -> None:
    config = {
        "modules": {"audition": True},
        "perception_feed": {
            "_stimulus_source_lived_seconds": lambda: 0.0,
            "stimulus_source": {"hearing": {"enabled": True}},
        },
    }
    watch = HearingStageWatch.from_config(config, _FakeBus())
    assert watch is not None


@pytest.mark.asyncio
async def test_start_stimulus_source_presence_with_watch_publishes_both() -> None:
    published: list[Event] = []

    class _Bus:
        async def publish(self, event: Event) -> str:
            published.append(event)
            return "1-0"

    clock = StimulusSourceClock(lived_offset_seconds=0.0)
    clock.mark_delivered("video", 7)
    clock.mark_delivered("audio", 3)
    stop = asyncio.Event()
    task = _start_stimulus_source_presence(
        {
            "modules": {"audition": True},
            "perception_feed": {
                "mode": "stimulus_source",
                "_shared_stimulus_source_clock": clock,
                "_stimulus_source_lived_seconds": lambda: 0.0,
                "stimulus_source": {"hearing": {"enabled": True}},
            },
        },
        _Bus(),
        stop,
    )
    assert task is not None
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    types = {event.type for event in published}
    assert "development.stimulus_source" in types
    assert "development.hearing_stage" in types
    hearing_events = [
        event for event in published if event.type == "development.hearing_stage"
    ]
    assert hearing_events[0].payload["stage"] == 0


@pytest.mark.asyncio
async def test_start_stimulus_source_presence_without_audition_publishes_no_hearing_stage() -> None:
    published: list[Event] = []

    class _Bus:
        async def publish(self, event: Event) -> str:
            published.append(event)
            return "1-0"

    clock = StimulusSourceClock(lived_offset_seconds=0.0)
    clock.mark_delivered("video", 7)
    clock.mark_delivered("audio", 3)
    stop = asyncio.Event()
    task = _start_stimulus_source_presence(
        {
            "modules": {"audition": False},
            "perception_feed": {
                "mode": "stimulus_source",
                "_shared_stimulus_source_clock": clock,
                "_stimulus_source_lived_seconds": lambda: 0.0,
                "stimulus_source": {"hearing": {"enabled": True}},
            },
        },
        _Bus(),
        stop,
    )
    assert task is not None
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    types = {event.type for event in published}
    assert "development.stimulus_source" in types
    assert "development.hearing_stage" not in types


@pytest.mark.asyncio
async def test_run_retries_a_failed_publish(
    caplog: pytest.LogCaptureFixture,
) -> None:
    W = 3600.0
    params = HearingBandParams(enabled=True, maturation_seconds=W)

    class _RetryBus:
        def __init__(self) -> None:
            self.events: list[Event] = []
            self._calls = 0

        async def publish(self, event: Event) -> str:
            self._calls += 1
            if self._calls == 1:
                raise RuntimeError("bus down")
            self.events.append(event)
            return "1-0"

    bus = _RetryBus()
    values = iter([0.0, 0.0, W])

    def awake() -> float:
        return next(values)

    watch = HearingStageWatch(bus, awake, params, period_s=0.01)
    stop = asyncio.Event()
    with caplog.at_level("WARNING"):
        await asyncio.wait_for(watch.run(stop), timeout=2.0)

    assert "hearing stage publish failed" in caplog.text
    stages = [event.payload["stage"] for event in bus.events]
    assert stages == [0, 4]
