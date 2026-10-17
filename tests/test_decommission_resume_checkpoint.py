# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from pathlib import Path

import pytest

from kaine.lifecycle import decommission
from kaine.lifecycle.decommission_locations import BACKUP_DELETE, entity_locations
from kaine.lifecycle.divergence import DivergenceAssessment
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    get_state_encryptor,
    set_state_encryptor,
)

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


def test_resume_checkpoint_is_backed_up_then_deleted(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    _seed(state_root, "lifecycle/checkpoint/checkpoint.json", "SECRET checkpoint")
    _seed(state_root, "lifecycle/stage.json", "SECRET stage")

    monkeypatch.setattr(decommission, "checkpoint_sqlite", lambda path: None)
    assessment = DivergenceAssessment(diverged=False, signals={}, summary="x")
    backup = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=_NO_QDRANT,
        out_root=tmp_path / "backups",
        entity_name="ResumeCheckpoint",
        assessment=assessment,
    )
    assert backup.ok

    bundle_texts = {
        p.read_text(errors="replace")
        for p in Path(backup.backup_path).rglob("*")
        if p.is_file()
    }
    assert "SECRET checkpoint" in bundle_texts
    assert (Path(backup.backup_path) / "locations" / "lifecycle.resume_checkpoint").exists()

    result = decommission.delete_entity_state(
        state_root=state_root,
        qdrant_cfg=_NO_QDRANT,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        dry_run=False,
    )
    assert result.errors == []
    assert not (state_root / "lifecycle" / "checkpoint").exists()


def test_resume_checkpoint_location_is_listed(tmp_path):
    locations = entity_locations(
        None,
        state_root=tmp_path / "state",
        data_root=tmp_path / "data",
        fork_root=tmp_path / "forks",
        entity_id=None,
    )
    matching = [loc for loc in locations if loc.key == "lifecycle.resume_checkpoint"]
    assert len(matching) == 1
    loc = matching[0]
    assert loc.decision == BACKUP_DELETE
    assert (tmp_path / "state" / "lifecycle" / "checkpoint") in loc.paths
