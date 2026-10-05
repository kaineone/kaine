# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Integration tests for entity identity wiring in forks, preservation,
revive, decommission, batch jobs and the cycle boot path.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pytest

from kaine.cycle.__main__ import _resolve_boot_identity
from kaine.cycle.revive_boot import RevivePlan, ReviveRefused, prepare_revive
from kaine.distributed.fork_being import build_forked_being_job
from kaine.experiment.run_context import RunContext, set_run_context
from kaine.lifecycle.decommission import capture_backup
from kaine.lifecycle.divergence import DivergenceAssessment
from kaine.lifecycle.identity import (
    EntityIdentity,
    IdentityError,
    has_prior_lived_history_in_lineage,
    load_identity,
    mint_identity,
    save_identity,
    write_identity_sidecar,
)
from kaine.lifecycle.manager import ForkManager
from kaine.lifecycle.preservation import ReviveError, preserve_live, revive
from kaine.lifecycle.snapshot import ForkSnapshot, snapshot_dir
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor


@pytest.fixture(autouse=True)
def _plaintext_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.fixture(autouse=True)
def _run_context():
    set_run_context(
        RunContext(
            run_id="testrun0123456789",
            seed=7,
            started_at=datetime.now(timezone.utc).isoformat(),
            git_sha=None,
        )
    )
    yield
    set_run_context(None)


@dataclass
class _FakeModule:
    name: str = "testmod"
    value: int = 0

    def serialize(self) -> dict[str, Any]:
        return {"value": self.value}

    def deserialize(self, state: dict[str, Any]) -> None:
        self.value = state["value"]


class _Registry:
    def __init__(self, value: int = 0) -> None:
        self.mod = _FakeModule(value=value)

    def all_modules(self) -> Iterable[_FakeModule]:
        return [self.mod]


class _MockRevive:
    def __init__(self, path: Path, identity: EntityIdentity) -> None:
        self.plan = RevivePlan(
            bundle=path,
            preservation_id=None,
            stage=None,
            identity=identity,
        )


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _all_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.is_file()]


def _find_bundle(out_root: Path) -> Path:
    bundles = [p for p in out_root.iterdir() if (p / "manifest.json").is_file()]
    assert len(bundles) == 1, bundles
    return bundles[0]


async def _preserve(registry, fork_root, out_root, identity=None):
    return await preserve_live(
        registry,
        fork_root=fork_root,
        out_root=out_root,
        entity_name="testentity",
        reason="test",
        identity=identity,
    )


@pytest.mark.asyncio
async def test_snapshot_with_identity_source_writes_metadata_and_sidecar(tmp_path):
    registry = _Registry()
    identity = mint_identity()
    fm = ForkManager(tmp_path / "forks", identity_source=lambda: identity)
    snap = fm.snapshot(registry, label="s1")

    assert snap.metadata.get("identity") == identity.to_dict()
    sidecar_path = snapshot_dir(fm.root, snap.id) / "identity.json"
    assert sidecar_path.exists()
    assert json.loads(sidecar_path.read_text()) == {
        "entity_id": identity.entity_id,
        "lineage": [],
    }

    fm2 = ForkManager(tmp_path / "forks2")
    snap2 = fm2.snapshot(registry, label="s2")
    assert "identity" not in snap2.metadata
    assert not (snapshot_dir(fm2.root, snap2.id) / "identity.json").exists()


@pytest.mark.asyncio
async def test_fork_lineage_and_sidecar(tmp_path):
    identity = mint_identity()
    fm = ForkManager(tmp_path / "forks", identity_source=lambda: identity)
    parent = fm.snapshot(_Registry())

    child = fm.fork(parent.id)
    child_identity = EntityIdentity.from_dict(child.metadata["identity"])
    assert child_identity.entity_id != identity.entity_id
    assert child_identity.lineage == (identity.entity_id,)

    sidecar = json.loads(
        (snapshot_dir(fm.root, child.id) / "identity.json").read_text()
    )
    assert sidecar["entity_id"] == child_identity.entity_id


@pytest.mark.asyncio
async def test_fork_of_unidentified_parent_mints_root(tmp_path):
    fm = ForkManager(tmp_path / "forks")
    parent = fm.snapshot(_Registry())

    child = fm.fork(parent.id)
    assert "identity" in child.metadata
    assert child.metadata.get("forked_from_unidentified") == parent.id
    child_identity = EntityIdentity.from_dict(child.metadata["identity"])
    assert child_identity.lineage == ()


