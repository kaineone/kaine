# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import base64
import json
import os
import shutil
from pathlib import Path

import pytest

from kaine import legacy_aliases
from kaine.config import load_runtime_config
from kaine.lifecycle import decommission
from kaine.lifecycle.decommission_locations import (
    cancel_voice_alignment_jobs,
    entity_locations,
)
from kaine.lifecycle.divergence import DivergenceAssessment
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    get_state_encryptor,
    set_state_encryptor,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
_NO_QDRANT = {"episodic_memory": {"backend": "inmemory"}, "social_cognition": {"backend": "inmemory"}}


@pytest.fixture(autouse=True)
def _reset_encryptor():
    """Disable encryption by default and restore the prior encryptor afterwards."""
    saved = get_state_encryptor()
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(saved)


def _seed(state_root, rel, content=None):
    p = state_root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content or f"SECRET {rel}", encoding="utf-8")
    return p


def test_tier0_profile_uses_no_qdrant(tmp_path, monkeypatch):
    """Tier 0 with no Qdrant endpoint never contacts Qdrant and finishes cleanly."""
    op = tmp_path / "op.toml"
    op.write_text("[modules]\nepisodic_memory = true\nsocial_cognition = true\n", encoding="utf-8")
    config = load_runtime_config(
        PROJECT_ROOT / "config" / "kaine.toml",
        op,
        env={"KAINE_TIER": "tier0"},
    )
    config["episodic_memory"].pop("qdrant", None)
    config["social_cognition"].pop("qdrant", None)
    assert config["tier"]["name"] == "tier0"
    assert decommission.qdrant_in_use(config) is False
    assert decommission.qdrant_endpoint_configured(config) is False

    def _no_qdrant(*args, **kwargs):
        raise AssertionError("Qdrant must not be contacted at tier 0")

    monkeypatch.setattr(decommission, "_qdrant_client", _no_qdrant)
    state_root = tmp_path / "state"
    _seed(state_root, "self_model/self_model.json")
    assessment = DivergenceAssessment(diverged=False, signals={}, summary="x")
    backup = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=config,
        out_root=tmp_path / "backups",
        entity_name="TierZero",
        assessment=assessment,
    )
    assert backup.ok
    result = decommission.delete_entity_state(
        state_root=state_root,
        qdrant_cfg=config,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        dry_run=False,
    )
    assert result.dropped_collections == []
    # No bus client here, so only the on-disk and Qdrant steps are judged.
    assert result.errors == []


def test_base_profile_with_memory_enabled_uses_qdrant(tmp_path):
    """The default base profile routes episodic memory to Qdrant when episodic memory is enabled."""
    op = tmp_path / "op.toml"
    op.write_text("[modules]\nepisodic_memory = true\n", encoding="utf-8")
    config = load_runtime_config(
        PROJECT_ROOT / "config" / "kaine.toml",
        op,
        env={},
    )
    assert decommission.qdrant_in_use(config) is True


def test_old_and_new_named_trees_are_backed_up_then_deleted(tmp_path, monkeypatch):
    """Old and new component names are both backed up then removed while audit logs are retained."""
    state_root = tmp_path / "state"
    backed_up_then_deleted = [
        "episodic_memory/episodic_memory.db",
        "episodic_memory/episodic_memory.db",
        "episodic_memory/episodic_memory.db-wal",
        "episodic_memory/episodic_memory.db-shm",
        "episodic_memory/episodic_memory.db-journal",
        "language/intent_expression.jsonl",
        "language/intent_expression.jsonl",
        "language/utterance_outcomes.jsonl",
        "language/utterance_outcomes.jsonl",
        "self_model/self_model.json",
        "self_model/self_model.json",
        "sleep/consolidation_divergence.json",
        "sleep/consolidation_divergence.json",
        "effectors/notifications.log",
        "effectors/notifications.log",
        "lifecycle/development_readout.json",
        "lifecycle/development_readout.json",
        "lifecycle/maturation_request.json",
        "lifecycle/maturation_request.json",
        "lifecycle/maturation_ack.json",
        "lifecycle/maturation_ack.json",
        "lifecycle/development_progress.json",
        "lifecycle/development_progress.json",
        "lifecycle/development_viability.json",
        "lifecycle/development_viability.json",
        "individuation/maturation_adapter.gguf",
        "individuation/maturation_adapter.gguf",
        "world_model/world_model.ckpt",
        "world_model/world_model.ckpt",
    ]
    deleted_without_backup = [
        "episodic_memory/store_health.json",
        "episodic_memory/store_health.json",
        "sleep/organ_window.json",
        "sleep/organ_window.json",
        "perception/desired.json",
        "perceptual_locus/desired.json",
    ]
    kept = [
        "effectors/audit.log",
        "effectors/audit.log",
    ]
    for rel in backed_up_then_deleted + deleted_without_backup + kept:
        _seed(state_root, rel)

    monkeypatch.setattr(decommission, "checkpoint_sqlite", lambda path: None)
    assessment = DivergenceAssessment(diverged=False, signals={}, summary="x")
    backup = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=_NO_QDRANT,
        out_root=tmp_path / "backups",
        entity_name="Renamed",
        assessment=assessment,
    )
    assert backup.ok
    bundle_texts = {
        p.read_text(errors="replace")
        for p in Path(backup.backup_path).rglob("*")
        if p.is_file()
    }
    for rel in backed_up_then_deleted:
        assert f"SECRET {rel}" in bundle_texts
    result = decommission.delete_entity_state(
        state_root=state_root,
        qdrant_cfg=_NO_QDRANT,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        dry_run=False,
    )
    assert result.errors == []
    for rel in backed_up_then_deleted + deleted_without_backup:
        assert not (state_root / rel).exists()
    for rel in kept:
        p = state_root / rel
        assert p.exists()
        assert p.read_text(encoding="utf-8") == f"SECRET {rel}"


