# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared line reader/writer for AES-256-GCM-encrypted JSONL files.

Each non-blank line is either a plaintext JSON object or a KAINE encryption
envelope.  The module depends only on the standard library and lazily imports
``kaine.security.crypto`` inside functions, so it can be used from any
boundary layer.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import stat
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Line:
    record: dict | None
    unreadable: bool


def encode_record(record: dict) -> str:
    from kaine.security.crypto import get_state_encryptor

    return get_state_encryptor().encrypt_text(json.dumps(record, sort_keys=True))


def _is_envelope(line: str) -> bool:
    from kaine.security.crypto import is_encrypted

    try:
        decoded = base64.b64decode(line, validate=True)
        return is_encrypted(decoded)
    except Exception:
        return False


def iter_records(path: Path | str) -> Iterator[Line]:
    """Yield one ``Line`` per non-blank line of ``path``.

    Envelope lines are decrypted with the active encryptor, whether or not
    state encryption is currently enabled.  Plaintext lines are parsed as JSON.
    A missing file yields nothing; other ``OSError``s propagate.
    """
    p = Path(path)
    try:
        fh = p.open("r", encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return
    with fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if _is_envelope(line):
                try:
                    from kaine.security.crypto import get_state_encryptor

                    plaintext = (
                        get_state_encryptor().decrypt(line.encode("ascii"))
                        .decode("utf-8")
                    )
                except Exception:
                    yield Line(None, True)
                    continue
            else:
                plaintext = line
            try:
                rec = json.loads(plaintext)
            except Exception:
                yield Line(None, True)
                continue
            if isinstance(rec, dict):
                yield Line(rec, False)
            else:
                yield Line(None, True)


def has_plaintext_line(path: Path | str) -> bool:
    """Return True if ``path`` contains any non-blank, non-envelope line.

    A missing file returns False.
    """
    p = Path(path)
    if not p.is_file():
        return False
    try:
        fh = p.open("r", encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return False
    with fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if not _is_envelope(line):
                return True
    return False


def has_envelope_line(path: Path | str) -> bool:
    """Return True if ``path`` contains at least one non-blank envelope line.

    A missing file returns False.
    """
    p = Path(path)
    if not p.is_file():
        return False
    try:
        fh = p.open("r", encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return False
    with fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if _is_envelope(line):
                return True
    return False


def rewrite_encrypted(path: Path | str) -> bool:
    """Rewrite every plaintext line of ``path`` as an encryption envelope.

    Envelope lines are kept byte for byte, including ones this key cannot
    decrypt, so nothing is ever dropped; blank lines are removed. The new
    content is written to a temp file in the same directory, fsynced and
    swapped in with ``os.replace``. Returns True only when the file changed,
    and False when encryption is disabled or the file is missing. The caller
    must be the file's only writer.
    """
    from kaine.security.crypto import get_state_encryptor

    p = Path(path)
    encryptor = get_state_encryptor()
    if not encryptor.enabled or not p.is_file():
        return False

    # Sweep temp files left behind by an interrupted rewrite.
    now_ns = time.time_ns()
    for leftover in p.parent.glob(p.name + ".*.tmp"):
        try:
            if now_ns - leftover.stat().st_mtime_ns > 60 * 10**9:
                leftover.unlink()
        except FileNotFoundError:
            pass

    st = os.stat(p)

    new_lines: list[str] = []
    changed = False
    try:
        fh = p.open("r", encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return False
    with fh:
        for raw in fh:
            line = raw.rstrip("\n").rstrip("\r")
            if not line.strip():
                changed = True
                continue
            if _is_envelope(line):
                new_lines.append(line)
            else:
                new_lines.append(encryptor.encrypt_text(line))
                changed = True

    if not changed:
        return False

    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=p.parent,
            delete=False,
            prefix=p.name + ".",
            suffix=".tmp",
        ) as tmp:
            tmp_path = Path(tmp.name)
            for nl in new_lines:
                tmp.write(nl + "\n")
            tmp.flush()
            os.fsync(tmp.fileno())

        os.chmod(tmp_path, stat.S_IMODE(st.st_mode))
        os.utime(tmp_path, ns=(st.st_atime_ns, st.st_mtime_ns))
        os.replace(tmp_path, p)
        dir_fd = os.open(p.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
        return True
    except Exception:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        raise
