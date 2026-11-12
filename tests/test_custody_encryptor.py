# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the per-entity EntityEncryptor wrapper."""

from __future__ import annotations

import base64
import os

import pytest
from cryptography.exceptions import InvalidTag

from kaine.security.crypto import CryptoConfigError
from kaine.security.custody.encryptor import EntityEncryptor
from kaine.security.custody.envelope import VALID_KINDS

_ENTITY = "ent-0123456789abcdef0123456789abcdef"


def _fresh_dek() -> bytes:
    return os.urandom(32)


# -- round-trip per kind ---------------------------------------------------


@pytest.mark.parametrize("kind", sorted(VALID_KINDS))
def test_round_trip_all_kinds(kind: str) -> None:
    dek = _fresh_dek()
    enc = EntityEncryptor(_ENTITY, dek)
    plaintext = b"cognitive state for " + kind.encode()
    blob = enc.encrypt(plaintext, kind=kind)
    assert enc.decrypt(blob, kind=kind) == plaintext


# -- cross-kind rejection -------------------------------------------------


def test_cross_kind_rejection() -> None:
    dek = _fresh_dek()
    enc = EntityEncryptor(_ENTITY, dek)
    blob = enc.encrypt(b"secret", kind="snapshot")
    with pytest.raises(InvalidTag):
        enc.decrypt(blob, kind="bundle")


# -- wrong DEK rejection --------------------------------------------------


def test_wrong_dek_rejection() -> None:
    dek_a = _fresh_dek()
    dek_b = _fresh_dek()
    enc_a = EntityEncryptor(_ENTITY, dek_a)
    enc_b = EntityEncryptor(_ENTITY, dek_b)
    blob = enc_a.encrypt(b"secret", kind="snapshot")
    with pytest.raises(InvalidTag):
        enc_b.decrypt(blob, kind="snapshot")


# -- text convenience round-trip -------------------------------------------


def test_text_round_trip() -> None:
    dek = _fresh_dek()
    enc = EntityEncryptor(_ENTITY, dek)
    original = "hello, cognitive state"
    encrypted = enc.encrypt_text(original, kind="snapshot")
    assert isinstance(encrypted, str)
    assert enc.decrypt_text(encrypted, kind="snapshot") == original


# -- maybe_decrypt: plaintext passthrough ----------------------------------


def test_maybe_decrypt_passes_plaintext() -> None:
    enc = EntityEncryptor(_ENTITY, _fresh_dek())
    raw = b"just plain bytes, not an envelope"
    assert enc.maybe_decrypt(raw, kind="snapshot") == raw


# -- maybe_decrypt: v2 blob -----------------------------------------------


def test_maybe_decrypt_decrypts_v2() -> None:
    dek = _fresh_dek()
    enc = EntityEncryptor(_ENTITY, dek)
    plaintext = b"v2 protected payload"
    blob = enc.encrypt(plaintext, kind="bundle")
    assert enc.maybe_decrypt(blob, kind="bundle") == plaintext


# -- maybe_decrypt: v1 blob raises CryptoConfigError ----------------------


def test_maybe_decrypt_raises_on_v1() -> None:
    enc = EntityEncryptor(_ENTITY, _fresh_dek())
    # Construct a fake v1 blob: magic + random bytes, base64-encoded.
    v1_framed = b"KAINEgcm1:" + os.urandom(28)
    v1_blob = base64.b64encode(v1_framed)
    with pytest.raises(CryptoConfigError, match="v1 envelopes"):
        enc.maybe_decrypt(v1_blob, kind="snapshot")


# -- enabled property ------------------------------------------------------


def test_enabled_always_true() -> None:
    enc = EntityEncryptor(_ENTITY, _fresh_dek())
    assert enc.enabled is True


# -- entity_id property ----------------------------------------------------


def test_entity_id_property() -> None:
    enc = EntityEncryptor(_ENTITY, _fresh_dek())
    assert enc.entity_id == _ENTITY


# -- close() zeros DEK ----------------------------------------------------


def test_close_zeros_dek() -> None:
    enc = EntityEncryptor(_ENTITY, _fresh_dek())
    enc.close()
    assert all(b == 0 for b in enc._dek)


# -- after close(), encrypt raises ----------------------------------------


def test_encrypt_after_close_raises() -> None:
    enc = EntityEncryptor(_ENTITY, _fresh_dek())
    enc.close()
    with pytest.raises(RuntimeError, match="closed"):
        enc.encrypt(b"nope", kind="snapshot")


# -- after close(), decrypt raises ----------------------------------------


def test_decrypt_after_close_raises() -> None:
    dek = _fresh_dek()
    enc = EntityEncryptor(_ENTITY, dek)
    blob = enc.encrypt(b"secret", kind="snapshot")
    enc.close()
    with pytest.raises(RuntimeError, match="closed"):
        enc.decrypt(blob, kind="snapshot")


# -- invalid entity_id at construction ------------------------------------


def test_empty_entity_id_raises() -> None:
    with pytest.raises(ValueError, match="entity_id"):
        EntityEncryptor("", _fresh_dek())


# -- invalid DEK length at construction ------------------------------------


@pytest.mark.parametrize("length", [0, 16, 31, 33, 64])
def test_invalid_dek_length_raises(length: int) -> None:
    with pytest.raises(ValueError, match="DEK must be exactly 32 bytes"):
        EntityEncryptor(_ENTITY, os.urandom(length))