def test_collection_names_cover_old_and_new_prefixes():
    """Episodic memory collection names include both legacy and current component names."""
    names = decommission._episodic_memory_collection_names({})
    assert "episodic_memory_episodic" in names
    assert "episodic_memory_episodic" in names
    assert "social_cognition_agents" in names
    assert "social_cognition_agents" in names
    assert len(names) == len(set(names))


def test_claimed_job_blocks_on_every_run(tmp_path):
    """A CLAIMED job is reported as still running even after a cancellation attempt."""
    jobs_dir = tmp_path / "jobs"
    j1 = jobs_dir / "j1"
    j1.mkdir(parents=True)
    (j1 / "CLAIMED").write_text("runner-1", encoding="utf-8")
    j2 = jobs_dir / "j2"
    j2.mkdir(parents=True)
    (j2 / "result.json").write_text("{}", encoding="utf-8")
    j3 = jobs_dir / "j3"
    j3.mkdir(parents=True)
    (j3 / "PENDING").write_text("", encoding="utf-8")

    clock = [0.0]

    def fake_sleep(dt):
        clock[0] += dt

    def fake_monotonic():
        return clock[0]

    cancelled, still_running = cancel_voice_alignment_jobs(
        jobs_dir, wait_s=1.0, poll_s=0.5, sleep=fake_sleep, monotonic=fake_monotonic
    )
    assert "j1" in cancelled
    assert "j1" in still_running
    assert "j2" not in cancelled
    assert "j2" not in still_running
    assert "j3" in cancelled
    assert "j3" not in still_running
    assert (j1 / "CANCELLED").exists()

    cancelled, still_running = cancel_voice_alignment_jobs(
        jobs_dir, wait_s=1.0, poll_s=0.5, sleep=fake_sleep, monotonic=fake_monotonic
    )
    assert "j1" not in cancelled
    assert "j1" in still_running


def test_permission_error_makes_deletion_incomplete(tmp_path, monkeypatch):
    """A permission error while removing a state directory marks deletion as incomplete."""
    state_root = tmp_path / "state"
    _seed(state_root, "self_model/self_model.json")
    _seed(state_root, "language/intent_expression.jsonl")
    real_rmtree = shutil.rmtree

    def guarded_rmtree(path, *args, **kwargs):
        if Path(path).name in legacy_aliases.name_forms("self_model"):
            raise PermissionError(path)
        return real_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(decommission.shutil, "rmtree", guarded_rmtree)
    result = decommission.delete_entity_state(
        state_root=state_root,
        qdrant_cfg=_NO_QDRANT,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        dry_run=False,
    )
    assert result.incomplete
    assert any(form in str(e) for form in legacy_aliases.name_forms("self_model") for e in result.errors)
    assert (state_root / "self_model").exists()
    assert not (state_root / "language").exists()


def test_failed_backup_purges_plaintext_when_encrypted(tmp_path, monkeypatch):
    """A failed backup removes all plaintext from the bundle when encryption is enabled."""
    key = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setenv("KAINE_STATE_KEY", key)
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))

    state_root = tmp_path / "state"
    _seed(state_root, "self_model/self_model.json", "SECRET self")
    _seed(state_root, "research/raw_bus_archive/a.jsonl", "SECRET bus")
    real_copytree = shutil.copytree

    def failing_copytree(src, dst, *args, **kwargs):
        if "raw_bus_archive" in str(src):
            raise OSError("disk full")
        return real_copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(decommission.shutil, "copytree", failing_copytree)
    assessment = DivergenceAssessment(diverged=False, signals={}, summary="x")
    result = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=_NO_QDRANT,
        out_root=tmp_path / "backups",
        entity_name="Encrypted",
        assessment=assessment,
    )
    assert not result.ok
    children = [p.name for p in Path(result.backup_path).iterdir()]
    assert children == ["BACKUP_FAILED.txt"]
    for p in Path(result.backup_path).rglob("*"):
        if p.is_file():
            assert "SECRET" not in p.read_text(errors="replace")


