# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the one-way v1/plaintext -> v2 per-entity migration tool."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest import mock

import pytest

from kaine.security.crypto import CryptoConfig, StateEncryptor
from kaine.security.custody.envelope import is_v2
from kaine.security.custody.keyring import KeyRing, SoftwareKek
from kaine.security.custody.migrate import (
    MigrationError,
    migrate,
)

_ENTITY_A = "ent-0123456789abcdef0123456789abcdef"
_ENTITY_B = "ent-fedcba9876543210fedcba9876543210"


def _make_kek() -> SoftwareKek:
    return SoftwareKek(os.urandom(32))


def _make_v1_encryptor() -> StateEncryptor:
    """Create a v1 StateEncryptor with a known key."""
    key = os.urandom(32)
    os.environ["KAINE_STATE_KEY"] = key.hex()
    enc = StateEncryptor(CryptoConfig(enabled=True))
    return enc


def _build_snapshot(entity_id: str) -> str:
    """Build a minimal snapshot JSON string with an entity_id in metadata."""
    return json.dumps({
        "id": "abcdef0123456789",
        "parent_id": None,
        "label": "",
        "timestamp": 1700000000.0,
        "modules": {},
        "adapters": [],
        "metadata": {
            "identity": {
                "entity_id": entity_id,
                "lineage": [],
                "origin": "minted",
                "minted_at": 1700000000.0,
                "legacy_source": None,
            }
        },
    })


def _setup_snapshot_entity(
    state_root: Path,
    entity_id: str,
    v1_enc: StateEncryptor | None = None,
    *,
    plaintext: bool = False,
) -> Path:
    """Create a snapshot entity directory with a snapshot.json.

    If v1_enc is provided, the snapshot is v1-encrypted.
    If plaintext is True, the snapshot is written as plaintext.
    """
    snap_id = "abcdef0123456789"
    entity_dir = state_root / snap_id
    entity_dir.mkdir(parents=True, exist_ok=True)

    snap_content = _build_snapshot(entity_id)

    if v1_enc is not None and not plaintext:
        blob = v1_enc.encrypt(snap_content.encode("utf-8"))
        (entity_dir / "snapshot.json").write_bytes(blob)
    else:
        (entity_dir / "snapshot.json").write_text(snap_content)

    # Write identity sidecar so entity_id discovery works
    (entity_dir / "identity.json").write_text(
        json.dumps({"entity_id": entity_id, "lineage": []})
    )

    return entity_dir


def _setup_artifact_files(entity_dir: Path, v1_enc: StateEncryptor | None = None) -> None:
    """Add artifact files to an entity directory."""
    art_dir = entity_dir / "artifacts" / "self_model"
    art_dir.mkdir(parents=True, exist_ok=True)

    content = b"self model artifact data"
    if v1_enc is not None:
        blob = v1_enc.encrypt(content)
        (art_dir / "document.json").write_bytes(blob)
    else:
        (art_dir / "document.json").write_bytes(content)


def _setup_preservation_entity(
    state_root: Path,
    entity_id: str,
    v1_enc: StateEncryptor | None = None,
) -> Path:
    """Create a preservation bundle directory."""
    pres_dir = state_root / "preservation" / entity_id
    pres_dir.mkdir(parents=True, exist_ok=True)

    # Write manifest
    manifest = {
        "identity": {
            "entity_id": entity_id,
            "lineage": [],
        },
        "preserved_at": 1700000000.0,
    }
    (pres_dir / "manifest.json").write_text(json.dumps(manifest))

    # Write bundle tar
    bundle_data = b"fake tar bundle content for testing"
    if v1_enc is not None:
        blob = v1_enc.encrypt(bundle_data)
        (pres_dir / "bundle.tar.enc").write_bytes(blob)
    else:
        (pres_dir / "bundle.tar").write_bytes(bundle_data)

    return pres_dir


