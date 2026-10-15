# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for rename_state guard and durability behaviour."""

import json
import shutil
import sqlite3

import pytest

from kaine import legacy_names
from kaine.lifecycle import rename_state
from kaine.state_io import write_json_atomic
from tests.test_rename_state import _FakeQdrant, _make_tree, _snapshot


@pytest.fixture(autouse=True)
def _persisted_done(monkeypatch):
    monkeypatch.setitem(legacy_names.SCOPE_STATUS, "persisted", "done")


def _root_and_outside(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    outside.mkdir(parents=True, exist_ok=True)
    return root, outside


def _outside_snapshot(outside):
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


@pytest.mark.parametrize("after_work", [False, True])
@pytest.mark.parametrize("k", range(12))
def test_migrate_interrupted_then_rerun_then_revert(tmp_path, monkeypatch, after_work, k):
    root, _outside = _root_and_outside(tmp_path)
    _make_tree(root)
    n = len(rename_state.plan(root))
    if k >= n:
        pytest.skip(f"tree has {n} steps")
    before = _snapshot(root)

    restore = _interrupting(monkeypatch, "_run_step", k, after_work=after_work)
    with pytest.raises(KeyboardInterrupt):
        rename_state.migrate(root, no_qdrant=True)
    restore()

    result = rename_state.migrate(root, no_qdrant=True)
    assert result.status == "resumed"

    fresh = tmp_path / "fresh"
    _make_tree(fresh)
    rename_state.migrate(fresh, no_qdrant=True)
    assert _snapshot(root) == _snapshot(fresh)

    revert_result = rename_state.revert(root)
    assert revert_result.status == "reverted"
    assert not (root / ".rename_state").exists()
    assert _snapshot(root) == before


@pytest.mark.parametrize("after_work", [False, True])
@pytest.mark.parametrize("k", range(12))
def test_migrate_interrupted_then_revert(tmp_path, monkeypatch, after_work, k):
    root, _outside = _root_and_outside(tmp_path)
    _make_tree(root)
    n = len(rename_state.plan(root))
    if k >= n:
        pytest.skip(f"tree has {n} steps")
    before = _snapshot(root)

    restore = _interrupting(monkeypatch, "_run_step", k, after_work=after_work)
    with pytest.raises(KeyboardInterrupt):
        rename_state.migrate(root, no_qdrant=True)
    restore()

    revert_result = rename_state.revert(root)
    assert revert_result.status == "reverted"
    assert not (root / ".rename_state").exists()
    assert _snapshot(root) == before


@pytest.mark.parametrize("after_work", [False, True])
@pytest.mark.parametrize("k", range(12))
def test_migrate_interrupted_then_revert_interrupted_then_revert(
    tmp_path, monkeypatch, after_work, k
):
    root, _outside = _root_and_outside(tmp_path)
    _make_tree(root)
    n = len(rename_state.plan(root))
    if k >= n:
        pytest.skip(f"tree has {n} steps")
    before = _snapshot(root)

    restore = _interrupting(monkeypatch, "_run_step", k, after_work=after_work)
    with pytest.raises(KeyboardInterrupt):
        rename_state.migrate(root, no_qdrant=True)
    restore()

    for j in range(n):
        copy_root = tmp_path / f"copy_{j}"
        shutil.copytree(root, copy_root)
        restore_rev = _interrupting(monkeypatch, "_revert_step", j, after_work=after_work)
        with pytest.raises(KeyboardInterrupt):
            rename_state.revert(copy_root)
        restore_rev()

        final = rename_state.revert(copy_root)
        assert final.status == "reverted"
        assert not (copy_root / ".rename_state").exists()
        assert _snapshot(copy_root) == before


@pytest.mark.parametrize("after_work", [False, True])
@pytest.mark.parametrize("k", range(12))
def test_full_migrate_then_revert_interrupted_then_revert(tmp_path, monkeypatch, after_work, k):
    root, _outside = _root_and_outside(tmp_path)
    _make_tree(root)
    n = len(rename_state.plan(root))
    if k >= n:
        pytest.skip(f"tree has {n} steps")
    before = _snapshot(root)

    rename_state.migrate(root, no_qdrant=True)

    restore = _interrupting(monkeypatch, "_revert_step", k, after_work=after_work)
    with pytest.raises(KeyboardInterrupt):
        rename_state.revert(root)
    restore()

    final = rename_state.revert(root)
    assert final.status == "reverted"
    assert not (root / ".rename_state").exists()
    assert _snapshot(root) == before


def test_revert_refuses_before_any_write_when_stage_changed(tmp_path):
    root, _outside = _root_and_outside(tmp_path)
    _make_tree(root)
    fake = _FakeQdrant(["mnemos_episodic"], {})
    rename_state.migrate(root, qdrant=fake)

    stage_path = root / "lifecycle" / "stage.json"
    stage_path.write_text(json.dumps({"stage": "embodied"}, indent=2, sort_keys=True))

    before = _snapshot(root)
    manifest_path = root / ".rename_state" / "manifest.json"
    manifest_bytes = manifest_path.read_bytes()
    aliases = fake.aliases().copy()

    with pytest.raises(rename_state.RenameStateError):
        rename_state.revert(root, qdrant=fake)

    assert _snapshot(root) == before
    assert manifest_path.read_bytes() == manifest_bytes
    assert fake.aliases() == aliases


def test_revert_stage_never_restores_over_a_changed_file(tmp_path):
    root, _outside = _root_and_outside(tmp_path)
    _make_tree(root)
    rename_state.migrate(root, no_qdrant=True)

    stage_path = root / "lifecycle" / "stage.json"
    stage_path.write_text(json.dumps({"stage": "embodied"}, indent=2, sort_keys=True))

    manifest = json.loads((root / ".rename_state" / "manifest.json").read_bytes())
    stage_step = next(s for s in manifest["steps"] if s["kind"] == "stage")

    with pytest.raises(rename_state.RenameStateError):
        rename_state._revert_stage(root, stage_step)

    assert json.loads(stage_path.read_bytes()) == {"stage": "embodied"}


def test_run_stage_refuses_a_changed_file(tmp_path):
    root = tmp_path / "root"
    _make_tree(root)
    stage_step = next(s for s in rename_state.plan(root) if s["kind"] == "stage")
    stage_step["backup"] = None

    stage_path = root / "lifecycle" / "stage.json"
    renamed = {
        "development_started_at": "t0",
        "stage": "development",
        "stimulus_source_seed": 7,
    }
    stage_path.write_text(json.dumps(renamed, sort_keys=True, separators=(",", ":")))

    before_bytes = stage_path.read_bytes()

    with pytest.raises(rename_state.RenameStateError):
        rename_state._run_stage(root, stage_step)

    assert stage_path.read_bytes() == before_bytes


def test_sqlite_rewrite_rolls_back_mid_rebuild(tmp_path, monkeypatch):
    sqlite_vec = pytest.importorskip("sqlite_vec")
    root, _outside = _root_and_outside(tmp_path)
    _make_tree(root)

    db_path = root / "mnemos" / "mnemos.db"
    con = sqlite3.connect(str(db_path))
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

    con = sqlite3.connect(str(db_path))
    try:
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        before_memories = con.execute(
            "SELECT collection, point_id, text, payload, affect FROM memories ORDER BY rowid"
        ).fetchall()
        before_vec = con.execute(
            "SELECT rowid, collection, embedding FROM vec_memories ORDER BY rowid"
        ).fetchall()
    finally:
        con.close()

    def bad_rewrite(con2, pairs):
        con2.execute("DROP TABLE vec_memories")
        raise RuntimeError("boom")

    monkeypatch.setattr(rename_state, "_rewrite_vec_table", bad_rewrite)

    with pytest.raises(RuntimeError, match="boom"):
        rename_state._apply_sqlite_renames(
            db_path, [["mnemos_episodic", "episodic_memory_episodic"]], True
        )

    con = sqlite3.connect(str(db_path))
    try:
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        after_memories = con.execute(
            "SELECT collection, point_id, text, payload, affect FROM memories ORDER BY rowid"
        ).fetchall()
        after_vec = con.execute(
            "SELECT rowid, collection, embedding FROM vec_memories ORDER BY rowid"
        ).fetchall()
    finally:
        con.close()

    assert after_memories == before_memories
    assert after_vec == before_vec


def test_plan_refuses_state_file_pair(tmp_path):
    root, _outside = _root_and_outside(tmp_path)
    _make_tree(root)
    (root / "lifecycle" / "maturation_ack.json").write_text("ack")
    with pytest.raises(rename_state.RenameStateError, match="birth_ack.json") as exc_info:
        rename_state.plan(root)
    assert "maturation_ack.json" in str(exc_info.value)


def test_plan_refuses_companion_pair(tmp_path, monkeypatch):
    root, _outside = _root_and_outside(tmp_path)
    _make_tree(root)
    entry = {"old": "lifecycle/a.db", "new": "lifecycle/b.db", "scope": "persisted"}
    monkeypatch.setattr(legacy_names, "STATE_PATHS", (entry,))
    (root / "lifecycle" / "a.db").write_bytes(b"not sqlite")
    (root / "lifecycle" / "a.db-wal").write_bytes(b"wal")
    (root / "lifecycle" / "b.db-wal").write_bytes(b"wal2")

    with pytest.raises(rename_state.RenameStateError, match="a.db-wal") as exc_info:
        rename_state.plan(root)
    assert "b.db-wal" in str(exc_info.value)


def test_safe_path_refuses_a_symlinked_parent(tmp_path):
    root, outside = _root_and_outside(tmp_path)
    _make_tree(root)
    rename_state.migrate(root, no_qdrant=True)

    target_dir = outside / "target"
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "x").write_bytes(b"outside")

    link = root / "linkdir"
    link.symlink_to(target_dir, target_is_directory=True)

    manifest_path = root / ".rename_state" / "manifest.json"
    manifest = json.loads(manifest_path.read_bytes())
    first_move = next(s for s in manifest["steps"] if s["kind"] == "move")
    first_move["dst"] = "linkdir/x"
    first_move["created_dirs"] = []
    write_json_atomic(manifest_path, manifest)

    before = _outside_snapshot(outside)
    with pytest.raises(rename_state.RenameStateError):
        rename_state.revert(root)

    assert _outside_snapshot(outside) == before
    assert (target_dir / "x").read_bytes() == b"outside"


