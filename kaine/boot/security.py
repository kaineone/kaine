# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""State-encryption install for the cycle."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


def install_state_encryption(kaine_config: dict[str, Any]) -> None:
    """Install the process-global StateEncryptor from `[security.state_encryption]`.

    Runs before any module persists state. When encryption is enabled but no
    key is available this raises `CryptoConfigError` so the entity does not
    boot without its key (fail-closed). When disabled (the shipped default)
    the installed encryptor is a transparent no-op.
    """
    from kaine.security.crypto import install_from_section

    section = (kaine_config.get("security") or {}).get("state_encryption") or {}
    install_from_section(section)
