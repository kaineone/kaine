# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import json
import sqlite3

import pytest

from kaine import legacy_aliases
from kaine.lifecycle import decommission
from kaine.lifecycle.decommission import (
    _qdrant_api_key,
    capture_backup,
    clear_entity_streams,
    delete_entity_state,
    qdrant_in_use,
)
from kaine.lifecycle.divergence import DivergenceAssessment
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor

# This deployment keeps no memory in Qdrant (the runtime default is Qdrant).
_NO_QDRANT = {"episodic_memory": {"backend": "inmemory"}, "social_cognition": {"backend": "inmemory"}}


@pytest.fixture(autouse=True)
def _disable_encryption():
    """Run tests without state encryption so sidecars are readable."""
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield


def _assessment():
    return DivergenceAssessment(diverged=True, signals={"individuation_significant": True})


def test_backup_copies_new_locations_and_delete_removes_them(tmp_path):
    """Backup and delete handle every new entity location."""
    state_root = tmp_path / "state"
    data_root = tmp_path / "data"
    fork_root = state_root / "forks"
    out_root = tmp_path / "backups"
    for path in (
        state_root / "sleep" / "consolidation_divergence.json",
        state_root / "lifecycle" / "stage.json",
        state_root / "effectors" / "files" / "a.txt",
        state_root / "research" / "raw_bus_archive" / "x.jsonl",
        state_root / "vocal" / "u.wav",
        state_root / "cycle" / "incidents" / "i.jsonl",
        state_root / "cycle" / "control.json",
        data_root / "evaluation" / "welfare" / "w.jsonl",
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix == ".wav":
            path.write_bytes(b"\x00")
        else:
            path.write_text("x", encoding="utf-8")

    result = capture_backup(
        state_root=state_root,
        fork_root=fork_root,
        data_root=data_root,
        qdrant_cfg=_NO_QDRANT,
        out_root=out_root,
        entity_name="Kaine Nova",
        assessment=_assessment(),
    )
    assert result.ok
    bdir = result.backup_path
    assert (
        bdir / "locations" / "sleep.consolidation_divergence" / "sleep" / "consolidation_divergence.json"
    ).is_file()
    assert (bdir / "locations" / "lifecycle.development" / "lifecycle" / "stage.json").is_file()
    assert (bdir / "locations" / "effectors.files" / "effectors" / "files" / "a.txt").is_file()
    assert (
        bdir / "locations" / "research.raw_bus_archive" / "research" / "raw_bus_archive" / "x.jsonl"
    ).is_file()

    result = delete_entity_state(
        state_root=state_root,
        qdrant_cfg=_NO_QDRANT,
        fork_root=fork_root,
        data_root=data_root,
    )
    assert not (state_root / "sleep" / "consolidation_divergence.json").exists()
    assert not (state_root / "lifecycle" / "stage.json").exists()
    assert not (state_root / "effectors" / "files" / "a.txt").exists()
    assert not (state_root / "research" / "raw_bus_archive" / "x.jsonl").exists()
    assert not (state_root / "vocal" / "u.wav").exists()
    assert (state_root / "cycle" / "incidents" / "i.jsonl").exists()
    assert (state_root / "cycle" / "control.json").exists()
    assert (data_root / "evaluation" / "welfare" / "w.jsonl").exists()
    assert "cycle.incidents" in result.retained_locations


def test_sqlite_store_is_checkpointed_and_backed_up(tmp_path):
    """SQLite WAL files are checkpointed into the backup and removed with the store."""
    state_root = tmp_path / "state"
    db_dir = state_root / "episodic_memory"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "episodic_memory.db"

    conn1 = sqlite3.connect(str(db_path))
    conn1.execute("CREATE TABLE t (c TEXT)")
    conn1.execute("PRAGMA journal_mode=WAL")
    conn1.commit()
    conn1.execute("INSERT INTO t VALUES ('row1')")
    conn1.commit()

    conn2 = sqlite3.connect(str(db_path))
    conn2.execute("INSERT INTO t VALUES ('row2')")
    conn2.commit()
    conn2.close()
    conn1.close()

    result = capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        qdrant_cfg=_NO_QDRANT,
        out_root=tmp_path / "backups",
        entity_name="Kaine Nova",
        assessment=_assessment(),
    )
    assert result.ok
    backup_db = (
        result.backup_path / "locations" / "episodic_memory.sqlite" / "episodic_memory" / "episodic_memory.db"
    )
    assert backup_db.is_file()
    backed = sqlite3.connect(str(backup_db))
    rows = backed.execute("SELECT c FROM t").fetchall()
    assert set(rows) == {("row1",), ("row2",)}
    backed.close()

    delete_entity_state(state_root=state_root, qdrant_cfg=_NO_QDRANT)
    assert not db_path.exists()
    assert not (db_path.parent / (db_path.name + "-wal")).exists()
    assert not (db_path.parent / (db_path.name + "-shm")).exists()


