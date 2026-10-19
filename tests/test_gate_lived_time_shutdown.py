# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for partial lived-time accrual and stimulus source time persistence at shutdown."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from kaine.lifecycle import stage as lifecycle_stage
from kaine.lifecycle.gate_runner import MaturationGateRunner
from kaine.lifecycle.maturation_gate import MaturationConfig
from tests.test_maturation_gate_runner import _make_bus, _make_registry


class _Clock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = t

    def now(self) -> float:
        return self.t


def _runner(
    clock: _Clock,
    state: lifecycle_stage.StageState | None = None,
    *,
    staging_enabled: bool = True,
    stimulus_source_feed_configured: bool = True,
) -> MaturationGateRunner:
    if state is None:
        state = lifecycle_stage.resolve_boot_stage(has_prior_lived_history=False)
    return MaturationGateRunner(
        bus=_make_bus(),
        config=MaturationConfig(
            enabled=True,
            min_lived_seconds=86400,
            gate_cadence_seconds=3600,
        ),
        registry=_make_registry(),
        entity_clock=clock,
        stage_state=state,
        staging_enabled=staging_enabled,
        stimulus_source_feed_configured=stimulus_source_feed_configured,
    )


@pytest.fixture(autouse=True)
def _patch_stage_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("kaine.lifecycle.stage.STAGE_PATH", tmp_path / "stage.json")


@pytest.mark.asyncio
async def test_clean_shutdown_keeps_partial_interval() -> None:
    clock = _Clock()
    runner = _runner(clock)
    await runner._evaluate_once()  # anchors at t=0
    clock.t = 60.0
    await runner._evaluate_once()
    clock.t = 105.0
    stop = asyncio.Event()
    stop.set()
    await runner.run(stop)
    assert lifecycle_stage.read_stage().lived_seconds == pytest.approx(105.0)


@pytest.mark.asyncio
async def test_restart_after_clean_shutdown_no_loss_no_double_count() -> None:
    clock = _Clock()
    runner = _runner(clock)
    await runner._evaluate_once()
    clock.t = 60.0
    await runner._evaluate_once()
    clock.t = 105.0
    stop = asyncio.Event()
    stop.set()
    await runner.run(stop)

    second_clock = _Clock()
    second_runner = _runner(second_clock, state=lifecycle_stage.read_stage())
    await second_runner._evaluate_once()
    second_clock.t = 60.0
    await second_runner._evaluate_once()
    assert lifecycle_stage.read_stage().lived_seconds == pytest.approx(165.0)


@pytest.mark.asyncio
async def test_crash_loses_partial_interval_no_double_count() -> None:
    clock = _Clock()
    runner = _runner(clock)
    await runner._evaluate_once()
    clock.t = 60.0
    await runner._evaluate_once()
    clock.t = 105.0
    # No shutdown: drop the runner.
    del runner

    second_clock = _Clock()
    second_runner = _runner(second_clock, state=lifecycle_stage.read_stage())
    await second_runner._evaluate_once()
    second_clock.t = 30.0
    await second_runner._evaluate_once()
    assert lifecycle_stage.read_stage().lived_seconds == pytest.approx(90.0)


@pytest.mark.asyncio
async def test_cancelled_run_task_records() -> None:
    clock = _Clock()
    runner = _runner(clock)
    stop = asyncio.Event()
    task = asyncio.create_task(runner.run(stop))
    await asyncio.sleep(0.05)
    clock.t = 30.0
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert lifecycle_stage.read_stage().lived_seconds == pytest.approx(30.0)


@pytest.mark.asyncio
async def test_shutdown_records_partial_interval() -> None:
    clock = _Clock()
    runner = _runner(clock)
    await runner._evaluate_once()
    clock.t = 60.0
    await runner._evaluate_once()
    clock.t = 90.0
    await runner.shutdown()
    assert lifecycle_stage.read_stage().lived_seconds == pytest.approx(90.0)


@pytest.mark.asyncio
async def test_shutdown_subtracts_paused_time() -> None:
    paused = [0.0]
    clock = _Clock()
    runner = _runner(clock)
    runner.set_pause_sources(
        paused_seconds=lambda: paused[0],
        is_paused=lambda: False,
    )
    await runner._evaluate_once()
    clock.t = 60.0
    await runner._evaluate_once()
    clock.t = 100.0
    paused[0] = 25.0
    stop = asyncio.Event()
    stop.set()
    await runner.run(stop)
    assert lifecycle_stage.read_stage().lived_seconds == pytest.approx(75.0)


