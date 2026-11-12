# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Per-entity DEK management with wrapped-key storage and caching.

``KeyRing`` loads wrapped DEKs from ``state/identity/keys/<entity_id>.dek.json``,
unwraps them via a pluggable ``KekProvider``, and hands back cached
``EntityEncryptor`` instances for the process lifetime.

``SoftwareKek`` is the development/testing KEK: AES-256-GCM with AAD binding
to the entity_id.  A TPM-sealed KEK replaces it in task 1.2.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

from kaine.security.custody.encryptor import EntityEncryptor


@runtime_checkable
class KekProvider(Protocol):
    """Pluggable key-encryption-key provider."""

    @property
    def kek_id(self) -> str: ...

    def wrap(self, dek: bytes, entity_id: str) -> bytes:
        """Wrap (encrypt) a DEK under the KEK, bound to entity_id."""
        ...

    def unwrap(self, wrapped: bytes, entity_id: str) -> bytes:
        """Unwrap (decrypt) a DEK, verifying the entity_id binding."""
        ...


class SoftwareKek:
    """Software KEK for development and testing (no TPM required)."""

    def __init__(self, kek_bytes: bytes) -> None:
        if len(kek_bytes) != 32:
            raise ValueError(
                f"KEK must be exactly 32 bytes, got {len(kek_bytes)}"
            )
        self._kek = bytearray(kek_bytes)
        self._kek_id = "software:" + hashlib.sha256(kek_bytes).hexdigest()[:16]

    @property
    def kek_id(self) -> str:
        return self._kek_id

    def wrap(self, dek: bytes, entity_id: str) -> bytes:
        """AES-256-GCM wrap with AAD binding to entity_id."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        if not entity_id:
            raise ValueError("entity_id must not be empty")
        aad = b"kaine/dek|" + entity_id.encode("utf-8")
        nonce = os.urandom(12)
        ciphertext = AESGCM(bytes(self._kek)).encrypt(nonce, dek, aad)
        return nonce + ciphertext

    def unwrap(self, wrapped: bytes, entity_id: str) -> bytes:
        """Unwrap; raises InvalidTag on wrong entity or wrong KEK."""
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        if not entity_id:
            raise ValueError("entity_id must not be empty")
        aad = b"kaine/dek|" + entity_id.encode("utf-8")
        nonce = wrapped[:12]
        ciphertext = wrapped[12:]
        return AESGCM(bytes(self._kek)).decrypt(nonce, ciphertext, aad)

    def close(self) -> None:
        """Best-effort KEK erasure."""
        for i in range(len(self._kek)):
            self._kek[i] = 0


@dataclass(frozen=True)
class WrappedDek:
    """On-disk record of a DEK wrapped under a KEK."""

    entity_id: str
    wrap: bytes
    kek_id: str
    policy: str
    created_at: float
    escrow: list

    def to_dict(self) -> dict:
        """Serialize to a JSON-safe dict."""
        import base64

        return {
            "entity_id": self.entity_id,
            "wrap": base64.b64encode(self.wrap).decode("ascii"),
            "kek_id": self.kek_id,
            "policy": self.policy,
            "created_at": self.created_at,
            "escrow": self.escrow,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> WrappedDek:
        """Deserialize from a JSON-loaded dict."""
        import base64

        return cls(
            entity_id=raw["entity_id"],
            wrap=base64.b64decode(raw["wrap"]),
            kek_id=raw["kek_id"],
            policy=raw["policy"],
            created_at=float(raw["created_at"]),
            escrow=list(raw.get("escrow", [])),
        )


class KeyRing:
    """Per-entity DEK management with caching."""

    def __init__(
        self, kek: KekProvider, *, state_root: Path | str = "state"
    ) -> None:
        self._kek = kek
        self._state_root = Path(state_root)
        self._cache: dict[str, EntityEncryptor] = {}

    def _keys_dir(self) -> Path:
        from kaine.storage import resolve

        return resolve(self._state_root / "identity" / "keys")

    def _dek_path(self, entity_id: str) -> Path:
        return self._keys_dir() / f"{entity_id}.dek.json"

    def generate_dek(self, entity_id: str) -> WrappedDek:
        """Generate a fresh DEK, wrap it, write the file, return the record."""
        if not entity_id:
            raise ValueError("entity_id must not be empty")

        path = self._dek_path(entity_id)
        if path.exists():
            raise FileExistsError(f"DEK file already exists: {path}")

        dek = secrets.token_bytes(32)
        wrapped_bytes = self._kek.wrap(dek, entity_id)
        record = WrappedDek(
            entity_id=entity_id,
            wrap=wrapped_bytes,
            kek_id=self._kek.kek_id,
            policy="software" if isinstance(self._kek, SoftwareKek) else "tpm",
            created_at=time.time(),
            escrow=[],
        )
        self._write_dek_file(path, record)

        enc = EntityEncryptor(entity_id, dek)
        self._cache[entity_id] = enc
        return record

    def encryptor_for(self, entity_id: str) -> EntityEncryptor:
        """Return a cached EntityEncryptor, loading the DEK if needed."""
        if entity_id in self._cache:
            return self._cache[entity_id]

        record = self._load_dek_file(entity_id)
        dek = self._kek.unwrap(record.wrap, entity_id)
        enc = EntityEncryptor(entity_id, dek)
        self._cache[entity_id] = enc
        return enc

    def has_dek(self, entity_id: str) -> bool:
        """True if a wrapped DEK file exists for entity_id."""
        return self._dek_path(entity_id).exists()

    def _write_dek_file(self, path: Path, record: WrappedDek) -> None:
        """Atomically write a wrapped DEK file, owner-only permissions."""
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        payload = json.dumps(record.to_dict(), indent=2, sort_keys=True)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(payload)
        try:
            os.chmod(tmp, 0o600)
        except (OSError, NotImplementedError):
            pass
        os.replace(tmp, path)

    def _load_dek_file(self, entity_id: str) -> WrappedDek:
        """Load and validate a wrapped DEK file."""
        path = self._dek_path(entity_id)
        if not path.exists():
            raise FileNotFoundError(
                f"no DEK file for entity {entity_id}: {path}"
            )
        raw = json.loads(path.read_text())
        record = WrappedDek.from_dict(raw)
        if record.entity_id != entity_id:
            raise ValueError(
                f"DEK file entity_id mismatch: file says {record.entity_id!r}, "
                f"expected {entity_id!r}"
            )
        return record

    def close(self) -> None:
        """Close all cached encryptors (best-effort DEK zeroing)."""
        for enc in self._cache.values():
            enc.close()
        self._cache.clear()
