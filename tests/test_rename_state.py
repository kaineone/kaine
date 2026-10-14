# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for ``kaine.lifecycle.rename_state``."""

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from kaine import legacy_names
from kaine.lifecycle import rename_state
from kaine.state_io import write_json_atomic


@pytest.fixture(autouse=True)
def _persisted_done(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "done")


def _write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data)
    else:
        path.write_bytes(data)


def _make_db(
    path: Path,
    collections=("mnemos_episodic", "mnemos_semantic", "empatheia_agents"),
):
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute(
        "CREATE TABLE memories (rowid INTEGER PRIMARY KEY AUTOINCREMENT, collection TEXT, "
        "point_id TEXT, text TEXT, payload TEXT, affect TEXT)"
    )
    for collection in collections:
        con.execute(
            "INSERT INTO memories (collection, point_id, text, payload, affect) "
            "VALUES (?, ?, ?, ?, ?)",
            (collection, "p", "t", "{}", "a"),
        )
    con.commit()
    con.close()


def _make_tree(
    root: Path, *, collections=("mnemos_episodic", "mnemos_semantic", "empatheia_agents")
):
    root = Path(root)
    _make_db(root / "mnemos" / "mnemos.db", collections=collections)
    _write(root / "mnemos" / "store_health.json", "{}")
    _write(root / "hypnos" / "consolidation_divergence.json", "[]")
    _write(root / "phantasia" / "world_model.ckpt", b"weights")
    stage = {"stage": "gestation", "gestation_started_at": "t0", "womb_seed": 7}
    write_json_atomic(root / "lifecycle" / "stage.json", stage)
    _write(root / "lifecycle" / "birth_ack.json", "ok")
    _write(root / "forks" / "abc" / "snapshot.json", "snap")


def _snapshot(root: Path):
    root = Path(root)
    files: dict[str, Any] = {}
    dirs: set[str] = set()
    paths = sorted(root.rglob("*"))
    for path in paths:
        rel = path.relative_to(root)
        key = str(rel).replace("\\", "/")
        if key.split("/")[0] == ".rename_state":
            continue
        if path.is_dir():
            dirs.add(key)
            continue
        if not key.endswith(".db"):
            files[key] = path.read_bytes()
    for path in paths:
        rel = path.relative_to(root)
        key = str(rel).replace("\\", "/")
        if key.split("/")[0] == ".rename_state":
            continue
        if path.is_dir() or not key.endswith(".db"):
            continue
        con = sqlite3.connect(str(path))
        try:
            rows = con.execute(
                "SELECT collection, point_id, text, payload, affect FROM memories ORDER BY rowid"
            ).fetchall()
        finally:
            con.close()
        files[key] = rows
    return files, dirs


def _raw_snapshot(root: Path):
    """Like ``_snapshot`` but reads every file as bytes (no sqlite decoding)."""
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


def drop_wal_shm(snapshot):
    files, dirs = snapshot
    return {k: v for k, v in files.items() if not (k.endswith("-wal") or k.endswith("-shm"))}, dirs


def _outside_snapshot(outside: Path):
    """Snapshot a sibling directory used as an attack target."""
    if not outside.exists():
        return {}, set()
    files: dict[str, bytes] = {}
    dirs: set[str] = set()
    for path in sorted(outside.rglob("*")):
        rel = path.relative_to(outside)
        key = str(rel).replace("\\", "/")
        if path.is_dir():
            dirs.add(key)
        else:
            files[key] = path.read_bytes()
    return files, dirs


def _attack_snapshot(root: Path, manifest_path: Path, outside: Path):
    """Snapshot everything an attacker might try to change."""
    manifest_bytes = manifest_path.read_bytes() if manifest_path.exists() else None
    return (_snapshot(root), manifest_bytes, _outside_snapshot(outside))


