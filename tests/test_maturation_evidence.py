# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for idempotent maturation evidence and trustworthy readiness readouts.

Uses a real fakeredis-backed AsyncBus, the real EntityClock with an injectable
monotonic clock, and the real stage file path so the gate runner's persistence
and cursor behaviour are exercised end-to-end.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from kaine.bus.client import _encode_event
from kaine.bus.schema import Event
from kaine.cycle.__main__ import _resolve_boot_stage
from kaine.entity_clock import EntityClock
from kaine.lifecycle.gate_runner import MaturationGateRunner
from kaine.lifecycle.maturation_gate import MaturationConfig
from kaine.lifecycle.stage import GESTATION, StageState, read_stage


class _FakeRegistry:
    """Registry that contains no modules; all signal reads must come from the bus/file."""

    def __contains__(self, name: object) -> bool:
        return False

    def get(self, name: str) -> Any:
        raise KeyError(name)


def _make_clock(time_list: list[float]) -> EntityClock:
    return EntityClock(monotonic=lambda: time_list[0])


def _runner(
    bus: Any,
    clock: EntityClock,
    stage_state: StageState,
    tmp_path: Path,
) -> MaturationGateRunner:
    return MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(
            enabled=True,
            gate_cadence_seconds=1.0,
            min_sleep_cycles=100,
            min_consolidation_passes=100,
            min_lived_seconds=1e9,
        ),
        registry=_FakeRegistry(),
        entity_clock=clock,
        stage_state=stage_state,
        staging_enabled=True,
        womb_feed_configured=True,
    )


@pytest.fixture
def stage_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    p = tmp_path / "stage.json"
    monkeypatch.setattr("kaine.lifecycle.stage.STAGE_PATH", p)
    return p


@pytest.mark.asyncio
async def test_lived_time_accumulates_and_survives_downtime(
    fake_async_bus: Any, stage_path: Path
) -> None:
    """Subjective lived time accumulates from the second tick and survives a restart."""
    t = [0.0]
    runner = _runner(fake_async_bus, _make_clock(t), StageState(stage=GESTATION), stage_path)
    await runner._evaluate_once()
    t[0] += 100.0
    await runner._evaluate_once()

    stage = read_stage(stage_path)
    assert stage.lived_seconds == pytest.approx(100.0)

    # Simulate a restart: a new clock whose subjective time starts 12 hours later,
    # but the persisted lived time must not jump on the first tick.
    t2 = [0.0]
    runner2 = _runner(
        fake_async_bus,
        EntityClock(origin=43200.0, monotonic=lambda: t2[0]),
        stage,
        stage_path,
    )
    await runner2._evaluate_once()
    assert runner2._stage.lived_seconds == pytest.approx(100.0)

    t2[0] += 50.0
    await runner2._evaluate_once()
    assert runner2._stage.lived_seconds == pytest.approx(150.0)

    persisted = read_stage(stage_path)
    assert persisted.lived_seconds == pytest.approx(150.0)


@pytest.mark.asyncio
async def test_frozen_clock_adds_no_lived_time(
    fake_async_bus: Any, stage_path: Path
) -> None:
    t = [0.0]
    clock = EntityClock(scale=0.0, monotonic=lambda: t[0])
    runner = _runner(fake_async_bus, clock, StageState(stage=GESTATION), stage_path)
    await runner._evaluate_once()
    t[0] += 100.0
    await runner._evaluate_once()
    assert runner._stage.lived_seconds == 0.0


