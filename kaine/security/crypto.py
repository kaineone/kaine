# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Application-layer encryption-at-rest for KAINE's persisted cognitive state.

`StateEncryptor` is an AES-256-GCM envelope around the bytes a module would
otherwise write to disk in the clear (the Eidolon self-model, fork/merge
snapshot bundles, sidecar observer JSONL, Phantasia checkpoints). It is
deliberately small and dependency-light: the only third-party import is
:mod:`cryptography` (``AESGCM``), and that import is lazy so a disabled
deployment never touches it.

Design
------
* **Algorithm.** AES-256-GCM (a 256-bit key, a 96-bit nonce, a 128-bit
  authentication tag). GCM is authenticated: any tampering with the
  ciphertext, nonce, or tag fails ``decrypt`` rather than returning garbage
  plaintext.
* **Nonce.** A fresh 96-bit nonce is drawn from ``os.urandom`` for **every**
  encryption and stored alongside the ciphertext. Nonces are never reused for
  a given key — reuse would break GCM's confidentiality and authenticity
  guarantees.
* **On-disk framing.** ``MAGIC || nonce(12) || ciphertext+tag``, base64-encoded
  so the result is safe to drop into UTF-8 JSON/JSONL files. The magic prefix
  lets ``maybe_decrypt`` tell encrypted blobs from legacy plaintext, so a
  disabled reader transparently passes plaintext through and an enabled reader
  can still ingest pre-encryption files.
* **Key source.** The key is loaded from the environment variable named by
  :attr:`CryptoConfig.key_env_var` (default ``KAINE_STATE_KEY``); failing that,
  from the Linux kernel keyring (``user`` keyring, description
  ``kaine:state_key``). It is NEVER hardcoded, logged, or persisted. The raw
  value may be 32 raw bytes, or base64/hex of 32 bytes.
* **Disabled = no-op.** When ``enabled`` is false (the shipped default), the
  encryptor is a transparent pass-through: ``encrypt`` returns its input and
  the :mod:`cryptography` library is never invoked. Every existing plaintext
  code path keeps working byte-for-byte.