@pytest.mark.asyncio
async def test_no_write_after_maturation(tmp_path: Path) -> None:
    state = lifecycle_stage.StageState(
        stage=lifecycle_stage.EMBODIED,
        lived_seconds=10.0,
    )
    lifecycle_stage.write_stage(state)
    before = (tmp_path / "stage.json").read_bytes()
    clock = _Clock()
    runner = _runner(clock, state=state)
    stop = asyncio.Event()
    stop.set()
    await runner.run(stop)
    await runner.shutdown()
    assert (tmp_path / "stage.json").read_bytes() == before


@pytest.mark.asyncio
async def test_no_write_with_staging_disabled() -> None:
    clock = _Clock()
    runner = _runner(clock, staging_enabled=False)
    await runner._evaluate_once()
    await runner.shutdown()
    assert not lifecycle_stage.STAGE_PATH.exists()


@pytest.mark.asyncio
async def test_no_write_before_boot_anchored() -> None:
    bus = _make_bus()
    bus.server_time_ms = AsyncMock(side_effect=RuntimeError("down"))
    clock = _Clock()
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(
            enabled=True,
            min_lived_seconds=86400,
            gate_cadence_seconds=3600,
        ),
        registry=_make_registry(),
        entity_clock=clock,
        stage_state=lifecycle_stage.resolve_boot_stage(has_prior_lived_history=False),
        staging_enabled=True,
        stimulus_source_feed_configured=True,
    )
    await runner._evaluate_once()
    await runner.shutdown()
    assert not lifecycle_stage.STAGE_PATH.exists()


@pytest.mark.asyncio
async def test_stimulus_source_seconds_recorded_each_tick_and_shutdown() -> None:
    clock = _Clock()
    runner = _runner(clock)
    reading = [100.0]
    runner.set_stimulus_source_clock(lambda: reading[0])
    await runner._evaluate_once()
    assert lifecycle_stage.read_stage().stimulus_source_seconds == pytest.approx(100.0)
    reading[0] = 175.5
    stop = asyncio.Event()
    stop.set()
    await runner.run(stop)
    assert lifecycle_stage.read_stage().stimulus_source_seconds == pytest.approx(175.5)


@pytest.mark.asyncio
async def test_invalid_or_failing_reader_keeps_last_good_value() -> None:
    clock = _Clock()
    runner = _runner(clock)
    reading = [100.0]
    runner.set_stimulus_source_clock(lambda: reading[0])
    await runner._evaluate_once()

    for bad in [RuntimeError("boom"), float("nan"), float("inf"), -1.0]:
        if isinstance(bad, RuntimeError):
            runner.set_stimulus_source_clock(lambda: (_ for _ in ()).throw(bad))
        else:
            runner.set_stimulus_source_clock(lambda bad=bad: bad)
        await runner._evaluate_once()
        assert runner.stage.stimulus_source_seconds == pytest.approx(100.0)

    runner.set_stimulus_source_clock(None)
    await runner._evaluate_once()
    assert runner.stage.stimulus_source_seconds == pytest.approx(100.0)


def test_stimulus_source_seconds_stage_round_trip() -> None:
    state = lifecycle_stage.StageState(stimulus_source_seconds=12.5)
    data = state.to_dict()
    restored = lifecycle_stage.StageState.from_dict(data)
    assert restored.stimulus_source_seconds == pytest.approx(12.5)

    missing = lifecycle_stage.StageState.from_dict({})
    assert missing.stimulus_source_seconds is None

    for bad in [True, "abc", -1, float("nan"), float("inf")]:
        coerced = lifecycle_stage.StageState.from_dict({"stimulus_source_seconds": bad})
        assert coerced.stimulus_source_seconds is None

    lifecycle_stage.write_stage(state)
    read = lifecycle_stage.read_stage()
    assert read.stimulus_source_seconds == pytest.approx(12.5)


@pytest.mark.asyncio
async def test_no_reader_leaves_stimulus_source_seconds_unrecorded() -> None:
    clock = _Clock()
    runner = _runner(clock)
    await runner._evaluate_once()
    await runner.shutdown()
    assert lifecycle_stage.read_stage().stimulus_source_seconds is None