def test_vec_rows_keep_ids_and_embeddings_and_knn_works(tmp_path):
    sqlite_vec = pytest.importorskip("sqlite_vec")
    root, _outside = _root_and_outside(tmp_path)
    _make_tree(root)

    db_path = root / "mnemos" / "mnemos.db"
    con = sqlite3.connect(str(db_path))
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
            (2, "mnemos_episodic", sqlite_vec.serialize_float32([0.5, 0.6, 0.7, 0.8])),
            (3, "mnemos_semantic", sqlite_vec.serialize_float32([0.9, 0.8, 0.7, 0.6])),
        ]
        for rowid, collection, embedding in rows:
            con.execute(
                "INSERT INTO vec_memories (rowid, collection, embedding) VALUES (?, ?, ?)",
                (rowid, collection, embedding),
            )
        con.commit()
    finally:
        con.close()

    rename_state.migrate(root, no_qdrant=True)

    new_db = root / "episodic_memory" / "episodic_memory.db"
    con = sqlite3.connect(str(new_db))
    try:
        con.enable_load_extension(True)
        sqlite_vec.load(con)
        con.enable_load_extension(False)
        vec_rows = con.execute(
            "SELECT rowid, collection, embedding FROM vec_memories ORDER BY rowid"
        ).fetchall()
        query_vec = sqlite_vec.serialize_float32([0.1, 0.2, 0.3, 0.4])
        knn = con.execute(
            "SELECT rowid FROM vec_memories WHERE embedding MATCH ? AND collection = ? "
            "AND k = 2 ORDER BY distance",
            (query_vec, "episodic_memory_episodic"),
        ).fetchall()
    finally:
        con.close()

    expected = [
        (1, "episodic_memory_episodic", sqlite_vec.serialize_float32([0.1, 0.2, 0.3, 0.4])),
        (2, "episodic_memory_episodic", sqlite_vec.serialize_float32([0.5, 0.6, 0.7, 0.8])),
        (3, "episodic_memory_semantic", sqlite_vec.serialize_float32([0.9, 0.8, 0.7, 0.6])),
    ]
    assert vec_rows == expected
    assert [r[0] for r in knn] == [1, 2]


