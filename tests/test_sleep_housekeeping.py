# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine/modules/sleep/housekeeping.py."""

import json
import logging.handlers
import os
from pathlib import Path

import pytest

from kaine.modules.sleep.housekeeping import (
    Housekeeper,
    HousekeepingConfig,
    HousekeepingRefused,
    bus_memory_bytes,
    rotated_log_backups,
)
from kaine.storage import data_root, set_data_root


def _write_file(path: Path, size: int = 400) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


@pytest.fixture(autouse=True)
def _set_data_root(tmp_path):
    previous = data_root()
    set_data_root(tmp_path)
    yield
    set_data_root(previous)


def _archive_config(tmp_path, **kwargs):
    # The archive is a volume the operator mounts, so it exists before any export.
    (tmp_path / "archive").mkdir(exist_ok=True)
    return HousekeepingConfig(archive_dir=str(tmp_path / "archive"), **kwargs)


def test_config_defaults():
    cfg = HousekeepingConfig()
    assert cfg.enabled is True
    assert cfg.disk_budget_bytes == 10 * 1024**3
    assert cfg.memory_budget_bytes == 1024**3
    assert cfg.time_allowance_s == 60.0
    assert cfg.archive_dir == ""


def test_config_from_section_empty():
    assert HousekeepingConfig.from_section(None) == HousekeepingConfig()
    assert HousekeepingConfig.from_section({}) == HousekeepingConfig()


def test_config_from_section_good():
    cfg = HousekeepingConfig.from_section(
        {
            "enabled": False,
            "disk_budget_bytes": 5 * 1024**3,
            "memory_budget_bytes": 2 * 1024**3,
            "time_allowance_s": 120.0,
            "archive_dir": "/tmp/archive",
        }
    )
    assert cfg.enabled is False
    assert cfg.disk_budget_bytes == 5 * 1024**3
    assert cfg.memory_budget_bytes == 2 * 1024**3
    assert cfg.time_allowance_s == 120.0
    assert cfg.archive_dir == "/tmp/archive"


def test_config_from_section_non_dict():
    with pytest.raises(ValueError, match="must be a table"):
        HousekeepingConfig.from_section("enabled = true")


@pytest.mark.parametrize(
    "bad",
    [
        {"enabled": 1},
        {"disk_budget_bytes": 0},
        {"disk_budget_bytes": -1},
        {"disk_budget_bytes": True},
        {"disk_budget_bytes": 1.5},
        {"memory_budget_bytes": 0},
        {"memory_budget_bytes": True},
        {"time_allowance_s": 0},
        {"time_allowance_s": float("nan")},
        {"time_allowance_s": float("inf")},
        {"time_allowance_s": True},
        {"archive_dir": 3},
        {"unknown_key": 1},
    ],
)
def test_config_from_section_bad_values(bad):
    base = {
        "enabled": True,
        "disk_budget_bytes": 1024,
        "memory_budget_bytes": 1024,
        "time_allowance_s": 1.0,
        "archive_dir": "",
    }
    with pytest.raises(ValueError):
        HousekeepingConfig.from_section({**base, **bad})


def test_archive_inside_root(tmp_path):
    cfg = HousekeepingConfig(
        archive_dir=str(tmp_path / "data" / "evaluation" / "archive")
    )
    with pytest.raises(HousekeepingRefused):
        Housekeeper(cfg)


def test_archive_equal_root(tmp_path):
    cfg = HousekeepingConfig(archive_dir=str(tmp_path / "data" / "evaluation"))
    with pytest.raises(HousekeepingRefused):
        Housekeeper(cfg)


def test_archive_under_state(tmp_path):
    cfg = HousekeepingConfig(archive_dir=str(tmp_path / "state" / "archive"))
    with pytest.raises(HousekeepingRefused):
        Housekeeper(cfg)


def test_archive_contains_root(tmp_path):
    cfg = HousekeepingConfig(archive_dir=str(tmp_path / "data"))
    with pytest.raises(HousekeepingRefused):
        Housekeeper(cfg)


