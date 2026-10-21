# SPDX-License-Identifier: Apache-2.0

import asyncio
import datetime
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import kaine.modules.sleep.housekeeping
import kaine.storage
from kaine.modules.sleep.housekeeping import (
    Housekeeper,
    HousekeepingConfig,
    _is_mounted_volume,
)


@pytest.fixture(autouse=True)
def _data_root(tmp_path):
    previous = kaine.storage.data_root()
    kaine.storage.set_data_root(tmp_path)
    yield
    kaine.storage.set_data_root(previous)


@pytest.fixture
def bus():
    return MagicMock()


@pytest.mark.parametrize(
    "value",
    [True, False, float("nan"), 0, 1, 1.5],
)
def test_disk_budget_share_rejects_invalid(value):
    with pytest.raises(ValueError, match=r"\[sleep\.housekeeping\] disk_budget_share"):
        HousekeepingConfig.from_section({"disk_budget_share": value})


def test_disk_budget_share_accepts_valid():
    cfg = HousekeepingConfig.from_section({"disk_budget_share": 0.25})
    assert cfg.disk_budget_share == 0.25


@pytest.mark.parametrize("value", [True, 0, -1])
def test_disk_budget_bytes_rejects_invalid(value):
    with pytest.raises(ValueError, match=r"\[sleep\.housekeeping\] disk_budget_bytes"):
        HousekeepingConfig.from_section({"disk_budget_bytes": value})


def test_disk_budget_bytes_accepts_positive_int():
    cfg = HousekeepingConfig.from_section({"disk_budget_bytes": 123})
    assert cfg.disk_budget_bytes == 123


def _fake_usage(total: int):
    def usage(path):
        return SimpleNamespace(total=total)

    return usage


def test_effective_disk_budget_uses_default_share():
    config = HousekeepingConfig()
    root = Path("/data/study")
    hk = Housekeeper(
        config,
        roots=[root],
        disk_usage=_fake_usage(100 * 1024**3),
    )
    assert hk.effective_disk_budget() == int(0.5 * 100 * 1024**3)


def test_effective_disk_budget_uses_explicit_bytes_and_report_flag():
    config = HousekeepingConfig(disk_budget_bytes=123)
    root = Path("/data/study")
    hk = Housekeeper(
        config,
        roots=[root],
        disk_usage=_fake_usage(100 * 1024**3),
    )
    assert hk.effective_disk_budget() == 123
    report = asyncio.run(hk.run())
    assert report["disk_budget_bytes"] == 123
    assert report["disk_budget_explicit"] is True


def test_effective_disk_budget_uses_smallest_root_volume():
    totals = {Path("/data/a"): 200 * 1024**3, Path("/data/b"): 80 * 1024**3}

    def usage(path):
        return SimpleNamespace(total=totals.get(path, 100 * 1024**3))

    config = HousekeepingConfig()
    hk = Housekeeper(
        config,
        roots=[Path("/data/a"), Path("/data/b")],
        disk_usage=usage,
    )
    assert hk.effective_disk_budget() == int(0.5 * 80 * 1024**3)


def test_is_mounted_volume_false_plain_tmp(tmp_path):
    roots = [tmp_path / "root"]
    roots[0].mkdir()
    archive = tmp_path / "archive"
    archive.mkdir()
    assert _is_mounted_volume(archive, roots) is False


def test_is_mounted_volume_false_same_device(monkeypatch, tmp_path):
    roots = [tmp_path / "root"]
    roots[0].mkdir()
    archive = tmp_path / "archive"
    archive.mkdir()
    root_dev = roots[0].stat().st_dev
    real_stat = os.stat

    def fake_stat(path, *args, **kwargs):
        # Compare by text: resolving here would call the patched os.stat again.
        if os.fspath(path) == os.fspath(archive):
            s = real_stat(path, *args, **kwargs)
            return SimpleNamespace(
                st_dev=root_dev,
                st_ino=s.st_ino,
                st_mode=s.st_mode,
            )
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(kaine.modules.sleep.housekeeping.os, "stat", fake_stat)
    monkeypatch.setattr(kaine.modules.sleep.housekeeping.os.path, "ismount", lambda p: True)
    assert _is_mounted_volume(archive, roots) is False


