# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import math
from pathlib import Path

import pytest

from kaine.bus.schema import Event
from kaine.bus.streams import HOUSEKEEPING_SOURCE
from kaine.cycle.housekeeping_floor import AwakeFloor
from kaine.persistence.study_record_gate import StudyRecordGate


class Usage:
    """A mutable stand-in for shutil.disk_usage's result."""

    def __init__(self, *, total, used, free):
        self.total = total
        self.used = used
        self.free = free


class FakeHousekeeper:
    def __init__(self, usage, free_per_call):
        self.usage = usage
        self.free_per_call = free_per_call
        self.calls = []
        self._excess = 0.0

    async def reclaim_regenerable(self, *, free_bytes, target_free):
        self.calls.append({"free_before": free_bytes(), "target_free": target_free})
        self.usage.free += self.free_per_call
        return {"reclaimed_files": 1, "reclaimed_bytes": self.free_per_call}

    def disk_excess(self):
        return self._excess


class FakePressure:
    def __init__(self):
        self.notes = []

    def note_floor_disk_excess(self, excess):
        self.notes.append(excess)

    def shared_pressure(self):
        return 0.0


class FakeBus:
    def __init__(self, raise_on=None):
        self.events = []
        self.raise_on = raise_on

    async def publish(self, event):
        if self.raise_on is not None:
            raise self.raise_on
        self.events.append(event)


def test_reserve_is_max_of_fixed_and_share() -> None:
    usage = Usage(total=1000, used=0, free=0)
    gate = StudyRecordGate()

    def disk_usage(path):
        return usage

    floor = AwakeFloor(
        None,
        None,
        volumes={"data": Path("/tmp")},
        reserve_bytes=100,
        reserve_share=0.25,
        period_s=1.0,
        is_asleep=lambda: False,
        gate=gate,
        disk_usage=disk_usage,
    )
    assert floor.reserve(1000) == 250
    assert floor.reserve(200) == 100


@pytest.mark.asyncio
async def test_above_reserve_nothing_happens(tmp_path) -> None:
    usage = Usage(total=1000, used=0, free=500)
    gate = StudyRecordGate()

    def disk_usage(path):
        return usage

    floor = AwakeFloor(
        FakeHousekeeper(usage, 0),
        FakePressure(),
        volumes={"data": tmp_path},
        reserve_bytes=100,
        reserve_share=0.0,
        period_s=1.0,
        is_asleep=lambda: False,
        gate=gate,
        disk_usage=disk_usage,
    )
    actions = await floor.check_once()
    assert actions == []
    assert not gate.suspended


@pytest.mark.asyncio
async def test_reclaim_runs_with_target_double_reserve(tmp_path) -> None:
    usage = Usage(total=1000, used=0, free=90)
    gate = StudyRecordGate()

    def disk_usage(path):
        return usage

    pressure = FakePressure()
    housekeeper = FakeHousekeeper(usage, 500)
    floor = AwakeFloor(
        housekeeper,
        pressure,
        volumes={"data": tmp_path},
        reserve_bytes=100,
        reserve_share=0.0,
        period_s=1.0,
        is_asleep=lambda: False,
        gate=gate,
        disk_usage=disk_usage,
    )
    actions = await floor.check_once()
    assert len(actions) == 1
    assert actions[0]["action"] == "reclaim"
    assert housekeeper.calls[0]["target_free"] == 200
    assert actions[0]["free_bytes_after"] >= 200
    assert not gate.suspended
    assert pressure.notes == [0.0]


@pytest.mark.asyncio
async def test_no_suspension_when_reclaim_reaches_reserve(tmp_path) -> None:
    usage = Usage(total=1000, used=0, free=50)
    gate = StudyRecordGate()

    def disk_usage(path):
        return usage

    housekeeper = FakeHousekeeper(usage, 60)  # frees to 110, above R=100 but below 2R
    floor = AwakeFloor(
        housekeeper,
        FakePressure(),
        volumes={"data": tmp_path},
        reserve_bytes=100,
        reserve_share=0.0,
        period_s=1.0,
        is_asleep=lambda: False,
        gate=gate,
        disk_usage=disk_usage,
    )
    actions = await floor.check_once()
    assert all(a["action"] != "suspend" for a in actions)
    assert not gate.suspended


@pytest.mark.asyncio
async def test_suspension_and_resume(tmp_path) -> None:
    usage = Usage(total=1000, used=0, free=50)
    gate = StudyRecordGate()

    def disk_usage(path):
        return usage

    housekeeper = FakeHousekeeper(usage, 20)  # never reaches R=100
    floor = AwakeFloor(
        housekeeper,
        FakePressure(),
        volumes={"data": tmp_path},
        reserve_bytes=100,
        reserve_share=0.0,
        period_s=1.0,
        is_asleep=lambda: False,
        gate=gate,
        disk_usage=disk_usage,
    )
    actions = await floor.check_once()
    assert any(a["action"] == "suspend" for a in actions)
    assert gate.suspended

    # Second check must not suspend again or re-publish suspend.
    actions2 = await floor.check_once()
    assert all(a["action"] != "suspend" for a in actions2)
    assert gate.suspended

    # Free space between R and 2R keeps the gate suspended.
    usage.free = 150
    actions3 = await floor.check_once()
    assert gate.suspended
    assert all(a["action"] != "resume" for a in actions3)

    # Back at 2R resumes.
    usage.free = 250
    actions4 = await floor.check_once()
    assert any(a["action"] == "resume" for a in actions4)
    assert not gate.suspended