@pytest.mark.asyncio
async def test_fork_refuses_disagreeing_sidecar_and_does_not_create_child(tmp_path):
    identity = mint_identity()
    fm = ForkManager(tmp_path / "forks", identity_source=lambda: identity)
    parent = fm.snapshot(_Registry())

    other = mint_identity()
    sidecar_path = snapshot_dir(fm.root, parent.id) / "identity.json"
    sidecar_path.write_text(
        json.dumps({"entity_id": other.entity_id, "lineage": []})
    )

    before = {p.name for p in fm.root.iterdir()}
    with pytest.raises(IdentityError):
        fm.fork(parent.id)
    after = {p.name for p in fm.root.iterdir()}
    assert after == before


@pytest.mark.asyncio
async def test_merge_keeps_target_identity_and_records_merged_from_entity(tmp_path):
    id_a = mint_identity()
    fm_a = ForkManager(tmp_path / "forks", identity_source=lambda: id_a)
    snap_a = fm_a.snapshot(_Registry())

    id_b = mint_identity()
    fm_b = ForkManager(tmp_path / "forks", identity_source=lambda: id_b)
    snap_b = fm_b.snapshot(_Registry())

    merged = fm_a.merge(snap_a.id, snap_b.id)
    assert merged.metadata["identity"] == id_a.to_dict()
    assert merged.metadata["merged_from_entity"] == id_b.entity_id
    assert merged.metadata["merged_from"] == [snap_a.id, snap_b.id]

    sidecar = json.loads(
        (snapshot_dir(fm_a.root, merged.id) / "identity.json").read_text()
    )
    assert sidecar["entity_id"] == id_a.entity_id


@pytest.mark.asyncio
async def test_preserve_live_identity_roundtrip_and_revive_rejects_tampered_manifest(tmp_path):
    registry = _Registry(value=0)
    fork_root = tmp_path / "forks"
    out_root = tmp_path / "backups"
    identity = mint_identity()

    result = await _preserve(registry, fork_root, out_root, identity=identity)
    bundle_dir = _find_bundle(out_root)

    manifest = json.loads((bundle_dir / "manifest.json").read_text())
    assert manifest.get("identity") == {
        "entity_id": identity.entity_id,
        "lineage": [],
    }

    snap = ForkSnapshot.from_dict(
        json.loads((fork_root / result.snapshot_id / "snapshot.json").read_text())
    )
    assert snap.metadata.get("identity") == identity.to_dict()

    registry.mod.value = 999
    await revive(bundle_dir, registry)
    assert registry.mod.value == 0

    other = mint_identity()
    manifest["identity"] = {"entity_id": other.entity_id, "lineage": []}
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True)
    )

    hashes_before = {str(p.relative_to(bundle_dir)): _hash_file(p) for p in _all_files(bundle_dir)}
    registry2 = _Registry(value=0)
    with pytest.raises(ReviveError):
        await revive(bundle_dir, registry2)
    hashes_after = {str(p.relative_to(bundle_dir)): _hash_file(p) for p in _all_files(bundle_dir)}
    assert hashes_after == hashes_before
    assert registry2.mod.value == 0


@pytest.mark.asyncio
async def test_prepare_revive_identity_from_manifest_or_legacy(tmp_path):
    fork_root = tmp_path / "forks"
    out_root = tmp_path / "backups"

    identity = mint_identity()
    await _preserve(_Registry(), fork_root, out_root, identity=identity)
    bundle_with_id = _find_bundle(out_root)
    plan_with_id = prepare_revive(bundle_with_id)
    assert plan_with_id.identity == identity

    result_legacy = await _preserve(_Registry(), fork_root, out_root)
    bundles = [p for p in out_root.iterdir() if p != bundle_with_id and (p / "manifest.json").is_file()]
    assert len(bundles) == 1
    bundle_without_id = bundles[0]

    plan_a = prepare_revive(bundle_without_id)
    plan_b = prepare_revive(bundle_without_id)
    # Deterministic: the same bundle always yields the same ID and source
    # (minted_at records when it was derived).
    assert plan_a.identity.entity_id == plan_b.identity.entity_id
    assert plan_a.identity.entity_id.startswith("legacy-")
    assert plan_a.identity.legacy_source == f"bundle:{result_legacy.preservation_id}"


