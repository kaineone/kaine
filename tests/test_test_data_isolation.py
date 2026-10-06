# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import os
from pathlib import Path

import pytest

from tests.conftest import (
    _REAL_ROOT_SKIP,
    _REAL_ROOT_SKIP_PREFIXES,
    _STATE_SKIP,
    _changed_dirs,
    _fingerprint,
)


def _data_root_fingerprint(root: str):
    """Fingerprint a real KAINE data root using its skip lists."""
    return _fingerprint(
        root,
        skip_names=_STATE_SKIP,
        full_skip_names=_REAL_ROOT_SKIP,
        full_skip_prefixes=_REAL_ROOT_SKIP_PREFIXES,
    )


def test_list_filesystems_default_is_empty():
    """The autouse fixture empties MOUNTS_PATH, so default discovery sees no disks."""
    from kaine.setup.storage_step import list_filesystems

    assert list_filesystems() == []


def test_changed_dirs_reports_modified_subdir(tmp_path):
    """The guard comparison helper surfaces a directory that gained a file."""
    state = tmp_path / "real" / "state"
    subdir = state / "subdir"
    subdir.mkdir(parents=True)

    before = _fingerprint(str(state), skip_names=_STATE_SKIP)
    (subdir / "file.txt").write_text("hello")
    after = _fingerprint(str(state), skip_names=_STATE_SKIP)

    changed = _changed_dirs(before, after)
    assert str(subdir) in changed
    assert str(subdir / "file.txt") in changed


def test_changed_dirs_reports_appended_file(tmp_path):
    """Appending to an existing file changes its size/mtime and is reported (F1)."""
    state = tmp_path / "real" / "state"
    subdir = state / "subdir"
    subdir.mkdir(parents=True)
    target = subdir / "file.txt"
    target.write_text("hello")

    before = _fingerprint(str(state), skip_names=_STATE_SKIP)
    with open(target, "a") as f:
        f.write("more")
    after = _fingerprint(str(state), skip_names=_STATE_SKIP)

    changed = _changed_dirs(before, after)
    assert str(target) in changed


def test_changed_dirs_reports_mtime_change_same_size(tmp_path):
    """Rewriting an existing file with the same length but a new mtime is reported (F1)."""
    state = tmp_path / "real" / "state"
    subdir = state / "subdir"
    subdir.mkdir(parents=True)
    target = subdir / "file.txt"
    target.write_text("1234567890")

    before = _fingerprint(str(state), skip_names=_STATE_SKIP)
    target.write_text("0987654321")
    # Force a distinct mtime so the change is detectable even if the clock
    # did not advance between the two snapshots.
    os.utime(target, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
    after = _fingerprint(str(state), skip_names=_STATE_SKIP)

    changed = _changed_dirs(before, after)
    assert str(target) in changed


def test_changed_dirs_reports_file_outside_state(tmp_path):
    """The real-root guard watches the whole data root, not only state/ (F2)."""
    root = tmp_path / "real"
    (root / "state").mkdir(parents=True)
    backups = root / "backups"
    backups.mkdir()

    before = _data_root_fingerprint(str(root))
    (backups / "bundle.tar").write_text("data")
    after = _data_root_fingerprint(str(root))

    changed = _changed_dirs(before, after)
    assert str(backups / "bundle.tar") in changed


def test_changed_dirs_ignores_fully_skipped_archive_dirs(tmp_path):
    """_archive* directories at the top of state/ are fully skipped."""
    state = tmp_path / "real" / "state"
    for name in ("_archive_x", "kept"):
        (state / name).mkdir(parents=True)

    before = _fingerprint(str(state), skip_names=_STATE_SKIP)
    (state / "_archive_x" / "file.txt").write_text("x")
    (state / "kept" / "file.txt").write_text("y")
    after = _fingerprint(str(state), skip_names=_STATE_SKIP)

    changed = _changed_dirs(before, after)
    assert str(state / "_archive_x" / "file.txt") not in changed
    assert str(state / "kept" / "file.txt") in changed


def test_fork_shallow_watch(tmp_path):
    """state/forks/ is watched at its top level but its contents are not walked (F3)."""
    root = tmp_path / "real"
    state = root / "state"
    forks = state / "forks"
    being_a = forks / "beingA"
    being_a.mkdir(parents=True)
    (being_a / "inner.json").write_text("{}")

    # Creating a new being is visible through the forks directory and the new key.
    before = _data_root_fingerprint(str(root))
    (forks / "beingB").mkdir()
    after = _data_root_fingerprint(str(root))
    changed = _changed_dirs(before, after)
    assert str(forks / "beingB") in changed

    # A write deep inside an existing fork is not walked into.
    before2 = _data_root_fingerprint(str(root))
    deep = being_a / "x" / "y.json"
    deep.parent.mkdir()
    deep.write_text("[]")
    after2 = _data_root_fingerprint(str(root))

    assert not any("beingA/x" in p for p in after2)
    assert str(deep) not in after2
    # ...but the being itself is seen to change (its own mtime moved), so a
    # write into a preserved being is still caught without reading it.
    assert str(being_a) in _changed_dirs(before2, after2)


def test_real_root_skip_ignores_operator_dirs(tmp_path):
    """Operator tooling/cache directories at the real root top are fully skipped."""
    root = tmp_path / "real"
    for name in ("models", "k1jevfoo", "data", "state"):
        (root / name).mkdir(parents=True)

    before = _data_root_fingerprint(str(root))
    (root / "models" / "x.txt").write_text("x")
    (root / "k1jevfoo" / "y.txt").write_text("y")
    (root / "data" / "watched.txt").write_text("z")
    after = _data_root_fingerprint(str(root))

    changed = _changed_dirs(before, after)
    assert str(root / "models" / "x.txt") not in changed
    assert str(root / "k1jevfoo" / "y.txt") not in changed
    assert str(root / "data" / "watched.txt") in changed


def test_guard_ignores_patched_os_functions(tmp_path, monkeypatch):
    """Directory and file stats are read through import-time real OS primitives, not
    patched module attributes.
    """
    from tests.conftest import _fingerprint

    state = tmp_path / "real" / "state"
    subdir = state / "subdir"
    subdir.mkdir(parents=True)

    before = _fingerprint(str(state), skip_names=frozenset())

    def broken_stat(*args, **kwargs):
        raise OSError("patched stat")

    def broken_scandir(*args, **kwargs):
        raise OSError("patched scandir")

    monkeypatch.setattr(os, "stat", broken_stat)
    monkeypatch.setattr(os, "scandir", broken_scandir)

    after = _fingerprint(str(state), skip_names=frozenset())

    assert _changed_dirs(before, after) == []


@pytest.mark.real_mounts
def test_real_mounts_marker_leaves_mounts_path_default():
    """A test that needs the real mount table must opt out of the autouse patch."""
    from kaine.setup.storage_step import MOUNTS_PATH

    assert MOUNTS_PATH == Path("/proc/mounts")
