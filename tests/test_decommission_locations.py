# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import base64
import json
import os
import sqlite3
import uuid
from pathlib import Path

from kaine.lifecycle import decommission_locations as dl
from kaine.lifecycle import identity as identity_mod
from kaine.lifecycle.snapshot import ForkSnapshot, save_snapshot
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor

SIDECAR_NAME = getattr(identity_mod, "SIDECAR_NAME", "identity.json")


def _make_id() -> str:
    return "ent-" + uuid.uuid4().hex


def test_every_inventoried_location_has_a_decision(tmp_path):
    """Every known location has a valid decommission decision and correct backup bundle naming."""
    state_root = tmp_path / "state"
    data_root = tmp_path / "data"
    fork_root = tmp_path / "forks"
    locations = dl.entity_locations(
        None,
        state_root=state_root,
        data_root=data_root,
        fork_root=fork_root,
        entity_id=None,
    )
    keys = [loc.key for loc in locations]
    for expected in (
        "episodic_memory.sqlite",
        "identity",
        "research.raw_bus_archive",
        "organ_adapters.own",
        "organ_adapters.shared",
        "cycle.incidents",
        "evaluation.welfare",
        "sleep.voice_jobs.own",
        "sleep.voice_jobs.shared",
        "forks.own",
        "forks.others",
    ):
        assert expected in keys, expected
    assert len(keys) == len(set(keys))
    for loc in locations:
        assert loc.decision in (dl.BACKUP_DELETE, dl.BACKUP_RETAIN, dl.DELETE, dl.RETAIN)
        if loc.decision == dl.BACKUP_DELETE:
            if loc.key == "individuation":
                assert loc.bundle_dir is None, loc.key
            else:
                assert loc.bundle_dir == f"locations/{loc.key}", loc.key


def test_config_paths_are_rebased(tmp_path):
    """Configured paths are rebased onto the provided runtime roots."""
    state_root = tmp_path / "state"
    data_root = tmp_path / "data"
    fork_root = tmp_path / "forks"
    config = {
        "episodic_memory": {"db_path": "state/mem/m.db"},
        "vocal": {"sink_path": "/abs/vox"},
    }
    locs = {
        loc.key: loc
        for loc in dl.entity_locations(
            config,
            state_root=state_root,
            data_root=data_root,
            fork_root=fork_root,
            entity_id=None,
        )
    }
    db = state_root / "mem" / "m.db"
    assert db in locs["episodic_memory.sqlite"].paths
    assert db.parent / "m.db-wal" in locs["episodic_memory.sqlite"].paths
    assert db.parent / "m.db-shm" in locs["episodic_memory.sqlite"].paths
    assert locs["vocal.audio"].paths == (Path("/abs/vox"),)


def test_module_forms_cover_renamed_directories(tmp_path):
    """Module paths include every known alias so renamed directories are covered."""
    state_root = tmp_path / "state"
    data_root = tmp_path / "data"
    fork_root = tmp_path / "forks"
    locs = {
        loc.key: loc
        for loc in dl.entity_locations(
            None,
            state_root=state_root,
            data_root=data_root,
            fork_root=fork_root,
            entity_id=None,
        )
    }
    assert state_root / "episodic_memory" / "mnemos.db" in locs["episodic_memory.sqlite"].paths


def test_replay_and_dashboard_record_follow_their_flags(tmp_path):
    """Replay and dashboard decisions follow their privacy flags."""
    state_root = tmp_path / "state"
    data_root = tmp_path / "data"
    fork_root = tmp_path / "forks"
    locs = {
        loc.key: loc
        for loc in dl.entity_locations(
            None,
            state_root=state_root,
            data_root=data_root,
            fork_root=fork_root,
            entity_id=None,
        )
    }
    assert locs["evaluation.replay"].decision == dl.RETAIN
    assert locs["dashboard.record"].decision == dl.RETAIN
    config = {
        "evaluation": {"observers": {"replay_redact_content": False}},
        "dashboard": {"dev_content_override": True},
    }
    locs2 = {
        loc.key: loc
        for loc in dl.entity_locations(
            config,
            state_root=state_root,
            data_root=data_root,
            fork_root=fork_root,
            entity_id=None,
        )
    }
    assert locs2["evaluation.replay"].decision == dl.DELETE
    assert locs2["dashboard.record"].decision == dl.DELETE