def test_other_entity_fork_is_kept(tmp_path):
    """Only this entity's own forks are backed up and deleted."""
    state_root = tmp_path / "state"
    fork_root = state_root / "forks"
    from kaine.lifecycle.identity import mint_identity, save_identity, write_identity_sidecar

    identity = mint_identity()
    save_identity(identity, state_root / "identity" / "entity.json")
    own = fork_root / "own"
    other = fork_root / "other"
    for d in (own, other):
        d.mkdir(parents=True, exist_ok=True)
        (d / "snapshot.json").write_text(
            json.dumps({"id": d.name, "metadata": {}}), encoding="utf-8"
        )
    write_identity_sidecar(own, identity)
    other_identity = mint_identity()
    write_identity_sidecar(other, other_identity)

    result = capture_backup(
        state_root=state_root,
        fork_root=fork_root,
        qdrant_cfg=_NO_QDRANT,
        out_root=tmp_path / "backups",
        entity_name="Kaine Nova",
        assessment=_assessment(),
    )
    assert result.ok
    assert (
        result.backup_path / "locations" / "forks.own" / "forks" / "own" / "snapshot.json"
    ).is_file()
    assert not (result.backup_path / "locations" / "forks.other").exists()

    delete_entity_state(state_root=state_root, qdrant_cfg=_NO_QDRANT, fork_root=fork_root)
    assert not own.exists()
    assert other.exists()


def test_qdrant_in_use_and_api_key_resolution(tmp_path):
    """qdrant_in_use detects the backend and _qdrant_api_key resolves keys."""
    on = {"modules": {"episodic_memory": True}}
    assert qdrant_in_use({**on, "episodic_memory": {"backend": "qdrant"}}) is True
    # A module that is not enabled never counts, whatever its backend says.
    assert qdrant_in_use({"episodic_memory": {"backend": "qdrant"}}) is False
    assert qdrant_in_use({"modules": {"episodic_memory": False}, "episodic_memory": {"backend": "qdrant"}}) is False
    # An enabled module without a backend key uses the runtime default, Qdrant.
    assert qdrant_in_use({**on, "episodic_memory": {}}) is True
    assert qdrant_in_use({**on}) is True
    assert qdrant_in_use({**on, "episodic_memory": {"backend": "sqlite_vec"}}) is False
    # The module key from before the rename counts too.
    old_key = next(f for f in legacy_aliases.name_forms("episodic_memory") if f != "episodic_memory")
    assert qdrant_in_use({"modules": {old_key: True}}) is True
    # A module the tier does not support never counts.
    assert (
        qdrant_in_use(
            {
                "modules": {"social_cognition": True},
                "social_cognition": {"backend": "qdrant"},
                "tier": {"unsupported_modules": ["social_cognition"]},
            }
        )
        is False
    )
    assert qdrant_in_use(None) is False

    conn_key = {"api_key": "conn", "host": "h", "port": 1}
    assert _qdrant_api_key(conn_key, env={"KAINE_QDRANT_API_KEY": "env"}) == "conn"

    assert _qdrant_api_key({"host": "h"}, env={"KAINE_QDRANT_API_KEY": "env"}) == "env"

    assert _qdrant_api_key({"host": "h"}, env={}, secrets_path=tmp_path / "nope.toml") is None

    secrets = tmp_path / "secrets.toml"
    secrets.write_text('[qdrant]\napi_key = "fromfile"\n')
    assert _qdrant_api_key({"host": "h"}, env={}, secrets_path=secrets) == "fromfile"


