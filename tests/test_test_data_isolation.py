# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os
from pathlib import Path

import pytest


def test_list_filesystems_default_is_empty():
    """The autouse fixture empties MOUNTS_PATH, so default discovery sees no disks."""
    from kaine.setup.storage_step import list_filesystems

    assert list_filesystems() == []


def test_changed_dirs_reports_modified_subdir(tmp_path):
    """The guard comparison helper surfaces a directory that gained a file."""
    from tests.conftest import _changed_dirs, _state_fingerprint

    state = tmp_path / "real" / "state"
    subdir = state / "subdir"
    subdir.mkdir(parents=True)

    before = _state_fingerprint(str(state))
    (subdir / "file.txt").write_text("hello")
    after = _state_fingerprint(str(state))

    changed = _changed_dirs(before, after)
    assert str(subdir) in changed


def test_changed_dirs_ignores_skipped_top_level_dirs(tmp_path):
    """forks, models and _archive* at the top level are not watched."""
    from tests.conftest import _changed_dirs, _state_fingerprint

    state = tmp_path / "real" / "state"
    for name in ("forks", "models", "_archive_x", "kept"):
        (state / name).mkdir(parents=True)

    before = _state_fingerprint(str(state))
    for name in ("forks", "models", "_archive_x"):
        (state / name / "file.txt").write_text("x")
    after = _state_fingerprint(str(state))

    changed = _changed_dirs(before, after)
    assert changed == []


def test_guard_ignores_patched_os_functions(tmp_path, monkeypatch):
    """Directory mtimes are read through import-time real OS primitives, not
    patched module attributes.
    """
    from tests.conftest import _changed_dirs, _state_fingerprint

    state = tmp_path / "real" / "state"
    subdir = state / "subdir"
    subdir.mkdir(parents=True)

    before = _state_fingerprint(str(state))

    def broken_stat(*args, **kwargs):
        raise OSError("patched stat")

    def broken_scandir(*args, **kwargs):
        raise OSError("patched scandir")

    monkeypatch.setattr(os, "stat", broken_stat)
    monkeypatch.setattr(os, "scandir", broken_scandir)

    after = _state_fingerprint(str(state))

    assert _changed_dirs(before, after) == []


@pytest.mark.real_mounts
def test_real_mounts_marker_leaves_mounts_path_default():
    """A test that needs the real mount table must opt out of the autouse patch."""
    from kaine.setup.storage_step import MOUNTS_PATH

    assert MOUNTS_PATH == Path("/proc/mounts")
