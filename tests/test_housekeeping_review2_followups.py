# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Follow-up regression tests for the second housekeeping review."""

from __future__ import annotations

import os

import pytest

import kaine.storage
from kaine.cycle.housekeeping_floor import AwakeFloor
from kaine.modules.sleep.housekeeping import Housekeeper, HousekeepingConfig
from kaine.persistence.study_record_gate import StudyRecordGate


@pytest.fixture(autouse=True)
def data_root(tmp_path):
    """Point kaine.storage at a fresh tmp_path for every test."""
    previous = kaine.storage.data_root()
    kaine.storage.set_data_root(tmp_path)
    yield tmp_path
    kaine.storage.set_data_root(previous)


def _make_hk(tmp_path, **kwargs):
    archive = tmp_path / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    protected = tmp_path / "state"
    protected.mkdir(parents=True, exist_ok=True)
    roots = [
        tmp_path / "data" / "evaluation",
        tmp_path / "data" / "workspace_trajectory",
    ]
    for r in roots:
        r.mkdir(parents=True, exist_ok=True)
    config = HousekeepingConfig(
        archive_dir=str(archive),
        disk_budget_bytes=kwargs.pop("disk_budget_bytes", 1),
        time_allowance_s=kwargs.pop("time_allowance_s", 300.0),
    )
    return Housekeeper(
        config,
        roots=roots,
        protected=protected,
        log_backups=lambda: [],
        today=lambda: "2026-10-20",
        **kwargs,
    )


class _Usage:
    """A mutable stand-in for shutil.disk_usage's result."""

    def __init__(self, *, total, used, free):
        self.total = total
        self.used = used
        self.free = free


class _FakeHousekeeper:
    def __init__(self, usage, free_per_call):
        self.usage = usage
        self.free_per_call = free_per_call
        self.calls = []
        self._excess = 0.0

    async def reclaim_regenerable(self, *, free_bytes, target_free, device=None):
        self.calls.append({"free_before": free_bytes(), "target_free": target_free})
        self.usage.free += self.free_per_call
        return {"reclaimed_files": 1, "reclaimed_bytes": self.free_per_call}

    def disk_excess(self):
        return self._excess


class _FakePressure:
    def __init__(self):
        self.notes = []

    def note_floor_disk_excess(self, excess):
        self.notes.append(excess)


@pytest.mark.asyncio
async def test_late_append_after_open_with_old_archive_copy(tmp_path, monkeypatch):
    hk_inst = _make_hk(tmp_path, archive_mounted=lambda p: True)
    root = tmp_path / "data" / "evaluation"
    src = root / "research_events" / "research_events-2026-10-01.jsonl"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("old\n", encoding="utf-8")

    archive = tmp_path / "archive"
    archive_copy = (
        archive / "evaluation" / "research_events" / "research_events-2026-10-01.jsonl"
    )
    archive_copy.parent.mkdir(parents=True, exist_ok=True)
    archive_copy.write_text("old\n", encoding="utf-8")

    real_fstat = os.fstat
    called = False

    def fstat_once(fd, *args, **kwargs):
        nonlocal called
        result = real_fstat(fd, *args, **kwargs)
        if not called:
            called = True
            # Append after recording the pre-append size so the open fd
            # still reads the newly appended bytes while before size is old.
            with open(src, "a", encoding="utf-8") as fh:
                fh.write("late\n")
        return result

    monkeypatch.setattr("kaine.modules.sleep.housekeeping.os.fstat", fstat_once)

    await hk_inst._export_to_archive(src, root, archive)

    if src.exists():
        assert src.read_text(encoding="utf-8") == "old\nlate\n"
    else:
        assert archive_copy.read_text(encoding="utf-8") == "old\nlate\n"


@pytest.mark.asyncio
async def test_floor_resume_survives_unreadable_volume(tmp_path):
    usage = _Usage(total=1000, used=990, free=10)
    gate = StudyRecordGate()

    def disk_usage(path):
        if getattr(disk_usage, "raise_for", None) == path:
            raise OSError("cannot read volume")
        return usage

    disk_usage.raise_for = None

    hk = _FakeHousekeeper(usage, free_per_call=0)
    pressure = _FakePressure()

    floor = AwakeFloor(
        hk,
        pressure,
        volumes={"data": tmp_path},
        reserve_bytes=100,
        reserve_share=0.0,
        period_s=60.0,
        is_asleep=lambda: False,
        gate=gate,
        disk_usage=disk_usage,
    )

    # First pass: low free space causes suspension.
    actions = await floor.check_once()
    assert gate.suspended
    assert any(a["action"] == "suspend" for a in actions)

    # Free space is now above target, but the volume is unreadable during
    # the resume check. The floor must stay suspended without raising.
    usage.free = 500
    disk_usage.raise_for = tmp_path

    actions = await floor.check_once()
    assert gate.suspended
    assert not any(a["action"] == "resume" for a in actions)

    # Volume becomes readable again with free space at the target.
    disk_usage.raise_for = None

    actions = await floor.check_once()
    assert not gate.suspended
    assert any(a["action"] == "resume" for a in actions)