def test_snapshot_attribution(tmp_path):
    """Fork snapshots are attributed using sidecars and snapshot metadata."""
    e1 = _make_id()
    e2 = _make_id()
    fork_root = tmp_path / "forks"
    for name in ("a", "b", "c", "d", "merged_adapters"):
        (fork_root / name).mkdir(parents=True)

    (fork_root / "a" / SIDECAR_NAME).write_text(
        json.dumps({"entity_id": e1, "lineage": []})
    )
    (fork_root / "b" / SIDECAR_NAME).write_text(
        json.dumps({"entity_id": e2, "lineage": []})
    )

    for name in ("a", "b", "c", "d"):
        (fork_root / name / "snapshot.json").write_text(json.dumps({}))
    (fork_root / "c" / "snapshot.json").write_text(
        json.dumps({"metadata": {"identity": {"entity_id": e1}}})
    )

    own, others, unattributed = dl.attribute_snapshots(fork_root, e1)
    assert [p.name for p in own] == ["a", "c"]
    assert [p.name for p in others] == ["b"]
    assert [p.name for p in unattributed] == ["d"]

    own2, others2, unattributed2 = dl.attribute_snapshots(fork_root, None)
    assert own2 == []
    assert others2 == []
    assert set(p.name for p in unattributed2) == {"a", "b", "c", "d"}


def test_malformed_sidecar_is_unattributed(tmp_path):
    """A malformed identity sidecar makes a snapshot unattributed regardless of entity_id."""
    snap_dir = tmp_path / "snapshots" / "malformed"
    snap_dir.mkdir(parents=True)
    (snap_dir / "snapshot.json").write_text(json.dumps({"id": _make_id()}))
    (snap_dir / SIDECAR_NAME).write_text("{")

    own, others, unattributed = dl.attribute_snapshots(snap_dir.parent, entity_id=_make_id())
    assert snap_dir in unattributed
    assert not own and not others

    own, others, unattributed = dl.attribute_snapshots(snap_dir.parent, entity_id=None)
    assert snap_dir in unattributed
    assert not own and not others


def test_encrypted_snapshots_are_attributed_and_their_adapters_kept(tmp_path, monkeypatch):
    """Encrypted fork snapshots are still attributed and keep referenced adapters."""
    fork_root = tmp_path / "forks"
    merged_dir = fork_root / "merged_adapters"
    e1 = _make_id()
    e2 = _make_id()
    this_adapter = merged_dir / "this_adapter"
    other_adapter = merged_dir / "other_adapter"
    this_adapter.mkdir(parents=True)
    other_adapter.mkdir(parents=True)

    try:
        monkeypatch.setenv(
            "KAINE_STATE_KEY", base64.b64encode(os.urandom(32)).decode("ascii")
        )
        set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))
        save_snapshot(
            fork_root,
            ForkSnapshot(
                id="snap-this",
                adapters=[str(this_adapter)],
                metadata={"identity": {"entity_id": e1}},
            ),
        )
        save_snapshot(
            fork_root,
            ForkSnapshot(
                id="snap-other",
                adapters=[str(other_adapter)],
                metadata={"identity": {"entity_id": e2}},
            ),
        )

        # The snapshots really are encrypted on disk, so plain JSON parsing fails.
        assert not (fork_root / "snap-this" / "snapshot.json").read_bytes().lstrip().startswith(b"{")

        own, others, unattributed = dl.attribute_snapshots(fork_root, e1)
        assert [p.name for p in own] == ["snap-this"]
        assert [p.name for p in others] == ["snap-other"]
        assert unattributed == []

        own_adapters, kept_adapters = dl.attribute_merged_adapters(
            fork_root, own, others + unattributed
        )
        assert own_adapters == [this_adapter]
        assert kept_adapters == [other_adapter]
    finally:
        set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def test_unreadable_kept_snapshot_keeps_all_merged_adapters(tmp_path):
    """A kept snapshot with an unreadable snapshot.json keeps every merged adapter."""
    fork_root = tmp_path / "forks"
    merged_dir = fork_root / "merged_adapters"
    children = [merged_dir / f"adapter{i}" for i in range(3)]
    for child in children:
        child.mkdir(parents=True)
    snap_dir = fork_root / "kept"
    snap_dir.mkdir(parents=True)
    (snap_dir / "snapshot.json").write_text("not valid json")

    own_adapters, kept_adapters = dl.attribute_merged_adapters(fork_root, [], [snap_dir])
    assert own_adapters == []
    assert set(c.name for c in kept_adapters) == {c.name for c in children}