def _interrupt_migrate(root: Path, monkeypatch, stop_at: int = 2):
    """Run migrate but raise KeyboardInterrupt before the ``stop_at``-th step."""
    original = rename_state._run_step
    call_count = 0

    def wrapper(r, step, qdrant):
        nonlocal call_count
        call_count += 1
        if call_count == stop_at:
            raise KeyboardInterrupt
        return original(r, step, qdrant)

    monkeypatch.setattr(rename_state, "_run_step", wrapper)
    try:
        with pytest.raises(KeyboardInterrupt):
            rename_state.migrate(root, no_qdrant=True)
    finally:
        monkeypatch.setattr(rename_state, "_run_step", original)


def test_pending_scope_is_noop(tmp_path, monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "pending")
    _make_tree(tmp_path)
    before = _snapshot(tmp_path)
    result = rename_state.migrate(tmp_path, no_qdrant=True)
    assert result.status == "noop"
    assert not (tmp_path / ".rename_state").exists()
    assert _snapshot(tmp_path) == before


def test_full_migration(tmp_path):
    _make_tree(tmp_path)
    result = rename_state.migrate(tmp_path, no_qdrant=True)
    assert result.status == "migrated"

    manifest = json.loads((tmp_path / ".rename_state" / "manifest.json").read_bytes())
    assert manifest["status"] == "complete"

    assert (tmp_path / "episodic_memory").is_dir()
    assert (tmp_path / "sleep").is_dir()
    assert (tmp_path / "world_model").is_dir()
    assert not (tmp_path / "mnemos").exists()
    assert not (tmp_path / "hypnos").exists()
    assert not (tmp_path / "phantasia").exists()

    db_path = tmp_path / "episodic_memory" / "episodic_memory.db"
    assert db_path.is_file()
    con = sqlite3.connect(str(db_path))
    try:
        collections = [
            r[0] for r in con.execute("SELECT DISTINCT collection FROM memories").fetchall()
        ]
    finally:
        con.close()
    assert sorted(collections) == [
        "episodic_memory_episodic",
        "episodic_memory_semantic",
        "social_cognition_agents",
    ]

    assert (tmp_path / "episodic_memory" / "store_health.json").is_file()
    assert (tmp_path / "sleep" / "consolidation_divergence.json").is_file()
    assert (tmp_path / "world_model" / "world_model.ckpt").read_bytes() == b"weights"
    assert (tmp_path / "lifecycle" / "maturation_ack.json").is_file()
    assert not (tmp_path / "lifecycle" / "birth_ack.json").exists()

    stage = json.loads((tmp_path / "lifecycle" / "stage.json").read_bytes())
    assert stage == {
        "stage": "development",
        "development_started_at": "t0",
        "stimulus_source_seed": 7,
    }

    assert (tmp_path / "forks" / "abc" / "snapshot.json").read_bytes() == b"snap"


def test_rerun_on_migrated_tree_is_noop(tmp_path):
    _make_tree(tmp_path)
    rename_state.migrate(tmp_path, no_qdrant=True)
    manifest_bytes = (tmp_path / ".rename_state" / "manifest.json").read_bytes()
    result = rename_state.migrate(tmp_path, no_qdrant=True)
    assert result.status == "noop"
    assert (tmp_path / ".rename_state" / "manifest.json").read_bytes() == manifest_bytes


def test_interruption_resume_revert(tmp_path, monkeypatch):
    _make_tree(tmp_path)
    before = _snapshot(tmp_path)

    original_run_step = rename_state._run_step
    call_count = 0

    def wrapper(root, step, qdrant):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            manifest = json.loads((tmp_path / ".rename_state" / "manifest.json").read_bytes())
            assert manifest["status"] == "in_progress"
            assert all(s["status"] == "pending" for s in manifest["steps"])
        if call_count == 3:
            raise KeyboardInterrupt
        return original_run_step(root, step, qdrant)

    monkeypatch.setattr(rename_state, "_run_step", wrapper)
    with pytest.raises(KeyboardInterrupt):
        rename_state.migrate(tmp_path, no_qdrant=True)

    manifest = json.loads((tmp_path / ".rename_state" / "manifest.json").read_bytes())
    assert manifest["status"] == "in_progress"
    steps = manifest["steps"]
    assert steps[0]["status"] in ("pending", "done")
    assert any(s["status"] == "pending" for s in steps)

    monkeypatch.setattr(rename_state, "_run_step", original_run_step)
    result = rename_state.migrate(tmp_path, no_qdrant=True)
    assert result.status == "resumed"

    fresh = tmp_path.parent / "fresh"
    _make_tree(fresh)
    rename_state.migrate(fresh, no_qdrant=True)
    assert _snapshot(tmp_path) == _snapshot(fresh)

    revert_result = rename_state.revert(tmp_path)
    assert revert_result.status == "reverted"
    assert not (tmp_path / ".rename_state").exists()
    assert _snapshot(tmp_path) == before