class TestMigrateV1Snapshot:
    """Test 1: Migrate a v1-encrypted snapshot.json to v2."""

    def test_v1_snapshot_migrated_to_v2(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        key = os.urandom(32)
        monkeypatch.setenv("KAINE_STATE_KEY", key.hex())
        v1_enc = StateEncryptor(CryptoConfig(enabled=True))

        state_root = tmp_path / "state"
        entity_dir = _setup_snapshot_entity(state_root, _ENTITY_A, v1_enc)

        kek = _make_kek()
        summary = migrate(state_root, kek=kek)

        assert not summary.dry_run
        assert len(summary.results) == 1
        assert summary.results[0].entity_id == _ENTITY_A
        assert summary.results[0].re_encrypted_count == 1

        # The file on disk should now be v2
        raw = (entity_dir / "snapshot.json").read_bytes()
        assert is_v2(raw)

        # Verify it decrypts correctly
        ring = KeyRing(kek, state_root=state_root)
        enc = ring.encryptor_for(_ENTITY_A)
        plaintext = enc.decrypt(raw, kind="snapshot")
        snap = json.loads(plaintext)
        assert snap["metadata"]["identity"]["entity_id"] == _ENTITY_A


class TestMigratePlaintextSnapshot:
    """Test 2: Migrate a plaintext snapshot.json to v2."""

    def test_plaintext_snapshot_encrypted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        key = os.urandom(32)
        monkeypatch.setenv("KAINE_STATE_KEY", key.hex())

        state_root = tmp_path / "state"
        entity_dir = _setup_snapshot_entity(state_root, _ENTITY_A, plaintext=True)

        original = (entity_dir / "snapshot.json").read_text()

        kek = _make_kek()
        summary = migrate(state_root, kek=kek)

        assert len(summary.results) == 1
        assert summary.results[0].encrypted_count == 1

        raw = (entity_dir / "snapshot.json").read_bytes()
        assert is_v2(raw)

        ring = KeyRing(kek, state_root=state_root)
        enc = ring.encryptor_for(_ENTITY_A)
        plaintext = enc.decrypt(raw, kind="snapshot")
        assert json.loads(plaintext) == json.loads(original)


class TestSkipV2:
    """Test 3: Skip a file that is already v2-encrypted."""

    def test_already_v2_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        key = os.urandom(32)
        monkeypatch.setenv("KAINE_STATE_KEY", key.hex())

        state_root = tmp_path / "state"
        entity_dir = _setup_snapshot_entity(state_root, _ENTITY_A, plaintext=True)

        # Pre-encrypt the snapshot as v2
        from kaine.security.custody.envelope import encrypt_v2

        snap_content = (entity_dir / "snapshot.json").read_bytes()
        dek = os.urandom(32)
        v2_blob = encrypt_v2(dek, _ENTITY_A, "snapshot", snap_content)
        (entity_dir / "snapshot.json").write_bytes(v2_blob)

        kek = _make_kek()
        summary = migrate(state_root, kek=kek, force=True)

        assert len(summary.results) == 1
        assert summary.results[0].skipped_v2_count == 1
        assert summary.results[0].encrypted_count == 0
        assert summary.results[0].re_encrypted_count == 0


class TestDryRun:
    """Test 4: Dry run makes no changes."""

    def test_dry_run_no_changes(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        key = os.urandom(32)
        monkeypatch.setenv("KAINE_STATE_KEY", key.hex())

        state_root = tmp_path / "state"
        entity_dir = _setup_snapshot_entity(state_root, _ENTITY_A, plaintext=True)

        original_content = (entity_dir / "snapshot.json").read_bytes()

        kek = _make_kek()
        summary = migrate(state_root, dry_run=True, kek=kek)

        assert summary.dry_run
        assert len(summary.results) == 1
        assert summary.results[0].encrypted_count == 1

        # File should be unchanged
        assert (entity_dir / "snapshot.json").read_bytes() == original_content

        # No backup directory created
        assert not (state_root / ".migration-backup").exists()

        # No DEK file created
        ring = KeyRing(kek, state_root=state_root)
        assert not ring.has_dek(_ENTITY_A)


class TestVerifyAfterEncrypt:
    """Test 5: Verify-after-encrypt catches corruption."""

    def test_corruption_detected(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        key = os.urandom(32)
        monkeypatch.setenv("KAINE_STATE_KEY", key.hex())

        state_root = tmp_path / "state"
        _setup_snapshot_entity(state_root, _ENTITY_A, plaintext=True)

        kek = _make_kek()

        # Mock the EntityEncryptor.decrypt to return different data (simulating corruption)
        from kaine.security.custody.encryptor import EntityEncryptor

        def bad_decrypt(self: EntityEncryptor, blob: bytes, *, kind: str) -> bytes:
            return b"corrupted data that does not match"

        with mock.patch.object(EntityEncryptor, "decrypt", bad_decrypt):
            summary = migrate(state_root, kek=kek)

        assert len(summary.results) == 1
        result = summary.results[0]
        assert result.error_count == 1
        assert "hash mismatch" in result.files[0].error


class TestBackupCreated:
    """Test 6: Backup directory is created before modification."""

    def test_backup_exists(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        key = os.urandom(32)
        monkeypatch.setenv("KAINE_STATE_KEY", key.hex())

        state_root = tmp_path / "state"
        _setup_snapshot_entity(state_root, _ENTITY_A, plaintext=True)

        kek = _make_kek()
        migrate(state_root, kek=kek)

        backup_root = state_root / ".migration-backup"
        assert backup_root.is_dir()

        # The backup should contain the snapshot directory
        backup_entries = list(backup_root.iterdir())
        assert len(backup_entries) == 1
        assert (backup_entries[0] / "snapshot.json").is_file()


class TestPreservationBundle:
    """Test 7: Migration of a preservation bundle tar."""

    def test_preservation_bundle_migrated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        key = os.urandom(32)
        monkeypatch.setenv("KAINE_STATE_KEY", key.hex())
        v1_enc = StateEncryptor(CryptoConfig(enabled=True))

        state_root = tmp_path / "state"
        pres_dir = _setup_preservation_entity(state_root, _ENTITY_B, v1_enc)

        kek = _make_kek()
        summary = migrate(state_root, kek=kek)

        # Find the preservation entity result
        pres_results = [r for r in summary.results if r.entity_id == _ENTITY_B]
        assert len(pres_results) == 1
        result = pres_results[0]
        assert result.re_encrypted_count == 1

        # The bundle file should be v2
        raw = (pres_dir / "bundle.tar.enc").read_bytes()
        assert is_v2(raw)


class TestRoundTrip:
    """Test 8: Round-trip -- migrated file decrypts to original plaintext."""

    def test_round_trip_integrity(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        key = os.urandom(32)
        monkeypatch.setenv("KAINE_STATE_KEY", key.hex())
        v1_enc = StateEncryptor(CryptoConfig(enabled=True))

        state_root = tmp_path / "state"
        entity_dir = _setup_snapshot_entity(state_root, _ENTITY_A, v1_enc)
        _setup_artifact_files(entity_dir, v1_enc)

        # Remember original plaintexts
        snap_plaintext = v1_enc.decrypt(
            (entity_dir / "snapshot.json").read_bytes()
        )
        art_plaintext = v1_enc.decrypt(
            (entity_dir / "artifacts" / "self_model" / "document.json").read_bytes()
        )

        kek = _make_kek()
        summary = migrate(state_root, kek=kek)

        assert not summary.errors
        result = summary.results[0]
        assert result.error_count == 0
        assert result.re_encrypted_count == 2  # snapshot + artifact

        # Decrypt both files and verify
        ring = KeyRing(kek, state_root=state_root)
        enc = ring.encryptor_for(_ENTITY_A)

        snap_v2 = (entity_dir / "snapshot.json").read_bytes()
        assert enc.decrypt(snap_v2, kind="snapshot") == snap_plaintext

        art_v2 = (entity_dir / "artifacts" / "self_model" / "document.json").read_bytes()
        assert enc.decrypt(art_v2, kind="artifact") == art_plaintext


class TestMigrationErrors:
    """Additional error-path tests."""

    def test_missing_state_root_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        key = os.urandom(32)
        monkeypatch.setenv("KAINE_STATE_KEY", key.hex())
        kek = _make_kek()
        with pytest.raises(MigrationError, match="does not exist"):
            migrate(tmp_path / "nonexistent", kek=kek)

    def test_no_state_key_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("KAINE_STATE_KEY", raising=False)
        state_root = tmp_path / "state"
        state_root.mkdir()
        kek = _make_kek()
        with pytest.raises(MigrationError, match="v1 decryptor"):
            migrate(state_root, kek=kek)

    def test_skip_entity_with_existing_dek(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        key = os.urandom(32)
        monkeypatch.setenv("KAINE_STATE_KEY", key.hex())

        state_root = tmp_path / "state"
        _setup_snapshot_entity(state_root, _ENTITY_A, plaintext=True)

        kek = _make_kek()
        ring = KeyRing(kek, state_root=state_root)
        ring.generate_dek(_ENTITY_A)

        summary = migrate(state_root, kek=kek)

        assert len(summary.results) == 1
        assert summary.results[0].skipped
