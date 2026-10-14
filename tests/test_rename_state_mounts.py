# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for rename_state mount-point and vacant-directory handling."""

from pathlib import Path

import pytest

from kaine import legacy_names
from kaine.lifecycle import rename_state


@pytest.fixture(autouse=True)
def _persisted_done(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "done")


OLD = {e["new_key"]: k for k, e in legacy_names.MODULES.items() if e["new_key"] != k}


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _snapshot(root: Path):
    root = Path(root)
    files: dict[str, bytes] = {}
    dirs: set[str] = set()
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        key = str(rel).replace("\\", "/")
        if key.split("/")[0] == ".rename_state":
            continue
        if path.is_dir():
            dirs.add(key)
        else:
            files[key] = path.read_bytes()
    return files, dirs


def _mount_checker(monkeypatch):
    mounts: set[Path] = set()

    def is_mount(p):
        try:
            return Path(p).resolve() in mounts
        except (OSError, ValueError):
            return False

    monkeypatch.setattr(rename_state, "_is_mount", is_mount)
    return mounts


def _make_compose(root: Path, mounts: set[Path]) -> tuple[dict[str, bytes], set[str]]:
    root = Path(root)
    old_sleep = OLD["sleep"]
    old_locus = OLD["perceptual_locus"]
    _write(root / old_sleep / "organ_window.json", b"window")
    _write(root / old_sleep / "adapters" / "a.gguf", b"adapter")
    (root / old_sleep / "voice_align_jobs").mkdir(parents=True)
    (root / "sleep" / "voice_align_jobs").mkdir(parents=True)
    _write(root / "sleep" / "voice_align_jobs" / "jobs.json", b'{"jobs":1}')
    (root / old_locus).mkdir(parents=True)
    (root / "perceptual_locus").mkdir(parents=True)
    mounts.add((root / "sleep" / "voice_align_jobs").resolve())
    mounts.add((root / "perceptual_locus").resolve())
    return _snapshot(root)


def _make_quadlet(root: Path, mounts: set[Path]) -> tuple[dict[str, bytes], set[str]]:
    root = Path(root)
    old_sleep = OLD["sleep"]
    old_locus = OLD["perceptual_locus"]
    _write(root / old_sleep / "organ_window.json", b"window")
    _write(root / old_sleep / "adapters" / "a.gguf", b"adapter")
    (root / old_locus).mkdir(parents=True)
    (root / "perceptual_locus").mkdir(parents=True)
    mounts.add((root / "perceptual_locus").resolve())
    return _snapshot(root)


def _interrupting(monkeypatch, name, k, *, after_work):
    original = getattr(rename_state, name)
    calls = 0

    def wrapper(root, step, qdrant):
        nonlocal calls
        if calls == k:
            calls += 1
            if not after_work:
                raise KeyboardInterrupt
            original(root, step, qdrant)
            raise KeyboardInterrupt
        calls += 1
        return original(root, step, qdrant)

    monkeypatch.setattr(rename_state, name, wrapper)
    return lambda: monkeypatch.setattr(rename_state, name, original)


@pytest.fixture(params=["compose", "quadlet"])
def layout(request, tmp_path, monkeypatch):
    root = tmp_path / "state"
    mounts = _mount_checker(monkeypatch)
    if request.param == "compose":
        _make_compose(root, mounts)
    else:
        _make_quadlet(root, mounts)
    return root, request.param


def test_migration_success(layout):
    root, name = layout
    result = rename_state.migrate(root, no_qdrant=True)
    assert result.status == "migrated"
    files, dirs = _snapshot(root)
    assert files["sleep/organ_window.json"] == b"window"
    assert files["sleep/adapters/a.gguf"] == b"adapter"
    if name == "compose":
        assert files["sleep/voice_align_jobs/jobs.json"] == b'{"jobs":1}'
    else:
        assert "sleep/voice_align_jobs/jobs.json" not in files
    assert OLD["sleep"] not in dirs
    assert not any(d.startswith(OLD["sleep"] + "/") for d in dirs)
    assert OLD["perceptual_locus"] not in dirs
    assert not any(d.startswith(OLD["perceptual_locus"] + "/") for d in dirs)