@pytest.mark.asyncio
async def test_prepare_revise_refuses_without_identity_or_preservation_id(tmp_path):
    fork_root = tmp_path / "forks"
    out_root = tmp_path / "backups"
    await _preserve(_Registry(), fork_root, out_root)
    bundle_dir = _find_bundle(out_root)

    manifest = json.loads((bundle_dir / "manifest.json").read_text())
    manifest.pop("identity", None)
    del manifest["preservation_id"]
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True)
    )

    with pytest.raises(ReviveRefused):
        prepare_revive(bundle_dir)


@pytest.mark.asyncio
async def test_has_prior_lived_history_scans_bundle_roots(tmp_path):
    identity = mint_identity()
    fm = ForkManager(tmp_path / "forks", identity_source=lambda: identity)
    await _preserve(_Registry(), fm.root, tmp_path / "backups", identity=identity)

    other_state = tmp_path / "other_state"
    (other_state / "identity").mkdir(parents=True)

    assert has_prior_lived_history_in_lineage(
        identity, other_state, bundle_roots=[tmp_path / "backups"]
    )
    other = mint_identity()
    assert not has_prior_lived_history_in_lineage(
        other, other_state, bundle_roots=[tmp_path / "backups"]
    )
    assert has_prior_lived_history_in_lineage(
        None, other_state, bundle_roots=[tmp_path / "backups"]
    )


def test_capture_backup_manifest_carries_identity(tmp_path):
    state_root = tmp_path / "state"
    identity = mint_identity()
    save_identity(identity, state_root / "identity" / "entity.json")

    assessment = DivergenceAssessment(diverged=False, signals={}, summary="test")
    result = capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        qdrant_cfg=None,
        out_root=tmp_path / "backups",
        entity_name="test",
        assessment=assessment,
    )
    assert result.ok
    manifest = json.loads((result.backup_path / "manifest.json").read_text())
    assert manifest.get("identity") == {
        "entity_id": identity.entity_id,
        "lineage": [],
    }


@pytest.mark.asyncio
async def test_build_forked_being_job_carries_fork_identity(tmp_path):
    identity = mint_identity()
    fm = ForkManager(tmp_path / "forks", identity_source=lambda: identity)
    snap = fm.snapshot(_Registry())

    job = build_forked_being_job(
        snap.id, "explore and return", fork_root=fm.root
    )
    assert job.inputs.get("fork_identity") == {
        "entity_id": identity.entity_id,
        "lineage": [],
    }


def test_resolve_boot_identity_fresh_tree_mints_despite_foreign_beings(tmp_path):
    state_root = tmp_path / "state"
    (state_root / "forks" / "foreign").mkdir(parents=True)
    write_identity_sidecar(state_root / "forks" / "foreign", mint_identity())

    (state_root / "backups" / "foreign").mkdir(parents=True)
    other = mint_identity()
    (state_root / "backups" / "foreign" / "manifest.json").write_text(
        json.dumps({"identity": {"entity_id": other.entity_id, "lineage": []}}, indent=2)
    )

    identity = _resolve_boot_identity(state_root, revive=None)
    assert identity.entity_id.startswith("ent-")
    assert load_identity(state_root / "identity" / "entity.json") == identity


def test_resolve_boot_identity_refuses_conflicting_revive_and_leaves_file(tmp_path):
    state_root = tmp_path / "state"
    existing = mint_identity()
    save_identity(existing, state_root / "identity" / "entity.json")

    plan_identity = mint_identity()
    revive = _MockRevive(tmp_path / "bundle", plan_identity)

    with pytest.raises(IdentityError):
        _resolve_boot_identity(state_root, revive=revive)

    assert load_identity(state_root / "identity" / "entity.json") == existing


def test_resolve_boot_identity_legacy_tree_then_snapshot_same_id(tmp_path):
    state_root = tmp_path / "state"
    (state_root / "phantasia").mkdir(parents=True)
    (state_root / "phantasia" / "world_model.ckpt").write_text("weights")

    identity = _resolve_boot_identity(state_root, revive=None)
    assert identity.entity_id.startswith("legacy-")

    identity_path = state_root / "identity" / "entity.json"
    assert load_identity(identity_path) == identity

    fm = ForkManager(
        tmp_path / "forks",
        identity_source=lambda: load_identity(identity_path),
    )
    snap = fm.snapshot(_Registry())
    assert snap.metadata.get("identity") == identity.to_dict()

    identity2 = _resolve_boot_identity(state_root, revive=None)
    assert identity2 == identity
