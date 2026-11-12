# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""v2 encryption envelope for entity key custody.

Adds per-envelope HKDF subkeys and authenticated associated data (AAD) to the
v1 AES-256-GCM scheme in ``kaine.security.crypto``.  Every envelope derives a
fresh AES-256-GCM key from the entity's DEK via HKDF-SHA256, keyed by a random
salt and bound to the entity_id and data kind through the AAD.  This removes
the ~2^32 random-nonce limit per key (critical for long-lived JSONL sinks) and
makes cross-entity or cross-kind replay fail authentication.
"""

from __future__ import annotations

import base64
import os

_MAGIC = b"KAINEgcm2:"
_SALT_BYTES = 16
_NONCE_BYTES = 12
_KEY_BYTES = 32

VALID_KINDS: frozenset[str] = frozenset(
    {
        "artifact",
        "snapshot",
        "sidecar-jsonl",
        "bundle",
        "world_model",
        "self_model",
        "individuation",
        "backup",
        "research",
    }
)


def _build_aad(entity_id: str, kind: str) -> bytes:
    return b"kaine/v2|" + entity_id.encode("utf-8") + b"|" + kind.encode("utf-8")


def _derive_subkey(dek: bytes, salt: bytes, aad: bytes) -> bytes:
    from cryptography.hazmat.primitives.hashes import SHA256
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    return HKDF(
        algorithm=SHA256(),
        length=_KEY_BYTES,
        salt=salt,
        info=aad,
    ).derive(dek)


def _validate(entity_id: str, kind: str) -> None:
    if not entity_id:
        raise ValueError("entity_id must not be empty")
    if kind not in VALID_KINDS:
        raise ValueError(
            f"kind {kind!r} is not valid; expected one of {sorted(VALID_KINDS)}"
        )


def encrypt_v2(dek: bytes, entity_id: str, kind: str, plaintext: bytes) -> bytes:
    """Encrypt *plaintext* under the entity's DEK with v2 framing.

    Returns a base64-encoded framed blob safe for UTF-8 JSON/JSONL files.
    Raises :class:`ValueError` if *kind* is not in :data:`VALID_KINDS` or
    *entity_id* is empty.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    _validate(entity_id, kind)
    aad = _build_aad(entity_id, kind)
    salt = os.urandom(_SALT_BYTES)
    nonce = os.urandom(_NONCE_BYTES)
    subkey = _derive_subkey(dek, salt, aad)
    ciphertext = AESGCM(subkey).encrypt(nonce, plaintext, aad)
    framed = _MAGIC + salt + nonce + ciphertext
    return base64.b64encode(framed)


def decrypt_v2(dek: bytes, entity_id: str, kind: str, blob: bytes) -> bytes:
    """Decrypt a v2 framed blob produced by :func:`encrypt_v2`.

    Raises :class:`ValueError` for invalid framing or parameters.  Raises
    :class:`cryptography.exceptions.InvalidTag` on tampered data or wrong
    *entity_id* / *kind* / *dek*.
    """
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    _validate(entity_id, kind)
    try:
        framed = base64.b64decode(blob, validate=True)
    except Exception as exc:
        raise ValueError("blob is not valid base64") from exc
    if not framed.startswith(_MAGIC):
        raise ValueError("blob is missing the v2 envelope header")
    header_end = len(_MAGIC)
    salt = framed[header_end : header_end + _SALT_BYTES]
    nonce = framed[header_end + _SALT_BYTES : header_end + _SALT_BYTES + _NONCE_BYTES]
    ciphertext = framed[header_end + _SALT_BYTES + _NONCE_BYTES :]
    if len(salt) != _SALT_BYTES or len(nonce) != _NONCE_BYTES or not ciphertext:
        raise ValueError("v2 envelope is truncated")
    aad = _build_aad(entity_id, kind)
    subkey = _derive_subkey(dek, salt, aad)
    return AESGCM(subkey).decrypt(nonce, ciphertext, aad)


def is_v2(blob: bytes) -> bool:
    """True if *blob* (raw binary or base64-encoded) carries the v2 magic."""
    if blob.startswith(_MAGIC):
        return True
    try:
        return base64.b64decode(blob, validate=True).startswith(_MAGIC)
    except Exception:
        return False
