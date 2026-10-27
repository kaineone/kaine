# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The stimulus source clock resumes from its own persisted time across restarts."""

import asyncio
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kaine.boot.perception_feed import (
    _install_shared_stimulus_source_clock,
    _shared_stimulus_source_objects,
    _stimulus_source_resume_seconds,
    gather_perception_feed_descriptor,
)
from kaine.cycle.__main__ import _phase_maturation
from kaine.lifecycle import stage as lifecycle_stage
from kaine.lifecycle.gate_runner import MaturationGateRunner
from kaine.lifecycle.maturation_gate import MaturationConfig
from kaine.lifecycle.stage import StageState, read_stage, write_stage
from kaine.modules.vision.feed import StimulusSourceClock
from tests.test_maturation_gate_runner import _make_bus, _make_registry


class _SettableClock:
    def __init__(self, value: float = 0.0) -> None:
        self._value = float(value)

    def now(self) -> float:
        return self._value

    def advance(self, delta: float) -> None:
        self._value += float(delta)

    def set(self, value: float) -> None:
        self._value = float(value)


@pytest.fixture(autouse=True)
def _patch_stage_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr("kaine.lifecycle.stage.STAGE_PATH", tmp_path / "stage.json")


def _assert_clock_near(clock: StimulusSourceClock, expected: float) -> None:
    value = clock.stimulus_source_seconds()
    assert expected <= value < expected + 1.0, f"expected {expected} <= {value} < {expected + 1.0}"


def test_install_resumes_from_stage_state_stimulus_time() -> None:
    feed: dict = {}
    _install_shared_stimulus_source_clock(
        feed,
        {},
        None,
        stage_state=StageState(lived_seconds=3522.5, stimulus_source_seconds=3598.7),
    )
    _assert_clock_near(feed["_shared_stimulus_source_clock"], 3598.7)
    assert feed["_stimulus_source_lived_seconds"]() == pytest.approx(3522.5)


def test_install_resumes_from_stage_file_stimulus_time(tmp_path: Path) -> None:
    stage_path = tmp_path / "stage.json"
    write_stage(StageState(lived_seconds=100.0, stimulus_source_seconds=150.0), stage_path)
    feed: dict = {}
    _install_shared_stimulus_source_clock(feed, {}, None, stage_path=stage_path)
    _assert_clock_near(feed["_shared_stimulus_source_clock"], 150.0)
    assert feed["_stimulus_source_lived_seconds"]() == pytest.approx(100.0)


def test_install_falls_back_to_awake_time_without_stimulus_field() -> None:
    # StageState with no stimulus_source_seconds field.
    feed1: dict = {}
    _install_shared_stimulus_source_clock(
        feed1,
        {},
        None,
        stage_state=StageState(lived_seconds=500.0),
    )
    _assert_clock_near(feed1["_shared_stimulus_source_clock"], 500.0)
    assert feed1["_stimulus_source_lived_seconds"]() == pytest.approx(500.0)

    # Same check via the stage file.
    stage_path = lifecycle_stage.STAGE_PATH
    write_stage(StageState(lived_seconds=500.0), stage_path)
    feed2: dict = {}
    _install_shared_stimulus_source_clock(feed2, {}, None, stage_path=stage_path)
    _assert_clock_near(feed2["_shared_stimulus_source_clock"], 500.0)


@pytest.mark.parametrize(
    "raw",
    [None, True, "abc", -1.0, float("nan"), float("inf")],
)
def test_resume_seconds_rejects_invalid_values(raw: object) -> None:
    lived_offset = 12.5
    state = types.SimpleNamespace(stimulus_source_seconds=raw)
    assert _stimulus_source_resume_seconds(state, lived_offset) == pytest.approx(lived_offset)


def test_resume_seconds_accepts_valid_values() -> None:
    lived_offset = 12.5
    assert _stimulus_source_resume_seconds(None, lived_offset) == pytest.approx(lived_offset)
    assert _stimulus_source_resume_seconds(
        types.SimpleNamespace(stimulus_source_seconds=0.0), 12.5
    ) == pytest.approx(0.0)
    assert _stimulus_source_resume_seconds(
        types.SimpleNamespace(stimulus_source_seconds=42.0), 12.5
    ) == pytest.approx(42.0)


