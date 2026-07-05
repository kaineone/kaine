# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Self-model (state/eidolon/self_model.json) at-rest encryption.

Verifies that when state encryption is enabled the on-disk self-model is
AES-256-GCM encrypted (unreadable without the key) and round-trips correctly
through `load`, and that the disabled default still writes/reads plaintext.
"""
from __future__ import annotations

import base64
import os

import pytest

from kaine.modules.eidolon.document import SelfModel, load, save_atomic
from kaine.security.crypto import (
    CryptoConfig,
    StateEncryptor,
    set_state_encryptor,
)

KEY_B64 = base64.b64encode(os.urandom(32)).decode("ascii")


@pytest.fixture
def enabled_global(monkeypatch):
    """Install an enabled process-global encryptor; restore disabled after."""
    monkeypatch.setenv("KAINE_STATE_KEY", KEY_B64)
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))
    try:
        yield
    finally:
        set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.fixture
def disabled_global():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def _model() -> SelfModel:
    return SelfModel(
        name="Kaine Voxel",
        values=["curiosity"],
        internal_speech_count=7,
        external_speech_count=3,
    )


def test_self_model_encrypted_on_disk_and_roundtrips(enabled_global, tmp_path):
    path = tmp_path / "eidolon" / "self_model.json"
    model = _model()
    save_atomic(path, model)

    raw = path.read_bytes()
    # On-disk bytes are NOT human-readable plaintext JSON.
    assert b"Kaine Voxel" not in raw
    assert b'"name"' not in raw

    # And they decrypt back to the original via load().
    restored = load(path)
    assert restored.name == "Kaine Voxel"
    assert restored.internal_speech_count == 7
    assert restored.external_speech_count == 3


def test_self_model_unreadable_without_key(enabled_global, tmp_path):
    path = tmp_path / "self_model.json"
    save_atomic(path, _model())
    raw = path.read_bytes()

    # A naive plaintext JSON reader cannot recover the content.
    import json

    with pytest.raises(Exception):
        json.loads(raw)

    # A disabled (keyless) reader passes the ciphertext through unchanged, so
    # it does NOT reconstruct the model — confirming confidentiality at rest.
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    with pytest.raises(Exception):
        load(path)


def test_self_model_plaintext_when_disabled(disabled_global, tmp_path):
    import json

    path = tmp_path / "self_model.json"
    save_atomic(path, _model())
    raw = path.read_text(encoding="utf-8")
    # Plaintext JSON, byte-for-byte the legacy behaviour.
    assert json.loads(raw)["name"] == "Kaine Voxel"
    assert load(path).name == "Kaine Voxel"
