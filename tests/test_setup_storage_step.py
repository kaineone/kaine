# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import shutil
from collections import namedtuple
from pathlib import Path

import pytest

from kaine.setup.steps import StepContext
from kaine.setup.storage_step import (
    GROWING_VOLUMES,
    existing_volumes,
    free_gb_at,
    list_filesystems,
    recommend_root,
    relocate,
    relocation_step,
    render_volume_override,
    storage_step,
    write_volume_override,
)

Usage = namedtuple("Usage", ["total", "used", "free"])
GB = 1024**3


@pytest.fixture(autouse=True)
def _no_real_cycle(monkeypatch):
    # relocate() refuses while a KAINE cycle runs; these tests must not depend
    # on what is running on the host.
    monkeypatch.setattr("kaine.setup.storage_step.cycle_process_running", lambda: False)


def _write(path, text):
    """Write *text* to *path*, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)



def test_list_filesystems_filters_and_decodes(tmp_path):
    mounts = tmp_path / "mounts"
    mounts.write_text(
        "/dev/sda1 / ext4 rw 0 0\n"
        "/dev/sdb1 /mnt/data ext4 rw 0 0\n"
        "tmpfs /tmp tmpfs rw 0 0\n"
        "proc /proc proc rw 0 0\n"
        "/dev/loop0 /snap/x squashfs ro 0 0\n"
        "proc /proc/foo\\040bar proc rw 0 0\n"
    )

    def fake_disk_usage(path):
        p = str(path)
        if p == "/":
            return Usage(total=100 * GB, used=30 * GB, free=70 * GB)
        if p == "/mnt/data":
            return Usage(total=200 * GB, used=40 * GB, free=160 * GB)
        raise OSError("unknown mount")

    rows = list_filesystems(mounts_path=mounts, disk_usage=fake_disk_usage)
    assert len(rows) == 2

    root = next(r for r in rows if r["mount"] == "/")
    assert root["is_system"]
    assert root["free_gb"] == 70.0
    assert root["total_gb"] == 100.0

    data = next(r for r in rows if r["mount"] == "/mnt/data")
    assert not data["is_system"]
    assert data["free_gb"] == 160.0
    assert data["total_gb"] == 200.0


def test_recommend_root_prefers_larger_data_drive():
    filesystems = [
        {"mount": "/", "free_gb": 10.0, "is_system": True},
        {"mount": "/mnt/data", "free_gb": 50.0, "is_system": False},
    ]
    assert recommend_root(filesystems) == "/mnt/data/kaine"


def test_recommend_root_returns_none_when_system_is_larger():
    filesystems = [
        {"mount": "/", "free_gb": 100.0, "is_system": True},
        {"mount": "/mnt/data", "free_gb": 50.0, "is_system": False},
    ]
    assert recommend_root(filesystems) is None


def test_storage_field_validation(monkeypatch):
    ctx = StepContext(config={}, host={}, extra={"min_free_gb": 10.0})
    field = storage_step.fields(ctx)[0]

    assert field.validate("") is None
    assert field.validate(None) is None

    err = field.validate("relative/path")
    assert err is not None
    assert "must be absolute" in err

    monkeypatch.setattr("kaine.setup.storage_step.free_gb_at", lambda _p: 5.0)
    err = field.validate("/data")
    assert err is not None
    assert "only 5.0 GB free" in err
    assert "at least 10 GB" in err

    monkeypatch.setattr("kaine.setup.storage_step.free_gb_at", lambda _p: 30.0)
    assert field.validate("/data") is None


def test_free_gb_at_finds_existing_ancestor(tmp_path):
    missing = tmp_path / "does" / "not" / "exist"
    usage = Usage(total=100 * GB, used=10 * GB, free=90 * GB)

    def fake_disk_usage(path):
        assert Path(path).resolve() == tmp_path.resolve()
        return usage

    assert free_gb_at(missing, disk_usage=fake_disk_usage) == 90.0


def test_relocate_copies_verifies_and_keeps_original(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    _write(old / "state" / "a.txt", "alpha")
    _write(old / "data" / "b.txt", "beta")

    ok, msg = relocate(old, new, out=lambda _s: None)
    assert ok is True
    assert (new / "state" / "a.txt").read_text() == "alpha"
    assert (new / "data" / "b.txt").read_text() == "beta"
    assert (old / "state" / "a.txt").exists()
    assert "copied and verified" in msg


def test_relocate_refuses_non_empty_target(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    _write(old / "state" / "a.txt", "alpha")
    _write(new / "state" / "existing.txt", "x")

    ok, msg = relocate(old, new, out=lambda _s: None)
    assert ok is False
    assert "already exists" in msg
    assert (new / "state" / "existing.txt").read_text() == "x"


def test_relocate_detects_corruption(monkeypatch, tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    _write(old / "state" / "a.txt", "alpha")
    real_copytree = shutil.copytree

    def corrupt_copytree(src, dst, symlinks=True, dirs_exist_ok=False):
        real_copytree(src, dst, symlinks=symlinks, dirs_exist_ok=dirs_exist_ok)
        if Path(dst).name == "state":
            # Same length, different bytes: only the SHA-256 comparison can catch it.
            (Path(dst) / "a.txt").write_text("alphx")

    monkeypatch.setattr("kaine.setup.storage_step.shutil.copytree", corrupt_copytree)

    ok, msg = relocate(old, new, out=lambda _s: None)
    assert ok is False
    assert "verification failed" in msg
    assert (new / "state" / "a.txt").exists()


def test_relocate_refuses_when_cycle_running(monkeypatch, tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    _write(old / "state" / "a.txt", "alpha")
    monkeypatch.setattr("kaine.setup.storage_step.cycle_process_running", lambda: True)

    ok, msg = relocate(old, new, out=lambda _s: None)
    assert ok is False
    assert "cycle is running" in msg
    assert not (new / "state").exists()


def test_relocation_step_failure_removes_storage_config(tmp_path):
    old = tmp_path / "old"
    new = tmp_path / "new"
    _write(old / "state" / "a.txt", "alpha")
    _write(new / "state" / "existing.txt", "x")

    ctx = StepContext(
        host={},
        config={"storage": {"data_root": str(new)}},
        extra={"old_root": old, "out": lambda _s: None},
    )
    relocation_step.apply(ctx, {"move": True})
    assert "storage" not in ctx.config
    assert "relocation_error" in ctx.extra


def test_render_volume_override():
    out = render_volume_override(Path("/data"))
    assert "volumes:" in out
    for v in GROWING_VOLUMES:
        assert f"  {v}:" in out
        assert f"device: /data/volumes/{v}" in out


def test_write_volume_override_writes_file_and_dirs(tmp_path):
    root = tmp_path / "root"
    compose = tmp_path / "compose"
    compose.mkdir()
    ok, msg = write_volume_override(root, compose, existing=set())
    assert ok is True
    path = compose / "kaine.storage.local.yml"
    assert path.exists()
    for v in GROWING_VOLUMES:
        assert (root / "volumes" / v).is_dir()
    assert "kaine.storage.local.yml" in msg


def test_write_volume_override_refuses_existing_volumes(tmp_path):
    root = tmp_path / "root"
    compose = tmp_path / "compose"
    ok, msg = write_volume_override(root, compose, existing={"kaine-state"})
    assert ok is False
    assert "kaine-state" in msg
    assert "docker run --rm -v kaine-state:/from" in msg
    assert not (compose / "kaine.storage.local.yml").exists()


def test_write_volume_override_no_docker(tmp_path):
    ok, msg = write_volume_override(
        tmp_path / "root", tmp_path / "compose", existing=None
    )
    assert ok is False
    assert "docker is not available" in msg


def test_existing_volumes_returns_none_on_failure(monkeypatch):
    def failing_run(*_args, **_kwargs):
        raise OSError("no docker")

    assert existing_volumes(run=failing_run) is None


def test_existing_volumes_parses_output(monkeypatch):
    class Result:
        returncode = 0
        stdout = "kaine-state\nkaine-data\n\n"

    assert existing_volumes(run=lambda *_a, **_k: Result()) == {"kaine-state", "kaine-data"}


def test_lifecycle_imports_still_work():
    from kaine.lifecycle.__main__ import _cycle_process_running
    from kaine.lifecycle.liveness import argv_is_cycle as _argv_is_cycle

    assert callable(_cycle_process_running)
    assert _argv_is_cycle([b"kaine.cycle"]) is True
    assert _argv_is_cycle([b"other"]) is False


def test_relocate_refuses_new_root_inside_old_data(tmp_path, monkeypatch):
    monkeypatch.setattr("kaine.setup.storage_step.cycle_process_running", lambda: False)
    old = tmp_path / "old"
    (old / "state").mkdir(parents=True)
    _write(old / "state" / "f.txt", "x")
    ok, msg = relocate(old, old / "state" / "nested", out=lambda s: None)
    assert ok is False
    assert "inside" in msg
    assert not (old / "state" / "nested").exists()
