# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the AES-256-GCM StateEncryptor (kaine/security/crypto.py).

Covers: encrypt/decrypt round-trip, transparent no-op when disabled,
fail-closed CryptoConfigError on a missing key, authenticated-encryption
tamper detection, and per-message nonce uniqueness.
"""
from __future__ import annotations

import base64
import os

import pytest

from kaine.security.crypto import (
    CryptoConfig,
    CryptoConfigError,
    StateEncryptor,
    get_state_encryptor,
    install_from_section,
    is_encrypted,
    set_state_encryptor,
)

KEY_B64 = base64.b64encode(os.urandom(32)).decode("ascii")


@pytest.fixture
def enabled_encryptor(monkeypatch):
    monkeypatch.setenv("KAINE_STATE_KEY", KEY_B64)
    return StateEncryptor(CryptoConfig(enabled=True))


# -- round-trip -------------------------------------------------------------


def test_roundtrip_bytes(enabled_encryptor):
    plaintext = b"who am i: numeric derived state only"
    blob = enabled_encryptor.encrypt(plaintext)
    assert blob != plaintext
    assert is_encrypted(base64.b64decode(blob))
    assert enabled_encryptor.decrypt(blob) == plaintext


def test_roundtrip_text(enabled_encryptor):
    text = '{"name": "Kaine Voxel", "internal_speech_count": 3}'
    blob = enabled_encryptor.encrypt_text(text)
    assert blob != text
    assert enabled_encryptor.decrypt_text(blob) == text


def test_ciphertext_is_not_human_readable(enabled_encryptor):
    text = "SECRET-MARKER-12345"
    blob = enabled_encryptor.encrypt_text(text)
    assert "SECRET-MARKER-12345" not in blob


# -- disabled = no-op -------------------------------------------------------


def test_disabled_is_passthrough():
    enc = StateEncryptor(CryptoConfig(enabled=False))
    assert enc.enabled is False
    assert enc.encrypt(b"hello") == b"hello"
    assert enc.encrypt_text("hello") == "hello"
    # maybe_decrypt leaves plaintext untouched.
    assert enc.maybe_decrypt(b"plain json line") == b"plain json line"


def test_disabled_does_not_import_cryptography():
    # Constructing a disabled encryptor must not require the library; we just
    # assert _aead stays None (the lazy AESGCM handle is never built).
    enc = StateEncryptor(CryptoConfig(enabled=False))
    assert enc._aead is None


# -- fail-closed on missing key --------------------------------------------


def test_missing_key_raises_at_construction(monkeypatch):
    monkeypatch.delenv("KAINE_STATE_KEY", raising=False)
    # Force the keyring fallback to yield nothing.
    monkeypatch.setattr(
        "kaine.security.crypto._load_key_from_keyring", lambda: None
    )
    with pytest.raises(CryptoConfigError):
        StateEncryptor(CryptoConfig(enabled=True))


def test_install_from_section_fail_closed(monkeypatch):
    monkeypatch.delenv("KAINE_STATE_KEY", raising=False)
    monkeypatch.setattr(
        "kaine.security.crypto._load_key_from_keyring", lambda: None
    )
    with pytest.raises(CryptoConfigError):
        install_from_section({"enabled": True})


def test_bad_key_length_raises(monkeypatch):
    monkeypatch.setenv("KAINE_STATE_KEY", "too-short")
    with pytest.raises(CryptoConfigError):
        StateEncryptor(CryptoConfig(enabled=True))


def test_unsupported_algorithm_raises(monkeypatch):
    monkeypatch.setenv("KAINE_STATE_KEY", KEY_B64)
    with pytest.raises(CryptoConfigError):
        StateEncryptor(CryptoConfig(enabled=True, algorithm="rot13"))


# -- authentication / tamper detection -------------------------------------


def test_tampered_ciphertext_fails_authentication(enabled_encryptor):
    from cryptography.exceptions import InvalidTag

    blob = enabled_encryptor.encrypt(b"trustworthy state")
    framed = bytearray(base64.b64decode(blob))
    # Flip a bit in the ciphertext+tag region (after magic + 12-byte nonce).
    framed[-1] ^= 0x01
    tampered = base64.b64encode(bytes(framed))
    with pytest.raises(InvalidTag):
        enabled_encryptor.decrypt(tampered)


def test_wrong_key_fails_authentication(monkeypatch):
    from cryptography.exceptions import InvalidTag

    monkeypatch.setenv("KAINE_STATE_KEY", KEY_B64)
    writer = StateEncryptor(CryptoConfig(enabled=True))
    blob = writer.encrypt(b"state under key A")

    other_key = base64.b64encode(os.urandom(32)).decode("ascii")
    monkeypatch.setenv("KAINE_STATE_KEY", other_key)
    reader = StateEncryptor(CryptoConfig(enabled=True))
    with pytest.raises(InvalidTag):
        reader.decrypt(blob)


def test_non_envelope_blob_rejected_by_strict_decrypt(enabled_encryptor):
    with pytest.raises(CryptoConfigError):
        enabled_encryptor.decrypt(base64.b64encode(b"not a kaine envelope"))


# -- nonce uniqueness -------------------------------------------------------


def test_nonce_unique_per_encryption(enabled_encryptor):
    plaintext = b"identical input every time"
    nonces = set()
    blobs = set()
    for _ in range(200):
        blob = enabled_encryptor.encrypt(plaintext)
        framed = base64.b64decode(blob)
        # magic(10) + nonce(12) + ciphertext.
        nonce = framed[10:22]
        assert len(nonce) == 12
        nonces.add(nonce)
        blobs.add(blob)
    # Every nonce — and therefore every ciphertext — is distinct.
    assert len(nonces) == 200
    assert len(blobs) == 200


# -- enabled reader still ingests legacy plaintext --------------------------


def test_enabled_reader_passes_through_legacy_plaintext(enabled_encryptor):
    legacy = b'{"legacy": "pre-encryption file"}'
    assert enabled_encryptor.maybe_decrypt(legacy) == legacy


# -- process-global install/reset ------------------------------------------


def test_default_global_is_disabled_noop():
    set_state_encryptor(StateEncryptor(CryptoConfig()))
    enc = get_state_encryptor()
    assert enc.enabled is False
    assert enc.encrypt(b"x") == b"x"