def test_interruption_after_work_then_resume_revert(tmp_path, monkeypatch):
    _make_tree(tmp_path)
    before = _snapshot(tmp_path)

    original_run_step = rename_state._run_step
    call_count = 0

    def wrapper(root, step, qdrant):
        nonlocal call_count
        call_count += 1
        result = original_run_step(root, step, qdrant)
        if call_count == 3:
            raise KeyboardInterrupt
        return result

    monkeypatch.setattr(rename_state, "_run_step", wrapper)
    with pytest.raises(KeyboardInterrupt):
        rename_state.migrate(tmp_path, no_qdrant=True)

    manifest = json.loads((tmp_path / ".rename_state" / "manifest.json").read_bytes())
    assert manifest["steps"][2]["status"] == "pending"

    monkeypatch.setattr(rename_state, "_run_step", original_run_step)
    result = rename_state.migrate(tmp_path, no_qdrant=True)
    assert result.status == "resumed"

    rename_state.revert(tmp_path)
    assert not (tmp_path / ".rename_state").exists()
    assert _snapshot(tmp_path) == before


def test_revert_straight_after_interrupt(tmp_path, monkeypatch):
    _make_tree(tmp_path)
    before = _snapshot(tmp_path)

    original_run_step = rename_state._run_step
    call_count = 0

    def wrapper(root, step, qdrant):
        nonlocal call_count
        call_count += 1
        if call_count == 3:
            raise KeyboardInterrupt
        return original_run_step(root, step, qdrant)

    monkeypatch.setattr(rename_state, "_run_step", wrapper)
    with pytest.raises(KeyboardInterrupt):
        rename_state.migrate(tmp_path, no_qdrant=True)

    monkeypatch.setattr(rename_state, "_run_step", original_run_step)
    rename_state.revert(tmp_path)
    assert not (tmp_path / ".rename_state").exists()
    assert _snapshot(tmp_path) == before


def test_refuse_both_module_dirs_present(tmp_path):
    _make_tree(tmp_path)
    (tmp_path / "episodic_memory").mkdir()
    (tmp_path / "episodic_memory" / "x").write_text("x")
    before = _snapshot(tmp_path)

    with pytest.raises(rename_state.RenameStateError):
        rename_state.migrate(tmp_path, no_qdrant=True)

    assert not (tmp_path / ".rename_state").exists()
    assert _snapshot(tmp_path) == before


def test_refuse_stage_old_and_new_fields(tmp_path):
    _make_tree(tmp_path)
    stage = {
        "stage": "gestation",
        "gestation_started_at": "t0",
        "development_started_at": "t1",
        "womb_seed": 7,
    }
    write_json_atomic(tmp_path / "lifecycle" / "stage.json", stage)
    before = _snapshot(tmp_path)

    with pytest.raises(rename_state.RenameStateError):
        rename_state.migrate(tmp_path, no_qdrant=True)

    assert not (tmp_path / ".rename_state").exists()
    assert _snapshot(tmp_path) == before


def test_refuse_db_both_collections(tmp_path):
    _make_tree(tmp_path, collections=("mnemos_episodic", "episodic_memory_episodic"))
    before = _snapshot(tmp_path)

    with pytest.raises(rename_state.RenameStateError):
        rename_state.migrate(tmp_path, no_qdrant=True)

    assert not (tmp_path / ".rename_state").exists()
    assert _snapshot(tmp_path) == before


