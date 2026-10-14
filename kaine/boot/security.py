# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""State-encryption install for the cycle."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


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
    from kaine.security.crypto import CryptoConfig, install_from_section

    section = (kaine_config.get("security") or {}).get("state_encryption") or {}
    desired = CryptoConfig.from_section(section)

    active = getattr(_crypto, "_active", None)
    if (
        active is not None
        and active.config == desired
        and (not desired.enabled or active._key == _crypto._resolve_key(desired))
    ):
        return

    install_from_section(section)
