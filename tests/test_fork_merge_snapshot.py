# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json

import pytest

from kaine.lifecycle.snapshot import (
    ForkSnapshot,
    InvalidSnapshotId,
    is_valid_snapshot_id,
    list_snapshots,
    load_snapshot,
    save_snapshot,
    snapshot_dir,
    snapshot_path,
)


def test_snapshot_assigns_id_when_not_given():
    snap = ForkSnapshot()
    assert snap.id
    assert len(snap.id) >= 8


def test_snapshot_roundtrip(tmp_path):
    snap = ForkSnapshot(
        parent_id=None,
        label="root",
        modules={"soma": {"wellness": 0.9}, "chronos": {"steps": 12}},
        adapters=["state/hypnos/adapters/a"],
        metadata={"note": "test"},
    )
    save_snapshot(tmp_path, snap)
    target = tmp_path / snap.id / "snapshot.json"
    assert target.exists()
    raw = json.loads(target.read_text())
    assert raw["modules"]["soma"]["wellness"] == 0.9
    loaded = load_snapshot(tmp_path, snap.id)
    assert loaded.id == snap.id
    assert loaded.modules == snap.modules
    assert loaded.adapters == snap.adapters
    assert loaded.metadata == snap.metadata


def test_save_is_atomic(tmp_path):
    snap = ForkSnapshot(modules={"k": {"v": 1}})
    save_snapshot(tmp_path, snap)
    # No leftover tmp file.
    tmp_files = list((tmp_path / snap.id).glob("*.tmp"))
    assert tmp_files == []


def test_list_snapshots_empty(tmp_path):
    assert list_snapshots(tmp_path) == []


def test_list_snapshots_sorted(tmp_path):
    a = ForkSnapshot(id="aaaa1111", modules={})
    b = ForkSnapshot(id="bbbb2222", modules={})
    save_snapshot(tmp_path, b)
    save_snapshot(tmp_path, a)
    assert list_snapshots(tmp_path) == ["aaaa1111", "bbbb2222"]


def test_from_dict_handles_missing_keys():
    snap = ForkSnapshot.from_dict({"id": "x"})
    assert snap.id == "x"
    assert snap.modules == {}
    assert snap.adapters == []


def test_from_dict_preserves_parent_id():
    snap = ForkSnapshot.from_dict({"id": "x", "parent_id": "y"})
    assert snap.parent_id == "y"


# ---------------------------------------------------------------------------
# P1 path-traversal defense: id validation + path-builder containment.
# ---------------------------------------------------------------------------


def test_is_valid_snapshot_id_accepts_fork_and_merge_forms():
    assert is_valid_snapshot_id("0123456789abcdef")  # 16-hex fork/root id
    assert is_valid_snapshot_id("0123456789abcdef+fedcba9876543210")  # merge id


@pytest.mark.parametrize(
    "bad",
    [
        "/etc/passwd",
        "../../etc/passwd",
        "..",
        "abc/def",
        "0123456789ABCDEF",   # uppercase (ids are lowercase hex)
        "0123456789abcde",    # 15 chars
        "0123456789abcdefg",  # 17 chars / non-hex
        "0123456789abcdef+",  # dangling separator
        "",
    ],
)
def test_is_valid_snapshot_id_rejects_traversal_and_malformed(bad):
    assert not is_valid_snapshot_id(bad)


@pytest.mark.parametrize("bad", ["/etc/passwd", "../../etc/passwd", "..", "a/../../b"])
def test_snapshot_path_raises_on_escaping_id(tmp_path, bad):
    """Even if the endpoint validator is bypassed, the path-builder refuses any
    id whose resolved path leaves the snapshot root (defense in depth)."""
    with pytest.raises(InvalidSnapshotId):
        snapshot_path(tmp_path, bad)
    with pytest.raises(InvalidSnapshotId):
        snapshot_dir(tmp_path, bad)


def test_load_snapshot_rejects_absolute_id(tmp_path):
    """load_snapshot must not read a file outside the root for an absolute id."""
    with pytest.raises(InvalidSnapshotId):
        load_snapshot(tmp_path, "/etc/passwd")


def test_snapshot_path_resolves_valid_id_under_root(tmp_path):
    """A well-formed id still resolves to a path under the root, and the normal
    write path (server-generated id) is unaffected."""
    valid = "0123456789abcdef"
    p = snapshot_path(tmp_path, valid)
    assert p == (tmp_path.resolve() / valid / "snapshot.json")
    # Merge-form ids resolve too (a legitimate `<hex>+<hex>` never escapes root).
    merge_id = "0123456789abcdef+fedcba9876543210"
    assert snapshot_dir(tmp_path, merge_id) == (tmp_path.resolve() / merge_id)
    # Round-trip through the real write/read path with a generated id.
    snap = ForkSnapshot(modules={"k": {"v": 1}})
    save_snapshot(tmp_path, snap)
    assert load_snapshot(tmp_path, snap.id).id == snap.id
