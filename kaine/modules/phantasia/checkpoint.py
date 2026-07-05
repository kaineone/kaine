# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Encryption-aware read/write for Phantasia world-model checkpoints.

Used by the opt-in weight-persistence path (``[phantasia].persist_weights``;
see ``module.py``): the shipped (``fake``) world model never checkpoints —
only the real DreamerV3 backend's exported param tree lands under
``state/phantasia/``, routed through the same
:class:`~kaine.security.crypto.StateEncryptor` as every other at-rest state
file: AES-256-GCM when ``[security.state_encryption].enabled`` is true, plain
bytes otherwise. Phantasia's zero-persistence guarantee for *experience data*
(the trajectory buffer, anything raw-sense-derived) is unaffected — a
checkpoint holds learned weights only.

A checkpoint is opaque bytes (a serialized RSSM param tree). These helpers
do not interpret it; they only frame/encrypt it on write and decrypt it on
read.
"""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_CHECKPOINT_DIR = Path("state/phantasia")


def save_checkpoint(path: Path | str, blob: bytes) -> Path:
    """Atomically write a world-model checkpoint, encrypting it at rest when
    state encryption is enabled.

    Writes to a sibling ``*.tmp`` and ``os.replace``s into place so a crash
    mid-save cannot corrupt the destination.
    """
    from kaine.security.crypto import get_state_encryptor

    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = get_state_encryptor().encrypt(blob)
    tmp = target.with_suffix(target.suffix + ".tmp")
    tmp.write_bytes(payload)
    os.replace(tmp, target)
    return target


def load_checkpoint(path: Path | str) -> bytes:
    """Read a world-model checkpoint, decrypting it when it is an encryption
    envelope (plaintext / pre-encryption files pass through unchanged)."""
    from kaine.security.crypto import get_state_encryptor

    target = Path(path)
    return get_state_encryptor().maybe_decrypt(target.read_bytes())