def test_failed_backup_hardens_permissions_when_unencrypted(tmp_path, monkeypatch):
    """A failed backup with encryption off restricts permissions on the bundle directory."""
    state_root = tmp_path / "state"
    _seed(state_root, "self_model/self_model.json", "SECRET self")
    _seed(state_root, "research/raw_bus_archive/a.jsonl", "SECRET bus")
    real_copytree = shutil.copytree

    def failing_copytree(src, dst, *args, **kwargs):
        if "raw_bus_archive" in str(src):
            raise OSError("disk full")
        return real_copytree(src, dst, *args, **kwargs)

    monkeypatch.setattr(decommission.shutil, "copytree", failing_copytree)
    assessment = DivergenceAssessment(diverged=False, signals={}, summary="x")
    result = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=_NO_QDRANT,
        out_root=tmp_path / "backups",
        entity_name="Unencrypted",
        assessment=assessment,
    )
    assert not result.ok
    bundle = Path(result.backup_path)
    assert (bundle.stat().st_mode & 0o777) == 0o700
    for p in bundle.rglob("*"):
        if p.is_dir():
            assert (p.stat().st_mode & 0o777) == 0o700
        elif p.is_file():
            assert (p.stat().st_mode & 0o777) == 0o600


def test_qdrant_probed_before_any_copy(tmp_path, monkeypatch):
    """Backup fails before copying state if Qdrant cannot be reached."""
    config = {"modules": {"episodic_memory": True}, "episodic_memory": {"backend": "qdrant"}}

    class BadQdrant:
        def get_aliases(self):
            """No collection aliases (a store that was never renamed)."""
            from types import SimpleNamespace

            return SimpleNamespace(aliases=[])

        def get_collections(self):
            raise ConnectionError("qdrant down")

        def close(self):
            pass

    monkeypatch.setattr(decommission, "_qdrant_client", lambda cfg: BadQdrant())
    state_root = tmp_path / "state"
    _seed(state_root, "self_model/self_model.json")
    assessment = DivergenceAssessment(diverged=False, signals={}, summary="x")
    result = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=config,
        out_root=tmp_path / "backups",
        entity_name="QdrantProbe",
        assessment=assessment,
    )
    assert not result.ok
    assert any("Qdrant" in str(e) for e in result.errors)
    assert not list((tmp_path / "backups").rglob("self_model.json"))


def test_trainer_workdir_is_backed_up_then_deleted(tmp_path):
    """Own voice alignment jobs are backed up and deleted; shared jobs are kept."""
    config = {
        **_NO_QDRANT,
        "sleep": {
            "voice_alignment": {
                "trainer_workdir": "state/train_work",
                "trainer_jobs_dir": "state/train_jobs",
            }
        },
    }
    state_root = tmp_path / "state"
    adapter_store = state_root / "sleep" / "adapters"
    adapter_store.mkdir(parents=True)
    _seed(state_root, "train_work/job1/pairs.jsonl", "SECRET pairs")
    _seed(state_root, "train_work/job1/job.json", json.dumps({"adapter_output_dir": str(adapter_store.resolve())}))
    _seed(state_root, "train_jobs/job2/spec.json", "{}")
    _seed(state_root, "train_jobs/job2/job.json", json.dumps({"adapter_output_dir": "/app/studies/s1/state/sleep/adapters"}))
    assessment = DivergenceAssessment(diverged=False, signals={}, summary="x")
    backup = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=config,
        out_root=tmp_path / "backups",
        entity_name="Trainer",
        assessment=assessment,
    )
    assert backup.ok
    bundle_texts = {
        p.read_text(errors="replace")
        for p in Path(backup.backup_path).rglob("*")
        if p.is_file()
    }
    assert "SECRET pairs" in bundle_texts
    result = decommission.delete_entity_state(
        state_root=state_root,
        qdrant_cfg=config,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        dry_run=False,
    )
    assert result.errors == []
    assert (state_root / "train_work").exists()
    assert (state_root / "train_jobs").exists()
    assert not (state_root / "train_work" / "job1").exists()
    assert (state_root / "train_jobs" / "job2").exists()
    assert (state_root / "train_jobs" / "job2" / "spec.json").exists()


def test_merged_adapters_follow_configured_output_dir(tmp_path):
    """Entity locations include merged adapters from the configured lifecycle output directory."""
    config = {"lifecycle": {"adapter_merge": {"output_dir": "state/merged_elsewhere"}}}
    state_root = tmp_path / "state"
    adapter_dir = state_root / "merged_elsewhere" / "a1"
    adapter_dir.mkdir(parents=True)
    (adapter_dir / "adapter.bin").write_text("adapter", encoding="utf-8")
    locations = entity_locations(
        config,
        state_root=state_root,
        data_root=tmp_path / "data",
        fork_root=tmp_path / "forks",
        entity_id="e1",
    )
    loc = next(
        (loc for loc in locations if loc.key == "forks.merged_adapters.own"), None
    )
    assert loc is not None
    assert adapter_dir in loc.paths


