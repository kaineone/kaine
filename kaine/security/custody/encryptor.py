# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Per-entity encryptor wrapping the v2 envelope.

``EntityEncryptor`` gives the ``StateEncryptor`` interface an entity-aware
variant: every call is bound to a fixed entity_id and requires an explicit
data kind, so cross-entity and cross-kind replay is rejected by the
authenticated envelope rather than by convention.
"""

from __future__ import annotations

from kaine.security.custody.envelope import (
    decrypt_v2,
    encrypt_v2,
    is_v2,
)

_KEY_BYTES = 32


class EntityEncryptor:
    """Per-entity encryptor using v2 envelopes.

    Drop-in replacement for ``StateEncryptor`` with entity_id and kind
    binding.  The DEK is stored as a mutable ``bytearray`` so
    :meth:`close` can zero it.
    """

    def __init__(self, entity_id: str, dek: bytes) -> None:
        if not entity_id:
            raise ValueError("entity_id must not be empty")
        if len(dek) != _KEY_BYTES:
            raise ValueError(
                f"DEK must be exactly {_KEY_BYTES} bytes, got {len(dek)}"
            )
        self._entity_id = entity_id
        self._dek = bytearray(dek)
        self._closed = False

    def _check_open(self) -> None:
        if self._closed:
            raise RuntimeError("encryptor has been closed")

    @property
    def enabled(self) -> bool:
        return True

    @property
    def entity_id(self) -> str:
        return self._entity_id

    # -- bytes API ---------------------------------------------------------

    def encrypt(self, plaintext: bytes, *, kind: str) -> bytes:
        """Encrypt with v2 envelope bound to this entity and kind."""
        self._check_open()
        return encrypt_v2(bytes(self._dek), self._entity_id, kind, plaintext)

    def decrypt(self, blob: bytes, *, kind: str) -> bytes:
        """Decrypt a v2 envelope for this entity and kind.

        Raises ``ValueError`` for non-v2 blobs.  Raises ``InvalidTag`` on
        wrong entity/kind/dek.
        """
        self._check_open()
        return decrypt_v2(bytes(self._dek), self._entity_id, kind, blob)

    def maybe_decrypt(self, blob: bytes, *, kind: str) -> bytes:
        """Decrypt if v2 envelope, else return as-is (for legacy plaintext).

        Raises ``CryptoConfigError`` for v1 envelopes (they need the old
        global key, not a per-entity DEK).
        """
        self._check_open()
        if is_v2(blob):
            return decrypt_v2(bytes(self._dek), self._entity_id, kind, blob)

        # Lazy import to avoid circular dependency (crypto -> custody ->
        # crypto).
        from kaine.security.crypto import CryptoConfigError, is_encrypted

        try:
            import base64

            framed = base64.b64decode(blob, validate=True)
        except Exception:
            return blob
        if is_encrypted(framed):
            raise CryptoConfigError(
                "v1 envelopes need the migration tool, not EntityEncryptor"
            )
        return blob

    # -- text convenience --------------------------------------------------

    def encrypt_text(self, text: str, *, kind: str) -> str:
        """Encrypt string; returns base64 ascii."""
        return self.encrypt(text.encode("utf-8"), kind=kind).decode("ascii")

    def decrypt_text(self, text: str, *, kind: str) -> str:
        """Decrypt text, tolerating legacy plaintext.  Raises on v1."""
        return self.maybe_decrypt(
            text.encode("utf-8"), kind=kind
        ).decode("utf-8")

    # -- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Best-effort DEK erasure.

        Overwrites the internal bytearray with zeros.  After this call every
        encrypt/decrypt method raises ``RuntimeError``.
        """
        for i in range(len(self._dek)):
            self._dek[i] = 0
        self._closed = True
