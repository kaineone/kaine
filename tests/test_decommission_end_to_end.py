# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""End-to-end decommission with a hand-written path inventory and a real password-protected Redis."""

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
from kaine.lifecycle.identity import mint_identity, save_identity, write_identity_sidecar
from kaine.lifecycle.snapshot import ForkSnapshot, save_snapshot
from kaine.modules.episodic_memory.storage import SqliteVecStorage
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    get_state_encryptor,
    set_state_encryptor,
)

if os.environ.get("KAINE_REQUIRE_REDIS_SERVER") == "1":
    # CI installs the memory-edge extra; a missing sqlite_vec there is an error, not a skip.
    import sqlite_vec  # noqa: F401
else:
    pytest.importorskip("sqlite_vec")


@pytest.fixture(scope="module")
def requirepass_redis(tmp_path_factory):
    """Start a real Redis server with requirepass and appendonly enabled."""
    if shutil.which("redis-server") is None:
        if os.environ.get("KAINE_REQUIRE_REDIS_SERVER") == "1":
            pytest.fail("redis-server not found on PATH; KAINE_REQUIRE_REDIS_SERVER=1 requires it")
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
    operator_path.write_text("[modules]\nmnemos = true\n", encoding="utf-8")
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


def _find_backup(out_root):
    """Return the single backup directory under the out-root."""
    candidates = [d for d in Path(out_root).iterdir() if d.is_dir()]
    assert len(candidates) == 1, candidates
    return candidates[0]