def test_delete_refuses_paths_outside_the_roots(tmp_path):
    """Delete refuses paths outside the declared roots except configured organ adapter directories."""
    outside = tmp_path / "elsewhere" / "files"
    outside.mkdir(parents=True)
    (outside / "sandboxed.bin").write_text("x", encoding="utf-8")
    config = {**_NO_QDRANT, "effectors": {"sandbox_path": str(outside)}}
    state_root = tmp_path / "state"
    _seed(state_root, "self_model/self_model.json")
    result = decommission.delete_entity_state(
        state_root=state_root,
        qdrant_cfg=config,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        dry_run=False,
    )
    assert (outside / "sandboxed.bin").exists()
    assert result.incomplete
    assert any(
        "outside the state, data and fork roots" in str(e) for e in result.errors
    )

    organ = tmp_path / "organ"
    organ.mkdir(parents=True)
    state_root2 = tmp_path / "state2"
    adapter_store2 = state_root2 / "sleep" / "adapters" / "a1"
    adapter_store2.mkdir(parents=True)
    (adapter_store2 / "adapter.gguf").write_bytes(b"OWN-ADAPTER")
    (organ / "active-1.gguf").write_bytes(b"OWN-ADAPTER")
    (organ / "organ.bin").write_text("y", encoding="utf-8")
    config2 = {
        **_NO_QDRANT,
        "sleep": {"voice_alignment": {"organ_adapters_dir": str(organ)}},
    }
    _seed(state_root2, "self_model/self_model.json")
    result2 = decommission.delete_entity_state(
        state_root=state_root2,
        qdrant_cfg=config2,
        fork_root=tmp_path / "forks2",
        data_root=tmp_path / "data2",
        dry_run=False,
    )
    assert result2.errors == []
    assert organ.exists()
    assert not (organ / "active-1.gguf").exists()
    assert (organ / "organ.bin").exists()


def test_symlink_in_shared_jobs_dir_is_kept_and_not_followed(tmp_path):
    """A directory symlink in a shared voice-jobs volume is kept and not followed."""
    outside = tmp_path / "shared" / "docs"
    outside.mkdir(parents=True)
    (outside / "keep.txt").write_text("KEEP", encoding="utf-8")
    jobs = tmp_path / "state" / "sleep" / "voice_align_jobs"
    jobs.mkdir(parents=True)
    (jobs / "escape").symlink_to(outside, target_is_directory=True)
    result = decommission.delete_entity_state(
        state_root=tmp_path / "state",
        qdrant_cfg=_NO_QDRANT,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        dry_run=False,
    )
    assert result.errors == []
    assert (jobs / "escape").is_symlink()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "KEEP"