def test_dry_run(tmp_path):
    _make_tree(tmp_path)
    before = _snapshot(tmp_path)
    result = rename_state.migrate(tmp_path, dry_run=True, no_qdrant=True)
    assert result.status == "dry_run"
    assert len(result.steps) > 0
    assert not (tmp_path / ".rename_state").exists()
    assert _snapshot(tmp_path) == before


def test_companion_moves_with_its_database(tmp_path):
    _make_tree(tmp_path)
    (tmp_path / "mnemos" / "mnemos.db").write_bytes(b"not a database")
    (tmp_path / "mnemos" / "mnemos.db-wal").write_bytes(b"wal-data")
    before = _raw_snapshot(tmp_path)

    result = rename_state.migrate(tmp_path, no_qdrant=True)
    assert result.status == "migrated"
    assert (tmp_path / "episodic_memory" / "episodic_memory.db-wal").read_bytes() == b"wal-data"

    move_steps = [s for s in result.steps if s["kind"] == "move"]
    wal_step = next(s for s in move_steps if s["dst"] == "episodic_memory/episodic_memory.db-wal")
    assert wal_step["companion"] is True
    db_step = next(s for s in move_steps if s["dst"] == "episodic_memory/episodic_memory.db")
    assert db_step["companion"] is False

    revert_result = rename_state.revert(tmp_path)
    assert revert_result.status == "reverted"
    assert not (tmp_path / ".rename_state").exists()
    assert not (tmp_path / "episodic_memory").exists()
    assert _raw_snapshot(tmp_path) == before


def test_companion_that_sqlite_removes_does_not_block_revert(tmp_path):
    _make_tree(tmp_path)
    con = sqlite3.connect(str(tmp_path / "mnemos" / "mnemos.db"))
    try:
        con.execute("PRAGMA journal_mode=WAL")
    finally:
        con.close()
    (tmp_path / "mnemos" / "mnemos.db-wal").write_bytes(b"stale")
    before = drop_wal_shm(_snapshot(tmp_path))

    result = rename_state.migrate(tmp_path, no_qdrant=True)
    assert result.status == "migrated"

    revert_result = rename_state.revert(tmp_path)
    assert revert_result.status == "reverted"
    assert not (tmp_path / ".rename_state").exists()

    after = drop_wal_shm(_snapshot(tmp_path))

    assert after == before


def test_plan_marks_companion_steps(tmp_path):
    _make_tree(tmp_path)
    (tmp_path / "mnemos" / "mnemos.db-wal").write_bytes(b"wal-data")
    (tmp_path / "mnemos" / "mnemos.db-shm").write_bytes(b"shm-data")
    steps = rename_state.plan(tmp_path)
    move_steps = [s for s in steps if s["kind"] == "move"]
    for s in move_steps:
        if s["dst"].endswith((".db-wal", ".db-shm", ".db-journal")):
            assert s["companion"] is True
        else:
            assert s["companion"] is False
    assert any(s["dst"] == "episodic_memory/episodic_memory.db-wal" for s in move_steps)
    assert any(s["dst"] == "episodic_memory/episodic_memory.db-shm" for s in move_steps)


def test_stage_invalid_json_left_intact(tmp_path):
    _make_tree(tmp_path)
    bad = b"{not json"
    (tmp_path / "lifecycle" / "stage.json").write_bytes(bad)
    rename_state.migrate(tmp_path, no_qdrant=True)
    assert (tmp_path / "lifecycle" / "stage.json").read_bytes() == bad
    manifest = json.loads((tmp_path / ".rename_state" / "manifest.json").read_bytes())
    assert not any(s["kind"] == "stage" for s in manifest["steps"])


class _FakeQdrant:
    def __init__(self, collections, aliases):
        self._collections = list(collections)
        self._aliases = dict(aliases)

    def collections(self):
        return list(self._collections)

    def aliases(self):
        return dict(self._aliases)

    def create_alias(self, alias, collection):
        self._aliases[alias] = collection

    def delete_alias(self, alias):
        self._aliases.pop(alias, None)