def test_empty_old_locus_beside_plain_new_removed(tmp_path, monkeypatch):
    root = tmp_path / "state"
    old_locus = OLD["perceptual_locus"]
    (root / old_locus).mkdir(parents=True)
    (root / "perceptual_locus").mkdir(parents=True)
    result = rename_state.migrate(root, no_qdrant=True)
    assert result.status == "migrated"
    _files, dirs = _snapshot(root)
    assert old_locus not in dirs
    assert "perceptual_locus" in dirs


def test_undeletable_old_locus_leftover_is_noop_on_second_run(tmp_path, monkeypatch):
    root = tmp_path / "state"
    old_locus = OLD["perceptual_locus"]
    (root / old_locus).mkdir(parents=True)
    (root / "perceptual_locus").mkdir(parents=True)
    _write(root / OLD["sleep"] / "organ_window.json", b"window")
    mounts = _mount_checker(monkeypatch)
    mounts.add((root / old_locus).resolve())
    result = rename_state.migrate(root, no_qdrant=True)
    assert result.status == "migrated"
    before_files, before_dirs = _snapshot(root)
    assert old_locus in before_dirs
    result2 = rename_state.migrate(root, no_qdrant=True)
    assert result2.status == "noop"
    assert _snapshot(root) == (before_files, before_dirs)


def test_real_content_both_sides_raises_and_leaves_tree(tmp_path, monkeypatch):
    root = tmp_path / "state"
    _write(root / OLD["sleep"] / "organ_window.json", b"window")
    _write(root / "sleep" / "other.json", b"other")
    before = _snapshot(root)
    with pytest.raises(rename_state.RenameStateError):
        rename_state.migrate(root, no_qdrant=True)
    after = _snapshot(root)
    assert after == before
    assert not (root / ".rename_state").exists()


@pytest.mark.parametrize("layout_name", ["compose", "quadlet"])
@pytest.mark.parametrize("after_work", [False, True])
@pytest.mark.parametrize("k", range(8))
def test_crash_resume(tmp_path, monkeypatch, layout_name, after_work, k):
    make = _make_compose if layout_name == "compose" else _make_quadlet
    root = tmp_path / "state"
    mounts = _mount_checker(monkeypatch)
    make(root, mounts)
    n = len(rename_state.plan(root, qdrant=None))
    if k >= n:
        pytest.skip(f"{layout_name} plan has {n} steps")

    fresh = tmp_path / "fresh"
    make(fresh, mounts)
    rename_state.migrate(fresh, no_qdrant=True)
    expected = _snapshot(fresh)

    restore = _interrupting(monkeypatch, "_run_step", k, after_work=after_work)
    with pytest.raises(KeyboardInterrupt):
        rename_state.migrate(root, no_qdrant=True)
    restore()

    result = rename_state.migrate(root, no_qdrant=True)
    assert result.status == "resumed"
    assert _snapshot(root) == expected


def test_revert_after_merge(tmp_path, monkeypatch):
    root = tmp_path / "state"
    mounts = _mount_checker(monkeypatch)
    before = _make_compose(root, mounts)
    rename_state.migrate(root, no_qdrant=True)
    result = rename_state.revert(root)
    assert result.status == "reverted"
    assert not (root / ".rename_state").exists()
    assert _snapshot(root) == before