class _NS:
    """Tiny attribute holder used instead of SimpleNamespace."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeQdrant:
    """In-memory Qdrant stand-in that records deletions and can fail export."""

    def __init__(self, collection_names):
        self.collections = {
            name: [
                _NS(
                    id="p1", payload={"text": "SECRET-qdrant"}, vector=[0.1, 0.2, 0.3, 0.4]
                )
            ]
            for name in collection_names
        }
        self.dropped = []
        self.deleted_calls = []
        self.fail_scroll = False
        self.closed = False

    def get_aliases(self):
        """No collection aliases (a store that was never renamed)."""
        from types import SimpleNamespace

        return SimpleNamespace(aliases=[])

    def get_collections(self):
        """Return the list of in-memory collection names."""
        return _NS(
            collections=[_NS(name=n) for n in self.collections.keys()]
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


def test_tier0_with_shipped_endpoint_and_reachable_qdrant_is_clean(tmp_path, monkeypatch):
    """Tier 0 keeps shipped endpoints but does not use Qdrant."""
    op = tmp_path / "op.toml"
    op.write_text("[modules]\nepisodic_memory = true\nsocial_cognition = true\n", encoding="utf-8")
    config = load_runtime_config(
        PROJECT_ROOT / "config" / "kaine.toml",
        op,
        env={"KAINE_TIER": "tier0"},
    )
    assert config["tier"]["name"] == "tier0"
    assert decommission.qdrant_in_use(config) is False
    assert decommission.qdrant_endpoint_configured(config) is True

    fake = _FakeQdrant([])
    monkeypatch.setattr(decommission, "_qdrant_client", lambda cfg: fake)
    state_root = tmp_path / "state"
    _seed(state_root, "self_model/self_model.json")
    assessment = DivergenceAssessment(diverged=False, signals={}, summary="x")
    backup = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=config,
        out_root=tmp_path / "backups",
        entity_name="TierZeroShipped",
        assessment=assessment,
    )
    assert backup.ok
    assert backup.qdrant_status == "exported"
    result = decommission.delete_entity_state(
        state_root=state_root,
        qdrant_cfg=config,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        dry_run=False,
    )
    assert result.dropped_collections == []
    assert result.errors == []


def test_module_off_collections_are_backed_up_then_dropped(tmp_path, monkeypatch):
    """Disabled module exports reachable Qdrant collections then drops them."""
    config = {"episodic_memory": {"backend": "qdrant", "qdrant": {"host": "127.0.0.1", "port": 1}}}
    assert decommission.qdrant_in_use(config) is False
    assert decommission.qdrant_endpoint_configured(config) is True

    names = decommission._episodic_memory_collection_names(config)
    fake = _FakeQdrant(names[:2])
    monkeypatch.setattr(decommission, "_qdrant_client", lambda cfg: fake)
    state_root = tmp_path / "state"
    _seed(state_root, "self_model/self_model.json")
    assessment = DivergenceAssessment(diverged=False, signals={}, summary="x")
    backup = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=config,
        out_root=tmp_path / "backups",
        entity_name="ModuleOff",
        assessment=assessment,
    )
    assert backup.ok
    assert backup.qdrant_status == "exported"
    for name in names[:2]:
        bundle = backup.backup_path / "qdrant" / f"{name}.jsonl"
        assert bundle.is_file()
        assert "SECRET-qdrant" in bundle.read_text(encoding="utf-8")
    result = decommission.delete_entity_state(
        state_root=state_root,
        qdrant_cfg=config,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        dry_run=False,
    )
    assert set(fake.dropped) == set(names[:2])
    assert result.errors == []


def test_module_off_unreachable_qdrant_fails_backup_and_absent_skips(tmp_path, monkeypatch):
    """Unreachable Qdrant fails the backup; qdrant_absent skips it entirely."""
    config = {"episodic_memory": {"backend": "qdrant", "qdrant": {"host": "127.0.0.1", "port": 1}}}
    assert decommission.qdrant_in_use(config) is False
    assert decommission.qdrant_endpoint_configured(config) is True

    monkeypatch.setattr(decommission, "_qdrant_client", lambda cfg: None)
    state_root = tmp_path / "state"
    _seed(state_root, "self_model/self_model.json")
    assessment = DivergenceAssessment(diverged=False, signals={}, summary="x")
    backup = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=config,
        out_root=tmp_path / "backups",
        entity_name="ModuleOffUnreachable",
        assessment=assessment,
    )
    assert backup.ok is False
    assert any("Qdrant" in err for err in backup.errors)
    backup_root = tmp_path / "backups"
    if backup_root.exists():
        assert not list(backup_root.rglob("self_model.json"))

    calls = []

    def recording_factory(cfg):
        calls.append(cfg)
        return None

    monkeypatch.setattr(decommission, "_qdrant_client", recording_factory)
    absent_backup = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=config,
        out_root=tmp_path / "backups2",
        entity_name="ModuleOffAbsent",
        assessment=assessment,
        qdrant_absent=True,
    )
    assert absent_backup.ok
    assert absent_backup.qdrant_status == "absent (asserted)"
    result = decommission.delete_entity_state(
        state_root=state_root,
        qdrant_cfg=config,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        dry_run=False,
        qdrant_absent=True,
    )
    assert result.errors == []
    assert calls == []


def test_allow_list_refuses_dangerous_entries(tmp_path):
    """Dangerous allow-list directories are refused and reported."""
    from kaine.lifecycle.decommission import delete_entity_state
    from kaine.lifecycle.decommission_locations import delete_roots

    state_root = tmp_path / "state"
    data_root = tmp_path / "data"
    fork_root = tmp_path / "forks"

    cases = [
        ("/", "the filesystem root"),
        ("/etc", "a top-level directory"),
        (str(Path.home()), "the home directory or an ancestor of it"),
        (str(tmp_path), "an ancestor of the state, data or fork root"),
    ]

    for path, expected_reason in cases:
        config = {"sleep": {"voice_alignment": {"trainer_workdir": path}}}
        roots, refused = delete_roots(
            config,
            state_root=state_root,
            data_root=data_root,
            fork_root=fork_root,
        )
        assert len(refused) == 1
        refused_path, reason = refused[0]
        assert str(refused_path) == path
        assert reason == expected_reason

    roots, refused = delete_roots(
        {},
        state_root=state_root,
        data_root=data_root,
        fork_root=fork_root,
    )
    assert refused == ()

    config = {
        "sleep": {"voice_alignment": {"organ_adapters_dir": "/organ-adapters"}}
    }
    roots, refused = delete_roots(
        config,
        state_root=state_root,
        data_root=data_root,
        fork_root=fork_root,
    )
    assert refused == ()

    config = {
        "sleep": {"voice_alignment": {"trainer_jobs_dir": "/trainer-jobs"}}
    }
    roots, refused = delete_roots(
        config,
        state_root=state_root,
        data_root=data_root,
        fork_root=fork_root,
    )
    assert refused == ()

    for path in ("/organ-adapters2", "/organ"):
        config = {"sleep": {"voice_alignment": {"organ_adapters_dir": path}}}
        roots, refused = delete_roots(
            config,
            state_root=state_root,
            data_root=data_root,
            fork_root=fork_root,
        )
        assert len(refused) == 1
        refused_path, reason = refused[0]
        assert str(refused_path) == path
        assert reason == "a top-level directory"

    config = {"sleep": {"voice_alignment": {"trainer_jobs_dir": "/trainer-jobs2"}}}
    roots, refused = delete_roots(
        config,
        state_root=state_root,
        data_root=data_root,
        fork_root=fork_root,
    )
    assert len(refused) == 1
    refused_path, reason = refused[0]
    assert str(refused_path) == "/trainer-jobs2"
    assert reason == "a top-level directory"

    qdrant_cfg = {
        **_NO_QDRANT,
        "sleep": {"voice_alignment": {"trainer_workdir": str(tmp_path)}},
    }
    result = delete_entity_state(
        state_root=state_root,
        data_root=data_root,
        fork_root=fork_root,
        qdrant_cfg=qdrant_cfg,
        dry_run=False,
    )
    assert result.incomplete is True
    assert any("refused allow-list entry" in err for err in result.errors)
    assert tmp_path.exists()


def test_backup_reports_probed_qdrant_collections(tmp_path, monkeypatch):
    """Backups report Qdrant collections, and output reflects checked and unchecked states."""
    import io

    from kaine.lifecycle.__main__ import _write_location_split

    config = {
        "episodic_memory": {
            "backend": "qdrant",
            "qdrant": {"host": "127.0.0.1", "port": 1},
        }
    }
    names = decommission._episodic_memory_collection_names(config)
    fake = _FakeQdrant(names[:2])
    monkeypatch.setattr(decommission, "_qdrant_client", lambda cfg: fake)

    state_root = tmp_path / "state"
    _seed(state_root, "self_model/self_model.json", content="{}")

    backup = decommission.capture_backup(
        qdrant_cfg=config,
        state_root=state_root,
        data_root=tmp_path / "data",
        fork_root=tmp_path / "forks",
        out_root=tmp_path / "backups",
        entity_name="Probed",
        assessment=DivergenceAssessment(diverged=False, signals={}, summary="x"),
    )
    assert backup.ok is True
    assert sorted(backup.qdrant_collections) == sorted(names[:2])

    manifest_path = backup.backup_path / "manifest.json"
    assert manifest_path.exists()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest.get("qdrant_collections") == backup.qdrant_collections

    out = io.StringIO()
    _write_location_split(
        out,
        config,
        state_root=state_root,
        data_dir=tmp_path / "data",
        fork_root=tmp_path / "forks",
        backup=backup,
    )
    out_text = out.getvalue()
    assert "Qdrant collections" in out_text
    assert names[0] in out_text

    # With --qdrant-absent asserted, Qdrant is skipped and the split says so.
    monkeypatch.setattr(decommission, "_qdrant_client", lambda cfg: None)
    absent_backup = decommission.capture_backup(
        qdrant_cfg=config,
        qdrant_absent=True,
        state_root=state_root,
        data_root=tmp_path / "data",
        fork_root=tmp_path / "forks",
        out_root=tmp_path / "backups_absent",
        entity_name="Absent",
        assessment=DivergenceAssessment(diverged=False, signals={}, summary="x"),
    )
    assert absent_backup.ok
    assert absent_backup.qdrant_status == "absent (asserted)"

    out2 = io.StringIO()
    _write_location_split(
        out2,
        config,
        state_root=state_root,
        data_dir=tmp_path / "data",
        fork_root=tmp_path / "forks",
        backup=absent_backup,
    )
    assert "Qdrant: skipped" in out2.getvalue()


def _store_adapter(state_root, name, data):
    """Write an adapter.gguf into this entity's adapter store and return its SHA-256."""
    import hashlib
    path = state_root / "sleep" / "adapters" / name / "adapter.gguf"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def test_shared_volumes_scoped_by_ownership(tmp_path):
    """Own organ and job entries are backed up and deleted; shared entries are kept."""
    state_root = tmp_path / "state"
    sha = _store_adapter(state_root, "a1", b"OWN-ADAPTER")
    organ = tmp_path / "organ"
    organ.mkdir(parents=True, exist_ok=True)
    (organ / "active-2.gguf").write_bytes(b"OWN-ADAPTER")
    (organ / "active.json").write_text(
        json.dumps({"file": "active-2.gguf", "sha256": sha, "generation": 2, "adapter_id": "a1"}),
        encoding="utf-8",
    )
    (organ / "active-1.gguf").write_bytes(b"STUDY-ADAPTER")
    (organ / "generation").write_text("2", encoding="utf-8")

    jobs = state_root / "sleep" / "voice_align_jobs"
    own_job = jobs / "own_job"
    own_job.mkdir(parents=True)
    (own_job / "job.json").write_text(
        json.dumps({"adapter_output_dir": str((state_root / "sleep" / "adapters").resolve())}),
        encoding="utf-8",
    )
    (own_job / "pairs.jsonl").write_text("SECRET own pairs", encoding="utf-8")

    study_job = jobs / "study_job"
    study_job.mkdir(parents=True)
    (study_job / "job.json").write_text(
        json.dumps({"adapter_output_dir": "out"}),
        encoding="utf-8",
    )
    (study_job / "pairs.jsonl").write_text("STUDY pairs", encoding="utf-8")
    (study_job / "out" / "x").mkdir(parents=True)
    (study_job / "out" / "x" / "adapter.gguf").write_bytes(b"STUDY-OUT")

    config = {
        **_NO_QDRANT,
        "sleep": {"voice_alignment": {"organ_adapters_dir": str(organ)}},
    }
    assessment = DivergenceAssessment(diverged=False, signals={}, summary="x")
    result = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=config,
        out_root=tmp_path / "backups",
        entity_name="Kaine Nova",
        assessment=assessment,
    )
    assert result.ok, result.errors
    backup_path = result.backup_path
    bundle_texts = {
        p.read_text(errors="replace")
        for p in backup_path.rglob("*")
        if p.is_file()
    }
    assert "OWN-ADAPTER" in bundle_texts
    assert "SECRET own pairs" in bundle_texts
    assert "STUDY-ADAPTER" not in bundle_texts
    assert "STUDY pairs" not in bundle_texts
    assert "STUDY-OUT" not in bundle_texts

    result = decommission.delete_entity_state(
        state_root=state_root,
        qdrant_cfg=config,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        dry_run=False,
    )
    assert result.errors == []
    # The live adapter named by active.json is backed up but kept.
    assert (organ / "active-2.gguf").read_bytes() == b"OWN-ADAPTER"
    assert (organ / "active.json").exists()
    assert not own_job.exists()
    assert (organ / "active-1.gguf").exists()
    assert (organ / "generation").exists()
    assert study_job.exists()
    assert (study_job / "pairs.jsonl").read_text(encoding="utf-8") == "STUDY pairs"
    assert str(organ / "active-1.gguf") in result.shared_kept
    assert str(jobs / "study_job") in result.shared_kept


