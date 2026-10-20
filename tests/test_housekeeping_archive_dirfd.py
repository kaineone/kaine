# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for archive export using directory descriptors (dir_fd)."""

import asyncio
import hashlib
import os
import stat
from pathlib import PurePath

import pytest

import kaine.modules.sleep.housekeeping as housekeeping_module
from kaine.modules.sleep.housekeeping import (
    ArchiveRefused,
    Housekeeper,
    HousekeepingConfig,
    _open_archive_dir,
    _sha256,
)
from kaine.storage import data_root, set_data_root


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
        today=lambda: "2026-10-21",
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


def test_export_race_directory_swapped_to_symlink_refused(rooted, monkeypatch):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    src = _study_file(tmp_path)
    _, root, archive, dest = _paths(hk, tmp_path)
    parent = dest.parent
    parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()

    swapped = False

    def race_wrapper(_archive, _dest):
        nonlocal swapped
        if not swapped:
            swapped = True
            real = parent.with_name(parent.name + ".real")
            os.rename(parent, real)
            os.symlink(outside, parent)

    monkeypatch.setattr(
        "kaine.modules.sleep.housekeeping._check_archive_path",
        race_wrapper,
    )

    with pytest.raises((ArchiveRefused, OSError)):
        asyncio.run(hk._export_to_archive(src, root, archive))

    assert src.exists()
    assert src.read_bytes() == _STUDY_BYTES
    assert list(outside.iterdir()) == []


def test_open_archive_dir_refuses_symlinked_component(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    archive = hk._archive
    archive.mkdir(exist_ok=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (archive / "evaluation").mkdir()
    os.symlink(outside, archive / "evaluation" / "research_events")
    with pytest.raises(ArchiveRefused):
        fd = _open_archive_dir(archive, PurePath("evaluation/research_events"))
        os.close(fd)


def test_normal_export_via_dirfd_verifies_and_removes_local(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    src = _study_file(tmp_path)
    _, root, archive, dest = _paths(hk, tmp_path)
    src_stat = os.lstat(src)

    size = asyncio.run(hk._export_to_archive(src, root, archive))

    assert size == len(_STUDY_BYTES)
    assert not src.exists()
    assert dest.exists()
    assert not dest.with_suffix(dest.suffix + ".part").exists()
    assert stat.S_ISREG(os.lstat(dest).st_mode)
    assert _sha256(dest) == _digest(_STUDY_BYTES)
    dest_stat = os.lstat(dest)
    assert (dest_stat.st_mode & 0o777) == (src_stat.st_mode & 0o777)
    assert dest_stat.st_mtime_ns == src_stat.st_mtime_ns


def test_export_creates_missing_directories_with_mode_700(rooted):
    tmp_path = rooted
    hk = _make_housekeeper(tmp_path)
    src = _study_file(tmp_path)
    _, root, archive, dest = _paths(hk, tmp_path)
    old_umask = os.umask(0)
    try:
        asyncio.run(hk._export_to_archive(src, root, archive))
        for part in (archive / "evaluation", archive / "evaluation" / "research_events"):
            st = os.lstat(part)
            assert stat.S_ISDIR(st.st_mode)
            assert (st.st_mode & 0o777) == 0o700
    finally:
        os.umask(old_umask)

    assert not src.exists()
    assert dest.exists()
    assert stat.S_ISREG(os.lstat(dest).st_mode)