def test_merged_adapter_attribution(tmp_path):
    """Merged adapter directories are kept when referenced by a retained snapshot."""
    fork_root = tmp_path / "forks"
    fork_root.mkdir(parents=True, exist_ok=True)
    (fork_root / "own_snap").mkdir()
    (fork_root / "kept_snap").mkdir()
    for name in ("x", "y", "z"):
        (fork_root / "merged_adapters" / name).mkdir(parents=True)

    (fork_root / "own_snap" / "snapshot.json").write_text(
        json.dumps({"adapters": ["merged_adapters/x"]})
    )
    (fork_root / "kept_snap" / "snapshot.json").write_text(
        json.dumps({"adapters": ["merged_adapters/y"]})
    )

    own_adapters, kept_adapters = dl.attribute_merged_adapters(
        fork_root, [fork_root / "own_snap"], [fork_root / "kept_snap"]
    )
    assert [p.name for p in own_adapters] == ["x", "z"]
    assert [p.name for p in kept_adapters] == ["y"]


def test_checkpoint_sqlite_truncates_wal(tmp_path):
    """Checkpointing a WAL-mode database truncates or removes the WAL file."""
    db_path = tmp_path / "test.db"
    conn1 = sqlite3.connect(str(db_path))
    conn1.execute("PRAGMA journal_mode=WAL")
    conn1.execute("CREATE TABLE t (c)")
    conn1.executemany("INSERT INTO t VALUES (?)", [(1,), (2,)])
    conn1.commit()

    conn2 = sqlite3.connect(str(db_path))
    conn2.execute("SELECT count(*) FROM t").fetchall()

    wal_path = db_path.parent / (db_path.name + "-wal")
    assert wal_path.exists()
    conn2.close()

    assert dl.checkpoint_sqlite(db_path) is None
    if wal_path.exists():
        assert wal_path.stat().st_size == 0

    conn1.close()
    missing = tmp_path / "missing.db"
    assert dl.checkpoint_sqlite(missing) is None


def test_cancel_marks_pending_and_waits_for_claimed(tmp_path):
    """Cancellation marks pending jobs and waits for claimed jobs to finish."""
    jobs_dir = tmp_path / "jobs"
    for name in ("j1", "j2", "j3", "j4"):
        (jobs_dir / name).mkdir(parents=True)

    (jobs_dir / "j1" / "READY").write_text("")
    (jobs_dir / "j2" / "CLAIMED").write_text("")
    (jobs_dir / "j3" / "CLAIMED").write_text("")
    (jobs_dir / "j4" / "result.json").write_text("done")

    now = 0.0
    calls = 0

    def fake_monotonic():
        return now

    def fake_sleep(_seconds):
        nonlocal now, calls
        now += 1.0
        calls += 1
        if calls == 2:
            (jobs_dir / "j2" / "result.json").write_text("done")

    cancelled, still_running = dl.cancel_voice_alignment_jobs(
        jobs_dir, wait_s=5.0, poll_s=1.0, sleep=fake_sleep, monotonic=fake_monotonic
    )
    assert sorted(cancelled) == ["j1", "j2", "j3"]
    assert still_running == ["j3"]
    assert not (jobs_dir / "j4" / "CANCELLED").exists()
