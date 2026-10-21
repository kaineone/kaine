# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for housekeeping archive mount behavior."""

import os
import stat

import pytest

import kaine.modules.sleep.housekeeping as housekeeping_module
import kaine.storage
from kaine.modules.sleep.housekeeping import Housekeeper, HousekeepingConfig


@pytest.fixture(autouse=True)
def _tmp_archive_counts_as_mounted(monkeypatch):
    """A tmp archive shares the test's filesystem; treat it as a mounted volume here.

    The real mount check is covered in tests/test_housekeeping_review2.py.
    """
    real_check = housekeeping_module._is_mounted_volume
    monkeypatch.setattr(
        housekeeping_module,
        "_is_mounted_volume",
        lambda archive, roots: os.path.isdir(archive) if "archive" in str(archive) else real_check(archive, roots),
    )


pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _set_data_root(tmp_path):
    previous = kaine.storage.data_root()
    kaine.storage.set_data_root(tmp_path)
    try:
        yield
    finally:
        kaine.storage.set_data_root(previous)


async def test_missing_archive_counts_as_unmounted_and_log_backup_deleted(tmp_path):
    study_dir = tmp_path / "data" / "evaluation" / "research_events"
    study_dir.mkdir(parents=True)
    study_file = study_dir / "research_events-2026-10-01.jsonl"
    study_file.write_text("study record\n")

    logs_dir = tmp_path / "logs"
    logs_dir.mkdir()
    backup = logs_dir / "process.log.1"
    backup.write_text("log backup\n")

    missing_archive = tmp_path / "missing"
    config = HousekeepingConfig(
        disk_budget_bytes=1,
        archive_dir=str(missing_archive),
    )
    hk = Housekeeper(
        config,
        log_backups=lambda: [backup],
        today=lambda: "2026-10-21",
    )

    report = await hk.run()

    assert report["stopped"] == "no_archive"
    assert report["archive"] is False
    assert study_file.exists()
    assert not missing_archive.exists()
    assert report["deleted_files"] == 1
    assert report["deleted_bytes"] == len("log backup\n")
    assert report["moved_files"] == 0


async def test_reclaim_regenerable_missing_archive_keeps_study_file(tmp_path):
    study_dir = tmp_path / "data" / "evaluation" / "research_events"
    study_dir.mkdir(parents=True)
    study_file = study_dir / "research_events-2026-10-01.jsonl"
    study_file.write_text("study record\n")

    config = HousekeepingConfig(
        disk_budget_bytes=1,
        archive_dir=str(tmp_path / "missing"),
    )
    hk = Housekeeper(config, log_backups=lambda: [], today=lambda: "2026-10-21")

    result = await hk.reclaim_regenerable(free_bytes=lambda: 0, target_free=1)

    assert study_file.exists()
    assert result == {"reclaimed_files": 0, "reclaimed_bytes": 0}


async def test_export_creates_archive_directories_with_mode_700(tmp_path):
    study_dir = tmp_path / "data" / "evaluation" / "research_events"
    study_dir.mkdir(parents=True)
    study_file = study_dir / "research_events-2026-10-01.jsonl"
    study_file.write_text("study record\n")

    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()

    config = HousekeepingConfig(
        disk_budget_bytes=1,
        archive_dir=str(archive_dir),
    )
    hk = Housekeeper(config, log_backups=lambda: [], today=lambda: "2026-10-21")

    old_umask = os.umask(0o022)
    try:
        await hk.run()
    finally:
        os.umask(old_umask)

    eval_dir = archive_dir / "evaluation"
    events_dir = eval_dir / "research_events"

    assert eval_dir.is_dir()
    assert events_dir.is_dir()
    assert stat.S_IMODE(os.lstat(eval_dir).st_mode) == 0o700
    assert stat.S_IMODE(os.lstat(events_dir).st_mode) == 0o700
    assert (events_dir / "research_events-2026-10-01.jsonl").exists()
