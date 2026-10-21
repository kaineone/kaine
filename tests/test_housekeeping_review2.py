# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Regression tests for the second review of sleep housekeeping.

The following old behaviours are intentionally changed. No existing test
file names are known in the provided context; update any test that relied
on:
  - the memory term being derived from a memory_reader / used_memory,
  - HousekeepingRefused for a vanished/symlink/non-regular/hard-linked file,
  - daily files dated yesterday being candidates,
  - an archive directory being accepted without a mount/device check.
"""

from __future__ import annotations

import os

import pytest

import kaine.modules.sleep.housekeeping as hk
import kaine.storage
from kaine.modules.sleep.housekeeping import (
    FileSkipped,
    Housekeeper,
    HousekeepingConfig,
    housekeeping_lock,
    study_record_roots,
)


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


@pytest.mark.asyncio
async def test_s1_late_append_retry_exports_both_lines(tmp_path, monkeypatch):
    hk_inst = _make_hk(tmp_path, archive_mounted=lambda p: True)
    src = tmp_path / "data" / "evaluation" / "study-2026-10-18.jsonl"
    src.write_text("line1\n")

    appended = False
    real_replace = os.replace

    def replace_once(*args, **kwargs):
        nonlocal appended
        result = real_replace(*args, **kwargs)
        if not appended:
            with open(src, "a", encoding="utf-8") as fh:
                fh.write("line2-late\n")
            appended = True
        return result

    monkeypatch.setattr(hk.os, "replace", replace_once)

    report = await hk_inst.run()
    assert report["moved_files"] == 1

    dest = tmp_path / "archive" / "evaluation" / "study-2026-10-18.jsonl"
    assert dest.exists()
    data = dest.read_bytes()
    assert b"line1\n" in data
    assert b"line2-late\n" in data
    assert not src.exists()


@pytest.mark.asyncio
async def test_s1_every_append_raises_and_keeps_local(tmp_path, monkeypatch):
    hk_inst = _make_hk(tmp_path, archive_mounted=lambda p: True)
    src = tmp_path / "data" / "evaluation" / "study-2026-10-18.jsonl"
    src.write_text("line1\n")

    real_replace = os.replace

    def replace_always(*args, **kwargs):
        result = real_replace(*args, **kwargs)
        with open(src, "a", encoding="utf-8") as fh:
            fh.write("line2-late\n")
        return result

    monkeypatch.setattr(hk.os, "replace", replace_always)

    report = await hk_inst.run()
    assert report["moved_files"] == 0
    assert src.exists()
    data = src.read_bytes()
    assert b"line1\n" in data
    assert b"line2-late\n" in data


@pytest.mark.asyncio
async def test_s2_unmounted_archive_skips_export(tmp_path):
    hk_inst = _make_hk(tmp_path)  # no archive_mounted override
    src = tmp_path / "data" / "evaluation" / "study-2026-10-18.jsonl"
    src.write_text("line1\n")

    report = await hk_inst.run()
    assert report["archive_mounted"] is False
    assert report["archive"] is False
    assert report["moved_files"] == 0
    assert src.exists()


@pytest.mark.asyncio
async def test_s3_vanishing_candidate_skipped(tmp_path, monkeypatch):
    hk_inst = _make_hk(tmp_path, archive_mounted=lambda p: True)
    src1 = tmp_path / "data" / "evaluation" / "first-2026-10-18.jsonl"
    src2 = tmp_path / "data" / "evaluation" / "second-2026-10-18.jsonl"
    src1.write_text("a\n")
    src2.write_text("b\n")

    original_candidates = Housekeeper.candidates

    def vanishing_candidates(self):
        cands = original_candidates(self)
        if cands:
            first = cands[0]
            if first.exists():
                first.unlink()
        return cands

    monkeypatch.setattr(Housekeeper, "candidates", vanishing_candidates)

    report = await hk_inst.run()
    assert report["moved_files"] == 1
    dest = tmp_path / "archive" / "evaluation" / "second-2026-10-18.jsonl"
    assert dest.exists()


@pytest.mark.asyncio
async def test_s4_hard_link_to_state_not_exported(tmp_path):
    hk_inst = _make_hk(tmp_path, archive_mounted=lambda p: True)
    protected_file = tmp_path / "state" / "protected.jsonl"
    protected_file.write_text("shared\n")
    src = tmp_path / "data" / "evaluation" / "study-2026-10-18.jsonl"
    os.link(protected_file, src)

    report = await hk_inst.run()
    assert report["moved_files"] == 0
    assert protected_file.exists()
    assert src.exists()


def test_s7_unlink_vanished_raises_file_skipped(tmp_path):
    missing = tmp_path / "gone.jsonl"
    with pytest.raises(FileSkipped) as exc_info:
        hk._unlink_regular(missing)
    assert issubclass(FileSkipped, OSError)
    assert isinstance(exc_info.value, OSError)


def test_candidate_dates_exclude_today_and_yesterday(tmp_path):
    hk_inst = _make_hk(tmp_path)
    today = tmp_path / "data" / "evaluation" / "study-2026-10-20.jsonl"
    yesterday = tmp_path / "data" / "evaluation" / "study-2026-10-19.jsonl"
    old = tmp_path / "data" / "evaluation" / "study-2026-10-18.jsonl"
    today.write_text("t\n")
    yesterday.write_text("y\n")
    old.write_text("o\n")

    cands = hk_inst.candidates()
    assert today not in cands
    assert yesterday not in cands
    assert old in cands


@pytest.mark.asyncio
async def test_stale_prefix_destination_is_reexported(tmp_path):
    hk_inst = _make_hk(tmp_path, archive_mounted=lambda p: True)
    src = tmp_path / "data" / "evaluation" / "study-2026-10-18.jsonl"
    src.write_text("line1\nline2\nline3\n")

    dest_dir = tmp_path / "archive" / "evaluation"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "study-2026-10-18.jsonl"
    dest.write_text("line1\nline2\n")

    report = await hk_inst.run()
    assert report["moved_files"] == 1
    assert not src.exists()
    assert dest.read_text() == "line1\nline2\nline3\n"


@pytest.mark.asyncio
async def test_failed_temp_write_leaves_no_part(tmp_path, monkeypatch):
    hk_inst = _make_hk(tmp_path, archive_mounted=lambda p: True)
    src = tmp_path / "data" / "evaluation" / "study-2026-10-18.jsonl"
    src.write_bytes(b"x" * (2 * 1024 * 1024 + 1))

    real_write = os.write
    calls = 0

    def flaky_write(fd, data):
        nonlocal calls
        if calls == 0:
            calls += 1
            return real_write(fd, data)
        raise OSError("disk full")

    monkeypatch.setattr(hk.os, "write", flaky_write)

    archive = hk_inst._mounted_archive()
    root = hk_inst._roots[0]
    with pytest.raises(OSError):
        await hk_inst._export_to_archive(src, root, archive)

    parts = list((tmp_path / "archive").rglob("*.part"))
    assert parts == []


def test_study_record_roots_drops_state_and_nested(tmp_path):
    cfg = {
        "evaluation": {
            "paths": {
                "evaluation_logs": "data/evaluation",
                "trajectory_dir": "data/workspace_trajectory",
            }
        },
        "research_event_log": {
            "log_dir": "data/research",
            "external_utterances": {"log_dir": "data/evaluation/external"},
            "dashboard_record": {"log_dir": "state/dashboard"},
            "raw_archive": {"archive_dir": "data/raw_archive"},
        },
    }
    roots = study_record_roots(cfg)
    names = [str(r.relative_to(tmp_path)).replace(os.sep, "/") for r in roots]
    assert names == [
        "data/evaluation",
        "data/workspace_trajectory",
        "data/research",
        "data/raw_archive",
    ]
    assert "data/evaluation/external" not in names
    assert "state/dashboard" not in names


@pytest.mark.asyncio
async def test_lock_held_during_run(tmp_path, monkeypatch):
    hk_inst = _make_hk(tmp_path)
    # Over budget, so the pass lists its candidates while it holds the lock.
    study = tmp_path / "data" / "evaluation" / "research_events" / "research_events-2026-10-01.jsonl"
    study.parent.mkdir(parents=True, exist_ok=True)
    study.write_text("x\n")
    original_candidates = Housekeeper.candidates
    seen = []

    def asserting_candidates(self):
        seen.append(housekeeping_lock().locked())
        return original_candidates(self)

    monkeypatch.setattr(Housekeeper, "candidates", asserting_candidates)
    await hk_inst.run()
    assert seen == [True]
    assert not housekeeping_lock().locked()


@pytest.mark.asyncio
async def test_memory_ignored_and_term_zero(tmp_path):
    async def huge_memory():
        return 10**12

    hk_inst = _make_hk(tmp_path, memory_reader=huge_memory)
    report = await hk_inst.run()
    assert report["memory_bytes"] is None
    assert report["memory_measured"] is False
    assert report["terms"]["memory"] == 0.0
    assert report["pressure"] == report["terms"]["disk"] + report["terms"]["episodic"]
