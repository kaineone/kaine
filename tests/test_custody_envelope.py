# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the v2 entity-key custody envelope."""

from __future__ import annotations

import base64
import os

import pytest
from cryptography.exceptions import InvalidTag

from kaine.security.custody.envelope import (
    VALID_KINDS,
    decrypt_v2,
    encrypt_v2,
    is_v2,
)

_ENTITY_A = "ent-0123456789abcdef0123456789abcdef"
_ENTITY_B = "ent-fedcba9876543210fedcba9876543210"


def _fresh_dek() -> bytes:
    return os.urandom(32)


# -- round-trip -----------------------------------------------------------


@pytest.mark.parametrize("kind", sorted(VALID_KINDS))
def test_round_trip_all_kinds(kind: str) -> None:
    dek = _fresh_dek()
    plaintext = b"cognitive state payload for " + kind.encode()
    blob = encrypt_v2(dek, _ENTITY_A, kind, plaintext)
    assert decrypt_v2(dek, _ENTITY_A, kind, blob) == plaintext


# -- cross-entity rejection -----------------------------------------------


def test_cross_entity_rejection() -> None:
    dek = _fresh_dek()
    blob = encrypt_v2(dek, _ENTITY_A, "snapshot", b"secret")
    with pytest.raises(InvalidTag):
        decrypt_v2(dek, _ENTITY_B, "snapshot", blob)


# -- cross-kind rejection -------------------------------------------------


def test_cross_kind_rejection() -> None:
    dek = _fresh_dek()
    blob = encrypt_v2(dek, _ENTITY_A, "snapshot", b"secret")
    with pytest.raises(InvalidTag):
        decrypt_v2(dek, _ENTITY_A, "bundle", blob)


# -- wrong DEK rejection --------------------------------------------------


def test_wrong_dek_rejection() -> None:
    dek_a = _fresh_dek()
    dek_b = _fresh_dek()
    blob = encrypt_v2(dek_a, _ENTITY_A, "snapshot", b"secret")
    with pytest.raises(InvalidTag):
        decrypt_v2(dek_b, _ENTITY_A, "snapshot", blob)


# -- tamper detection ------------------------------------------------------


def test_tamper_detection() -> None:
    dek = _fresh_dek()
    blob = encrypt_v2(dek, _ENTITY_A, "snapshot", b"secret")
    raw = base64.b64decode(blob)
    # Flip one byte in the ciphertext region (past the header+salt+nonce).
    tampered = bytearray(raw)
    tampered[-1] ^= 0xFF
    reencoded = base64.b64encode(bytes(tampered))
    with pytest.raises(InvalidTag):
        decrypt_v2(dek, _ENTITY_A, "snapshot", reencoded)


# -- invalid kind ----------------------------------------------------------


def test_invalid_kind_encrypt() -> None:
    with pytest.raises(ValueError, match="not valid"):
        encrypt_v2(_fresh_dek(), _ENTITY_A, "diary", b"nope")


def test_invalid_kind_decrypt() -> None:
    with pytest.raises(ValueError, match="not valid"):
        decrypt_v2(_fresh_dek(), _ENTITY_A, "diary", b"anything")


# -- empty entity_id -------------------------------------------------------


def test_empty_entity_id_encrypt() -> None:
    with pytest.raises(ValueError, match="entity_id"):
        encrypt_v2(_fresh_dek(), "", "snapshot", b"nope")


def test_empty_entity_id_decrypt() -> None:
    with pytest.raises(ValueError, match="entity_id"):
        decrypt_v2(_fresh_dek(), "", "snapshot", b"anything")


# -- is_v2 detection -------------------------------------------------------


def test_is_v2_base64() -> None:
    dek = _fresh_dek()
    blob = encrypt_v2(dek, _ENTITY_A, "snapshot", b"test")
    assert is_v2(blob) is True


def test_is_v2_raw() -> None:
    dek = _fresh_dek()
    blob = encrypt_v2(dek, _ENTITY_A, "snapshot", b"test")
    raw = base64.b64decode(blob)
    assert is_v2(raw) is True


def test_is_v2_rejects_v1() -> None:
    v1_blob = base64.b64encode(b"KAINEgcm1:" + os.urandom(28))
    assert is_v2(v1_blob) is False


def test_is_v2_rejects_garbage() -> None:
    assert is_v2(b"not an envelope at all") is False


# -- nonce uniqueness (different salts) ------------------------------------


def test_nonce_uniqueness() -> None:
    dek = _fresh_dek()
    plaintext = b"identical payload"
    blob_a = encrypt_v2(dek, _ENTITY_A, "snapshot", plaintext)
    blob_b = encrypt_v2(dek, _ENTITY_A, "snapshot", plaintext)
    assert blob_a != blob_b


# -- output is valid UTF-8 ASCII (safe for JSON/JSONL) ---------------------


def test_output_is_ascii_safe() -> None:
    dek = _fresh_dek()
    blob = encrypt_v2(dek, _ENTITY_A, "bundle", b"\x00\xff" * 1024)
    text = blob.decode("ascii")
    assert text == text.encode("utf-8").decode("utf-8")
