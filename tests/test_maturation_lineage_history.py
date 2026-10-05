# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Lineage-scoped prior-lived-history detection (maturation-gate task 3.3).

Every test uses explicit temporary roots; the real ``state/`` tree is never
touched.
"""

from __future__ import annotations

import contextlib
import json
from pathlib import Path
from typing import Iterator

import pytest

from kaine.cycle.__main__ import _resolve_boot_stage
from kaine.lifecycle import stage as st
from kaine.lifecycle.identity import (
    EntityIdentity,
    fork_identity,
    lived_before,
    mint_identity,
    resolve_spawn_identity,
    write_identity_sidecar,
)
from kaine.storage import set_data_root


def _manifest(identity: EntityIdentity) -> dict[str, object]:
    return {
        "identity": {
            "entity_id": identity.entity_id,
            "lineage": list(identity.lineage),
        }
    }


@contextlib.contextmanager
def _data_root(root: Path) -> Iterator[None]:
    """Temporarily install ``root`` as the process data root, restoring the
    previous root afterwards so no other test inherits it."""
    import kaine.storage as s

    previous = s._PROCESS_ROOT
    set_data_root(root)
    try:
        yield
    finally:
        set_data_root(previous)


def test_lived_before_false_for_fresh_identity_with_only_foreign_records(
    tmp_path: Path,
) -> None:
    me = mint_identity()
    other = mint_identity()

    forks = tmp_path / "forks" / "foreign"
    forks.mkdir(parents=True)
    (forks / "snapshot.json").write_text("{}")
    write_identity_sidecar(forks, other)

    backups = tmp_path / "backups" / "b1"
    backups.mkdir(parents=True)
    (backups / "manifest.json").write_text(json.dumps(_manifest(other)))

    assert lived_before(me, tmp_path) is False
    assert lived_before(me, tmp_path, bundle_roots=[tmp_path / "backups"]) is False


def test_lived_before_true_when_fork_sidecar_names_this_being(tmp_path: Path) -> None:
    me = mint_identity()
    forks = tmp_path / "forks" / "mine"
    forks.mkdir(parents=True)
    (forks / "snapshot.json").write_text("{}")
    write_identity_sidecar(forks, me)
    assert lived_before(me, tmp_path) is True


def test_lived_before_true_when_fork_sidecar_names_ancestor(tmp_path: Path) -> None:
    parent = mint_identity()
    child = fork_identity(parent)
    forks = tmp_path / "forks" / "ancestor-fork"
    forks.mkdir(parents=True)
    (forks / "snapshot.json").write_text("{}")
    write_identity_sidecar(forks, parent)
    assert lived_before(child, tmp_path) is True


def test_lived_before_true_when_bundle_names_this_being(tmp_path: Path) -> None:
    me = mint_identity()
    bundle_root = tmp_path / "alt_backups"
    bundle = bundle_root / "b1"
    bundle.mkdir(parents=True)
    (bundle / "manifest.json").write_text(json.dumps(_manifest(me)))
    assert lived_before(me, tmp_path, bundle_roots=[bundle_root]) is True


def test_lived_before_true_for_unknown_identity(tmp_path: Path) -> None:
    assert lived_before(None, tmp_path) is True


def test_lived_before_true_for_legacy_tree_without_sidecars(tmp_path: Path) -> None:
    phantasia = tmp_path / "phantasia"
    phantasia.mkdir(parents=True)
    (phantasia / "world_model.ckpt").write_text("weights")

    forks = tmp_path / "forks" / "old"
    forks.mkdir(parents=True)
    (forks / "snapshot.json").write_text("{}")

    identity = resolve_spawn_identity(tmp_path)
    assert identity.origin == "legacy"
    assert lived_before(identity, tmp_path) is True


def test_lived_before_true_for_minted_being_with_only_desired_state(
    tmp_path: Path,
) -> None:
    me = mint_identity()
    perception = tmp_path / "perception"
    perception.mkdir(parents=True)
    (perception / "desired.json").write_text("{}")
    assert lived_before(me, tmp_path) is True


def test_resolve_boot_stage_gestation_for_fresh_identity_with_foreign_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path
    state_root = data_root / "state"

    monkeypatch.setattr(st, "STAGE_PATH", state_root / "lifecycle" / "stage.json")

    me = mint_identity()
    other = mint_identity()

    fork_dir = state_root / "forks" / "foreign"
    fork_dir.mkdir(parents=True)
    (fork_dir / "snapshot.json").write_text("{}")
    write_identity_sidecar(fork_dir, other)

    bundle_dir = state_root / "backups" / "b1"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "manifest.json").write_text(json.dumps(_manifest(other)))

    config = {"developmental_stage": {"enabled": True}}

    with _data_root(data_root):
        stage_state, enabled, fresh = _resolve_boot_stage(config, identity=me)

    assert enabled is True
    assert stage_state.stage == st.GESTATION
    assert fresh is True


def test_resolve_boot_stage_embodied_for_legacy_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_root = tmp_path
    state_root = data_root / "state"

    monkeypatch.setattr(st, "STAGE_PATH", state_root / "lifecycle" / "stage.json")

    phantasia = state_root / "phantasia"
    phantasia.mkdir(parents=True)
    (phantasia / "world_model.ckpt").write_text("weights")

    old_fork = state_root / "forks" / "old"
    old_fork.mkdir(parents=True)
    (old_fork / "snapshot.json").write_text("{}")

    config = {"developmental_stage": {"enabled": True}}

    with _data_root(data_root):
        identity = resolve_spawn_identity(state_root)
        stage_state, enabled, fresh = _resolve_boot_stage(config, identity=identity)

    assert identity.origin == "legacy"
    assert enabled is True
    assert stage_state.stage == st.EMBODIED
    assert fresh is False


def test_has_prior_lived_history_reads_bundle_roots(tmp_path: Path) -> None:
    me = mint_identity()
    bundle_dir = tmp_path / "backups" / "b1"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "manifest.json").write_text(json.dumps(_manifest(me)))
    state_root = tmp_path / "state"
    state_root.mkdir()
    assert st.has_prior_lived_history(me, state_root) is False
    assert st.has_prior_lived_history(me, state_root, bundle_roots=[tmp_path / "backups"]) is True


def test_resolve_boot_stage_finds_own_bundle_under_configured_out_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # This being was preserved into the configured preservation out_root, and
    # its tree holds none of its own lived artifacts: it has lived, so it must
    # not be regressed into gestation.
    monkeypatch.setattr("kaine.lifecycle.stage.STAGE_PATH", tmp_path / "state" / "lifecycle" / "stage.json")
    me = mint_identity()
    (tmp_path / "state").mkdir()
    bundle_dir = tmp_path / "preserved" / "b1"
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "manifest.json").write_text(json.dumps(_manifest(me)))
    config = {
        "developmental_stage": {"enabled": True},
        "preservation": {"divergence_monitor": {"out_root": "preserved"}},
    }
    with _data_root(tmp_path):
        stage_state, _enabled, fresh = _resolve_boot_stage(config, identity=me)
    assert stage_state.stage == st.EMBODIED
    assert fresh is False