def test_check_allowed(tmp_path):
    log_backup = _write_file(tmp_path / "logs" / "kaine.log.1")
    protected_backup = _write_file(tmp_path / "state" / "kaine.log.1")
    hk = Housekeeper(
        _archive_config(tmp_path),
        log_backups=lambda: [log_backup, protected_backup],
    )
    root = hk._roots[0]
    protected = hk._protected

    # Protected files that must never be touched.
    protected_paths = [
        protected / "episodic_memory" / "p.jsonl",
        protected / "world_model" / "p.jsonl",
        protected / "self_model" / "p.jsonl",
        protected / "identity" / "p.jsonl",
        protected / "sleep" / "adapters" / "p.jsonl",
        protected / "preservation" / "p.jsonl",
        protected / "forks" / "p.jsonl",
    ]
    for p in protected_paths:
        _write_file(p)

    allowed = _write_file(root / "ok.jsonl")
    assert hk.check_allowed(allowed) == allowed.resolve()

    # A current process-log backup is allowed even outside the roots.
    assert hk.check_allowed(log_backup) == log_backup.resolve()

    # Outside every root.
    outside = _write_file(tmp_path / "elsewhere" / "x.jsonl")

    # Symlink to a protected file.
    symlink_to_protected = root / "link_to_protected.jsonl"
    os.symlink(protected_paths[0], symlink_to_protected)

    # Symlink to an allowed file (still refused because it is a symlink).
    real_allowed = root / "real.jsonl"
    _write_file(real_allowed)
    symlink_to_allowed = root / "link_to_allowed.jsonl"
    os.symlink(real_allowed, symlink_to_allowed)

    # Directory.
    directory = root / "a_directory"
    directory.mkdir()

    # Path with ".." that resolves outside the allowed root.
    _write_file(root.parent / "outside.jsonl")
    dotdot = root / ".." / "outside.jsonl"

    refused = [
        *protected_paths,
        protected_backup,
        outside,
        symlink_to_protected,
        symlink_to_allowed,
        directory,
        dotdot,
    ]
    for path in refused:
        with pytest.raises(HousekeepingRefused):
            hk.check_allowed(path)
        assert path.exists()


@pytest.mark.asyncio
async def test_run_moves_oldest_study_records(tmp_path):
    # 1600 bytes against 900: the two oldest closed files go, 800 remain.
    cfg = _archive_config(tmp_path, disk_budget_bytes=900)
    hk = Housekeeper(cfg, today=lambda: "2026-10-20", log_backups=lambda: [])
    root = hk._roots[0]

    for date in ("2026-10-17", "2026-10-18", "2026-10-19"):
        _write_file(root / "research_events" / f"research_events-{date}.jsonl")
    _write_file(root / "research_events" / "research_events-2026-10-20.jsonl")

    report = await hk.run()
    assert report["enabled"] is True
    assert report["stopped"] == "within_budget"
    assert report["moved_files"] == 2
    assert report["moved_bytes"] == 800
    assert report["deleted_files"] == 0
    assert report["disk_bytes_after"] == 800
    assert report["pressure"] == pytest.approx(0.0)

    archive = Path(cfg.archive_dir).resolve()
    assert (
        archive / "evaluation" / "research_events" / "research_events-2026-10-17.jsonl"
    ).exists()
    assert (
        archive / "evaluation" / "research_events" / "research_events-2026-10-18.jsonl"
    ).exists()
    assert not (
        root / "research_events" / "research_events-2026-10-17.jsonl"
    ).exists()
    assert (
        root / "research_events" / "research_events-2026-10-19.jsonl"
    ).exists()
    assert (
        root / "research_events" / "research_events-2026-10-20.jsonl"
    ).exists()


