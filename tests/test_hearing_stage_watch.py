# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the hearing stage watch publisher."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from kaine.bus.schema import Event
from kaine.bus.streams import DEVELOPMENT_SOURCE
from kaine.cycle.__main__ import _start_stimulus_source_presence
from kaine.cycle.hearing_stage_watch import HEARING_STAGE_TYPE, HearingStageWatch
from kaine.modules.audition.hearing_band import HEARING_BAND_STAGES, HearingBandParams
from kaine.modules.audition.hearing_stage_state import HearingStageState
from kaine.modules.vision.feed import StimulusSourceClock


class _FakeBus:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def publish(self, event: Event) -> str:
        self.events.append(event)
        return "1-0"


PARAMS = HearingBandParams(
    enabled=True,
    saturation_window_seconds=100.0,
    min_dwell_seconds=200.0,
    max_dwell_seconds=1000.0,
)
LOW = 0.05


class _Clock:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


def _state() -> HearingStageState:
    return HearingStageState(PARAMS)


def test_check_reports_initial_stage_and_transitions() -> None:
    clock = _Clock()
    state = _state()
    watch = HearingStageWatch(_FakeBus(), clock, state, lambda stage: LOW)

    payload0 = watch.check()
    assert payload0 == {
        "stage": 0,
        "previous_stage": None,
        "low_hz": HEARING_BAND_STAGES[0][0],
        "high_hz": HEARING_BAND_STAGES[0][1],
        "awake_seconds": 0.0,
        "dwell_seconds": 0.0,
    }
    assert watch.check() is None

    clock.value = 300.0
    payload1 = watch.check()
    assert payload1 == {
        "stage": 1,
        "previous_stage": 0,
        "low_hz": HEARING_BAND_STAGES[1][0],
        "high_hz": HEARING_BAND_STAGES[1][1],
        "awake_seconds": 300.0,
        "dwell_seconds": 0.0,
    }
    assert watch.current == payload1


def test_check_passes_current_stage_to_provider() -> None:
    clock = _Clock()
    seen: list[int] = []

    def provider(stage: int) -> float | None:
        seen.append(stage)
        return LOW

    watch = HearingStageWatch(_FakeBus(), clock, _state(), provider)
    watch.check()
    clock.value = 300.0
    watch.check()
    clock.value = 301.0
    watch.check()
    assert seen == [0, 0, 1]


def test_check_without_provider_never_saturates_until_dmax() -> None:
    clock = _Clock()
    watch = HearingStageWatch(_FakeBus(), clock, _state())
    watch.check()
    clock.value = 999.0
    assert watch.check() is None
    clock.value = 1000.0
    payload = watch.check()
    assert payload is not None and payload["stage"] == 1


def test_provider_exception_counts_as_missing(caplog: pytest.LogCaptureFixture) -> None:
    clock = _Clock()

    def provider(stage: int) -> float | None:
        raise RuntimeError("affect gone")

    state = _state()
    watch = HearingStageWatch(_FakeBus(), clock, state, provider)
    watch.check()
    clock.value = 500.0
    with caplog.at_level("DEBUG"):
        assert watch.check() is None
    assert state.saturated_seconds == 0.0
    assert state.dwell_seconds == 500.0
    assert "lp provider failed" in caplog.text


def test_check_logs_stage_transition(caplog: pytest.LogCaptureFixture) -> None:
    watch = HearingStageWatch(_FakeBus(), _Clock(), _state())
    with caplog.at_level("INFO"):
        watch.check()
    assert "stimulus source: hearing stage 0 of 4 (353.6 to 707.1 Hz) at 0 s awake" in caplog.text


def test_watch_resumes_a_persisted_stage(tmp_path) -> None:
    path = tmp_path / "hearing_stage.json"
    path.write_text('{"version": 1, "stage": 2, "dwell_seconds": 50.0}')
    state = HearingStageState.load(PARAMS, path=path)
    watch = HearingStageWatch(_FakeBus(), _Clock(10.0), state)
    payload = watch.check()
    assert payload["stage"] == 2
    assert payload["previous_stage"] is None
    assert payload["dwell_seconds"] == 50.0


@pytest.mark.asyncio
async def test_run_publishes_events_and_returns_after_stage_4(tmp_path) -> None:
    bus = _FakeBus()
    path = tmp_path / "hearing_stage.json"
    state = HearingStageState(PARAMS, path=path)
    values = iter([0.0] + [1000.0 * k for k in range(1, 5)])
    watch = HearingStageWatch(bus, lambda: next(values), state, period_s=0.01)
    await asyncio.wait_for(watch.run(asyncio.Event()), timeout=2.0)

    assert {event.type for event in bus.events} == {HEARING_STAGE_TYPE}
    assert {event.source for event in bus.events} == {DEVELOPMENT_SOURCE}
    assert [event.payload["stage"] for event in bus.events] == [0, 1, 2, 3, 4]
    assert json.loads(path.read_text())["stage"] == 4


@pytest.mark.asyncio
async def test_run_saves_state_on_stop(tmp_path) -> None:
    path = tmp_path / "hearing_stage.json"
    state = HearingStageState(PARAMS, path=path)
    clock = _Clock()
    watch = HearingStageWatch(_FakeBus(), clock, state, period_s=0.01)
    stop = asyncio.Event()
    task = asyncio.create_task(watch.run(stop))
    await asyncio.sleep(0.05)
    clock.value = 10.0
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)
    assert json.loads(path.read_text())["dwell_seconds"] == 10.0