def test_lived_provider_follows_awake_time_not_stimulus_time() -> None:
    ent = _SettableClock(0.0)
    feed: dict = {}
    _install_shared_stimulus_source_clock(
        feed,
        {},
        ent,
        stage_state=StageState(lived_seconds=500.0, stimulus_source_seconds=900.0),
    )
    assert feed["_stimulus_source_lived_seconds"]() == pytest.approx(500.0)
    ent.advance(10.0)
    assert feed["_stimulus_source_lived_seconds"]() == pytest.approx(510.0)


def test_shared_objects_resumes_from_patched_stage_path(tmp_path: Path) -> None:
    write_stage(
        StageState(lived_seconds=100.0, stimulus_source_seconds=150.0),
        tmp_path / "stage.json",
    )
    clock, lived = _shared_stimulus_source_objects({})
    _assert_clock_near(clock, 150.0)
    assert lived() == pytest.approx(100.0)


def test_gather_descriptor_records_both_offsets(tmp_path: Path) -> None:
    write_stage(
        StageState(lived_seconds=100.0, stimulus_source_seconds=150.0),
        tmp_path / "stage.json",
    )
    descriptor = gather_perception_feed_descriptor(
        {"perception_feed": {"mode": "stimulus_source", "seed": 3}}
    )
    assert descriptor["lived_offset_seconds"] == pytest.approx(100.0)
    assert descriptor["stimulus_source_offset_seconds"] == pytest.approx(150.0)

    # Without a stage file both offsets are 0.
    (tmp_path / "stage.json").unlink()
    fallback_descriptor = gather_perception_feed_descriptor(
        {"perception_feed": {"mode": "stimulus_source", "seed": 3}}
    )
    assert fallback_descriptor["lived_offset_seconds"] == pytest.approx(0.0)
    assert fallback_descriptor["stimulus_source_offset_seconds"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_restart_round_trip_does_not_advance_downtime() -> None:
    mono = [1000.0]
    clock1 = StimulusSourceClock(lived_offset_seconds=0.0, clock=lambda: mono[0])
    ent = _SettableClock(0.0)

    runner = MaturationGateRunner(
        bus=_make_bus(),
        config=MaturationConfig(
            enabled=True,
            gate_cadence_seconds=3600,
        ),
        registry=_make_registry(),
        entity_clock=ent,
        stage_state=lifecycle_stage.resolve_boot_stage(has_prior_lived_history=False),
        staging_enabled=True,
        stimulus_source_feed_configured=True,
    )
    runner.set_stimulus_source_clock(clock1.stimulus_source_seconds)

    await runner._evaluate_once()
    mono[0] = 4598.7
    ent.set(3522.5)
    await runner.shutdown()

    state = read_stage()
    assert state is not None
    assert state.stimulus_source_seconds == pytest.approx(3598.7, abs=0.1)

    # 12 hours of downtime pass on the wall clock but the process is not running.
    mono[0] += 43200.0

    feed2: dict = {}
    _install_shared_stimulus_source_clock(feed2, None, None)
    clock2 = feed2["_shared_stimulus_source_clock"]
    _assert_clock_near(clock2, 3598.7)
    # It must not resume from lived time (3522.5) nor include the downtime.
    assert clock2.stimulus_source_seconds() < 3600.0
    assert feed2["_stimulus_source_lived_seconds"]() == pytest.approx(3522.5)


@pytest.mark.asyncio
async def test_phase_maturation_hands_clock_to_gate_runner() -> None:
    clock = StimulusSourceClock(lived_offset_seconds=0.0)
    ctx = types.SimpleNamespace(
        gate_runner=MagicMock(),
        cycle=MagicMock(),
        individuation_cfg=None,
        kaine_config={"perception_feed": {"mode": "stimulus_source", "_shared_stimulus_source_clock": clock}},
        staging_enabled=False,
        stage_state=StageState(),
        stop_event=asyncio.Event(),
    )
    await _phase_maturation(ctx)
    ctx.gate_runner.set_stimulus_source_clock.assert_called_once_with(
        clock.stimulus_source_seconds
    )


@pytest.mark.asyncio
async def test_phase_maturation_skips_clock_when_none() -> None:
    ctx = types.SimpleNamespace(
        gate_runner=MagicMock(),
        cycle=MagicMock(),
        individuation_cfg=None,
        kaine_config={"perception_feed": {"mode": "off"}},
        staging_enabled=False,
        stage_state=StageState(),
        stop_event=asyncio.Event(),
    )
    await _phase_maturation(ctx)
    ctx.gate_runner.set_stimulus_source_clock.assert_not_called()