@pytest.mark.asyncio
async def test_run_no_archive(tmp_path):
    cfg = HousekeepingConfig(disk_budget_bytes=600)
    hk = Housekeeper(cfg, today=lambda: "2026-10-20", log_backups=lambda: [])
    root = hk._roots[0]

    for date in ("2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20"):
        _write_file(root / "research_events" / f"research_events-{date}.jsonl")

    report = await hk.run()
    assert report["stopped"] == "no_archive"
    assert report["moved_files"] == 0
    assert report["deleted_files"] == 0
    assert report["disk_bytes_after"] == 1600
    assert report["pressure"] == pytest.approx(1600 / 600 - 1)
    # Unexported study records are never deleted.
    for date in ("2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20"):
        assert (
            root / "research_events" / f"research_events-{date}.jsonl"
        ).exists()


@pytest.mark.asyncio
async def test_run_deletes_log_backups_oldest_first_without_archive(tmp_path):
    old = _write_file(tmp_path / "logs" / "kaine.log.1", 400)
    new = _write_file(tmp_path / "logs" / "kaine.log.2", 400)
    os.utime(old, (1000, 1000))
    os.utime(new, (2000, 2000))

    cfg = HousekeepingConfig(disk_budget_bytes=800)
    hk = Housekeeper(
        cfg, today=lambda: "2026-10-20", log_backups=lambda: [old, new]
    )
    root = hk._roots[0]
    study = _write_file(
        root / "research_events" / "research_events-2026-10-19.jsonl", 400
    )

    # 1200 bytes against 800: deleting the oldest backup is enough.
    report = await hk.run()
    assert report["stopped"] == "within_budget"
    assert report["deleted_files"] == 1
    assert report["deleted_bytes"] == 400
    assert report["moved_files"] == 0
    assert not old.exists()
    assert new.exists()
    # The unexported study record is never deleted.
    assert study.exists()
    assert report["disk_bytes_after"] == 800


@pytest.mark.asyncio
async def test_run_within_budget(tmp_path):
    cfg = _archive_config(tmp_path, disk_budget_bytes=2000)
    hk = Housekeeper(cfg, today=lambda: "2026-10-20", log_backups=lambda: [])
    root = hk._roots[0]

    for date in ("2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20"):
        _write_file(root / "research_events" / f"research_events-{date}.jsonl")

    report = await hk.run()
    assert report["stopped"] == "within_budget"
    assert report["moved_files"] == 0
    assert report["pressure"] == 0.0


@pytest.mark.asyncio
async def test_run_time_allowance(tmp_path):
    clock_values = [0.0, 0.0, 61.0, 62.0]
    clock_iter = iter(clock_values)

    def fake_clock():
        return next(clock_iter)

    cfg = _archive_config(tmp_path, disk_budget_bytes=200, time_allowance_s=60.0)
    hk = Housekeeper(
        cfg, today=lambda: "2026-10-20", log_backups=lambda: [], clock=fake_clock
    )
    root = hk._roots[0]

    for date in ("2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20"):
        _write_file(root / "research_events" / f"research_events-{date}.jsonl")

    report = await hk.run()
    assert report["stopped"] == "time"
    assert report["moved_files"] == 1
    assert report["moved_bytes"] == 400
    assert report["disk_bytes_after"] == 1200
    assert report["pressure"] == pytest.approx(1200 / 200 - 1)


@pytest.mark.asyncio
async def test_run_only_today_over_budget(tmp_path):
    cfg = _archive_config(tmp_path, disk_budget_bytes=200)
    hk = Housekeeper(cfg, today=lambda: "2026-10-20", log_backups=lambda: [])
    root = hk._roots[0]

    _write_file(root / "research_events" / "research_events-2026-10-20.jsonl")

    report = await hk.run()
    assert report["stopped"] == "no_candidates"
    assert report["moved_files"] == 0
    assert (
        root / "research_events" / "research_events-2026-10-20.jsonl"
    ).exists()


