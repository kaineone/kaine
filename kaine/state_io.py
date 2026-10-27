# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boundary-neutral atomic JSON state writer.

A single fail-safe ``write_json_atomic`` shared by every component that
persists small JSON state files (perception/control/escalation state, the
preflight gate, the runtime snapshot, the experiment manifest, organ revision
provenance, ...). Each of these had its own byte-identical ``_atomic_write``
copy; consolidating them keeps the on-disk format identical everywhere and
removes the drift risk.

The write is crash-safe: the payload is serialized to a sibling ``*.tmp`` file
and ``os.replace``d into place, which is atomic on POSIX. Serialization is
``json.dumps(payload, indent=2, sort_keys=True)`` so output bytes are stable
and diff-friendly.

This module is deliberately stdlib-only and imports nothing from the rest of
``kaine``, so it is import-legal from the core runtime, the modules, the
evaluation sidecar, and the boundary-neutral homes alike.

NOTE: The ENCRYPTING state writers (``kaine.lifecycle.snapshot``,
``kaine.lifecycle.decommission``, ``kaine.modules.world_model.checkpoint``,
``kaine.modules.self_model.document``) are a justified specialization — they
encrypt the payload (and chmod 0600) before it touches disk — and stay
SEPARATE from this plaintext helper on purpose.
"""
from __future__ import annotations

import json
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

__all__ = ["write_json_atomic", "update_json_locked", "file_lock"]


def write_json_atomic(path: Path, payload: Any) -> None:
    """Atomically write ``payload`` as pretty, sorted JSON to ``path``.

    Creates the parent directory if needed, writes to a temp file unique to this
    call in the same directory (so concurrent writers never share one), fsyncs
    it, then ``os.replace``s it into place (atomic on POSIX). The temp file is
    removed if anything fails. The serialization is
    ``json.dumps(payload, indent=2, sort_keys=True)`` and the file mode follows
    the process umask, as before.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    data = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
    try:
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fsync(fd)
        finally:
            os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Hold an exclusive advisory ``flock`` on ``<path>.lock`` (no-op without fcntl)."""
    try:
        import fcntl
    except ImportError:  # non-POSIX
        yield
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path.with_name(path.name + ".lock"), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        os.close(fd)  # closing the descriptor releases the flock


def update_json_locked(
    path: Path, fn: Callable[[Any], Any], default: Any = None
) -> Any:
    """Locked read-modify-write of a JSON file shared by several processes.

    Takes an exclusive lock on ``<path>.lock``, reads the current JSON (or
    ``default`` when the file is missing or unreadable), passes it to ``fn``,
    writes the returned value with :func:`write_json_atomic` and releases the
    lock. If ``fn`` raises, nothing is written. Returns the value written.
    """
    path = Path(path)
    with file_lock(path):
        try:
            current = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            current = default
        updated = fn(current)
        write_json_atomic(path, updated)
        return updated
