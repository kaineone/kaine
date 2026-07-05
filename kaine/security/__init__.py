# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Security primitives for KAINE.

Currently this package provides application-layer encryption-at-rest for
persisted cognitive state (`crypto`). The active :class:`StateEncryptor` is a
process-global installed at boot; modules call :func:`get_state_encryptor`
rather than threading config through every persistence call site.
"""
from kaine.security.crypto import (
    CryptoConfig,
    CryptoConfigError,
    StateEncryptor,
    get_state_encryptor,
    set_state_encryptor,
)

__all__ = [
    "CryptoConfig",
    "CryptoConfigError",
    "StateEncryptor",
    "get_state_encryptor",
    "set_state_encryptor",
]
