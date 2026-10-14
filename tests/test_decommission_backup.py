# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kaine.lifecycle.decommission import capture_backup, delete_entity_state
from kaine.lifecycle.divergence import DivergenceAssessment
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    get_state_encryptor,
    set_state_encryptor,
)

# This deployment keeps no memory in Qdrant (the runtime default is Qdrant).
_NO_QDRANT = {"episodic_memory": {"backend": "inmemory"}, "social_cognition": {"backend": "inmemory"}}


def _seed_state(state_root: Path) -> None:
    (state_root / "eidolon").mkdir(parents=True, exist_ok=True)
    (state_root / "eidolon" / "self_model.json").write_text(
        json.dumps({"name": "Kaine Nova", "drift_count": 1}), encoding="utf-8"
    )
    (state_root / "lingua").mkdir(parents=True, exist_ok=True)
    (state_root / "lingua" / "intent_expression.jsonl").write_text(
        '{"intent": "x"}\n', encoding="utf-8"
    )
    (state_root / "hypnos" / "adapters").mkdir(parents=True, exist_ok=True)
    (state_root / "hypnos" / "adapters" / "voice.bin").write_bytes(b"w")


def _seed_fork(fork_root: Path, entity_id: str | None = None) -> None:
    from kaine.lifecycle.snapshot import ForkSnapshot, save_snapshot

    metadata = {"identity": {"entity_id": entity_id}} if entity_id else {}
    snap = ForkSnapshot(label="root", modules={"interoception": {"wellness": 0.9}}, metadata=metadata)
    save_snapshot(fork_root, snap)


def _seed_identity(state_root: Path) -> str:
    """Give the entity an identity so its fork snapshots can be attributed to it."""
    from kaine.lifecycle.identity import mint_identity, save_identity

    identity = mint_identity()
    save_identity(identity, state_root / "identity" / "entity.json")
    return identity.entity_id


def _assessment(diverged=True) -> DivergenceAssessment:
    return DivergenceAssessment(
        diverged=diverged, signals={"individuation_significant": diverged}, summary="x"
    )


def test_capture_backup_copies_artifacts_and_manifest(tmp_path):
    state_root = tmp_path / "state"
    fork_root = tmp_path / "forks"
    out_root = tmp_path / "backups"
    _seed_state(state_root)
    _seed_fork(fork_root, _seed_identity(state_root))

    result = capture_backup(
        state_root=state_root,
        fork_root=fork_root,
        qdrant_cfg=_NO_QDRANT,
        out_root=out_root,
        entity_name="Kaine Nova",
        assessment=_assessment(),
        continuity_note="wants to persist",
    )
    assert result.ok
    bdir = result.backup_path
    assert (bdir / "self_model.json").is_file()
    assert (bdir / "intent_expression.jsonl").is_file()
    assert (bdir / "locations" / "sleep.adapters" / "hypnos" / "adapters" / "voice.bin").is_file()
    assert (bdir / "snapshot.json").is_file()
    assert not (bdir / "QDRANT_BACKUP_INSTRUCTIONS.txt").exists()

    manifest = json.loads((bdir / "manifest.json").read_text())
    assert manifest["entity_name"] == "Kaine Nova"
    # S3: the plaintext manifest carries only the NON-sensitive inventory plus a
    # bare diverged bool — never the inner-life fields.
    assert manifest["diverged"] is True
    assert "assessment" not in manifest
    assert "continuity_note" not in manifest
    assert "self_model.json" in manifest["inventory"]
    assert "restore_notes" in manifest
    assert manifest["qdrant"] == "not used"
    assert isinstance(manifest["locations"], list)
    # S3: the sensitive inner-life rides in separate sidecars. Encryption is
    # disabled here (no key), so they are honest plaintext sidecars.
    assess = json.loads((bdir / "assessment.json").read_text())
    assert assess["diverged"] is True
    assert assess["signals"] == {"individuation_significant": True}

    cont = json.loads((bdir / "continuity.json").read_text())
    assert cont["continuity_note"] == "wants to persist"


def test_backup_covers_every_file_of_renamed_and_sibling_dirs(tmp_path):
    """Renamed and sibling state directories are backed up whole and removed on delete."""
    state_root = tmp_path / "state"
    fork_root = tmp_path / "forks"
    out_root = tmp_path / "backups"
    files = {
        "eidolon/self_model.json": '{"self": true}',
        "eidolon/extra.json": '{"extra": true}',
        "self_model/notes.json": '{"notes": true}',
        "lingua/intent_expression.jsonl": '{"intent": "x"}\n',
        "lingua/monologue.jsonl": '{"monologue": "y"}\n',
        "world_model/w.ckpt": b"weights",
    }
    for rel, content in files.items():
        path = state_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")

    result = capture_backup(
        state_root=state_root,
        fork_root=fork_root,
        qdrant_cfg=_NO_QDRANT,
        out_root=out_root,
        entity_name="RenamedDirs",
        assessment=_assessment(),
    )
    assert result.ok
    bdir = result.backup_path
    bundled = {
        bdir / "locations" / "self_model" / "eidolon" / "self_model.json",
        bdir / "locations" / "self_model" / "eidolon" / "extra.json",
        bdir / "locations" / "self_model" / "self_model" / "notes.json",
        bdir / "locations" / "language" / "lingua" / "intent_expression.jsonl",
        bdir / "locations" / "language" / "lingua" / "monologue.jsonl",
        bdir / "locations" / "world_model" / "world_model" / "w.ckpt",
    }
    for path in bundled:
        assert path.is_file(), f"{path} missing from bundle"

    del_result = delete_entity_state(
        state_root=state_root,
        qdrant_cfg=_NO_QDRANT,
        dry_run=False,
    )
    assert not del_result.errors
    for rel in files:
        assert not (state_root / rel).exists()


