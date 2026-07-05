# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Fork/merge export-bundle at-rest encryption (state/forks/<id>/snapshot.json).

Verifies that with encryption enabled the snapshot bundle is AES-256-GCM
encrypted on disk, imports (decrypts) correctly with the right key, and fails
to import with the wrong key.
"""
from __future__ import annotations

import base64
import os

import pytest

from kaine.lifecycle.snapshot import ForkSnapshot, load_snapshot, save_snapshot
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    set_state_encryptor,
)

KEY_A = base64.b64encode(os.urandom(32)).decode("ascii")
KEY_B = base64.b64encode(os.urandom(32)).decode("ascii")


@pytest.fixture(autouse=True)
def restore_default():
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def _snap() -> ForkSnapshot:
    return ForkSnapshot(
        parent_id=None,
        label="root",
        modules={"soma": {"wellness": 0.9}, "chronos": {"steps": 12}},
        adapters=["state/hypnos/adapters/a"],
        metadata={"note": "fork export"},
    )


def _install(key_b64: str, monkeypatch):
    monkeypatch.setenv("KAINE_STATE_KEY", key_b64)
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))


def test_fork_bundle_encrypted_on_disk(monkeypatch, tmp_path):
    _install(KEY_A, monkeypatch)
    snap = _snap()
    save_snapshot(tmp_path, snap)

    target = tmp_path / snap.id / "snapshot.json"
    raw = target.read_bytes()
    # The bundle is not human-readable JSON.
    assert b'"soma"' not in raw
    assert b"wellness" not in raw
    import json

    with pytest.raises(Exception):
        json.loads(raw)


def test_fork_import_with_correct_key(monkeypatch, tmp_path):
    _install(KEY_A, monkeypatch)
    snap = _snap()
    save_snapshot(tmp_path, snap)

    restored = load_snapshot(tmp_path, snap.id)
    assert restored.id == snap.id
    assert restored.modules["soma"]["wellness"] == 0.9
    assert restored.metadata["note"] == "fork export"


def test_fork_import_with_wrong_key_fails(monkeypatch, tmp_path):
    from cryptography.exceptions import InvalidTag

    _install(KEY_A, monkeypatch)
    snap = _snap()
    save_snapshot(tmp_path, snap)

    # Re-key the reader: out-of-band key mismatch must fail authentication.
    _install(KEY_B, monkeypatch)
    with pytest.raises(InvalidTag):
        load_snapshot(tmp_path, snap.id)


def test_fork_bundle_plaintext_when_disabled(tmp_path):
    import json

    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    snap = _snap()
    save_snapshot(tmp_path, snap)
    target = tmp_path / snap.id / "snapshot.json"
    raw = json.loads(target.read_text())
    assert raw["modules"]["soma"]["wellness"] == 0.9
    assert load_snapshot(tmp_path, snap.id).id == snap.id