def test_qdrant_alias(tmp_path):
    _make_tree(tmp_path)
    qdrant = _FakeQdrant(["mnemos_episodic", "other"], {})
    rename_state.migrate(tmp_path, qdrant=qdrant)
    assert qdrant.aliases() == {"episodic_memory_episodic": "mnemos_episodic"}

    rename_state.revert(tmp_path, qdrant=qdrant)
    assert qdrant.aliases() == {}

    other = tmp_path.parent / "other"
    _make_tree(other)
    rename_state.migrate(other, qdrant=qdrant)
    with pytest.raises(rename_state.RenameStateError, match="Qdrant client"):
        rename_state.revert(other, qdrant=None)
    assert "episodic_memory_episodic" in qdrant.aliases()
    assert (other / ".rename_state").exists()


def test_qdrant_alias_conflict(tmp_path):
    _make_tree(tmp_path)
    qdrant = _FakeQdrant(["mnemos_episodic", "other"], {"episodic_memory_episodic": "other"})
    with pytest.raises(rename_state.RenameStateError):
        rename_state.migrate(tmp_path, qdrant=qdrant)
    assert not (tmp_path / ".rename_state").exists()


def test_migrate_requires_an_explicit_qdrant_choice(tmp_path, capsys):
    _make_tree(tmp_path)
    before = _snapshot(tmp_path)

    with pytest.raises(rename_state.RenameStateError):
        rename_state.migrate(tmp_path)
    assert not (tmp_path / ".rename_state").exists()
    assert _snapshot(tmp_path) == before

    qdrant = _FakeQdrant([], {})
    with pytest.raises(rename_state.RenameStateError):
        rename_state.migrate(tmp_path, qdrant=qdrant, no_qdrant=True)

    ret = rename_state.main([str(tmp_path)])
    assert ret == 2
    captured = capsys.readouterr()
    assert "--no-qdrant" in captured.err


def test_sqlite_vec(tmp_path):
    sqlite_vec = pytest.importorskip("sqlite_vec")
    _make_tree(tmp_path)

    con = sqlite3.connect(str(tmp_path / "mnemos" / "mnemos.db"))
    try:
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        con.execute(
            "CREATE VIRTUAL TABLE vec_memories USING vec0("
            "collection text partition key, embedding float[4] distance_metric=cosine)"
        )
        rows = [
            (1, "mnemos_episodic", sqlite_vec.serialize_float32([0.1, 0.2, 0.3, 0.4])),
            (2, "mnemos_semantic", sqlite_vec.serialize_float32([0.4, 0.3, 0.2, 0.1])),
        ]
        for rowid, collection, embedding in rows:
            con.execute(
                "INSERT INTO vec_memories (rowid, collection, embedding) VALUES (?, ?, ?)",
                (rowid, collection, embedding),
            )
        con.commit()
    finally:
        con.close()

    rename_state.migrate(tmp_path, no_qdrant=True)

    con = sqlite3.connect(str(tmp_path / "episodic_memory" / "episodic_memory.db"))
    try:
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        vec_rows = con.execute(
            "SELECT rowid, collection, embedding FROM vec_memories ORDER BY rowid"
        ).fetchall()
    finally:
        con.close()

    expected = [
        (1, "episodic_memory_episodic", sqlite_vec.serialize_float32([0.1, 0.2, 0.3, 0.4])),
        (2, "episodic_memory_semantic", sqlite_vec.serialize_float32([0.4, 0.3, 0.2, 0.1])),
    ]
    assert vec_rows == expected

    rename_state.revert(tmp_path)

    con = sqlite3.connect(str(tmp_path / "mnemos" / "mnemos.db"))
    try:
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        vec_rows = con.execute(
            "SELECT rowid, collection, embedding FROM vec_memories ORDER BY rowid"
        ).fetchall()
    finally:
        con.close()

    original = [
        (1, "mnemos_episodic", sqlite_vec.serialize_float32([0.1, 0.2, 0.3, 0.4])),
        (2, "mnemos_semantic", sqlite_vec.serialize_float32([0.4, 0.3, 0.2, 0.1])),
    ]
    assert vec_rows == original


