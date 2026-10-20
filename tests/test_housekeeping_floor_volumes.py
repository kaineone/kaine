# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os as os_module
from pathlib import Path

import pytest

import kaine.storage
from kaine.cycle.housekeeping_floor import AwakeFloor
from kaine.modules.sleep.housekeeping import Housekeeper, HousekeepingConfig
from kaine.persistence.study_record_gate import StudyRecordGate


class Usage:
    """A mutable stand-in for shutil.disk_usage's result."""

    def __init__(self, *, total, used, free):
        self.total = total
        self.used = used
        self.free = free


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


@pytest.mark.asyncio
async def test_reclaim_regenerable_device_filter_for_log_backup(tmp_path, monkeypatch):
    """Device filter skips candidates on a different st_dev; None disables it."""
    import kaine.modules.sleep.housekeeping as hk

    prev_root = kaine.storage.data_root()
    kaine.storage.set_data_root(tmp_path)
    try:
        same_dev = tmp_path / "same.log"
        same_dev.write_text("same")
        other_dev = tmp_path / "other.log"
        other_dev.write_text("other")

        real_stat = os_module.stat

        def fake_stat(path, *, dir_fd=None, follow_symlinks=True):
            st = real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
            fields = list(st)[:10]
            if os_module.path.abspath(path) == os_module.path.abspath(other_dev):
                fields[2] = st.st_dev + 1000
            return os_module.stat_result(fields)

        monkeypatch.setattr(hk.os, "stat", fake_stat)

        config = HousekeepingConfig(disk_budget_bytes=1)
        housekeeper = Housekeeper(config)

        # Treat both files as log-backup candidates.
        monkeypatch.setattr(
            housekeeper, "candidates", lambda: iter([same_dev, other_dev])
        )
        monkeypatch.setattr(housekeeper, "check_allowed", lambda path: Path(path))
        monkeypatch.setattr(housekeeper, "_is_log_backup", lambda path: True)

        deleted = []

        def fake_delete(path):
            deleted.append(Path(path))
            return 4

        monkeypatch.setattr(housekeeper, "_delete", fake_delete)

        # device matching tmp_path: only the same-device backup is deleted.
        await housekeeper.reclaim_regenerable(
            free_bytes=lambda: 0 if len(deleted) < 1 else 1000,
            target_free=10,
            device=os_module.stat(tmp_path).st_dev,
        )
        assert deleted == [same_dev]

        deleted.clear()

        # device=None: both backups are deletable.
        await housekeeper.reclaim_regenerable(
            free_bytes=lambda: 0 if len(deleted) < 2 else 1000,
            target_free=10,
            device=None,
        )
        assert set(deleted) == {same_dev, other_dev}
    finally:
        kaine.storage.set_data_root(prev_root)


@pytest.mark.asyncio
async def test_check_once_passes_device(tmp_path):
    """The device keyword forwarded to reclaim_regenerable matches the volume."""
    class RecordingHousekeeper:
        def __init__(self):
            self.calls = []

        async def reclaim_regenerable(self, *, free_bytes, target_free, device=None):
            self.calls.append({"device": device})
            return {"reclaimed_files": 0, "reclaimed_bytes": 0}

        def disk_excess(self):
            return 0.0

    hk = RecordingHousekeeper()
    path = tmp_path / "a"
    path.mkdir()
    usage = Usage(total=1000, used=900, free=100)

    floor = AwakeFloor(
        hk,
        FakePressure(),
        volumes={"data": path},
        reserve_bytes=200,
        reserve_share=0.0,
        period_s=1.0,
        is_asleep=lambda: False,
        gate=StudyRecordGate(),
        disk_usage=lambda p: usage,
    )
    await floor.check_once()
    assert hk.calls == [{"device": os_module.stat(path).st_dev}]


@pytest.mark.asyncio
async def test_second_volume_recorded_while_suspended(tmp_path, monkeypatch):
    """A second low volume is recorded while suspended; resume waits for all."""
    import kaine.cycle.housekeeping_floor as floor_module

    data_path = tmp_path / "data"
    state_path = tmp_path / "state"
    data_path.mkdir()
    state_path.mkdir()

    real_stat = os_module.stat

    def fake_stat(path, *, dir_fd=None, follow_symlinks=True):
        st = real_stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        fields = list(st)[:10]
        if os_module.path.abspath(path) == os_module.path.abspath(data_path):
            fields[2] = 1
        elif os_module.path.abspath(path) == os_module.path.abspath(state_path):
            fields[2] = 2
        return os_module.stat_result(fields)

    monkeypatch.setattr(floor_module.os, "stat", fake_stat)

    R = 100
    total = 1000

    usages = {
        data_path: Usage(total=total, used=0, free=R - 1),
        state_path: Usage(total=total, used=0, free=R + 100),
    }

    class NoopHousekeeper:
        def __init__(self):
            self.calls = []

        async def reclaim_regenerable(self, *, free_bytes, target_free, device=None):
            self.calls.append({"device": device})
            return {"reclaimed_files": 0, "reclaimed_bytes": 0}

        def disk_excess(self):
            return 0.0

    hk = NoopHousekeeper()
    bus = FakeBus()

    floor = AwakeFloor(
        hk,
        FakePressure(),
        volumes={"data": data_path, "state": state_path},
        reserve_bytes=R,
        reserve_share=0.0,
        period_s=1.0,
        is_asleep=lambda: False,
        gate=StudyRecordGate(),
        bus=bus,
        disk_usage=lambda p: usages[p],
    )

    # Only "data" is low: reclaim and suspend once.
    actions = await floor.check_once()
    assert [a["action"] for a in actions] == ["reclaim", "suspend"]
    assert floor._gate.suspended
    assert floor._suspending_volumes == {"data"}

    # "state" also drops below R: no new suspend action, but it is recorded.
    usages[state_path].free = R - 1
    actions = await floor.check_once()
    assert [a["action"] for a in actions] == ["reclaim", "reclaim"]
    assert floor._gate.suspended
    assert floor._suspending_volumes == {"data", "state"}

    # "data" returns to 2R while "state" is still low: no resume.
    usages[data_path].free = 2 * R + 1
    actions = await floor.check_once()
    assert [a["action"] for a in actions] == ["reclaim"]
    assert floor._gate.suspended
    assert floor._suspending_volumes == {"data", "state"}

    # "state" returns to 2R: resume.
    usages[state_path].free = 2 * R + 1
    actions = await floor.check_once()
    assert [a["action"] for a in actions] == ["resume"]
    assert not floor._gate.suspended
    assert floor._suspending_volumes == set()