@pytest.mark.asyncio
async def test_sleeps_before_first_tick_are_ignored(
    fake_async_bus: Any, stage_path: Path
) -> None:
    for _ in range(2):
        await fake_async_bus.publish(
            Event(
                source="hypnos",
                type="hypnos.sleep.completed",
                payload={},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        )

    runner = _runner(fake_async_bus, _make_clock([0.0]), StageState(stage=GESTATION), stage_path)
    await runner._evaluate_once()
    assert runner._stage.sleep_count == 0
    assert runner._stage.hypnos_cursor is not None

    for _ in range(2):
        await fake_async_bus.publish(
            Event(
                source="hypnos",
                type="hypnos.sleep.completed",
                payload={},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        )
    await runner._evaluate_once()
    assert runner._stage.sleep_count == 2


@pytest.mark.asyncio
async def test_only_hypnos_completed_events_count(
    fake_async_bus: Any, stage_path: Path
) -> None:
    runner = _runner(fake_async_bus, _make_clock([0.0]), StageState(stage=GESTATION), stage_path)
    await runner._evaluate_once()  # anchor cursor at the (empty) stream tail

    await fake_async_bus.publish(
        Event(
            source="hypnos",
            type="hypnos.sleep.started",
            payload={},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
    )
    await fake_async_bus.publish(
        Event(
            source="hypnos",
            type="hypnos.sleep.completed",
            payload={},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
    )
    await fake_async_bus.publish(
        Event(
            source="other",
            type="hypnos.sleep.completed",
            payload={},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
    )
    await runner._evaluate_once()
    assert runner._stage.sleep_count == 1


@pytest.mark.asyncio
async def test_sleep_count_resumes_across_restarts(
    fake_async_bus: Any, stage_path: Path
) -> None:
    runner = _runner(fake_async_bus, _make_clock([0.0]), StageState(stage=GESTATION), stage_path)
    await runner._evaluate_once()

    for _ in range(2):
        await fake_async_bus.publish(
            Event(
                source="hypnos",
                type="hypnos.sleep.completed",
                payload={},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        )
    await runner._evaluate_once()
    assert runner._stage.sleep_count == 2

    await fake_async_bus.publish(
        Event(
            source="hypnos",
            type="hypnos.sleep.completed",
            payload={},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
    )

    # Simulate a crash: a new runner resumes from the persisted stage file.
    stage = read_stage(stage_path)
    runner2 = _runner(fake_async_bus, _make_clock([0.0]), stage, stage_path)
    await runner2._evaluate_once()
    assert runner2._stage.sleep_count == 3

    # Idempotent: no new events means the count stays flat.
    await runner2._evaluate_once()
    assert runner2._stage.sleep_count == 3


@pytest.mark.asyncio
async def test_womb_readiness_readout_trustworthiness(
    fake_async_bus: Any, stage_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bus = fake_async_bus
    monkeypatch.setattr(bus, "server_time_ms", AsyncMock(return_value=1_000_000))

    runner = _runner(bus, _make_clock([0.0]), StageState(stage=GESTATION), stage_path)
    await runner._evaluate_once()
    assert runner._boot_ms == 1_000_000

    # No readout at all.
    assert await runner._womb_readiness_readout() is None

    # Wrong event type is ignored.
    await bus.client.xadd(
        "womb.out",
        _encode_event(
            Event(
                source="womb",
                type="womb.heartbeat",
                payload={"readout": {"x": 1}},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        ),
        id="1000001-0",
    )
    assert await runner._womb_readiness_readout() is None
    await bus.client.delete("womb.out")

    # A readout from just before this boot is ignored even though it is young
    # enough to pass the age window (500 ms old against a 3 s window).
    await bus.client.xadd(
        "womb.out",
        _encode_event(
            Event(
                source="womb",
                type="gestation.readiness",
                payload={"readout": {"x": 1}},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        ),
        id="999500-0",
    )
    assert await runner._womb_readiness_readout() is None
    await bus.client.delete("womb.out")

    # Fresh valid readout -> the embedded readout dict.
    await bus.client.xadd(
        "womb.out",
        _encode_event(
            Event(
                source="womb",
                type="gestation.readiness",
                payload={"readout": {"x": 1}},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        ),
        id="1001000-0",
    )
    readout = await runner._womb_readiness_readout()
    assert readout == {"x": 1}

    # Stale by age (default 3 cadences * 1.0 s).
    monkeypatch.setattr(bus, "server_time_ms", AsyncMock(return_value=1_010_000))
    await bus.client.delete("womb.out")
    await bus.client.xadd(
        "womb.out",
        _encode_event(
            Event(
                source="womb",
                type="gestation.readiness",
                payload={"readout": {"x": 1}},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            )
        ),
        id="1001000-0",
    )
    assert await runner._womb_readiness_readout() is None


def test_resolve_boot_stage_does_not_write_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("kaine.lifecycle.stage.STAGE_PATH", tmp_path / "stage.json")
    monkeypatch.chdir(tmp_path)

    stage, staging_enabled, is_fresh = _resolve_boot_stage(
        {"developmental_stage": {"enabled": True}}
    )
    assert stage.is_gestating
    assert staging_enabled is True
    assert is_fresh is True
    assert not (tmp_path / "stage.json").exists()
