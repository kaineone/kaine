# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from pathlib import Path

import pytest

from kaine.lifecycle import decommission
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


def test_stored_self_rhythm_identity_is_backed_up_then_deleted(tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    backed_up_then_deleted = [
        "lifecycle/self_rhythm_identity.json",
        "lifecycle/development_progress.json",
    ]
    deleted_without_backup = []
    for rel in backed_up_then_deleted + deleted_without_backup:
        _seed(state_root, rel)

    monkeypatch.setattr(decommission, "checkpoint_sqlite", lambda path: None)
    assessment = DivergenceAssessment(diverged=False, signals={}, summary="x")
    backup = decommission.capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        data_root=tmp_path / "data",
        qdrant_cfg=_NO_QDRANT,
        out_root=tmp_path / "backups",
        entity_name="Identity",
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