def test_plan_refuses_a_locked_database(tmp_path):
    root, _outside = _root_and_outside(tmp_path)
    _make_tree(root)
    db_path = root / "mnemos" / "mnemos.db"
    con = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        con.execute("BEGIN EXCLUSIVE")
        with pytest.raises(rename_state.RenameStateError, match="database") as exc_info:
            rename_state.plan(root)
        assert "mnemos.db" in str(exc_info.value)
    finally:
        con.execute("ROLLBACK")
        con.close()


def test_plan_refuses_a_hot_journal(tmp_path):
    root, _outside = _root_and_outside(tmp_path)
    _make_tree(root)
    (root / "mnemos" / "mnemos.db-journal").write_bytes(b"journal")

    with pytest.raises(
        rename_state.RenameStateError, match="cannot read the collections"
    ) as exc_info:
        rename_state.plan(root)
    assert "mnemos.db" in str(exc_info.value)


def test_plan_tolerates_a_database_without_memories(tmp_path):
    root, _outside = _root_and_outside(tmp_path)
    _make_tree(root)
    db_path = root / "mnemos" / "mnemos.db"
    db_path.unlink()
    con = sqlite3.connect(str(db_path))
    try:
        con.execute("CREATE TABLE other (x)")
        con.commit()
    finally:
        con.close()

    steps = rename_state.plan(root)
    assert not any(s["kind"] == "sqlite" for s in steps)