def test_no_records_keeps_shared_volumes_whole(tmp_path):
    """When no adapter records exist, shared volumes are kept whole."""
    state_root = tmp_path / "state"
    organ = tmp_path / "organ"
    organ.mkdir(parents=True, exist_ok=True)
    (organ / "active-1.gguf").write_bytes(b"STUDY-ADAPTER")
    (organ / "active.json").write_text(json.dumps({"sha256": "abc"}), encoding="utf-8")

    jobs = state_root / "sleep" / "voice_align_jobs"
    job_a = jobs / "job_a"
    job_a.mkdir(parents=True)
    (job_a / "job.json").write_text(json.dumps({"adapter_output_dir": "out"}), encoding="utf-8")
    (job_a / "pairs.jsonl").write_text("STUDY pairs", encoding="utf-8")

    config = {
        **_NO_QDRANT,
        "sleep": {"voice_alignment": {"organ_adapters_dir": str(organ)}},
    }
    result = decommission.delete_entity_state(
        state_root=state_root,
        qdrant_cfg=config,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        dry_run=False,
    )
    assert result.errors == []
    assert (organ / "active-1.gguf").exists()
    assert (organ / "active.json").exists()
    assert job_a.exists()
    assert (job_a / "pairs.jsonl").read_text(encoding="utf-8") == "STUDY pairs"
    organ_note = next(
        (n for n in result.attribution_notes if str(organ) in n and "nothing in" in n and "could be attributed" in n),
        "",
    )
    jobs_note = next(
        (n for n in result.attribution_notes if str(jobs) in n and "nothing in" in n and "could be attributed" in n),
        "",
    )
    assert organ_note
    assert jobs_note