def test_created_dirs_for_new_destination(tmp_path, monkeypatch):
    _make_tree(tmp_path)
    _write(tmp_path / "lifecycle" / "extra.json", b"extra")
    entry = {
        "old": "lifecycle/extra.json",
        "new": "newdir/sub/extra.json",
        "scope": "persisted",
    }
    monkeypatch.setattr(legacy_names, "STATE_PATHS", legacy_names.STATE_PATHS + (entry,))
    before = _snapshot(tmp_path)

    result = rename_state.migrate(tmp_path, no_qdrant=True)
    assert result.status == "migrated"
    assert (tmp_path / "newdir" / "sub" / "extra.json").read_bytes() == b"extra"

    move_step = next(s for s in result.steps if s["dst"] == "newdir/sub/extra.json")
    assert move_step["created_dirs"] == ["newdir", "newdir/sub"]

    rename_state.revert(tmp_path)
    assert not (tmp_path / "newdir").exists()
    assert _snapshot(tmp_path) == before


def test_stage_backups_are_per_step_and_revert_to_original(tmp_path):
    _make_tree(tmp_path)
    before = _snapshot(tmp_path)

    rename_state.migrate(tmp_path, no_qdrant=True)
    write_json_atomic(
        tmp_path / "lifecycle" / "stage.json",
        {"stage": "gestation", "gestation_started_at": "t0", "womb_seed": 7},
    )

    result = rename_state.migrate(tmp_path, no_qdrant=True)
    assert result.status == "migrated"
    stage_steps = [s for s in result.steps if s["kind"] == "stage"]
    assert len(stage_steps) == 2
    assert stage_steps[0]["backup"] != stage_steps[1]["backup"]
    assert (tmp_path / stage_steps[0]["backup"]).exists()
    assert (tmp_path / stage_steps[1]["backup"]).exists()

    revert_result = rename_state.revert(tmp_path)
    assert revert_result.status == "reverted"
    assert not (tmp_path / ".rename_state").exists()
    assert _snapshot(tmp_path) == before


def test_main_dry_run(tmp_path):
    _make_tree(tmp_path)
    ret = rename_state.main([str(tmp_path), "--dry-run", "--no-qdrant"])
    assert ret == 0
    assert not (tmp_path / ".rename_state").exists()


def test_main_conflict(tmp_path, capsys):
    _make_tree(tmp_path)
    # Data under both names: an empty new directory alone would be merged into.
    (tmp_path / "episodic_memory").mkdir()
    (tmp_path / "episodic_memory" / "other.json").write_text("{}")
    ret = rename_state.main([str(tmp_path), "--no-qdrant"])
    assert ret == 2
    captured = capsys.readouterr()
    assert "kaine.lifecycle.rename_state:" in captured.err
    assert not (tmp_path / ".rename_state").exists()


def test_resume_refuses_absolute_move_dst(tmp_path, monkeypatch):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    _make_tree(root)

    _interrupt_migrate(root, monkeypatch, stop_at=2)

    manifest_path = root / ".rename_state" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for step in manifest["steps"]:
        if step["kind"] == "move" and step["status"] == "pending":
            step["dst"] = str(outside / "x")
            break
    else:
        raise RuntimeError("no pending move step found")
    write_json_atomic(manifest_path, manifest)

    before = _attack_snapshot(root, manifest_path, outside)
    with pytest.raises(rename_state.RenameStateError):
        rename_state.migrate(root, no_qdrant=True)
    assert _attack_snapshot(root, manifest_path, outside) == before