def test_is_mounted_volume_true_different_device(monkeypatch, tmp_path):
    roots = [tmp_path / "root"]
    roots[0].mkdir()
    archive = tmp_path / "archive"
    archive.mkdir()
    root_dev = roots[0].stat().st_dev
    real_stat = os.stat

    def fake_stat(path, *args, **kwargs):
        # Compare by text: resolving here would call the patched os.stat again.
        if os.fspath(path) == os.fspath(archive):
            s = real_stat(path, *args, **kwargs)
            return SimpleNamespace(
                st_dev=root_dev + 1,
                st_ino=s.st_ino,
                st_mode=s.st_mode,
            )
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(kaine.modules.sleep.housekeeping.os, "stat", fake_stat)
    monkeypatch.setattr(kaine.modules.sleep.housekeeping.os.path, "ismount", lambda p: True)
    assert _is_mounted_volume(archive, roots) is True


def test_is_mounted_volume_false_different_device_not_a_mount(monkeypatch, tmp_path):
    # Another device alone is not enough: the archive must also be a mount point.
    roots = [tmp_path / "root"]
    roots[0].mkdir()
    archive = tmp_path / "archive"
    archive.mkdir()
    root_dev = roots[0].stat().st_dev
    real_stat = os.stat

    def fake_stat(path, *args, **kwargs):
        if os.fspath(path) == os.fspath(archive):
            s = real_stat(path, *args, **kwargs)
            return SimpleNamespace(st_dev=root_dev + 1, st_ino=s.st_ino, st_mode=s.st_mode)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(kaine.modules.sleep.housekeeping.os, "stat", fake_stat)
    monkeypatch.setattr(kaine.modules.sleep.housekeeping.os.path, "ismount", lambda p: False)
    assert _is_mounted_volume(archive, roots) is False


def test_default_archive_dir():
    cfg = HousekeepingConfig()
    assert cfg.archive_dir == "/app/archive"


def test_default_archive_missing_means_no_export(tmp_path):
    roots = [tmp_path / "study"]
    roots[0].mkdir()
    config = HousekeepingConfig()
    hk = Housekeeper(
        config,
        roots=roots,
        disk_usage=_fake_usage(100 * 1024**3),
    )
    assert hk._mounted_archive() is None


def test_growth_bytes_per_day_window(tmp_path, monkeypatch):
    root = tmp_path / "study"
    sink = root / "sink"
    sink.mkdir(parents=True)
    base = datetime.date(2024, 1, 15)
    yesterday = base - datetime.timedelta(days=1)
    two_days_ago = base - datetime.timedelta(days=2)
    too_old = base - datetime.timedelta(days=10)
    for date, size in [
        (yesterday, 1000),
        (two_days_ago, 2000),
        (too_old, 5000),
    ]:
        (sink / f"record-{date.isoformat()}.jsonl").write_text("x" * size)

    config = HousekeepingConfig()
    hk = Housekeeper(
        config,
        roots=[root],
        today=lambda: base.isoformat(),
        disk_usage=_fake_usage(100 * 1024**3),
    )
    assert hk.growth_bytes_per_day() == (1000 + 2000) / 2


def test_growth_bytes_per_day_none_when_no_files(tmp_path):
    root = tmp_path / "study"
    root.mkdir()
    config = HousekeepingConfig()
    hk = Housekeeper(
        config,
        roots=[root],
        disk_usage=_fake_usage(100 * 1024**3),
    )
    assert hk.growth_bytes_per_day() is None