def test_a_mount_point_inside_the_old_directory_is_refused(tmp_path, monkeypatch):
    """A mount under the old directory cannot be moved; the operator remounts it."""
    root = tmp_path / "state"
    mounts = _mount_checker(monkeypatch)
    _write(root / OLD["sleep"] / "organ_window.json", b"window")
    _write(root / OLD["sleep"] / "adapters" / "a.gguf", b"adapter")
    mounts.add((root / OLD["sleep"] / "adapters").resolve())
    (root / "sleep" / "voice_align_jobs").mkdir(parents=True)
    mounts.add((root / "sleep" / "voice_align_jobs").resolve())
    before = _snapshot(root)
    with pytest.raises(rename_state.RenameStateError, match="mount holding data"):
        rename_state.migrate(root, no_qdrant=True)
    assert _snapshot(root) == before


def test_a_bind_mount_from_the_same_filesystem_counts_as_a_mount(tmp_path, monkeypatch):
    """Container runtimes bind-mount named volumes from the same filesystem, which
    os.path.ismount does not see; the mount table does."""
    volume = tmp_path / "state" / "sleep" / "voice_align_jobs"
    volume.mkdir(parents=True)
    plain = tmp_path / "state" / "sleep" / "plain"
    plain.mkdir()
    monkeypatch.setattr(rename_state, "_mountinfo_points", lambda: {str(volume.resolve())})
    assert rename_state._detect_mount(volume)
    assert not rename_state._detect_mount(plain)


def test_an_old_directory_that_is_itself_a_mount_point_is_refused(tmp_path, monkeypatch):
    root = tmp_path / "state"
    mounts = _mount_checker(monkeypatch)
    _write(root / OLD["sleep"] / "organ_window.json", b"window")
    mounts.add((root / OLD["sleep"]).resolve())
    before = _snapshot(root)
    with pytest.raises(rename_state.RenameStateError, match="mount holding data"):
        rename_state.migrate(root, no_qdrant=True)
    assert _snapshot(root) == before


def _refuses_unchanged(root):
    before = _snapshot(root)
    with pytest.raises(rename_state.RenameStateError, match="mount holding data"):
        rename_state.migrate(root, no_qdrant=True)
    assert _snapshot(root) == before
    assert not (root / ".rename_state").exists()


def test_an_old_store_mount_holding_data_beside_an_empty_new_directory_refuses(tmp_path, monkeypatch):
    """(a) An old episodic memory directory that is a mount holding the database."""
    root = tmp_path / "state"
    mounts = _mount_checker(monkeypatch)
    old_store = root / OLD["episodic_memory"]
    _write(old_store / "memory.db", b"SQLite format 3\x00 rows")
    mounts.add(old_store.resolve())
    (root / "episodic_memory").mkdir(parents=True)
    _refuses_unchanged(root)


def test_an_old_adapters_mount_holding_data_beside_an_empty_new_directory_refuses(tmp_path, monkeypatch):
    """(b) An old adapters mount with data beside an empty new sleep directory."""
    root = tmp_path / "state"
    mounts = _mount_checker(monkeypatch)
    _write(root / OLD["sleep"] / "adapters" / "a.gguf", b"adapter")
    mounts.add((root / OLD["sleep"] / "adapters").resolve())
    (root / "sleep").mkdir(parents=True)
    _refuses_unchanged(root)


def test_an_old_jobs_mount_holding_data_beside_a_new_directory_with_data_refuses(tmp_path, monkeypatch):
    """(c) An old voice-alignment jobs mount with jobs beside a new sleep directory with data."""
    root = tmp_path / "state"
    mounts = _mount_checker(monkeypatch)
    _write(root / OLD["sleep"] / "voice_align_jobs" / "job1.json", b"{}")
    mounts.add((root / OLD["sleep"] / "voice_align_jobs").resolve())
    _write(root / "sleep" / "organ_window.json", b"window")
    before = _snapshot(root)
    with pytest.raises(rename_state.RenameStateError):
        rename_state.migrate(root, no_qdrant=True)
    assert _snapshot(root) == before