def test_revert_refuses_absolute_move_dst(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    _make_tree(root)
    rename_state.migrate(root, no_qdrant=True)

    manifest_path = root / ".rename_state" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for step in manifest["steps"]:
        if step["kind"] == "move":
            step["dst"] = str(outside / "x")
            break
    write_json_atomic(manifest_path, manifest)

    before = _attack_snapshot(root, manifest_path, outside)
    with pytest.raises(rename_state.RenameStateError):
        rename_state.revert(root)
    assert _attack_snapshot(root, manifest_path, outside) == before


def test_revert_refuses_dotdot_move_src(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    _make_tree(root)
    rename_state.migrate(root, no_qdrant=True)

    victim = outside / "victim"
    victim.parent.mkdir(parents=True, exist_ok=True)
    victim.write_text("stolen")

    manifest_path = root / ".rename_state" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for step in manifest["steps"]:
        if step["kind"] == "move":
            step["src"] = "../outside/victim"
            break
    write_json_atomic(manifest_path, manifest)

    before = _attack_snapshot(root, manifest_path, outside)
    with pytest.raises(rename_state.RenameStateError):
        rename_state.revert(root)
    assert _attack_snapshot(root, manifest_path, outside) == before


def test_revert_refuses_symlinked_dst_outside_root(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    _make_tree(root)
    rename_state.migrate(root, no_qdrant=True)

    target_dir = outside / "target_dir"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "file.txt").write_text("outside")

    sleep = root / "sleep"
    if sleep.exists():
        shutil.rmtree(sleep)
    sleep.symlink_to(target_dir, target_is_directory=True)

    manifest_path = root / ".rename_state" / "manifest.json"
    before = _attack_snapshot(root, manifest_path, outside)
    with pytest.raises(rename_state.RenameStateError):
        rename_state.revert(root)
    assert _attack_snapshot(root, manifest_path, outside) == before


def test_migrate_refuses_symlinked_src_outside_root(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    _make_tree(root)

    target = outside / "hypnos_target"
    target.mkdir(parents=True, exist_ok=True)
    (target / "keep.txt").write_text("out")

    sleep = root / "hypnos"
    if sleep.exists():
        shutil.rmtree(sleep)
    sleep.symlink_to(target, target_is_directory=True)

    manifest_path = root / ".rename_state" / "manifest.json"
    before = _attack_snapshot(root, manifest_path, outside)
    with pytest.raises(rename_state.RenameStateError):
        rename_state.migrate(root, no_qdrant=True)
    assert _attack_snapshot(root, manifest_path, outside) == before
    assert not manifest_path.exists()
    assert not (root / ".rename_state").exists()


def test_resume_refuses_created_dir_outside_root(tmp_path, monkeypatch):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    _make_tree(root)

    _interrupt_migrate(root, monkeypatch, stop_at=2)

    manifest_path = root / ".rename_state" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for step in manifest["steps"]:
        if step["kind"] == "move" and step["status"] == "pending":
            step["created_dirs"] = ["../outside/made"]
            break
    else:
        raise RuntimeError("no pending move step found")
    write_json_atomic(manifest_path, manifest)

    before = _attack_snapshot(root, manifest_path, outside)
    with pytest.raises(rename_state.RenameStateError):
        rename_state.migrate(root, no_qdrant=True)
    assert _attack_snapshot(root, manifest_path, outside) == before
    assert not (outside / "made").exists()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m.__setitem__("steps", ["not a dict"]),
        lambda m: m["steps"].append({"kind": "bad", "status": "pending"}),
        lambda m: m["steps"].append(
            {"kind": "move", "src": "a", "status": "pending", "created_dirs": []}
        ),
        lambda m: m["steps"].append(
            {"kind": "move", "src": 1, "dst": "b", "created_dirs": [], "status": "pending"}
        ),
        lambda m: m["steps"].append(
            {"kind": "sqlite", "path": "x.db", "pairs": "bad", "vec": False, "status": "pending"}
        ),
        lambda m: m["steps"].append(
            {"kind": "move", "src": "a", "dst": "b", "created_dirs": [], "status": "weird"}
        ),
        lambda m: m.__setitem__("version", 2),
    ],
    ids=[
        "step_not_dict",
        "unknown_kind",
        "move_missing_dst",
        "move_src_int",
        "sqlite_pairs_str",
        "status_weird",
        "version_2",
    ],
)
def test_revert_refuses_malformed_manifest(tmp_path, mutation):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    _make_tree(root)
    rename_state.migrate(root, no_qdrant=True)

    manifest_path = root / ".rename_state" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    mutation(manifest)
    write_json_atomic(manifest_path, manifest)

    before = _attack_snapshot(root, manifest_path, outside)
    with pytest.raises(rename_state.RenameStateError):
        rename_state.revert(root)
    assert _attack_snapshot(root, manifest_path, outside) == before


def test_revert_refuses_invalid_json_manifest(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    _make_tree(root)
    rename_state.migrate(root, no_qdrant=True)

    manifest_path = root / ".rename_state" / "manifest.json"
    manifest_path.write_bytes(b"{not json")

    before = _attack_snapshot(root, manifest_path, outside)
    with pytest.raises(rename_state.RenameStateError, match="not valid JSON"):
        rename_state.revert(root)
    assert _attack_snapshot(root, manifest_path, outside) == before


def test_revert_refuses_symlinked_manifest_dir(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    _make_tree(root)
    rename_state.migrate(root, no_qdrant=True)

    manifest_path = root / ".rename_state" / "manifest.json"
    outside_m = outside / "m"
    shutil.copytree(root / ".rename_state", outside_m)
    before_outside = _outside_snapshot(outside)
    shutil.rmtree(root / ".rename_state")
    (root / ".rename_state").symlink_to(outside_m, target_is_directory=True)
    before = _attack_snapshot(root, manifest_path, outside)

    with pytest.raises(rename_state.RenameStateError):
        rename_state.revert(root)
    assert _attack_snapshot(root, manifest_path, outside) == before
    assert _outside_snapshot(outside) == before_outside


def test_migrate_refuses_symlinked_manifest_dir(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    _make_tree(root)
    rename_state.migrate(root, no_qdrant=True)

    manifest_path = root / ".rename_state" / "manifest.json"
    outside_m = outside / "m"
    shutil.copytree(root / ".rename_state", outside_m)
    before_outside = _outside_snapshot(outside)
    shutil.rmtree(root / ".rename_state")
    (root / ".rename_state").symlink_to(outside_m, target_is_directory=True)
    before = _attack_snapshot(root, manifest_path, outside)

    with pytest.raises(rename_state.RenameStateError):
        rename_state.migrate(root, no_qdrant=True)
    assert _attack_snapshot(root, manifest_path, outside) == before
    assert _outside_snapshot(outside) == before_outside


def test_revert_refuses_created_dir_not_ancestor(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    _make_tree(root)
    rename_state.migrate(root, no_qdrant=True)

    manifest_path = root / ".rename_state" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for step in manifest["steps"]:
        if step["kind"] == "move" and step["dst"] == "sleep":
            step["created_dirs"] = ["lifecycle"]
            break
    write_json_atomic(manifest_path, manifest)

    before = _attack_snapshot(root, manifest_path, outside)
    with pytest.raises(rename_state.RenameStateError):
        rename_state.revert(root)
    assert _attack_snapshot(root, manifest_path, outside) == before


def test_revert_refuses_stage_backup_outside_manifest_dir(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    _make_tree(root)
    rename_state.migrate(root, no_qdrant=True)

    manifest_path = root / ".rename_state" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    for step in manifest["steps"]:
        if step["kind"] == "stage":
            step["backup"] = "lifecycle/birth_ack.json"
            break
    write_json_atomic(manifest_path, manifest)

    before = _attack_snapshot(root, manifest_path, outside)
    with pytest.raises(rename_state.RenameStateError):
        rename_state.revert(root)
    assert _attack_snapshot(root, manifest_path, outside) == before


def test_revert_refuses_qdrant_alias_pointing_elsewhere(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    _make_tree(tmp_path)
    qdrant = _FakeQdrant(["mnemos_episodic", "other"], {})
    rename_state.migrate(tmp_path, qdrant=qdrant)
    qdrant._aliases["episodic_memory_episodic"] = "other"

    manifest_path = tmp_path / ".rename_state" / "manifest.json"
    before = _attack_snapshot(tmp_path, manifest_path, outside)
    with pytest.raises(rename_state.RenameStateError):
        rename_state.revert(tmp_path, qdrant=qdrant)
    assert _attack_snapshot(tmp_path, manifest_path, outside) == before
    assert qdrant.aliases().get("episodic_memory_episodic") == "other"