def test_days_until_budget_normal(monkeypatch, tmp_path):
    root = tmp_path / "study"
    root.mkdir()
    config = HousekeepingConfig()
    hk = Housekeeper(
        config,
        roots=[root],
        disk_usage=_fake_usage(100 * 1024**3),
    )
    monkeypatch.setattr(hk, "disk_bytes", lambda: 10 * 1024**3)
    monkeypatch.setattr(hk, "growth_bytes_per_day", lambda: 1 * 1024**3)
    assert hk.days_until_budget() == (50 * 1024**3 - 10 * 1024**3) / (1 * 1024**3)


def test_days_until_budget_already_reached(monkeypatch, tmp_path):
    root = tmp_path / "study"
    root.mkdir()
    config = HousekeepingConfig()
    hk = Housekeeper(
        config,
        roots=[root],
        disk_usage=_fake_usage(100 * 1024**3),
    )
    monkeypatch.setattr(hk, "disk_bytes", lambda: 60 * 1024**3)
    monkeypatch.setattr(hk, "growth_bytes_per_day", lambda: 1 * 1024**3)
    assert hk.days_until_budget() == 0.0


def test_days_until_budget_unknown_when_no_growth(monkeypatch, tmp_path):
    root = tmp_path / "study"
    root.mkdir()
    config = HousekeepingConfig()
    hk = Housekeeper(
        config,
        roots=[root],
        disk_usage=_fake_usage(100 * 1024**3),
    )
    monkeypatch.setattr(hk, "growth_bytes_per_day", lambda: None)
    assert hk.days_until_budget() is None

    monkeypatch.setattr(hk, "growth_bytes_per_day", lambda: 0.0)
    assert hk.days_until_budget() is None


def test_disk_excess_uses_effective_budget(monkeypatch, tmp_path):
    root = tmp_path / "study"
    root.mkdir()
    config = HousekeepingConfig()
    hk = Housekeeper(
        config,
        roots=[root],
        disk_usage=_fake_usage(100 * 1024**3),
    )
    monkeypatch.setattr(hk, "disk_bytes", lambda: 60 * 1024**3)
    expected = max(0.0, 60 * 1024**3 / (50 * 1024**3) - 1.0)
    assert hk.disk_excess() == expected


def test_make_sleep_logs_projection_notice(tmp_path, monkeypatch, caplog, bus):
    monkeypatch.setattr(
        kaine.modules.sleep.housekeeping,
        "bus_memory_bytes",
        lambda client: 0,
    )
    study_root = tmp_path / "study"
    sink = study_root / "sink"
    sink.mkdir(parents=True)
    yesterday = datetime.datetime.now(datetime.timezone.utc).date() - datetime.timedelta(days=1)
    (sink / f"record-{yesterday.isoformat()}.jsonl").write_text("x" * 1024)
    monkeypatch.setattr(
        kaine.modules.sleep.housekeeping,
        "study_record_roots",
        lambda cfg: [study_root],
    )

    from kaine.boot.factories.sleep import make_sleep

    with caplog.at_level(logging.WARNING, logger="kaine.boot.factories.sleep"):
        make_sleep(bus, {})

    assert "sleep housekeeping: no archive volume is mounted" in caplog.text
    assert "about" in caplog.text
    assert "days" in caplog.text


def test_make_sleep_logs_unknown_projection(tmp_path, monkeypatch, caplog, bus):
    monkeypatch.setattr(
        kaine.modules.sleep.housekeeping,
        "bus_memory_bytes",
        lambda client: 0,
    )
    study_root = tmp_path / "study"
    study_root.mkdir()
    monkeypatch.setattr(
        kaine.modules.sleep.housekeeping,
        "study_record_roots",
        lambda cfg: [study_root],
    )

    from kaine.boot.factories.sleep import make_sleep

    with caplog.at_level(logging.WARNING, logger="kaine.boot.factories.sleep"):
        make_sleep(bus, {})

    assert "sleep housekeeping: no archive volume is mounted" in caplog.text
    assert "unknown" in caplog.text