def test_capture_backup_fails_when_qdrant_unreachable(tmp_path):
    state_root = tmp_path / "state"
    _seed_state(state_root)
    result = capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        qdrant_cfg={"modules": {"episodic_memory": True}, "episodic_memory": {"qdrant": {"host": "127.0.0.1", "port": 59999}}},
        out_root=tmp_path / "backups",
        entity_name="Kaine Nova",
        assessment=_assessment(),
    )
    assert not result.ok
    assert any("qdrant" in e.lower() for e in result.errors)
    assert not (result.backup_path / "QDRANT_BACKUP_INSTRUCTIONS.txt").exists()


def test_capture_backup_encrypts_when_enabled(tmp_path, monkeypatch):
    # Install an enabled encryptor with a known key.
    key = b"0" * 32
    monkeypatch.setenv("KAINE_STATE_KEY", key.decode())
    prev = get_state_encryptor()
    enc = StateEncryptor(CryptoConfig(enabled=True, key_env_var="KAINE_STATE_KEY"))
    set_state_encryptor(enc)
    try:
        state_root = tmp_path / "state"
        _seed_state(state_root)
        result = capture_backup(
            state_root=state_root,
            fork_root=tmp_path / "forks",
            qdrant_cfg=_NO_QDRANT,
            out_root=tmp_path / "backups",
            entity_name="Kaine Nova",
            assessment=_assessment(),
        )
        assert result.ok
        assert result.encrypted is True
        bdir = result.backup_path
        # Plaintext artifacts are gone; an encrypted bundle + readable manifest remain.
        assert (bdir / "bundle.tar.enc").is_file()
        assert not (bdir / "self_model.json").exists()
        assert not (bdir / "assessment.json").exists()
        assert (bdir / "manifest.json").is_file()
        # S3: the plaintext manifest leaks no inner-life.
        manifest = json.loads((bdir / "manifest.json").read_text())
        assert "continuity_note" not in manifest
        assert "assessment" not in manifest
        assert manifest["diverged"] is True
        # The encrypted blob round-trips back to the original tar; the sensitive
        # sidecars ride INSIDE the encrypted tar.
        blob = (bdir / "bundle.tar.enc").read_text().encode("ascii")
        raw = enc.decrypt(blob)
        import io
        import tarfile

        with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
            names = tf.getnames()
            assert "self_model.json" in names
            assert "assessment.json" in names
            # assessment.json inside the tar is itself StateEncryptor-encrypted.
            member = tf.extractfile("assessment.json")
            assert member is not None
            inner = enc.maybe_decrypt(member.read()).decode("utf-8")
        assert "individuation_significant" in inner
    finally:
        set_state_encryptor(prev)


def test_capture_backup_plaintext_when_disabled(tmp_path):
    state_root = tmp_path / "state"
    _seed_state(state_root)
    result = capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        qdrant_cfg=_NO_QDRANT,
        out_root=tmp_path / "backups",
        entity_name="Kaine Nova",
        assessment=_assessment(),
    )
    assert result.ok
    assert result.encrypted is False
    assert (result.backup_path / "self_model.json").is_file()
    assert not (result.backup_path / "bundle.tar.enc").exists()


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission semantics")
def test_capture_backup_bundle_dir_is_owner_only(tmp_path):
    """S4 — bundle dir is 0700 and sensitive files are 0600 (POSIX)."""
    state_root = tmp_path / "state"
    _seed_state(state_root)
    result = capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        qdrant_cfg=_NO_QDRANT,
        out_root=tmp_path / "backups",
        entity_name="Kaine Nova",
        assessment=_assessment(),
    )
    assert result.ok
    bdir = result.backup_path
    assert (bdir.stat().st_mode & 0o777) == 0o700
    assert ((bdir / "self_model.json").stat().st_mode & 0o077) == 0  # no group/other
    assert ((bdir / "manifest.json").stat().st_mode & 0o077) == 0


class _BoomEncryptor:
    """Stand-in encryptor that is enabled but fails on encrypt() (S7)."""

    enabled = True

    def encrypt_text(self, text: str) -> str:
        return text  # sidecars write fine; the bundle-tar encrypt is what fails

    def encrypt(self, raw: bytes) -> bytes:
        raise RuntimeError("forced encryption failure")


def test_capture_backup_purges_plaintext_on_encryption_failure(tmp_path):
    """S7 — encryption failure removes all plaintext entity content + aborts."""
    prev = get_state_encryptor()
    set_state_encryptor(_BoomEncryptor())
    try:
        state_root = tmp_path / "state"
        _seed_state(state_root)
        result = capture_backup(
            state_root=state_root,
            fork_root=tmp_path / "forks",
            qdrant_cfg=_NO_QDRANT,
            out_root=tmp_path / "backups",
            entity_name="Kaine Nova",
            assessment=_assessment(),
            continuity_note="wants to persist",
        )
        assert result.ok is False
        assert result.encryption_failed is True
        bdir = result.backup_path
        # No plaintext entity content lingers — only the error marker remains.
        names = {p.name for p in bdir.iterdir()}
        assert names == {"ENCRYPTION_FAILED.txt"}
        for leaked in (
            "self_model.json",
            "intent_expression.jsonl",
            "snapshot.json",
            "manifest.json",
            "continuity.json",
            "assessment.json",
        ):
            assert not (bdir / leaked).exists()
    finally:
        set_state_encryptor(prev)
