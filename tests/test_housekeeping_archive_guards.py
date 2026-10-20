# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for layered archive-side guards in housekeeping."""

import asyncio
import hashlib
import os

import pytest

from kaine.modules.sleep.housekeeping import (
    ArchiveRefused,
    Housekeeper,
    HousekeepingConfig,
    HousekeepingRefused,
    _check_archive_path,
    _same_file,
    _sha256,
    _unlink_regular,
)
from kaine.storage import data_root, set_data_root

_STUDY_BYTES = b'{"event": "test"}\n'


@pytest.fixture(autouse=True)
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


def test_check_archive_path_refuses_symlink_component(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    archive = hk._archive
    real = archive / "real"
    real.mkdir(parents=True, exist_ok=True)
    link = archive / "evaluation"
    os.symlink(real, link)
    dest = archive / "evaluation" / "x.jsonl"
    with pytest.raises(ArchiveRefused):
        _check_archive_path(archive, dest)


def test_check_archive_path_refuses_resolving_outside(rooted):
    tmp_path = rooted
    _make_housekeeper(tmp_path)
    _study_file(tmp_path)
    (tmp_path / "archive").mkdir(parents=True, exist_ok=True)
    archive = tmp_path / "archive" / ".." / "archive"
    dest = archive / ".." / "outside" / "x.jsonl"
    with pytest.raises(ArchiveRefused):
        _check_archive_path(archive, dest)


def test_export_refuses_same_file_hard_link(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    src = _study_file(tmp_path)
    root = hk._roots[0]
    archive = hk._archive
    dest = archive / root.name / src.relative_to(root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    os.link(src, dest)
    assert _same_file(src, dest) is True
    other = tmp_path / "other.jsonl"
    other.write_bytes(b"other bytes\n")
    assert _same_file(src, other) is False
    with pytest.raises(ArchiveRefused):
        asyncio.run(hk._export_to_archive(src, root, archive))
    assert src.exists()
    assert src.read_bytes() == _STUDY_BYTES


def test_export_refuses_part_symlink_bypassing_lexists(rooted, monkeypatch):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    src = _study_file(tmp_path)
    root = hk._roots[0]
    archive = hk._archive
    dest = archive / root.name / src.relative_to(root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside.jsonl"
    outside.write_bytes(b"outside bytes\n")
    temp = dest.with_suffix(dest.suffix + ".part")
    os.symlink(outside, temp)
    real_lexists = os.path.lexists

    def fake_lexists(path):
        if os.fspath(path) == os.fspath(temp):
            return False
        return real_lexists(path)

    monkeypatch.setattr(
        "kaine.modules.sleep.housekeeping.os.path.lexists", fake_lexists
    )
    with pytest.raises((OSError, ArchiveRefused)):
        asyncio.run(hk._export_to_archive(src, root, archive))
    assert outside.read_bytes() == b"outside bytes\n"
    assert src.exists()
    assert src.read_bytes() == _STUDY_BYTES


def test_sha256_does_not_follow_symlinks(rooted):
    tmp_path = rooted
    target = tmp_path / "target.jsonl"
    target.write_bytes(b"target bytes\n")
    link = tmp_path / "link.jsonl"
    os.symlink(target, link)
    with pytest.raises(OSError):
        _sha256(link)


def test_unlink_regular_behavior(rooted):
    tmp_path = rooted
    target = tmp_path / "target.jsonl"
    target.write_bytes(b"target bytes\n")
    link = tmp_path / "link.jsonl"
    os.symlink(target, link)
    with pytest.raises(HousekeepingRefused):
        _unlink_regular(link)
    assert target.read_bytes() == b"target bytes\n"
    assert os.path.islink(link)

    directory = tmp_path / "directory"
    directory.mkdir()
    with pytest.raises(HousekeepingRefused):
        _unlink_regular(directory)
    assert directory.is_dir()

    regular = tmp_path / "regular.jsonl"
    regular.write_bytes(b"regular bytes\n")
    size = _unlink_regular(regular)
    assert size == len(b"regular bytes\n")
    assert not regular.exists()


def test_export_refuses_corrupted_replace_reverification(rooted, monkeypatch):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    src = _study_file(tmp_path)
    root = hk._roots[0]
    archive = hk._archive
    real_replace = os.replace

    def corrupting_replace(src_path, dst_path, *, src_dir_fd=None, dst_dir_fd=None):
        real_replace(src_path, dst_path, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)
        with open(dst_path, "wb") as f:
            f.write(b"corrupted bytes\n")

    monkeypatch.setattr(
        "kaine.modules.sleep.housekeeping.os.replace", corrupting_replace
    )
    with pytest.raises(ArchiveRefused):
        asyncio.run(hk._export_to_archive(src, root, archive))
    assert src.exists()
    assert src.read_bytes() == _STUDY_BYTES


def test_delete_uses_lstat_recheck_for_symlink(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    target = tmp_path / "target.jsonl"
    target.write_bytes(b"target bytes\n")
    link = tmp_path / "link.jsonl"
    os.symlink(target, link)
    with pytest.raises(HousekeepingRefused):
        hk._delete(link)
    assert target.read_bytes() == b"target bytes\n"
    assert os.path.islink(link)
