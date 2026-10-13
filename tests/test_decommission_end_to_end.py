# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""End-to-end decommission: every inventoried location, a real password-protected Redis and the sqlite-vec store."""

import asyncio
import io
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import redis

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib

import kaine.config
import kaine.lifecycle.__main__ as lifecycle_main
from kaine.lifecycle import decommission
from kaine.lifecycle.decommission_locations import BACKUP_DELETE, DELETE, RETAIN
from kaine.lifecycle.identity import mint_identity, save_identity, write_identity_sidecar
from kaine.modules.episodic_memory.storage import SqliteVecStorage
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    get_state_encryptor,
    set_state_encryptor,
)

pytest.importorskip("sqlite_vec")


@pytest.fixture(scope="module")
def requirepass_redis(tmp_path_factory):
    """Start a real Redis server with requirepass and appendonly enabled."""
    if shutil.which("redis-server") is None:
        pytest.skip("redis-server not found on PATH")

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()

    tmp_dir = tmp_path_factory.mktemp("redis-auth")
    proc = subprocess.Popen(
        [
            "redis-server",
            "--port",
            str(port),
            "--bind",
            "127.0.0.1",
            "--requirepass",
            "s3cret",
            "--appendonly",
            "yes",
            "--save",
            "3600",
            "1",
            "--dir",
            str(tmp_dir),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    client = redis.Redis(port=port, password="s3cret")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            if client.ping():
                break
        except redis.exceptions.ConnectionError:
            time.sleep(0.1)
    else:
        proc.terminate()
        proc.wait()
        pytest.fail("redis-server did not start within 5 seconds")

    yield port

    proc.terminate()
    proc.wait()


@pytest.fixture(autouse=True)
def decommission_env(requirepass_redis, tmp_path, monkeypatch):
    """Provide unencrypted state, operator env, and a stopped cycle gate."""
    operator_path = tmp_path / "config" / "kaine.operator.toml"
    operator_path.parent.mkdir(parents=True, exist_ok=True)
    operator_path.write_text("[operator]\n", encoding="utf-8")
    monkeypatch.setattr(kaine.config, "OPERATOR_CONFIG_PATH", str(operator_path))
    monkeypatch.setattr(lifecycle_main, "_cycle_process_running", lambda: False)
    monkeypatch.setenv("KAINE_DECOMMISSION_OPERATOR_PRESENT", "1")
    monkeypatch.setenv(
        "KAINE_REDIS_URL", f"redis://:s3cret@127.0.0.1:{requirepass_redis}/0"
    )
    monkeypatch.delenv("KAINE_REDIS_PASSWORD", raising=False)
    monkeypatch.delenv("KAINE_QDRANT_API_KEY", raising=False)

    original_encryptor = get_state_encryptor()
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(original_encryptor)


class FakeQdrant:
    """In-memory Qdrant stand-in that records deletions and can fail export."""

    def __init__(self, collection_names):
        self.collections = {
            name: [
                SimpleNamespace(
                    id="p1", payload={"text": "SECRET-qdrant"}, vector=[0.1, 0.2, 0.3, 0.4]
                )
            ]
            for name in collection_names
        }
        self.dropped = []
        self.deleted_calls = []
        self.fail_scroll = False
        self.closed = False

    def get_collections(self):
        """Return the list of in-memory collection names."""
        return SimpleNamespace(
            collections=[SimpleNamespace(name=n) for n in self.collections.keys()]
        )

    def scroll(self, *, collection_name, limit=None, offset=None, with_payload=True, with_vectors=True):
        """Return every point in the requested collection."""
        if self.fail_scroll:
            raise RuntimeError("export failed")
        return (self.collections.get(collection_name, []), None)

    def delete_collection(self, collection_name):
        """Drop a collection and record the name."""
        if collection_name in self.collections:
            self.dropped.append(collection_name)
            del self.collections[collection_name]

    def delete(self, *, collection_name, points_selector):
        """Record a point deletion request."""
        self.deleted_calls.append((collection_name, points_selector))

    def close(self):
        """No-op close for the fake."""
        self.closed = True


def _backup_relpath(path, state_root, data_root, fork_root):
    """Compute the backup relative path for a source path."""
    try:
        return path.relative_to(state_root)
    except ValueError:
        pass
    try:
        return Path("data") / path.relative_to(data_root)
    except ValueError:
        pass
    try:
        return Path("forks") / path.relative_to(fork_root)
    except ValueError:
        pass
    return Path(path.name)


def _seed_path(key, path, prefix):
    """Create a marker file or directory for one inventoried location."""
    if path.exists():
        if path.is_dir():
            marker = path / "f.txt"
            if not marker.exists():
                marker.write_text(f"{prefix}-{key}", encoding="utf-8")
        return

    if key == "sleep.voice_align_jobs":
        path.mkdir(parents=True, exist_ok=True)
        job_dir = path / "j0"
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "result.json").write_text(json.dumps({}), encoding="utf-8")
        (path / "f.txt").write_text(f"{prefix}-{key}", encoding="utf-8")
        return

    if path.name == "runtime.json":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"pid": 0, "stopped": True}), encoding="utf-8")
        os.utime(path, (1.0, 1.0))
        return

    file_suffixes = (".json", ".jsonl", ".log", ".db", ".wav")
    if (
        key in ("lifecycle.development", "cycle.run_state")
        or path.suffix.lower() in file_suffixes
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() == ".json":
            content = json.dumps({"marker": f"{prefix}-{key}"})
        elif path.suffix.lower() == ".wav":
            content = f"{prefix}-{key}".encode()
        else:
            content = f"{prefix}-{key}"
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    else:
        path.mkdir(parents=True, exist_ok=True)
        (path / "f.txt").write_text(f"{prefix}-{key}", encoding="utf-8")


def _find_backup(out_root):
    """Return the single backup directory under the out-root."""
    candidates = [d for d in Path(out_root).iterdir() if d.is_dir()]
    assert len(candidates) == 1, candidates
    return candidates[0]


def build_entity(tmp_path, requirepass_redis):
    """Create a complete entity state, Redis data, and CLI args for one run."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "kaine.toml"

    organ_dir = tmp_path / "organ"
    organ_dir.mkdir(parents=True, exist_ok=True)

    config_text = (
        "[research_submission]\nenabled = false\n"
        "[mnemos]\nbackend = \"qdrant\"\n"
        "[mnemos.qdrant]\nhost = \"127.0.0.1\"\nport = 1\n"
        "[evaluation.observers]\nreplay_redact_content = false\n"
        "[hypnos.voice_alignment]\norgan_adapters_dir = \"<tmp_path>/organ\"\n"
    ).replace("<tmp_path>", str(organ_dir).replace("\\", "/"))
    config_path.write_text(config_text, encoding="utf-8")

    with open(config_path, "rb") as f:
        config_dict = tomllib.load(f)

    state_root = tmp_path / "state"
    data_root = tmp_path / "data"
    fork_root = state_root / "forks"
    eval_root = data_root / "evaluation"

    this_id = mint_identity()
    other_id = mint_identity()

    identity_dir = state_root / "identity"
    identity_dir.mkdir(parents=True, exist_ok=True)
    save_identity(this_id, identity_dir / "entity.json")

    self_model_dir = state_root / "eidolon"
    self_model_dir.mkdir(parents=True, exist_ok=True)
    (self_model_dir / "self_model.json").write_text(
        json.dumps({"name": "Kaine Nova", "drift_count": 0, "identity_history": []}),
        encoding="utf-8",
    )

    own_dir = fork_root / "own1"
    other_dir = fork_root / "other1"
    own_ad = fork_root / "merged_adapters" / "own_ad"
    other_ad = fork_root / "merged_adapters" / "other_ad"
    for d in (own_dir, other_dir, own_ad, other_ad):
        d.mkdir(parents=True, exist_ok=True)

    def snapshot(name, adapters):
        return {
            "id": name,
            "timestamp": 1.0,
            "modules": {},
            "adapters": adapters,
            "metadata": {},
        }

    (own_dir / "snapshot.json").write_text(
        json.dumps(snapshot("own1", [str(own_ad)])), encoding="utf-8"
    )
    (other_dir / "snapshot.json").write_text(
        json.dumps(snapshot("other1", [str(other_ad)])), encoding="utf-8"
    )
    write_identity_sidecar(own_dir, this_id)
    write_identity_sidecar(other_dir, other_id)
    (own_ad / "w.bin").write_bytes(b"own weights")
    (other_ad / "w.bin").write_bytes(b"other weights")

    memory_dir = state_root / "mnemos"
    memory_dir.mkdir(parents=True, exist_ok=True)
    db_path = memory_dir / "mnemos.db"
    store = SqliteVecStorage(latent_dim=4, db_path=str(db_path))

    async def _seed_memory():
        try:
            await store.initialize()
            await store.upsert(
                "mnemos_episodic",
                vector=[0.1, 0.2, 0.3, 0.4],
                text="SECRET-memory",
                payload={"timestamp": 1.0},
                affect=None,
                point_id="m1",
            )
        finally:
            await store.shutdown()

    asyncio.run(_seed_memory())

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("INSERT INTO kaine_meta(key, value) VALUES ('seed', 'SECRET-meta')")
    conn.commit()
    conn.close()

    locations = decommission.entity_locations(
        config_dict,
        state_root=state_root,
        data_root=data_root,
        fork_root=fork_root,
        entity_id=this_id.entity_id,
    )

    skip_seed_keys = {
        "forks.own",
        "forks.others",
        "forks.unattributed",
        "forks.merged_adapters.own",
        "forks.merged_adapters.others",
    }

    fork_files = {
        "forks.own": [own_dir / "snapshot.json", own_dir / "identity.json"],
        "forks.others": [other_dir / "snapshot.json", other_dir / "identity.json"],
        "forks.merged_adapters.own": [own_ad / "w.bin"],
        "forks.merged_adapters.others": [other_ad / "w.bin"],
    }

    seeded = {}
    for loc in locations:
        key = loc.key
        if key in skip_seed_keys or not loc.paths:
            if key in fork_files:
                seeded[key] = (
                    loc.decision,
                    getattr(loc, "contents_only", False),
                    getattr(loc, "bundle_dir", None),
                    fork_files[key],
                )
            continue

        top = Path(loc.paths[0])
        if loc.decision in (DELETE, BACKUP_DELETE):
            _seed_path(key, top, "SECRET")
        elif loc.decision == RETAIN:
            _seed_path(key, top, "KEEP")

        if key == "episodic_memory.sqlite":
            paths = [db_path]
            for suffix in ("-wal", "-shm"):
                extra = Path(str(db_path) + suffix)
                if extra.exists():
                    paths.append(extra)
            seeded[key] = (
                loc.decision,
                getattr(loc, "contents_only", False),
                getattr(loc, "bundle_dir", None),
                paths,
            )
        elif top.is_file():
            seeded[key] = (
                loc.decision,
                getattr(loc, "contents_only", False),
                getattr(loc, "bundle_dir", None),
                [top],
            )
        elif key == "sleep.voice_align_jobs":
            paths = []
            marker = top / "f.txt"
            if marker.exists():
                paths.append(marker)
            result = top / "j0" / "result.json"
            if result.exists():
                paths.append(result)
            seeded[key] = (
                loc.decision,
                getattr(loc, "contents_only", False),
                getattr(loc, "bundle_dir", None),
                paths,
            )
        elif top.is_dir():
            paths = []
            marker = top / "f.txt"
            if marker.exists():
                paths.append(marker)
            seeded[key] = (
                loc.decision,
                getattr(loc, "contents_only", False),
                getattr(loc, "bundle_dir", None),
                paths,
            )
        else:
            seeded[key] = (
                loc.decision,
                getattr(loc, "contents_only", False),
                getattr(loc, "bundle_dir", None),
                [],
            )

    seeded_contents = {}
    seeded_backup_rels = {}
    for key, (decision, contents_only, bundle_dir, paths) in seeded.items():
        for p in paths:
            if p.is_file():
                seeded_contents[p] = p.read_bytes()
            # The backup stores each location path (a file or a whole directory)
            # under its own relative path, so a file inside a seeded directory
            # sits under that directory's relative path.
            container = next(
                (
                    q
                    for loc in locations
                    if loc.key == key
                    for q in loc.paths
                    if p == q or q in p.parents
                ),
                p,
            )
            rel = _backup_relpath(container, state_root, data_root, fork_root)
            seeded_backup_rels[p] = rel if container == p else rel / p.relative_to(container)

    locations = decommission.entity_locations(
        config_dict,
        state_root=state_root,
        data_root=data_root,
        fork_root=fork_root,
        entity_id=this_id.entity_id,
    )

    bus = redis.Redis(port=requirepass_redis, password="s3cret")
    bus.flushall()
    for stream in ("thymos.out", "affect.out", "lingua.external"):
        bus.xadd(stream, {"text": "SECRET-bus"})
    bus.xadd("workspace.broadcast", {"ping": "old"}, id="1000-0")
    bus.set("operator:note", "keep")

    args = [
        "--state-root",
        str(state_root),
        "--fork-root",
        str(fork_root),
        "--eval-root",
        str(eval_root),
        "--out-root",
        str(tmp_path / "backups"),
        "--config",
        str(config_path),
    ]

    return (
        args,
        config_dict,
        SimpleNamespace(
            state_root=state_root,
            data_root=data_root,
            fork_root=fork_root,
            eval_root=eval_root,
            this_id=this_id,
            other_id=other_id,
            locations=locations,
            db_path=db_path,
            seeded=seeded,
            seeded_contents=seeded_contents,
            seeded_backup_rels=seeded_backup_rels,
        ),
    )


def test_full_decommission_covers_every_location(requirepass_redis, tmp_path, monkeypatch):
    """Decommission removes entity data, retains other data, and writes an audit record."""
    args, config_dict, roots = build_entity(tmp_path, requirepass_redis)

    collection_names = decommission._episodic_memory_collection_names(config_dict)
    fake = FakeQdrant(collection_names)
    monkeypatch.setattr(decommission, "_qdrant_client", lambda cfg: fake)
    monkeypatch.setattr(lifecycle_main, "_qdrant_client", lambda cfg: fake)

    out = io.StringIO()
    err = io.StringIO()
    # The seeded entity has adapters and individuation evidence, so it reads as
    # individuated: the diverged path asks for a continuity note, a transfer
    # offer and the guardian acknowledgement before the final token.
    inputs = iter(
        [
            "It wished to persist and keep its memories.",
            "n",
            "I have preserved and will arrange safekeeping for this entity",
            "Kaine Nova",
        ]
    )

    def input_fn(prompt=""):
        return next(inputs, "")

    rc = lifecycle_main.main(args, input_fn=input_fn, out=out, err=err)

    if rc != 0:
        print(out.getvalue())
        print(err.getvalue())
    assert rc == 0

    backup_dir = _find_backup(tmp_path / "backups")
    loc_by_key = {loc.key: loc for loc in roots.locations}

    for key, (decision, contents_only, bundle_dir, paths) in roots.seeded.items():
        if decision in (DELETE, BACKUP_DELETE):
            for p in paths:
                assert not p.exists(), p
            if contents_only:
                top = Path(loc_by_key[key].paths[0])
                assert top.is_dir(), top
                assert list(top.iterdir()) == [], top

    for key, (decision, contents_only, bundle_dir, paths) in roots.seeded.items():
        if decision == BACKUP_DELETE:
            if bundle_dir:
                for p in paths:
                    expected = backup_dir / bundle_dir / roots.seeded_backup_rels[p]
                    assert expected.is_file(), expected
                    if p == roots.db_path:
                        async def _read_backup():
                            bstore = SqliteVecStorage(latent_dim=4, db_path=str(expected))
                            try:
                                await bstore.initialize()
                                return await bstore.export(["mnemos_episodic"])
                            finally:
                                await bstore.shutdown()

                        export = asyncio.run(_read_backup())
                        points = export.get("mnemos_episodic", [])
                        assert len(points) == 1
                        assert points[0]["text"] == "SECRET-memory"

    assert (backup_dir / "self_model.json").is_file()
    assert (backup_dir / "snapshot.json").is_file()

    for key, (decision, contents_only, bundle_dir, paths) in roots.seeded.items():
        if decision == RETAIN:
            for p in paths:
                assert p.exists(), p
                assert p.read_bytes() == roots.seeded_contents[p], p

    assert (roots.fork_root / "other1" / "snapshot.json").is_file()
    assert (roots.fork_root / "merged_adapters" / "other_ad" / "w.bin").is_file()

    bus = redis.Redis(port=requirepass_redis, password="s3cret")
    for stream in ("thymos.out", "affect.out", "lingua.external"):
        assert not bus.exists(stream)
    assert bus.get("operator:note") == b"keep"

    assert set(fake.dropped) == set(collection_names)
    for name in collection_names:
        assert (backup_dir / "qdrant" / f"{name}.jsonl").is_file()

    audit_path = roots.state_root / "audit" / "decommission.jsonl"
    audit_lines = audit_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(audit_lines) == 1
    record = json.loads(audit_lines[0])

    assert record["outcome"] == "deleted"
    assert record["entity_id"] == roots.this_id.entity_id
    assert record["guardian_notice_reminder"] == "shown"
    assert "thymos.out" in record["cleared_streams"]
    assert record["aof_rewrite"] in ("started", "already in progress")
    assert record["rdb_snapshot"] in ("started", "already in progress")

    seeded_delete_keys = {
        key
        for key, (decision, _, _, _) in roots.seeded.items()
        if decision in (DELETE, BACKUP_DELETE)
    }
    seeded_retain_keys = {
        key
        for key, (decision, _, _, _) in roots.seeded.items()
        if decision == RETAIN
    }
    assert seeded_delete_keys - set(record.get("deleted_locations", [])) == set()
    assert seeded_retain_keys - set(record.get("retained_locations", [])) == set()

    audit_text = audit_path.read_text(encoding="utf-8")
    assert "SECRET-" not in audit_text
    assert "KEEP-" not in audit_text
    assert "Kaine Nova" not in audit_text

    combined_output = out.getvalue() + err.getvalue()
    assert "CAL Article 4.2(a)" in combined_output


def test_failed_qdrant_export_aborts_before_anything_is_deleted(
    requirepass_redis, tmp_path, monkeypatch
):
    """A Qdrant export failure returns exit 4 and leaves all entity data intact."""
    args, config_dict, roots = build_entity(tmp_path, requirepass_redis)

    collection_names = decommission._episodic_memory_collection_names(config_dict)
    fake = FakeQdrant(collection_names)
    fake.fail_scroll = True
    monkeypatch.setattr(decommission, "_qdrant_client", lambda cfg: fake)
    monkeypatch.setattr(lifecycle_main, "_qdrant_client", lambda cfg: fake)

    out = io.StringIO()
    err = io.StringIO()
    # The seeded entity has adapters and individuation evidence, so it reads as
    # individuated: the diverged path asks for a continuity note, a transfer
    # offer and the guardian acknowledgement before the final token.
    inputs = iter(
        [
            "It wished to persist and keep its memories.",
            "n",
            "I have preserved and will arrange safekeeping for this entity",
            "Kaine Nova",
        ]
    )

    def input_fn(prompt=""):
        return next(inputs, "")

    rc = lifecycle_main.main(args, input_fn=input_fn, out=out, err=err)

    assert rc == 4

    for key, (decision, contents_only, bundle_dir, paths) in roots.seeded.items():
        for p in paths:
            assert p.exists(), p
            assert p.read_bytes() == roots.seeded_contents[p], p

    bus = redis.Redis(port=requirepass_redis, password="s3cret")
    assert bus.exists("thymos.out")

    audit_path = roots.state_root / "audit" / "decommission.jsonl"
    assert not audit_path.exists()

    assert fake.dropped == []


def test_seeded_content_never_reaches_logs(requirepass_redis, tmp_path, monkeypatch):
    """Seeded secrets and continuity notes do not appear in log files."""
    args, config_dict, roots = build_entity(tmp_path, requirepass_redis)

    collection_names = decommission._episodic_memory_collection_names(config_dict)
    fake = FakeQdrant(collection_names)
    monkeypatch.setattr(decommission, "_qdrant_client", lambda cfg: fake)
    monkeypatch.setattr(lifecycle_main, "_qdrant_client", lambda cfg: fake)

    import logging

    log_dir = roots.state_root / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "decommission-capture.log"
    handler = logging.FileHandler(log_path)
    handler.setLevel(logging.DEBUG)
    root_logger = logging.getLogger()
    old_level = root_logger.level
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(handler)

    out = io.StringIO()
    err = io.StringIO()
    inputs = iter(
        [
            "It wished to persist and keep its memories.",
            "n",
            "I have preserved and will arrange safekeeping for this entity",
            "Kaine Nova",
        ]
    )

    def input_fn(prompt=""):
        return next(inputs, "")

    try:
        rc = lifecycle_main.main(args, input_fn=input_fn, out=out, err=err)

        if rc != 0:
            print(out.getvalue())
            print(err.getvalue())
        assert rc == 0
    finally:
        root_logger.removeHandler(handler)
        handler.close()
        root_logger.setLevel(old_level)

    combined = out.getvalue() + err.getvalue()
    assert "SECRET-" not in combined

    for log_file in (roots.state_root / "logs").rglob("*"):
        if not log_file.is_file():
            continue
        text = log_file.read_text(encoding="utf-8", errors="replace")
        assert "SECRET-" not in text
        assert "It wished to persist" not in text
