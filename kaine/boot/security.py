# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""State-encryption install for the cycle."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from kaine.security.custody.keyring import KeyRing


def install_state_encryption(kaine_config: dict[str, Any]) -> None:
    """Install the process-global StateEncryptor from `[security.state_encryption]`.

    Idempotent: if a compatible encryptor is already active it is kept in place.
    The cycle's entrypoint installs the encryptor early so that revive plans
    and the research preflight round-trip use the configured key; the boot
    registry's later call keeps working for the other entrypoints without
    replacing it.

    When encryption is enabled but no key is available this raises
    `CryptoConfigError` so the entity does not boot without its key
    (fail-closed). When disabled (the shipped default) the installed encryptor
    is a transparent no-op.
    """
    import kaine.security.crypto as _crypto

    section = (kaine_config.get("security") or {}).get("state_encryption") or {}
    desired = _crypto.CryptoConfig.from_section(section)

    active = getattr(_crypto, "_active", None)
    if (
        active is not None
        and active.config == desired
        and (not desired.enabled or active._key == _crypto._resolve_key(desired))
    ):
        return

    _crypto.install_from_section(section)


def build_keyring(kaine_config: dict[str, Any]) -> KeyRing | None:
    """Build a KeyRing from ``[security.custody]``, or None when disabled.

    Reads ``enabled`` (bool, default False), ``kek_source`` ("env" or "tpm",
    default "env"), ``kek_env_var`` (default "KAINE_CUSTODY_KEK") and
    ``state_root`` (default "state"). TPM is not yet implemented (task 1.2).
    """
    import kaine.security.crypto as _crypto

    section = (kaine_config.get("security") or {}).get("custody") or {}
    if not section.get("enabled", False):
        return None

    kek_source = section.get("kek_source", "env")
    state_root = section.get("state_root", "state")

    if kek_source == "tpm":
        raise _crypto.CryptoConfigError(
            "custody kek_source='tpm' is not yet implemented (task 1.2); "
            "use kek_source='env' with KAINE_CUSTODY_KEK"
        )

    if kek_source != "env":
        raise _crypto.CryptoConfigError(
            f"custody kek_source={kek_source!r} is not recognized; "
            f"use 'env' or (when implemented) 'tpm'"
        )

    import os

    env_var = section.get("kek_env_var", "KAINE_CUSTODY_KEK")
    raw = os.environ.get(env_var)
    if not raw:
        raise _crypto.CryptoConfigError(
            f"custody is enabled but {env_var} is not set or empty"
        )
    try:
        kek_bytes = bytes.fromhex(raw)
    except ValueError as exc:
        raise _crypto.CryptoConfigError(
            f"custody {env_var} is not valid hex: {exc}"
        ) from exc

    from kaine.security.custody.keyring import KeyRing as _KeyRing
    from kaine.security.custody.keyring import SoftwareKek

    try:
        kek = SoftwareKek(kek_bytes)
    except (ValueError, TypeError) as exc:
        raise _crypto.CryptoConfigError(
            f"custody KEK is invalid (expected 32 bytes, got {len(kek_bytes)}): {exc}"
        ) from exc
    return _KeyRing(kek, state_root=state_root)
