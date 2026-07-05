# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kaine.lifecycle.decommission import capture_backup
from kaine.lifecycle.divergence import DivergenceAssessment
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    get_state_encryptor,
    set_state_encryptor,
)


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


def _seed_fork(fork_root: Path) -> None:
    from kaine.lifecycle.snapshot import ForkSnapshot, save_snapshot

    snap = ForkSnapshot(label="root", modules={"soma": {"wellness": 0.9}})
    save_snapshot(fork_root, snap)


def _assessment(diverged=True) -> DivergenceAssessment:
    return DivergenceAssessment(
        diverged=diverged, signals={"individuation_significant": diverged}, summary="x"
    )


def test_capture_backup_copies_artifacts_and_manifest(tmp_path):
    state_root = tmp_path / "state"
    fork_root = tmp_path / "forks"
    out_root = tmp_path / "backups"
    _seed_state(state_root)
    _seed_fork(fork_root)

    result = capture_backup(
        state_root=state_root,
        fork_root=fork_root,
        qdrant_cfg={},  # no qdrant → instructions written
        out_root=out_root,
        entity_name="Kaine Nova",
        assessment=_assessment(),
        continuity_note="wants to persist",
    )
    assert result.ok
    bdir = result.backup_path
    assert (bdir / "self_model.json").is_file()
    assert (bdir / "intent_expression.jsonl").is_file()
    assert (bdir / "adapters" / "voice.bin").is_file()
    assert (bdir / "snapshot.json").is_file()
    assert (bdir / "QDRANT_BACKUP_INSTRUCTIONS.txt").is_file()

    manifest = json.loads((bdir / "manifest.json").read_text())
    assert manifest["entity_name"] == "Kaine Nova"
    # S3: the plaintext manifest carries only the NON-sensitive inventory plus a
    # bare diverged bool — never the inner-life fields.
    assert manifest["diverged"] is True
    assert "assessment" not in manifest
    assert "continuity_note" not in manifest
    assert "self_model.json" in manifest["inventory"]
    assert "restore_notes" in manifest
    # S3: the sensitive inner-life rides in separate sidecars. Encryption is
    # disabled here (no key), so they are honest plaintext sidecars.
    assess = json.loads((bdir / "assessment.json").read_text())
    assert assess["diverged"] is True
    assert assess["signals"] == {"individuation_significant": True}
    cont = json.loads((bdir / "continuity.json").read_text())
    assert cont["continuity_note"] == "wants to persist"


def test_capture_backup_qdrant_unreachable_writes_instructions(tmp_path):
    state_root = tmp_path / "state"
    _seed_state(state_root)
    result = capture_backup(
        state_root=state_root,
        fork_root=tmp_path / "forks",
        qdrant_cfg={"mnemos": {"qdrant": {"host": "127.0.0.1", "port": 59999}}},
        out_root=tmp_path / "backups",
        entity_name="Kaine Nova",
        assessment=_assessment(),
    )
    assert result.ok  # never crashes on unreachable qdrant
    assert (result.backup_path / "QDRANT_BACKUP_INSTRUCTIONS.txt").is_file()


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
            qdrant_cfg={},
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
        qdrant_cfg={},
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
        qdrant_cfg={},
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
            qdrant_cfg={},
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
