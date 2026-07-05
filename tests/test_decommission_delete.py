# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from pathlib import Path

from kaine.lifecycle.decommission import delete_entity_state


def _seed(state_root: Path) -> None:
    for sub in ("eidolon", "lingua", "perception", "forks"):
        (state_root / sub).mkdir(parents=True, exist_ok=True)
        (state_root / sub / "f.json").write_text("{}", encoding="utf-8")
    (state_root / "hypnos" / "adapters").mkdir(parents=True, exist_ok=True)
    (state_root / "hypnos" / "adapters" / "a.bin").write_bytes(b"w")
    (state_root / "cycle").mkdir(parents=True, exist_ok=True)
    (state_root / "cycle" / "runtime.json").write_text("{}", encoding="utf-8")
    # An operator file we must NOT touch.
    (state_root / "cycle" / "control.json").write_text("{}", encoding="utf-8")
    # A sibling tree outside state_root must never be touched.
    outside = state_root.parent / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    (outside / "keep.txt").write_text("keep", encoding="utf-8")


def test_dry_run_removes_nothing(tmp_path):
    state_root = tmp_path / "state"
    _seed(state_root)
    result = delete_entity_state(
        state_root=state_root, qdrant_cfg={}, redis_cfg=None, dry_run=True
    )
    assert result.dry_run is True
    assert result.removed_paths == []
    # Everything still on disk.
    assert (state_root / "eidolon" / "f.json").exists()
    assert (state_root / "hypnos" / "adapters" / "a.bin").exists()
    # The would-remove report lists the intended subtrees.
    joined = " ".join(result.would_remove_paths)
    assert "eidolon" in joined and "forks" in joined and "adapters" in joined


def test_delete_removes_only_intended_paths(tmp_path):
    state_root = tmp_path / "state"
    _seed(state_root)
    result = delete_entity_state(
        state_root=state_root,
        qdrant_cfg={"mnemos": {"qdrant": {"host": "127.0.0.1", "port": 59999}}},
        redis_cfg=None,
        dry_run=False,
    )
    # Intended subtrees gone.
    assert not (state_root / "eidolon").exists()
    assert not (state_root / "lingua").exists()
    assert not (state_root / "perception").exists()
    assert not (state_root / "forks").exists()
    assert not (state_root / "hypnos" / "adapters").exists()
    assert not (state_root / "cycle" / "runtime.json").exists()
    # Operator file preserved.
    assert (state_root / "cycle" / "control.json").exists()
    # Outside-state_root tree untouched.
    assert (state_root.parent / "outside" / "keep.txt").exists()
    assert result.removed_paths


def test_delete_handles_missing_state(tmp_path):
    state_root = tmp_path / "state"  # never created
    result = delete_entity_state(
        state_root=state_root, qdrant_cfg={}, redis_cfg=None, dry_run=False
    )
    # No on-disk removals, no crash.
    assert result.removed_paths == []