def test_an_old_jobs_mount_holding_data_is_refused_without_a_new_directory(tmp_path, monkeypatch):
    """A plain rename would carry the mount to the new path for one boot only."""
    root = tmp_path / "state"
    mounts = _mount_checker(monkeypatch)
    _write(root / OLD["sleep"] / "organ_window.json", b"window")
    _write(root / OLD["sleep"] / "voice_align_jobs" / "job1.json", b"{}")
    mounts.add((root / OLD["sleep"] / "voice_align_jobs").resolve())
    _refuses_unchanged(root)


def test_an_empty_old_mount_point_is_still_vacant(tmp_path, monkeypatch):
    root = tmp_path / "state"
    mounts = _mount_checker(monkeypatch)
    _write(root / OLD["sleep"] / "organ_window.json", b"window")
    (root / OLD["sleep"] / "voice_align_jobs").mkdir(parents=True)
    mounts.add((root / OLD["sleep"] / "voice_align_jobs").resolve())
    (root / "sleep" / "voice_align_jobs").mkdir(parents=True)
    mounts.add((root / "sleep" / "voice_align_jobs").resolve())
    result = rename_state.migrate(root, no_qdrant=True)
    assert result.status == "migrated"
    files, _dirs = _snapshot(root)
    assert files["sleep/organ_window.json"] == b"window"


def test_a_removal_that_meets_data_refuses_and_leaves_the_manifest_in_progress(tmp_path, monkeypatch):
    """Data that appears in an old directory between planning and removal stops the run."""
    import json

    root = tmp_path / "state"
    _mount_checker(monkeypatch)
    (root / OLD["perceptual_locus"]).mkdir(parents=True)
    (root / "perceptual_locus").mkdir(parents=True)
    original = rename_state._run_step

    def write_then_run(r, step, qdrant):
        if step["kind"] == "remove_vacant":
            _write(root / OLD["perceptual_locus"] / "late.json", b"late")
        return original(r, step, qdrant)

    monkeypatch.setattr(rename_state, "_run_step", write_then_run)
    with pytest.raises(rename_state.RenameStateError, match="holds data"):
        rename_state.migrate(root, no_qdrant=True)
    assert (root / OLD["perceptual_locus"] / "late.json").read_bytes() == b"late"
    manifest = json.loads((root / ".rename_state" / "manifest.json").read_text())
    assert manifest["status"] == "in_progress"


def test_the_mount_table_parser_unescapes_spaces(monkeypatch):
    import io

    line = "36 35 98:0 /src /mnt/state\\040dir rw,relatime - ext4 /dev/root rw\n"
    monkeypatch.setattr("builtins.open", lambda *a, **k: io.StringIO(line))
    assert rename_state._mountinfo_points() == {"/mnt/state dir"}


def test_a_removal_that_cannot_remove_an_empty_directory_refuses(tmp_path, monkeypatch):
    import errno
    import os

    root = tmp_path / "state"
    _mount_checker(monkeypatch)
    (root / OLD["perceptual_locus"]).mkdir(parents=True)
    (root / "perceptual_locus").mkdir(parents=True)

    def refuse_rmdir(path, *args, **kwargs):
        raise PermissionError(errno.EPERM, "Operation not permitted", str(path))

    monkeypatch.setattr(os, "rmdir", refuse_rmdir)
    with pytest.raises(rename_state.RenameStateError, match="cannot remove"):
        rename_state.migrate(root, no_qdrant=True)
    assert (root / OLD["perceptual_locus"]).is_dir()


def test_a_deeper_mount_holding_data_refuses_a_merge(tmp_path, monkeypatch):
    """A merge would move a child directory and carry a mount below it."""
    root = tmp_path / "state"
    mounts = _mount_checker(monkeypatch)
    _write(root / OLD["sleep"] / "organ_window.json", b"window")
    _write(root / OLD["sleep"] / "voice_align_jobs" / "sub" / "job1.json", b"{}")
    mounts.add((root / OLD["sleep"] / "voice_align_jobs" / "sub").resolve())
    (root / "sleep").mkdir(parents=True)
    _refuses_unchanged(root)