def test_module_on_with_absent_flag_still_exports_and_drops(tmp_path, monkeypatch):
    """--qdrant-absent still exports and drops Qdrant collections when the module is on."""
    config = {
        "modules": {"episodic_memory": True},
        "episodic_memory": {"backend": "qdrant", "qdrant": {"host": "127.0.0.1", "port": 1}},
    }
    names = decommission._episodic_memory_collection_names(config)
    fake = _FakeQdrant(names[:2])
    monkeypatch.setattr(decommission, "_qdrant_client", lambda cfg: fake)

    state_root = tmp_path / "state"
    (state_root / "self_model").mkdir(parents=True)
    (state_root / "self_model" / "self_model.json").write_text(json.dumps({}), encoding="utf-8")

    result = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=config,
        out_root=tmp_path / "backups",
        entity_name="Kaine Nova",
        qdrant_absent=True,
        assessment=DivergenceAssessment(diverged=False, signals={}, summary="x"),
    )
    assert result.ok
    assert result.qdrant_status == "exported"
    backup_path = result.backup_path
    for name in names[:2]:
        assert (backup_path / "qdrant" / f"{name}.jsonl").exists()

    result = decommission.delete_entity_state(
        state_root=state_root,
        qdrant_cfg=config,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_absent=True,
        dry_run=False,
    )
    assert set(fake.dropped) == set(names[:2])
    assert result.errors == []


