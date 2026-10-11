# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Versioned, encrypted system-prompt storage for voice alignment.

Each distinct system prompt is written once under
``<intent_log_dir>/system_prompts/<sha256>.txt``.  The digest is computed over
the decrypted text; writes and reads verify it, so a corrupt or tampered file
is treated as missing.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import tempfile
from pathlib import Path

log = logging.getLogger(__name__)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def store_dir_for(intent_log_path: Path) -> Path:
    """Return the directory that holds system prompts for an intent log."""
    return intent_log_path.parent / "system_prompts"


def digest_of(text: str) -> str:
    """Return the sha256 hex digest of ``text`` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_system_prompt(store_dir: Path, text: str) -> str:
    """Write ``text`` to ``<store_dir>/<digest>.txt`` atomically and once.

    The file is created with mode 0o600, written through a temp file in the
    same directory, fsynced, and moved with ``os.replace``.  The directory is
    created with mode 0o700.  If the digest file already exists the write is
    skipped.
    """
    from kaine.security.crypto import get_state_encryptor

    digest = digest_of(text)
    store_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    dest = store_dir / f"{digest}.txt"
    if dest.exists():
        return digest

    ciphertext = get_state_encryptor().encrypt(text.encode("utf-8"))
    fd, tmp_path = tempfile.mkstemp(dir=store_dir, prefix=f".{digest}-", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(ciphertext)
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:
        try:
            os.close(fd)
        except OSError:
            # Already closed by the file object; the original error is re-raised.
            pass
        Path(tmp_path).unlink(missing_ok=True)
        raise

    os.replace(tmp_path, dest)
    return digest


def read_system_prompt(store_dir: Path, digest: str) -> str | None:
    """Read and verify the system prompt for ``digest``.

    Returns ``None`` when the digest is malformed, the file is missing,
    decryption fails, the bytes are not UTF-8, or the digest does not match
    the decrypted text.  Logs a warning for digest mismatch or decryption
    failure.
    """
    from kaine.security.crypto import get_state_encryptor

    if not isinstance(digest, str) or not _DIGEST_RE.fullmatch(digest):
        return None

    path = store_dir / f"{digest}.txt"
    if not path.is_file():
        return None

    raw = path.read_bytes()
    try:
        plaintext = get_state_encryptor().maybe_decrypt(raw)
    except Exception as exc:
        log.warning("system prompt %s could not be decrypted: %s", digest, exc)
        return None

    try:
        text = plaintext.decode("utf-8")
    except UnicodeDecodeError:
        return None

    if digest_of(text) != digest:
        log.warning("system prompt %s digest mismatch", digest)
        return None

    return text


def store_bytes(store_dir: Path) -> int:
    """Return the sum of file sizes in ``store_dir``."""
    if not store_dir.exists():
        return 0
    total = 0
    for entry in store_dir.iterdir():
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total
