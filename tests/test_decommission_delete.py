# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from kaine.lifecycle.decommission import delete_entity_state
from kaine.memory_kinds import (
    EPISODIC_MEMORY_STAMP_COLLECTION,
    stamp_key,
    stamp_point_id,
    strength_key,
)

# This deployment keeps no memory in Qdrant (the runtime default is Qdrant).
_NO_QDRANT = {"mnemos": {"backend": "inmemory"}, "empatheia": {"backend": "inmemory"}}

HAS_QDRANT = importlib.util.find_spec("qdrant_client") is not None


def _seed(state_root: Path) -> None:
    for path in ("eidolon/f.json", "lingua/f.json", "perception/f.json"):
        p = state_root / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
    fork_snap = state_root / "forks" / "s1"
    fork_snap.mkdir(parents=True, exist_ok=True)
    (fork_snap / "snapshot.json").write_text(
        json.dumps({"id": "s1", "metadata": {}}), encoding="utf-8"
    )
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
        state_root=state_root, qdrant_cfg=_NO_QDRANT, dry_run=True
    )
    assert result.dry_run is True
    assert result.removed_paths == []
    # Everything still on disk.
    assert (state_root / "eidolon" / "f.json").exists()
    assert (state_root / "hypnos" / "adapters" / "a.bin").exists()
    assert (state_root / "forks" / "s1").exists()
    # The would-remove report lists the intended subtrees.
    joined = " ".join(result.would_remove_paths)
    # Without an identity no fork snapshot is attributed to this entity, so
    # forks/s1 is kept and does not appear here.
    assert str(state_root / "eidolon") in joined and "adapters" in joined
    assert "forks" not in joined


def test_delete_removes_only_intended_paths(tmp_path):
    state_root = tmp_path / "state"
    _seed(state_root)
    result = delete_entity_state(
        state_root=state_root,
        qdrant_cfg=_NO_QDRANT,
        dry_run=False,
    )
    # Intended subtrees gone.
    assert not (state_root / "eidolon").exists()
    assert not (state_root / "lingua").exists()
    assert not (state_root / "perception").exists()
    assert (state_root / "forks" / "s1").exists()  # no identity -> cannot attribute
    assert (state_root / "forks").is_dir()
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
        state_root=state_root, qdrant_cfg=_NO_QDRANT, dry_run=False
    )
    # No on-disk removals, no crash.
    assert result.removed_paths == []


class _DecommissionFakeQdrantClient:
    def __init__(self):
        self.collections = {
            "mnemos_episodic": None,
            "mnemos_semantic": None,
            "mnemos_short_term": None,
            "mnemos_procedural": None,
            "empatheia_agents": None,
            EPISODIC_MEMORY_STAMP_COLLECTION: None,
        }
        self.deleted_collections: list[str] = []
        self.deleted_points: list[tuple[str, list[str]]] = []

    def get_collections(self):
        coll_type = type("Coll", (), {})
        out = []
        for name in self.collections:
            c = coll_type()
            c.name = name
            out.append(c)
        return type("Collections", (), {"collections": out})()

    def delete_collection(self, collection_name: str) -> None:
        self.deleted_collections.append(collection_name)
        self.collections.pop(collection_name, None)

    def delete(self, *, collection_name: str, points_selector) -> None:
        self.deleted_points.append((collection_name, list(points_selector.points)))

    def close(self) -> None:
        pass


@pytest.mark.skipif(not HAS_QDRANT, reason="qdrant_client not installed")
def test_decommission_deletes_stamp_point(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    _seed(state_root)
    fake = _DecommissionFakeQdrantClient()
    monkeypatch.setattr(
        "kaine.lifecycle.decommission._qdrant_client",
        lambda _cfg: fake,
    )
    result = delete_entity_state(
        state_root=state_root,
        qdrant_cfg={
            "modules": {"mnemos": True},
            "mnemos": {
                "qdrant": {
                    "host": "127.0.0.1",
                    "port": 6533,
                    "api_key": "test",
                }
            }
        },
        dry_run=False,
    )
    expected_key = stamp_key("mnemos_")
    expected_pid = stamp_point_id(expected_key)
    assert f"{EPISODIC_MEMORY_STAMP_COLLECTION}:{expected_key}" in result.dropped_collections
    assert any(
        coll == EPISODIC_MEMORY_STAMP_COLLECTION and expected_pid in pids
        for coll, pids in fake.deleted_points
    )
    assert "mnemos_episodic" in fake.deleted_collections

    strength_key_str = strength_key("mnemos_")
    strength_pid = stamp_point_id(strength_key_str)
    assert f"{EPISODIC_MEMORY_STAMP_COLLECTION}:{strength_key_str}" in result.dropped_collections
    assert any(
        coll == EPISODIC_MEMORY_STAMP_COLLECTION and strength_pid in pids
        for coll, pids in fake.deleted_points
    )


@pytest.mark.skipif(not HAS_QDRANT, reason="qdrant_client not installed")
def test_decommission_keeps_strength_meta_when_a_drop_fails(tmp_path, monkeypatch):
    """A failed collection drop keeps the episodic memory module's strength meta point."""
    state_root = tmp_path / "state"
    _seed(state_root)

    class FragileQdrant(_DecommissionFakeQdrantClient):
        def delete_collection(self, collection_name: str) -> None:
            if collection_name == "mnemos_semantic":
                raise RuntimeError("semantic drop failed")
            super().delete_collection(collection_name)

    fake = FragileQdrant()
    monkeypatch.setattr(
        "kaine.lifecycle.decommission._qdrant_client",
        lambda _cfg: fake,
    )
    result = delete_entity_state(
        state_root=state_root,
        qdrant_cfg={
            "modules": {"mnemos": True},
            "mnemos": {
                "qdrant": {
                    "host": "127.0.0.1",
                    "port": 6533,
                    "api_key": "test",
                }
            }
        },
        dry_run=False,
    )
    stamp = stamp_key("mnemos_")
    stamp_pid = stamp_point_id(stamp)
    strength = strength_key("mnemos_")
    strength_pid = stamp_point_id(strength)

    assert f"{EPISODIC_MEMORY_STAMP_COLLECTION}:{stamp}" in result.dropped_collections
    assert any(
        coll == EPISODIC_MEMORY_STAMP_COLLECTION and stamp_pid in pids
        for coll, pids in fake.deleted_points
    )
    assert not any(
        coll == EPISODIC_MEMORY_STAMP_COLLECTION and strength_pid in pids
        for coll, pids in fake.deleted_points
    )
    assert f"{EPISODIC_MEMORY_STAMP_COLLECTION}:{strength}" not in result.dropped_collections
    assert any("strength meta kept" in err for err in result.errors)