def test_manifest_fsynced_before_first_move(tmp_path, monkeypatch):
    if not rename_state.os.path.exists("/proc/self/fd"):
        pytest.skip("/proc/self/fd is unavailable")

    root, _outside = _root_and_outside(tmp_path)
    _make_tree(root)

    fsynced_paths: list[str] = []
    real_fsync = rename_state.os.fsync

    def capture_fsync(fd):
        path = rename_state.os.readlink(f"/proc/self/fd/{fd}")
        fsynced_paths.append(path)
        return real_fsync(fd)

    monkeypatch.setattr(rename_state.os, "fsync", capture_fsync)

    real_run_step = rename_state._run_step
    checked = False

    def wrapped(r, step, qdrant):
        nonlocal checked
        if not checked:
            assert any(p.endswith("/.rename_state/manifest.json.tmp") for p in fsynced_paths)
            assert any(p.endswith("/.rename_state") for p in fsynced_paths)
            checked = True
        return real_run_step(r, step, qdrant)

    monkeypatch.setattr(rename_state, "_run_step", wrapped)

    result = rename_state.migrate(root, no_qdrant=True)
    assert checked
    assert result.status in ("migrated", "resumed")


@pytest.mark.parametrize(
    "exc_class,args",
    [
        (PermissionError, ("denied",)),
        (sqlite3.OperationalError, ("locked",)),
        (ImportError, ("no sqlite_vec",)),
    ],
)
def test_main_reports_errors_without_traceback(tmp_path, monkeypatch, capsys, exc_class, args):
    root = tmp_path / "root"

    def fake_migrate(*a, **k):
        raise exc_class(*args)

    monkeypatch.setattr(rename_state, "migrate", fake_migrate)
    ret = rename_state.main([str(root), "--no-qdrant"])

    captured = capsys.readouterr()
    assert ret == 1
    lines = captured.err.strip().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith(f"kaine.lifecycle.rename_state: {exc_class.__name__}")
    assert "Traceback" not in captured.err


def test_write_json_durable_finishes_short_writes(tmp_path, monkeypatch):
    real_write = rename_state.os.write
    calls = 0

    def capped_write(fd, data):
        nonlocal calls
        calls += 1
        return real_write(fd, bytes(data)[:7])

    monkeypatch.setattr(rename_state.os, "write", capped_write)
    rename_state._write_json_durable(tmp_path / "m.json", {"a": "x" * 50})
    assert json.loads((tmp_path / "m.json").read_text()) == {"a": "x" * 50}
    assert calls > 1