Key management beyond loading (rotation, backup, out-of-band transfer for
cross-host fork/merge) is the operator's responsibility and is documented in
``SECURITY.md``.
"""
from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger(__name__)

# Framing magic. Bumping the trailing version invalidates older blobs on read.
_MAGIC = b"KAINEgcm1:"
_NONCE_BYTES = 12  # 96-bit nonce — the GCM standard / recommended size.
_KEY_BYTES = 32  # AES-256.

_DEFAULT_KEY_ENV_VAR = "KAINE_STATE_KEY"
_DEFAULT_ALGORITHM = "aes-256-gcm"
# Keyring description used when falling back to the Linux kernel keyring.
_KEYRING_DESC = "kaine:state_key"


class CryptoConfigError(RuntimeError):
    """Raised at startup when encryption is enabled but cannot be configured
    (e.g. no key available, or an unsupported algorithm)."""


@dataclass(frozen=True)
class CryptoConfig:
    """Configuration for state-at-rest encryption.

    Built from the ``[security.state_encryption]`` TOML table. Ships disabled.
    """

    enabled: bool = False
    key_env_var: str = _DEFAULT_KEY_ENV_VAR
    algorithm: str = _DEFAULT_ALGORITHM

    @classmethod
    def from_section(cls, section: Optional[dict]) -> "CryptoConfig":
        section = section or {}
        return cls(
            enabled=bool(section.get("enabled", False)),
            key_env_var=str(section.get("key_env_var", _DEFAULT_KEY_ENV_VAR)),
            algorithm=str(section.get("algorithm", _DEFAULT_ALGORITHM)),
        )


def _decode_key(raw: str | bytes) -> bytes:
    """Coerce an operator-provided key into 32 raw bytes.

    Accepts (in order): exactly-32 raw bytes/utf-8, base64 of 32 bytes, or
    hex of 32 bytes. Anything else is a configuration error.
    """
    if isinstance(raw, str):
        candidate = raw.strip()
        raw_bytes = candidate.encode("utf-8")
    else:
        candidate = ""
        raw_bytes = raw

    if len(raw_bytes) == _KEY_BYTES:
        return raw_bytes

    if candidate:
        # Try base64 (urlsafe + standard) then hex.
        for decoder in (base64.urlsafe_b64decode, base64.b64decode):
            try:
                decoded = decoder(candidate + "=" * (-len(candidate) % 4))
                if len(decoded) == _KEY_BYTES:
                    return decoded
            except (ValueError, TypeError):
                # Not valid base64 (binascii.Error is a ValueError subclass)
                # under this variant — fall through and try the next decoder,
                # then hex. `_resolve_key` raises CryptoConfigError below if
                # every format fails, so a bad key never falls through as an
                # accepted key.
                pass
        try:
            decoded = bytes.fromhex(candidate)
            if len(decoded) == _KEY_BYTES:
                return decoded
        except ValueError:
            # Not valid hex either; fall through to the error below.
            pass

    raise CryptoConfigError(
        "KAINE_STATE_KEY must decode to exactly 32 bytes (AES-256): supply 32 "
        "raw bytes, or base64/hex of 32 bytes. Never commit this value."
    )


def _load_key_from_keyring() -> Optional[bytes]:
    """Best-effort read of the key from the Linux kernel keyring.

    Returns None if the platform lacks the keyring (e.g. non-Linux, or the
    `keyutils` bindings are absent) or the key is not present. Never raises.
    """
    try:
        import keyutils  # type: ignore
    except Exception:
        return None
    try:
        key_id = keyutils.request_key(_KEYRING_DESC, keyutils.KEY_SPEC_USER_KEYRING)
        if key_id is None:
            return None
        return bytes(keyutils.read_key(key_id))
    except Exception:
        return None


def _resolve_key(config: CryptoConfig) -> bytes:
    """Resolve the AES-256 key from env var, else the kernel keyring.

    Raises CryptoConfigError if neither source yields a usable key.
    """
    env_val = os.environ.get(config.key_env_var)
    if env_val:
        return _decode_key(env_val)
    keyring_val = _load_key_from_keyring()
    if keyring_val:
        return _decode_key(keyring_val)
    raise CryptoConfigError(
        f"state encryption is enabled but no key was found: set ${config.key_env_var} "
        f"or add a '{_KEYRING_DESC}' key to the Linux kernel keyring. The entity "
        "will not boot without a key."
    )


def is_encrypted(blob: bytes) -> bool:
    """True if `blob` carries the KAINE encryption magic prefix."""
    return blob[: len(_MAGIC)] == _MAGIC


class StateEncryptor:
    """AES-256-GCM envelope for at-rest state bytes.

    When ``config.enabled`` is false this is a transparent pass-through and the
    :mod:`cryptography` library is never imported.
    """

    def __init__(self, config: Optional[CryptoConfig] = None) -> None:
        self._config = config or CryptoConfig()
        self._key: Optional[bytes] = None
        self._aead = None  # lazily-built AESGCM instance
        if self._config.enabled:
            algo = self._config.algorithm.lower()
            if algo != _DEFAULT_ALGORITHM:
                raise CryptoConfigError(
                    f"unsupported state-encryption algorithm {self._config.algorithm!r}: "
                    f"only {_DEFAULT_ALGORITHM!r} is supported"
                )
            # Resolve + validate the key NOW so a missing key fails at startup,
            # not on the first write hours into a run.
            self._key = _resolve_key(self._config)
            self._build_aead()

    @property
    def enabled(self) -> bool:
        return self._config.enabled

    @property
    def config(self) -> CryptoConfig:
        return self._config

    def _build_aead(self) -> None:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM

        assert self._key is not None
        self._aead = AESGCM(self._key)

    # -- bytes API ------------------------------------------------------

    def encrypt(self, plaintext: bytes) -> bytes:
        """Encrypt `plaintext`, returning a base64 framed blob.

        No-op pass-through when disabled. A fresh random 96-bit nonce is used
        per call (never reused for a key).
        """
        if not self._config.enabled:
            return plaintext
        if self._aead is None:  # pragma: no cover - constructor guarantees this
            self._build_aead()
        nonce = os.urandom(_NONCE_BYTES)
        ciphertext = self._aead.encrypt(nonce, plaintext, None)  # type: ignore[union-attr]
        framed = _MAGIC + nonce + ciphertext
        return base64.b64encode(framed)

    def decrypt(self, blob: bytes) -> bytes:
        """Decrypt a framed blob produced by :meth:`encrypt`.

        Raises if authentication fails (tampering) or if `blob` is not a valid
        KAINE encryption envelope. Use :meth:`maybe_decrypt` for inputs that
        may be legacy plaintext.
        """
        try:
            framed = base64.b64decode(blob, validate=True)
        except Exception as exc:
            raise CryptoConfigError("ciphertext is not valid base64") from exc
        if not is_encrypted(framed):
            raise CryptoConfigError("blob is missing the KAINE encryption header")
        nonce = framed[len(_MAGIC) : len(_MAGIC) + _NONCE_BYTES]
        ciphertext = framed[len(_MAGIC) + _NONCE_BYTES :]
        if self._aead is None:
            if not self._config.enabled or self._key is None:
                raise CryptoConfigError(
                    "cannot decrypt: state encryption is not configured with a key"
                )
            self._build_aead()
        # AESGCM.decrypt raises cryptography.exceptions.InvalidTag on tamper.
        return self._aead.decrypt(nonce, ciphertext, None)  # type: ignore[union-attr]

    def maybe_decrypt(self, blob: bytes) -> bytes:
        """Decrypt `blob` if it is an encryption envelope, else return it as-is.

        This is the read-side counterpart that keeps disabled deployments and
        pre-encryption files working: plaintext flows straight through, and an
        enabled reader can still ingest legacy plaintext written before the key
        existed.
        """
        try:
            framed = base64.b64decode(blob, validate=True)
        except Exception:
            return blob
        if not is_encrypted(framed):
            return blob
        return self.decrypt(blob)

    # -- text convenience ----------------------------------------------

    def encrypt_text(self, text: str) -> str:
        """Encrypt a string; returns base64 ascii (or the original when off)."""
        if not self._config.enabled:
            return text
        return self.encrypt(text.encode("utf-8")).decode("ascii")

    def decrypt_text(self, text: str) -> str:
        """Decrypt text written by :meth:`encrypt_text`, tolerating plaintext."""
        # Fast path: a disabled encryptor never wrote an envelope, so skip the
        # base64 round-trip in maybe_decrypt entirely (this runs per-line over
        # potentially large sink files during admissibility scans).
        if not self._config.enabled:
            return text
        return self.maybe_decrypt(text.encode("utf-8")).decode("utf-8")


# ---------------------------------------------------------------------------
# Process-global active encryptor.
#
# Modules persist through `get_state_encryptor()` rather than threading a
# CryptoConfig through every call site. Boot installs the configured encryptor
# via `set_state_encryptor`; the default is a disabled no-op so imports and
# tests work without any setup.
# ---------------------------------------------------------------------------

_active: Optional[StateEncryptor] = None


def get_state_encryptor() -> StateEncryptor:
    """Return the process-global StateEncryptor (a disabled no-op by default)."""
    global _active
    if _active is None:
        _active = StateEncryptor(CryptoConfig())
    return _active


def set_state_encryptor(encryptor: StateEncryptor) -> None:
    """Install the process-global StateEncryptor (called once at boot)."""
    global _active
    _active = encryptor


def install_from_section(section: Optional[dict]) -> StateEncryptor:
    """Build a StateEncryptor from a `[security.state_encryption]` table and
    install it as the process-global. Returns the installed encryptor.

    Raises CryptoConfigError at startup if enabled and no key is available.
    """
    encryptor = StateEncryptor(CryptoConfig.from_section(section))
    set_state_encryptor(encryptor)
    return encryptor