def test_failed_qdrant_export_fails_the_backup(tmp_path, monkeypatch):
    """A Qdrant export error makes the whole backup fail."""
    state_root = tmp_path / "state"
    (state_root / "self_model").mkdir(parents=True, exist_ok=True)
    (state_root / "self_model" / "self_model.json").write_text("{}", encoding="utf-8")

    cfg = {"modules": {"episodic_memory": True}, "episodic_memory": {"backend": "qdrant"}}
    collection = decommission._episodic_memory_collection_names(cfg)[0]

    class FakeClient:
        def get_aliases(self):
            """No collection aliases (a store that was never renamed)."""
            from types import SimpleNamespace

            return SimpleNamespace(aliases=[])

        def get_collections(self):
            class Coll:
                pass

            c = Coll()
            c.name = collection

            class Resp:
                pass

            r = Resp()
            r.collections = [c]
            return r

        def scroll(self, **kwargs):
            raise RuntimeError("boom")

        def close(self):
            pass

    monkeypatch.setattr(decommission, "_qdrant_client", lambda _: FakeClient())
    result = capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        qdrant_cfg=cfg,
        out_root=tmp_path / "backups",
        entity_name="Kaine Nova",
        assessment=_assessment(),
    )
    assert not result.ok
    assert any("qdrant" in e.lower() for e in result.errors)


def test_shared_organ_volume_keeps_other_entities_files(tmp_path):
    """A shared organ directory only deletes files attributable to this entity."""
    state_root = tmp_path / "state"
    adapter_store = state_root / "sleep" / "adapters" / "a1"
    adapter_store.mkdir(parents=True, exist_ok=True)
    (adapter_store / "adapter.gguf").write_bytes(b"OWN-ADAPTER")
    organ = tmp_path / "organ"
    organ.mkdir(parents=True, exist_ok=True)
    (organ / "active-1.gguf").write_bytes(b"OWN-ADAPTER")
    (organ / "active-0.gguf").write_bytes(b"STUDY-ADAPTER")
    (organ / "active.json").write_text("{}", encoding="utf-8")

    result = capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg={
            **_NO_QDRANT,
            "sleep": {"voice_alignment": {"organ_adapters_dir": str(organ)}},
        },
        out_root=tmp_path / "backups",
        entity_name="Kaine Nova",
        assessment=_assessment(),
    )
    assert result.ok
    bdir = result.backup_path
    # The entity's own organ file is backed up; the other entity's is not.
    assert (bdir / "locations" / "organ_adapters.own" / "active-1.gguf").read_bytes() == b"OWN-ADAPTER"
    bundle_bytes = [p.read_bytes() for p in bdir.rglob("*") if p.is_file()]
    assert b"STUDY-ADAPTER" not in bundle_bytes

    delete_entity_state(
        state_root=state_root,
        qdrant_cfg={
            **_NO_QDRANT,
            "sleep": {"voice_alignment": {"organ_adapters_dir": str(organ)}},
        },
    )
    assert not (organ / "active-1.gguf").exists()
    assert (organ / "active-0.gguf").exists()
    assert (organ / "active.json").exists()
    assert organ.is_dir()


def test_rdb_snapshot_status_reported(tmp_path):
    """clear_entity_streams requests a fresh RDB snapshot when snapshots are on."""
    redis = pytest.importorskip("fakeredis")
    client = redis.FakeRedis()
    client.xadd("kaine:entity:stream", {"f": "v"})
    result = clear_entity_streams(client, ["kaine:entity:stream"], dry_run=False)
    assert result.rdb_snapshot is not None
