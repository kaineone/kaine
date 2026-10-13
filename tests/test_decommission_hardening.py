# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import base64
import os
import shutil
from pathlib import Path

import pytest

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
_NO_QDRANT = {"mnemos": {"backend": "inmemory"}, "empatheia": {"backend": "inmemory"}}


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
    """Tier 0 disables Qdrant so backup and delete complete without contacting it."""
    op = tmp_path / "op.toml"
    op.write_text("[modules]\nmnemos = true\nempatheia = true\n", encoding="utf-8")
    config = load_runtime_config(
        PROJECT_ROOT / "config" / "kaine.toml",
        op,
        env={"KAINE_TIER": "tier0"},
    )
    assert config["tier"]["name"] == "tier0"
    assert decommission.qdrant_in_use(config) is False

    def _no_qdrant(*args, **kwargs):
        raise AssertionError("Qdrant must not be contacted at tier 0")

    monkeypatch.setattr(decommission, "_qdrant_client", _no_qdrant)
    state_root = tmp_path / "state"
    _seed(state_root, "eidolon/self_model.json")
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
    """The default base profile routes episodic memory to Qdrant when mnemos is enabled."""
    op = tmp_path / "op.toml"
    op.write_text("[modules]\nmnemos = true\n", encoding="utf-8")
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
        "mnemos/mnemos.db",
        "episodic_memory/episodic_memory.db",
        "episodic_memory/episodic_memory.db-wal",
        "episodic_memory/episodic_memory.db-shm",
        "episodic_memory/episodic_memory.db-journal",
        "lingua/intent_expression.jsonl",
        "language/intent_expression.jsonl",
        "lingua/utterance_outcomes.jsonl",
        "language/utterance_outcomes.jsonl",
        "eidolon/self_model.json",
        "self_model/self_model.json",
        "hypnos/consolidation_divergence.json",
        "sleep/consolidation_divergence.json",
        "praxis/notifications.log",
        "effectors/notifications.log",
        "lifecycle/gestation_readout.json",
        "lifecycle/development_readout.json",
        "lifecycle/birth_request.json",
        "lifecycle/maturation_request.json",
        "lifecycle/birth_ack.json",
        "lifecycle/maturation_ack.json",
        "lifecycle/gestation_progress.json",
        "lifecycle/development_progress.json",
        "lifecycle/gestation_viability.json",
        "lifecycle/development_viability.json",
        "individuation/birth_adapter.gguf",
        "individuation/maturation_adapter.gguf",
        "phantasia/world_model.ckpt",
        "world_model/world_model.ckpt",
    ]
    deleted_without_backup = [
        "mnemos/store_health.json",
        "episodic_memory/store_health.json",
        "hypnos/organ_window.json",
        "sleep/organ_window.json",
        "perception/desired.json",
        "perceptual_locus/desired.json",
    ]
    kept = [
        "praxis/audit.log",
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
    assert "mnemos_episodic" in names
    assert "episodic_memory_episodic" in names
    assert "empatheia_agents" in names
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
    _seed(state_root, "eidolon/self_model.json")
    _seed(state_root, "lingua/intent_expression.jsonl")
    real_rmtree = shutil.rmtree

    def guarded_rmtree(path, *args, **kwargs):
        if Path(path).name == "eidolon":
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
    assert any("eidolon" in str(e) for e in result.errors)
    assert (state_root / "eidolon").exists()
    assert not (state_root / "lingua").exists()


def test_failed_backup_purges_plaintext_when_encrypted(tmp_path, monkeypatch):
    """A failed backup removes all plaintext from the bundle when encryption is enabled."""
    key = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setenv("KAINE_STATE_KEY", key)
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))

    state_root = tmp_path / "state"
    _seed(state_root, "eidolon/self_model.json", "SECRET self")
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
    _seed(state_root, "eidolon/self_model.json", "SECRET self")
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
    config = {"modules": {"mnemos": True}, "mnemos": {"backend": "qdrant"}}

    class BadQdrant:
        def get_collections(self):
            raise ConnectionError("qdrant down")

        def close(self):
            pass

    monkeypatch.setattr(decommission, "_qdrant_client", lambda cfg: BadQdrant())
    state_root = tmp_path / "state"
    _seed(state_root, "eidolon/self_model.json")
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
    """Voice alignment training directories are backed up and then emptied but kept as roots."""
    config = {
        **_NO_QDRANT,
        "hypnos": {
            "voice_alignment": {
                "trainer_workdir": "state/train_work",
                "trainer_jobs_dir": "state/train_jobs",
            }
        },
    }
    state_root = tmp_path / "state"
    _seed(state_root, "train_work/job1/pairs.jsonl", "SECRET pairs")
    _seed(state_root, "train_jobs/job2/spec.json", "{}")
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
    assert not (state_root / "train_jobs" / "job2").exists()


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
    config = {**_NO_QDRANT, "praxis": {"sandbox_path": str(outside)}}
    state_root = tmp_path / "state"
    _seed(state_root, "eidolon/self_model.json")
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
    (organ / "organ.bin").write_text("y", encoding="utf-8")
    config2 = {
        **_NO_QDRANT,
        "hypnos": {"voice_alignment": {"organ_adapters_dir": str(organ)}},
    }
    state_root2 = tmp_path / "state2"
    _seed(state_root2, "eidolon/self_model.json")
    result2 = decommission.delete_entity_state(
        state_root=state_root2,
        qdrant_cfg=config2,
        fork_root=tmp_path / "forks2",
        data_root=tmp_path / "data2",
        dry_run=False,
    )
    assert result2.errors == []
    assert organ.exists()
    assert not list(organ.iterdir())


def test_symlink_in_contents_only_dir_is_unlinked_not_followed(tmp_path):
    """A directory symlink inside a contents-only location is removed as a link; its target survives."""
    outside = tmp_path / "shared" / "docs"
    outside.mkdir(parents=True)
    (outside / "keep.txt").write_text("KEEP", encoding="utf-8")
    jobs = tmp_path / "state" / "hypnos" / "voice_align_jobs"
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
    assert not (jobs / "escape").exists() and not (jobs / "escape").is_symlink()
    assert (outside / "keep.txt").read_text(encoding="utf-8") == "KEEP"
