# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for symlink resistance in housekeeping archive export."""

import asyncio
import hashlib
import os
import stat

import pytest

from kaine.modules.sleep.housekeeping import (
    ArchiveRefused,
    Housekeeper,
    HousekeepingConfig,
    HousekeepingRefused,
    _sha256,
)
from kaine.storage import data_root, set_data_root

_STUDY_BYTES = b'{"event": "test"}\n'


@pytest.fixture
def rooted(tmp_path):
    old = data_root()
    set_data_root(tmp_path)
    try:
        yield tmp_path
    finally:
        set_data_root(old)


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_housekeeper(tmp_path):
    # The archive is a volume the operator mounts, so it exists before any export.
    (tmp_path / "archive").mkdir(exist_ok=True)
    return Housekeeper(
        HousekeepingConfig(disk_budget_bytes=1, archive_dir=str(tmp_path / "archive")),
        log_backups=lambda: [],
        today=lambda: "2026-10-20",
    )


def _study_file(tmp_path):
    src = (
        tmp_path
        / "data"
        / "evaluation"
        / "research_events"
        / "research_events-2026-10-01.jsonl"
    )
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_bytes(_STUDY_BYTES)
    return src


def _paths(hk, tmp_path):
    root = hk._roots[0]
    src = root / "research_events" / "research_events-2026-10-01.jsonl"
    archive = hk._archive
    dest = archive / root.name / src.relative_to(root)
    return src, root, archive, dest


def test_export_refuses_dest_symlink_to_src(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    _study_file(tmp_path)
    src, root, archive, dest = _paths(hk, tmp_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src, dest)
    with pytest.raises(ArchiveRefused):
        asyncio.run(hk._export_to_archive(src, root, archive))
    assert src.read_bytes() == _STUDY_BYTES


def test_export_refuses_dest_symlink_to_equal_file(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    _study_file(tmp_path)
    src, root, archive, dest = _paths(hk, tmp_path)
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(_STUDY_BYTES)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(outside, dest)
    with pytest.raises(ArchiveRefused):
        asyncio.run(hk._export_to_archive(src, root, archive))
    assert src.read_bytes() == _STUDY_BYTES
    assert outside.read_bytes() == _STUDY_BYTES


def test_export_refuses_directory_component_symlink(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    _study_file(tmp_path)
    src, root, archive, dest = _paths(hk, tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    archive.mkdir(parents=True, exist_ok=True)
    os.symlink(elsewhere, archive / "evaluation")
    with pytest.raises(ArchiveRefused):
        asyncio.run(hk._export_to_archive(src, root, archive))
    assert src.read_bytes() == _STUDY_BYTES


def test_export_refuses_planted_part_symlink(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    _study_file(tmp_path)
    src, root, archive, dest = _paths(hk, tmp_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(b"planted bytes\n")
    temp = dest.with_suffix(dest.suffix + ".part")
    os.symlink(outside, temp)
    with pytest.raises(ArchiveRefused):
        asyncio.run(hk._export_to_archive(src, root, archive))
    assert src.read_bytes() == _STUDY_BYTES
    assert outside.read_bytes() == b"planted bytes\n"


def test_export_refuses_dest_resolving_outside_archive(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    _study_file(tmp_path)
    src, root, archive, dest = _paths(hk, tmp_path)
    outsidedir = tmp_path / "outsidedir"
    outsidedir.mkdir()
    (archive / "evaluation").mkdir(parents=True)
    os.symlink(outsidedir, archive / "evaluation" / "research_events")
    with pytest.raises(ArchiveRefused):
        asyncio.run(hk._export_to_archive(src, root, archive))
    assert src.read_bytes() == _STUDY_BYTES


def test_export_replaces_leftover_part_file(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    _study_file(tmp_path)
    src, root, archive, dest = _paths(hk, tmp_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_suffix(dest.suffix + ".part")
    temp.write_bytes(b"leftover bytes\n")
    size = asyncio.run(hk._export_to_archive(src, root, archive))
    assert size == len(_STUDY_BYTES)
    assert not src.exists()
    assert dest.exists()
    assert not temp.exists()
    assert stat.S_ISREG(os.lstat(dest).st_mode)
    assert _sha256(dest) == _digest(_STUDY_BYTES)


def test_normal_export_verifies_and_removes_local(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    _study_file(tmp_path)
    src, root, archive, dest = _paths(hk, tmp_path)
    size = asyncio.run(hk._export_to_archive(src, root, archive))
    assert size == len(_STUDY_BYTES)
    assert not src.exists()
    assert dest.exists()
    assert not dest.with_suffix(dest.suffix + ".part").exists()
    assert stat.S_ISREG(os.lstat(dest).st_mode)
    assert _sha256(dest) == _digest(_STUDY_BYTES)


def test_run_keeps_local_file_on_archive_refusal(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    _study_file(tmp_path)
    src, root, archive, dest = _paths(hk, tmp_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src, dest)
    report = asyncio.run(hk.run())
    assert report["moved_files"] == 0
    assert src.read_bytes() == _STUDY_BYTES


def test_archive_copy_verified_false_for_symlink_and_reclaim_leaves_local(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    _study_file(tmp_path)
    src, root, archive, dest = _paths(hk, tmp_path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.symlink(src, dest)
    assert hk._archive_copy_verified(src, root, archive) is False
    result = asyncio.run(hk.reclaim_regenerable(free_bytes=lambda: 0, target_free=1))
    assert result["reclaimed_files"] == 0
    assert result["reclaimed_bytes"] == 0
    assert src.read_bytes() == _STUDY_BYTES


def test_delete_refuses_symlink_and_preserves_target(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    target = tmp_path / "target.jsonl"
    target.write_bytes(b"target bytes\n")
    link = tmp_path / "link.jsonl"
    os.symlink(target, link)
    with pytest.raises(HousekeepingRefused):
        hk._delete(link)
    assert target.read_bytes() == b"target bytes\n"