@pytest.mark.asyncio
async def test_run_existing_destination_same_bytes(tmp_path):
    cfg = _archive_config(tmp_path, disk_budget_bytes=600)
    hk = Housekeeper(cfg, today=lambda: "2026-10-20", log_backups=lambda: [])
    root = hk._roots[0]

    src = _write_file(root / "research_events" / "research_events-2026-10-17.jsonl")
    later = _write_file(root / "research_events" / "research_events-2026-10-18.jsonl")

    archive = Path(cfg.archive_dir).resolve()
    dest = (
        archive / "evaluation" / "research_events" / "research_events-2026-10-17.jsonl"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(src.read_bytes())

    # The archive copy matches: the local verified copy is removed and
    # counted, and that alone brings the pass within budget.
    report = await hk.run()
    assert report["stopped"] == "within_budget"
    assert report["moved_files"] == 1
    assert report["moved_bytes"] == 400
    assert not src.exists()
    assert dest.read_bytes() == b"x" * 400
    assert later.exists()


@pytest.mark.asyncio
async def test_run_existing_destination_different_bytes(tmp_path):
    cfg = _archive_config(tmp_path, disk_budget_bytes=200)
    hk = Housekeeper(cfg, today=lambda: "2026-10-20", log_backups=lambda: [])
    root = hk._roots[0]

    src = _write_file(root / "research_events" / "research_events-2026-10-17.jsonl")
    later = _write_file(root / "research_events" / "research_events-2026-10-18.jsonl")

    archive = Path(cfg.archive_dir).resolve()
    dest = (
        archive / "evaluation" / "research_events" / "research_events-2026-10-17.jsonl"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"different content, not x")

    # The archive copy differs: the local file stays, the pass goes on,
    # and the later file is still exported.
    report = await hk.run()
    assert src.exists()
    assert dest.read_bytes() == b"different content, not x"
    assert report["moved_files"] == 1
    assert not later.exists()
    assert (
        archive / "evaluation" / "research_events" / "research_events-2026-10-18.jsonl"
    ).exists()


@pytest.mark.asyncio
async def test_run_export_checksum_mismatch_keeps_source(tmp_path, monkeypatch):
    def fake_sha256(path):
        if str(path).endswith(".part"):
            return "0" * 64
        return "1" * 64

    monkeypatch.setattr(
        "kaine.modules.sleep.housekeeping._sha256", fake_sha256
    )

    cfg = _archive_config(tmp_path, disk_budget_bytes=100)
    hk = Housekeeper(cfg, today=lambda: "2026-10-20", log_backups=lambda: [])
    root = hk._roots[0]
    src = _write_file(root / "research_events" / "research_events-2026-10-19.jsonl")

    report = await hk.run()
    assert report["moved_files"] == 0
    assert report["stopped"] == "no_candidates"
    assert src.exists()
    archive = Path(cfg.archive_dir).resolve()
    dest_dir = archive / "evaluation" / "research_events"
    assert not (dest_dir / "research_events-2026-10-19.jsonl").exists()
    assert not (dest_dir / "research_events-2026-10-19.jsonl.part").exists()


@pytest.mark.asyncio
async def test_run_disabled(tmp_path):
    cfg = HousekeepingConfig(enabled=False)
    hk = Housekeeper(cfg, today=lambda: "2026-10-20", log_backups=lambda: [])
    root = hk._roots[0]

    _write_file(root / "research_events" / "research_events-2026-10-17.jsonl")

    report = await hk.run()
    assert report == {"enabled": False}
    assert (
        root / "research_events" / "research_events-2026-10-17.jsonl"
    ).exists()


def test_disk_bytes_counts_log_backups(tmp_path):
    backups = [
        _write_file(tmp_path / "logs" / "kaine.log.1", 100),
        _write_file(tmp_path / "logs" / "kaine.log.2", 200),
    ]
    hk = Housekeeper(
        _archive_config(tmp_path),
        today=lambda: "2026-10-20",
        log_backups=lambda: backups,
    )
    root = hk._roots[0]
    _write_file(root / "research_events" / "research_events-2026-10-19.jsonl", 400)
    assert hk.disk_bytes() == 700


def test_disk_excess(tmp_path):
    cfg = _archive_config(tmp_path, disk_budget_bytes=400)
    hk = Housekeeper(cfg, today=lambda: "2026-10-20", log_backups=lambda: [])
    assert hk.disk_excess() == 0.0
    root = hk._roots[0]
    _write_file(root / "research_events" / "research_events-2026-10-19.jsonl", 800)
    assert hk.disk_excess() == pytest.approx(1.0)


def test_rotated_log_backups_drops_state(tmp_path):
    good_base = tmp_path / "logs" / "kaine.log"
    good_base.parent.mkdir(parents=True, exist_ok=True)
    good_backup = _write_file(tmp_path / "logs" / "kaine.log.1")
    state_base = tmp_path / "state" / "kaine.log"
    state_base.parent.mkdir(parents=True, exist_ok=True)
    state_backup = _write_file(tmp_path / "state" / "kaine.log.1")

    good_handler = logging.handlers.RotatingFileHandler(
        good_base, maxBytes=1024, backupCount=2
    )
    state_handler = logging.handlers.RotatingFileHandler(
        state_base, maxBytes=1024, backupCount=2
    )
    root_logger = logging.getLogger()
    root_logger.addHandler(good_handler)
    root_logger.addHandler(state_handler)
    try:
        found = rotated_log_backups()
        assert good_backup in found
        # A backup under state/ is never returned.
        assert state_backup not in found
    finally:
        root_logger.removeHandler(good_handler)
        root_logger.removeHandler(state_handler)
        good_handler.close()
        state_handler.close()


@pytest.mark.asyncio
async def test_reclaim_regenerable_stops_at_target(tmp_path):
    log_backup = _write_file(tmp_path / "logs" / "kaine.log.1", 400)
    os.utime(log_backup, (1000, 1000))

    cfg = _archive_config(tmp_path)
    hk = Housekeeper(
        cfg, today=lambda: "2026-10-20", log_backups=lambda: [log_backup]
    )
    root = hk._roots[0]
    exported = _write_file(
        root / "research_events" / "research_events-2026-10-17.jsonl", 400
    )
    unexported = _write_file(
        root / "research_events" / "research_events-2026-10-18.jsonl", 400
    )
    os.utime(exported, (2000, 2000))
    os.utime(unexported, (3000, 3000))

    archive = Path(cfg.archive_dir).resolve()
    dest = (
        archive / "evaluation" / "research_events" / "research_events-2026-10-17.jsonl"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(exported.read_bytes())

    watched = [log_backup, exported, unexported]

    def free_bytes():
        return sum(400 for p in watched if not p.exists())

    result = await hk.reclaim_regenerable(free_bytes=free_bytes, target_free=400)
    assert result == {"reclaimed_files": 1, "reclaimed_bytes": 400}
    # The oldest spent file goes, then the target is met and the pass stops.
    assert not log_backup.exists()
    assert exported.exists()
    assert unexported.exists()


@pytest.mark.asyncio
async def test_reclaim_regenerable_never_deletes_unexported(tmp_path):
    cfg = _archive_config(tmp_path)
    hk = Housekeeper(cfg, today=lambda: "2026-10-20", log_backups=lambda: [])
    root = hk._roots[0]
    exported = _write_file(
        root / "research_events" / "research_events-2026-10-17.jsonl", 400
    )
    unexported = _write_file(
        root / "research_events" / "research_events-2026-10-18.jsonl", 400
    )
    os.utime(exported, (1000, 1000))
    os.utime(unexported, (2000, 2000))

    archive = Path(cfg.archive_dir).resolve()
    dest = (
        archive / "evaluation" / "research_events" / "research_events-2026-10-17.jsonl"
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(exported.read_bytes())

    def free_bytes():
        return 0  # always below target

    result = await hk.reclaim_regenerable(
        free_bytes=free_bytes, target_free=10**9
    )
    assert result == {"reclaimed_files": 1, "reclaimed_bytes": 400}
    # The verified-exported copy is deleted, the archive copy stays.
    assert not exported.exists()
    assert dest.exists()
    # The unexported study record stays even though free space is still
    # below target.
    assert unexported.exists()


@pytest.mark.asyncio
async def test_memory_and_episodic_pressure(tmp_path):
    cfg = _archive_config(
        tmp_path,
        disk_budget_bytes=10 * 1024**3,
        memory_budget_bytes=1024**3,
    )

    async def mem_3gb():
        return 3 * 1024**3

    hk = Housekeeper(
        cfg, memory_reader=mem_3gb, episodic_budget_bytes=10, log_backups=lambda: []
    )
    report = await hk.run(episodic_store_bytes=15)
    assert report["memory_bytes"] == 3 * 1024**3
    assert report["pressure"] == pytest.approx(2.0 + 0.5)

    # No memory reader.
    hk2 = Housekeeper(cfg, episodic_budget_bytes=10, log_backups=lambda: [])
    report2 = await hk2.run(episodic_store_bytes=15)
    assert report2["memory_bytes"] is None
    assert report2["pressure"] == pytest.approx(0.5)

    # No episodic budget configured.
    hk3 = Housekeeper(cfg, memory_reader=mem_3gb, log_backups=lambda: [])
    report3 = await hk3.run(episodic_store_bytes=15)
    assert report3["pressure"] == pytest.approx(2.0)

    # Memory reader that raises.
    async def mem_bad():
        raise RuntimeError("boom")

    hk4 = Housekeeper(cfg, memory_reader=mem_bad, log_backups=lambda: [])
    report4 = await hk4.run()
    assert report4["memory_bytes"] is None
    assert report4["pressure"] == 0.0


@pytest.mark.asyncio
async def test_report_terms_sum_to_pressure(tmp_path):
    cfg = HousekeepingConfig(
        disk_budget_bytes=600,
        memory_budget_bytes=1024**3,
    )

    async def mem_3gb():
        return 3 * 1024**3

    hk = Housekeeper(
        cfg,
        memory_reader=mem_3gb,
        episodic_budget_bytes=10,
        today=lambda: "2026-10-20",
        log_backups=lambda: [],
    )
    root = hk._roots[0]
    for date in ("2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20"):
        _write_file(root / "research_events" / f"research_events-{date}.jsonl")

    report = await hk.run(episodic_store_bytes=15)
    terms = report["terms"]
    assert terms["disk"] == pytest.approx(1600 / 600 - 1)
    assert terms["memory"] == pytest.approx(2.0)
    assert terms["episodic"] == pytest.approx(0.5)
    assert report["pressure"] == pytest.approx(
        terms["disk"] + terms["memory"] + terms["episodic"]
    )


@pytest.mark.asyncio
async def test_bus_memory_bytes():
    class OkClient:
        async def info(self, section):
            assert section == "memory"
            return {"used_memory": 123}

    assert await bus_memory_bytes(OkClient()) == 123

    class MissingClient:
        async def info(self, section):
            return {"total_memory": 456}

    assert await bus_memory_bytes(MissingClient()) is None

    class BadClient:
        async def info(self, section):
            raise RuntimeError("boom")

    assert await bus_memory_bytes(BadClient()) is None


@pytest.mark.asyncio
async def test_report_contains_no_filenames(tmp_path):
    cfg = _archive_config(tmp_path, disk_budget_bytes=600)
    hk = Housekeeper(cfg, today=lambda: "2026-10-20", log_backups=lambda: [])
    root = hk._roots[0]

    for date in ("2026-10-17", "2026-10-18", "2026-10-19", "2026-10-20"):
        _write_file(root / "research_events" / f"research_events-{date}.jsonl")

    report = await hk.run()
    dumped = json.dumps(report, sort_keys=True)
    assert "research_events" not in dumped


@pytest.mark.asyncio
async def test_symlink_named_like_a_daily_file_is_skipped(tmp_path):
    cfg = _archive_config(tmp_path, disk_budget_bytes=100)
    hk = Housekeeper(cfg, today=lambda: "2026-10-20", log_backups=lambda: [])
    root = hk._roots[0]
    real = _write_file(root / "research_events" / "research_events-2026-10-18.jsonl")
    target = _write_file(tmp_path / "state" / "episodic_memory" / "store.jsonl")
    link = root / "research_events" / "research_events-2026-10-17.jsonl"
    os.symlink(target, link)
    assert hk.candidates() == [real]
    report = await hk.run()
    assert report["moved_files"] == 1
    assert link.is_symlink() and target.exists()