@pytest.mark.asyncio
async def test_run_survives_awake_exception_and_publishes_later(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bus = _FakeBus()
    values: list[Any] = [0.0, RuntimeError("awake failed once")] + [
        1000.0 * k for k in range(1, 5)
    ]
    iterator = iter(values)

    def awake() -> float:
        val = next(iterator)
        if isinstance(val, Exception):
            raise val
        return val

    watch = HearingStageWatch(bus, awake, _state(), period_s=0.01)
    with caplog.at_level("WARNING"):
        await asyncio.wait_for(watch.run(asyncio.Event()), timeout=2.0)

    assert "hearing stage check failed" in caplog.text
    assert [event.payload["stage"] for event in bus.events] == [0, 1, 2, 3, 4]


def _feed(state: Any = None, lived: Any = lambda: 0.0) -> dict[str, Any]:
    feed: dict[str, Any] = {"_stimulus_source_lived_seconds": lived}
    if state is not None:
        feed["_hearing_stage_state"] = state
    return feed


def test_from_config_returns_none_without_state() -> None:
    config = {"modules": {"audition": True}, "perception_feed": _feed()}
    assert HearingStageWatch.from_config(config, _FakeBus()) is None


def test_from_config_returns_none_without_lived_seconds() -> None:
    config = {"perception_feed": {"_hearing_stage_state": _state()}}
    assert HearingStageWatch.from_config(config, _FakeBus()) is None


def test_from_config_returns_none_for_wrong_state_type() -> None:
    config = {"perception_feed": _feed(state=object())}
    assert HearingStageWatch.from_config(config, _FakeBus()) is None


def test_from_config_does_not_need_audition_or_hearing_enabled() -> None:
    config = {
        "modules": {"audition": False},
        "perception_feed": {
            **_feed(state=_state()),
            "stimulus_source": {"hearing": {"enabled": False}},
        },
    }
    assert HearingStageWatch.from_config(config, _FakeBus()) is not None


def test_from_config_passes_lp_provider() -> None:
    clock = _Clock()
    seen: list[int] = []

    def provider(stage: int) -> float | None:
        seen.append(stage)
        return LOW

    config = {"perception_feed": _feed(state=_state(), lived=clock)}
    watch = HearingStageWatch.from_config(config, _FakeBus(), provider)
    assert watch is not None
    watch.check()
    assert seen == [0]


def _source_config(clock: StimulusSourceClock, state: Any) -> dict[str, Any]:
    return {
        "perception_feed": {
            "mode": "stimulus_source",
            "_shared_stimulus_source_clock": clock,
            "_stimulus_source_lived_seconds": lambda: 0.0,
            **({"_hearing_stage_state": state} if state is not None else {}),
        },
    }


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
        _source_config(clock, _state()), _Bus(), stop, lp_provider=lambda stage: LOW
    )
    assert task is not None
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    types = {event.type for event in published}
    assert "development.stimulus_source" in types
    assert "development.hearing_stage" in types
    hearing_events = [e for e in published if e.type == "development.hearing_stage"]
    assert hearing_events[0].payload["stage"] == 0


@pytest.mark.asyncio
async def test_start_stimulus_source_presence_without_state_publishes_no_hearing_stage() -> None:
    published: list[Event] = []

    class _Bus:
        async def publish(self, event: Event) -> str:
            published.append(event)
            return "1-0"

    clock = StimulusSourceClock(lived_offset_seconds=0.0)
    clock.mark_delivered("video", 7)
    clock.mark_delivered("audio", 3)
    stop = asyncio.Event()
    task = _start_stimulus_source_presence(_source_config(clock, None), _Bus(), stop)
    assert task is not None
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)

    types = {event.type for event in published}
    assert "development.stimulus_source" in types
    assert "development.hearing_stage" not in types


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


@pytest.mark.asyncio
async def test_run_retries_a_failed_publish(caplog: pytest.LogCaptureFixture) -> None:
    bus = _RetryBus()
    values = iter([0.0, 0.0] + [1000.0 * k for k in range(1, 5)])
    watch = HearingStageWatch(bus, lambda: next(values), _state(), period_s=0.01)
    with caplog.at_level("WARNING"):
        await asyncio.wait_for(watch.run(asyncio.Event()), timeout=2.0)

    assert "hearing stage publish failed" in caplog.text
    assert [event.payload["stage"] for event in bus.events] == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_run_keeps_a_failed_stage_when_the_next_one_arrives() -> None:
    bus = _RetryBus()
    calls = 0

    def awake() -> float:
        nonlocal calls
        calls += 1
        return 0.0 if calls == 1 else 1000.0 * (calls - 1)

    watch = HearingStageWatch(bus, awake, _state(), period_s=0.01)
    await asyncio.wait_for(watch.run(asyncio.Event()), timeout=2.0)

    stages = [event.payload["stage"] for event in bus.events]
    assert stages[:2] == [0, 1]
    assert stages[-1] == 4
    assert bus.events[1].payload["previous_stage"] == 0