@pytest.mark.asyncio
async def test_asleep_does_nothing(tmp_path) -> None:
    usage = Usage(total=1000, used=0, free=50)
    gate = StudyRecordGate()

    def disk_usage(path):
        return usage

    housekeeper = FakeHousekeeper(usage, 0)
    floor = AwakeFloor(
        housekeeper,
        FakePressure(),
        volumes={"data": tmp_path},
        reserve_bytes=100,
        reserve_share=0.0,
        period_s=1.0,
        is_asleep=lambda: True,
        gate=gate,
        disk_usage=disk_usage,
    )
    actions = await floor.check_once()
    assert actions == []
    assert housekeeper.calls == []
    assert not gate.suspended


@pytest.mark.asyncio
async def test_same_filesystem_checked_once(tmp_path) -> None:
    usage = Usage(total=1000, used=0, free=50)
    gate = StudyRecordGate()

    def disk_usage(path):
        return usage

    housekeeper = FakeHousekeeper(usage, 0)
    floor = AwakeFloor(
        housekeeper,
        FakePressure(),
        volumes={"data": tmp_path, "state": tmp_path},
        reserve_bytes=100,
        reserve_share=0.0,
        period_s=1.0,
        is_asleep=lambda: False,
        gate=gate,
        disk_usage=disk_usage,
    )
    await floor.check_once()
    assert len(housekeeper.calls) == 1


@pytest.mark.asyncio
async def test_bus_publishes_events_and_failure_ignored(tmp_path) -> None:
    usage = Usage(total=1000, used=0, free=50)
    gate = StudyRecordGate()

    def disk_usage(path):
        return usage

    bus = FakeBus()
    housekeeper = FakeHousekeeper(usage, 200)
    floor = AwakeFloor(
        housekeeper,
        FakePressure(),
        volumes={"data": tmp_path},
        reserve_bytes=100,
        reserve_share=0.0,
        period_s=1.0,
        is_asleep=lambda: False,
        gate=gate,
        bus=bus,
        disk_usage=disk_usage,
    )
    actions = await floor.check_once()
    assert len(actions) >= 1
    await asyncio.sleep(0.05)
    assert len(bus.events) >= 1
    event = bus.events[0]
    assert isinstance(event, Event)
    assert event.source == HOUSEKEEPING_SOURCE
    assert event.type == "housekeeping.floor"
    assert event.payload == actions[0]

    # A failing publish must not stop check_once.
    bus.raise_on = RuntimeError("boom")
    usage.free = 50
    actions2 = await floor.check_once()
    assert len(actions2) >= 1


@pytest.mark.asyncio
async def test_run_stops_on_stop_event(tmp_path) -> None:
    usage = Usage(total=1000, used=0, free=500)
    gate = StudyRecordGate()

    def disk_usage(path):
        return usage

    floor = AwakeFloor(
        FakeHousekeeper(usage, 0),
        FakePressure(),
        volumes={"data": tmp_path},
        reserve_bytes=100,
        reserve_share=0.0,
        period_s=0.05,
        is_asleep=lambda: False,
        gate=gate,
        disk_usage=disk_usage,
    )
    stop_event = asyncio.Event()
    task = asyncio.create_task(floor.run(stop_event))
    await asyncio.sleep(0.12)
    stop_event.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert not task.cancelled()


def test_validation_errors() -> None:
    good_kwargs = {
        "volumes": {"data": Path("/tmp")},
        "reserve_bytes": 100,
        "reserve_share": 0.0,
        "period_s": 1.0,
        "is_asleep": lambda: False,
    }

    with pytest.raises(ValueError):
        AwakeFloor(None, None, **{**good_kwargs, "reserve_bytes": -1})

    with pytest.raises(ValueError):
        AwakeFloor(None, None, **{**good_kwargs, "reserve_bytes": True})

    with pytest.raises(ValueError):
        AwakeFloor(None, None, **{**good_kwargs, "reserve_share": 1.0})

    with pytest.raises(ValueError):
        AwakeFloor(None, None, **{**good_kwargs, "reserve_share": float("inf")})

    with pytest.raises(ValueError):
        AwakeFloor(None, None, **{**good_kwargs, "period_s": 0.0})

    with pytest.raises(ValueError):
        AwakeFloor(None, None, **{**good_kwargs, "period_s": math.nan})

    with pytest.raises(ValueError):
        AwakeFloor(None, None, **{**good_kwargs, "volumes": {}})


@pytest.mark.asyncio
async def test_payloads_contain_no_paths(tmp_path) -> None:
    usage = Usage(total=1000, used=0, free=50)
    gate = StudyRecordGate()

    def disk_usage(path):
        return usage

    housekeeper = FakeHousekeeper(usage, 0)
    floor = AwakeFloor(
        housekeeper,
        FakePressure(),
        volumes={"data": tmp_path},
        reserve_bytes=100,
        reserve_share=0.0,
        period_s=1.0,
        is_asleep=lambda: False,
        gate=gate,
        bus=FakeBus(),
        disk_usage=disk_usage,
    )
    await floor.check_once()
    usage.free = 250
    await floor.check_once()
    # Drain bus tasks before inspecting payloads.
    await asyncio.sleep(0.05)

    def has_path(obj):
        if isinstance(obj, Path):
            return True
        if isinstance(obj, str) and "/" in obj:
            return True
        if isinstance(obj, dict):
            return any(has_path(v) for v in obj.values())
        if isinstance(obj, (list, tuple)):
            return any(has_path(i) for i in obj)
        return False

    for event in floor._bus.events:
        assert not has_path(event.payload)
        assert not has_path(event.source)
        assert not has_path(event.type)