def test_remote_failure_keeps_local_state(tmp_path, monkeypatch):
    """A failing remote store keeps all local state."""
    config = {
        "modules": {"episodic_memory": True},
        "episodic_memory": {"backend": "qdrant", "qdrant": {"host": "127.0.0.1", "port": 1}},
    }
    monkeypatch.setattr(decommission, "_qdrant_client", lambda cfg: None)

    state_root = tmp_path / "state"
    (state_root / "self_model").mkdir(parents=True)
    (state_root / "self_model" / "self_model.json").write_text(json.dumps({}), encoding="utf-8")

    result = decommission.delete_entity_state(
        state_root=state_root,
        qdrant_cfg=config,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        dry_run=False,
    )
    assert (state_root / "self_model" / "self_model.json").exists()
    assert result.incomplete
    assert any("local state kept because a remote store" in err for err in result.errors)


def test_job_started_from_this_entitys_adapter_is_not_claimed(tmp_path):
    """A job holding this entity's adapter only as previous_adapter belongs to whoever ran it, so it is kept."""
    from kaine.lifecycle.decommission_locations import attribute_job_dirs

    state_root = tmp_path / "state"
    sha = _store_adapter(state_root, "a1", b"OWN-ADAPTER")
    jobs = tmp_path / "jobs"
    forked = jobs / "forked_line_job"
    (forked / "previous_adapter").mkdir(parents=True)
    (forked / "previous_adapter" / "adapter.gguf").write_bytes(b"OWN-ADAPTER")
    (forked / "job.json").write_text(json.dumps({"adapter_output_dir": "out"}), encoding="utf-8")
    ran_here = jobs / "ran_here"
    (ran_here / "out" / "x").mkdir(parents=True)
    (ran_here / "out" / "x" / "adapter.gguf").write_bytes(b"OWN-ADAPTER")

    own, shared, _notes = attribute_job_dirs(
        jobs, {sha}, (state_root / "sleep" / "adapters",)
    )
    assert own == [ran_here]
    assert shared == [forked]


def test_live_organ_adapter_is_backed_up_but_kept(tmp_path):
    state_root = tmp_path / "state"
    sha_new = _store_adapter(state_root, "a2", b"OWN-NEW")
    _store_adapter(state_root, "a1", b"OWN-OLD")

    organ = tmp_path / "organ"
    organ.mkdir(parents=True, exist_ok=True)
    active_new = organ / "active-2.gguf"
    active_old = organ / "active-1.gguf"
    active_json = organ / "active.json"
    active_new.write_bytes(b"OWN-NEW")
    active_old.write_bytes(b"OWN-OLD")
    active_json.write_text(
        json.dumps(
            {
                "file": "active-2.gguf",
                "sha256": sha_new,
                "generation": 2,
                "adapter_id": "a2",
            }
        ),
        encoding="utf-8",
    )

    config = {
        **_NO_QDRANT,
        "sleep": {"voice_alignment": {"organ_adapters_dir": str(organ)}},
    }

    out_root = tmp_path / "backups"
    backup = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=config,
        out_root=out_root,
        entity_name="Live",
        assessment=DivergenceAssessment(diverged=False, signals={}, summary="x"),
    )
    assert backup is not None

    found = set()
    for path in out_root.rglob("*"):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if b"OWN-NEW" in data:
            found.add("new")
        if b"OWN-OLD" in data:
            found.add("old")
        if b"active-2.gguf" in data:
            found.add("active_json")
    assert {"new", "old", "active_json"} <= found

    result = decommission.delete_entity_state(
        state_root=state_root,
        qdrant_cfg=config,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        dry_run=False,
    )
    assert result.errors == []
    assert active_new.read_bytes() == b"OWN-NEW"
    assert active_json.exists()
    assert json.loads(active_json.read_text())["file"] == "active-2.gguf"
    assert not active_old.exists()
    assert "organ_adapters.live" in result.retained_locations
    assert str(active_new) in result.live_kept


def test_cancel_only_leaves_other_entities_jobs_alone(tmp_path):
    jobs = tmp_path / "jobs"
    own = jobs / "own"
    other_pending = jobs / "other_pending"
    other_claimed = jobs / "other_claimed"
    own.mkdir(parents=True)
    other_pending.mkdir(parents=True)
    other_claimed.mkdir(parents=True)
    (other_claimed / "CLAIMED").write_text("")
    slept = []
    cancelled, running = cancel_voice_alignment_jobs(
        jobs,
        only={"own"},
        wait_s=5.0,
        poll_s=1.0,
        sleep=slept.append,
        monotonic=lambda: float(sum(slept)),
    )
    assert cancelled == ["own"]
    assert running == []
    assert (own / "CANCELLED").exists()
    assert not (other_pending / "CANCELLED").exists()
    assert not (other_claimed / "CANCELLED").exists()
    assert slept == []