def build_entity(tmp_path, port):
    """Create a complete entity state, Redis data, and CLI args for one run."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    config_path = config_dir / "kaine.toml"

    state_root = tmp_path / "state"
    data_root = tmp_path / "data"
    fork_root = tmp_path / "forks"
    organ = tmp_path / "organ"
    organ.mkdir(parents=True, exist_ok=True)

    config_text = (
        "[research_submission]\nenabled = false\n"
        "[mnemos]\nbackend = \"qdrant\"\n"
        "[mnemos.qdrant]\nhost = \"127.0.0.1\"\nport = 1\n"
        "[evaluation.observers]\nreplay_redact_content = false\n"
        "[hypnos.voice_alignment]\norgan_adapters_dir = \"<organ>\"\n"
    ).replace("<organ>", organ.as_posix())
    config_path.write_text(config_text, encoding="utf-8")

    with open(config_path, "rb") as f:
        config_dict = tomllib.load(f)

    this_id = mint_identity()
    other_id = mint_identity()

    identity_path = state_root / "identity" / "entity.json"
    identity_path.parent.mkdir(parents=True, exist_ok=True)
    save_identity(this_id, identity_path)

    seeded = {}

    def _rel(path):
        return path.relative_to(tmp_path).as_posix()

    def _write(rel, fate):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if rel == "state/eidolon/self_model.json":
            # The CLI reads the entity's name from here for the confirmation token.
            content = json.dumps({"name": "Kaine Nova", "note": f"SECRET {rel}"}).encode()
        elif fate in ("backup", "delete"):
            content = f"SECRET {rel}".encode()
        else:
            content = f"KEEP {rel}".encode()
        path.write_bytes(content)
        seeded[rel] = (fate, content)

    backup_paths = [
        "state/eidolon/self_model.json",
        "state/eidolon/extra_notes.json",
        "state/self_model/self_model.json",
        "state/lingua/intent_expression.jsonl",
        "state/lingua/monologue.jsonl",
        "state/language/intent_expression.jsonl",
        "state/lingua/utterance_outcomes.jsonl",
        "state/language/voice_measures.jsonl",
        "state/hypnos/adapters/a1/adapter.bin",
        "state/sleep/adapters/a2/adapter.bin",
        "state/hypnos/consolidation_divergence.json",
        "state/sleep/consolidation_divergence.json",
        "state/phantasia/world_model.ckpt",
        "state/world_model/world_model.ckpt",
        "state/individuation/ledger_extra.json",
        "state/individuation/maturation_adapter.gguf",
        "state/lifecycle/stage.json",
        "state/lifecycle/gestation_progress.json",
        "state/lifecycle/development_progress.json",
        "state/lifecycle/birth_request.json",
        "state/lifecycle/maturation_request.json",
        "state/praxis/files/note.txt",
        "state/effectors/files/note2.txt",
        "state/praxis/notifications.log",
        "state/effectors/notifications.log",
        "state/hypnos/voice_align_jobs/job1/pairs.jsonl",
        "state/sleep/voice_align_jobs/job2/pairs.jsonl",
        "organ/active/adapter.gguf",
        "state/research/raw_bus_archive/2026-10-13.jsonl",
        "state/research/external_utterances/2026-10-13.jsonl",
    ]

    delete_paths = [
        "state/mnemos/store_health.json",
        "state/episodic_memory/store_health.json",
        "state/hypnos/organ_window.json",
        "state/sleep/organ_window.json",
        "state/vox/utt1.wav",
        "state/vocal/utt2.wav",
        "state/perception/desired.json",
        "state/perceptual_locus/runtime.json",
        "state/cycle/escalation.json",
        "state/preservation/divergence_edge.json",
        "data/evaluation/replay/r.jsonl",
    ]

    keep_paths = [
        "state/cycle/incidents/i.jsonl",
        "state/cycle/preservation/p.jsonl",
        "state/cycle/caretaker_ack.json",
        "state/cycle/override_audit.jsonl",
        "state/cycle/control.json",
        "state/lifecycle/spawn_acknowledgements.jsonl",
        "state/praxis/audit.log",
        "state/effectors/audit.log",
        "state/hypnos/voice_alignment_audit.jsonl",
        "state/sleep/voice_alignment_audit.jsonl",
        "data/evaluation/coherence/c.jsonl",
        "data/evaluation/welfare/w.jsonl",
        "data/ignition/i.jsonl",
        "data/nexus_record/n.jsonl",
        "state/logs/cycle.log",
    ]

    for rel in backup_paths:
        _write(rel, "backup")
    for rel in delete_paths:
        _write(rel, "delete")
    for rel in keep_paths:
        _write(rel, "keep")

    runtime_path = state_root / "cycle" / "runtime.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_path.write_text("{}", encoding="utf-8")
    past = time.time() - 3600
    os.utime(runtime_path, (past, past))
    seeded["state/cycle/runtime.json"] = ("delete", b"{}")

    seeded[_rel(identity_path)] = ("backup", identity_path.read_bytes())

    own_ad = fork_root / "merged_adapters" / "own_ad"
    other_ad = fork_root / "merged_adapters" / "other_ad"
    own_ad.mkdir(parents=True, exist_ok=True)
    other_ad.mkdir(parents=True, exist_ok=True)
    _write("forks/merged_adapters/own_ad/w.bin", "backup")
    _write("forks/merged_adapters/other_ad/w.bin", "keep")

    save_snapshot(
        fork_root,
        ForkSnapshot(
            id="own1",
            adapters=[str(own_ad)],
            metadata={"identity": {"entity_id": this_id.entity_id}},
        ),
    )
    save_snapshot(
        fork_root,
        ForkSnapshot(
            id="other1",
            adapters=[str(other_ad)],
            metadata={"identity": {"entity_id": other_id.entity_id}},
        ),
    )
    save_snapshot(fork_root, ForkSnapshot(id="loose1", adapters=[], metadata={}))
    write_identity_sidecar(fork_root / "own1", this_id)
    write_identity_sidecar(fork_root / "other1", other_id)

    for rel in ("forks/own1", "forks/other1", "forks/loose1"):
        for path in (tmp_path / rel).rglob("*"):
            if path.is_file():
                fate = "backup" if rel == "forks/own1" else "keep"
                seeded[_rel(path)] = (fate, path.read_bytes())

    old_name_db = state_root / "mnemos" / "mnemos.db"
    old_name_db.parent.mkdir(parents=True, exist_ok=True)
    store = SqliteVecStorage(latent_dim=4, db_path=str(old_name_db))

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

    episodic_db = state_root / "episodic_memory" / "episodic_memory.db"
    episodic_db.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(episodic_db))
    conn.execute("CREATE TABLE notes(text TEXT)")
    conn.execute("INSERT INTO notes(text) VALUES (?)", ("SECRET new-db",))
    conn.commit()
    conn.close()

    dbs = {_rel(old_name_db): "old", _rel(episodic_db): "new"}

    bus = redis.Redis(port=port, password="s3cret")
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
        str(data_root / "evaluation"),
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
            organ=organ,
            this_id=this_id,
            other_id=other_id,
            seeded=seeded,
            dbs=dbs,
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
    bundle_bytes = set()
    for path in backup_dir.rglob("*"):
        if path.is_file():
            bundle_bytes.add(path.read_bytes())

    for rel, (fate, content) in roots.seeded.items():
        path = tmp_path / rel
        if fate == "backup":
            assert not path.exists(), path
            assert content in bundle_bytes, rel
        elif fate == "delete":
            assert not path.exists(), path
            assert content not in bundle_bytes, rel
        else:
            assert path.exists(), path
            assert path.read_bytes() == content, path

    for rel in (
        "organ",
        "state/hypnos/voice_align_jobs",
        "state/sleep/voice_align_jobs",
    ):
        directory = tmp_path / rel
        assert directory.is_dir(), directory
        assert list(directory.iterdir()) == [], directory

    for db_rel in roots.dbs:
        db_path = tmp_path / db_rel
        for suffix in ("", "-wal", "-shm", "-journal"):
            extra = Path(str(db_path) + suffix)
            assert not extra.exists(), extra

    old_name_backup = [p for p in backup_dir.rglob("mnemos.db") if p.is_file()]
    assert len(old_name_backup) == 1, old_name_backup

    async def _read_old_name_backup():
        bstore = SqliteVecStorage(latent_dim=4, db_path=str(old_name_backup[0]))
        try:
            await bstore.initialize()
            return await bstore.export(["mnemos_episodic"])
        finally:
            await bstore.shutdown()

    export = asyncio.run(_read_old_name_backup())
    points = export.get("mnemos_episodic", [])
    assert len(points) == 1
    assert points[0]["text"] == "SECRET-memory"

    episodic_backup = [p for p in backup_dir.rglob("episodic_memory.db") if p.is_file()]
    assert len(episodic_backup) == 1, episodic_backup
    conn = sqlite3.connect(str(episodic_backup[0]))
    rows = conn.execute("SELECT text FROM notes").fetchall()
    conn.close()
    assert rows == [("SECRET new-db",)]

    assert set(fake.dropped) == set(collection_names)
    for name in collection_names:
        assert (backup_dir / "qdrant" / f"{name}.jsonl").is_file()

    bus = redis.Redis(port=requirepass_redis, password="s3cret")
    for stream in ("thymos.out", "affect.out", "lingua.external"):
        assert not bus.exists(stream)
    assert bus.get("operator:note") == b"keep"

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
    assert isinstance(record["deleted_locations"], list)
    assert record["deleted_locations"]
    assert "forks.others" in record["retained_locations"]

    audit_text = audit_path.read_text(encoding="utf-8")
    assert "SECRET" not in audit_text
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

    for rel, (fate, content) in roots.seeded.items():
        path = tmp_path / rel
        assert path.exists(), path
        assert path.read_bytes() == content, path

    for db_rel in roots.dbs:
        assert (tmp_path / db_rel).exists()

    bus = redis.Redis(port=requirepass_redis, password="s3cret")
    assert bus.exists("thymos.out")

    audit_path = roots.state_root / "audit" / "decommission.jsonl"
    assert not audit_path.exists()

    assert fake.dropped == []


def test_seeded_content_never_reaches_logs(requirepass_redis, tmp_path, monkeypatch):
    """Seeded secrets and continuity notes do not appear in log files."""
    import logging

    args, config_dict, roots = build_entity(tmp_path, requirepass_redis)

    collection_names = decommission._episodic_memory_collection_names(config_dict)
    fake = FakeQdrant(collection_names)
    monkeypatch.setattr(decommission, "_qdrant_client", lambda cfg: fake)
    monkeypatch.setattr(lifecycle_main, "_qdrant_client", lambda cfg: fake)

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
    assert "SECRET" not in combined

    for log_file in (roots.state_root / "logs").rglob("*"):
        if not log_file.is_file():
            continue
        text = log_file.read_text(encoding="utf-8", errors="replace")
        assert "SECRET" not in text
        assert "It wished to persist" not in text
