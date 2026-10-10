# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Helpers for detecting whether a KAINE cognitive cycle is alive on this host."""

from __future__ import annotations

import os
from pathlib import Path


def argv_is_cycle(args: list[bytes]) -> bool:
    """Return True if any argv element identifies a KAINE cognitive cycle."""
    for arg in args:
        if arg == b"kaine.cycle" or arg.startswith(b"kaine.cycle."):
            return True
        if arg == b"-mkaine.cycle" or arg.startswith(b"-mkaine.cycle."):
            return True
        if arg.endswith(b"kaine/cycle/__main__.py"):
            return True
    return False


def cycle_process_details(
    proc_root: str = "/proc",
) -> tuple[bool | None, int | None, list[str] | None]:
    """Return details about a visible ``kaine.cycle`` process.

    Returns ``(state, pid, argv)`` where ``state`` has the same meaning as
    :func:`cycle_process_state`, ``pid`` is the pid of the first matching
    process, and ``argv`` is its decoded command line.  When no cycle is
    found, ``pid`` and ``argv`` are ``None``.
    """
    root = Path(proc_root)
    if not root.is_dir():
        return (False, None, None)
    self_pid = os.getpid()
    unknown = False
    try:
        proc_entries = os.listdir(root)
    except OSError:
        return (None, None, None)
    for name in proc_entries:
        if not name.isdigit():
            continue
        try:
            pid = int(name)
            if pid == self_pid:
                continue
        except ValueError:
            continue
        try:
            raw = (root / name / "cmdline").read_bytes()
        except (FileNotFoundError, ProcessLookupError):
            continue
        except OSError:
            unknown = True
            continue
        except Exception:
            unknown = True
            continue
        if not raw:
            continue
        if argv_is_cycle(raw.split(b"\0")):
            argv = [
                a.decode("utf-8", "replace")
                for a in raw.split(b"\0")
                if a
            ]
            return (True, pid, argv)
    return (None, None, None) if unknown else (False, None, None)


def cycle_process_state(proc_root: str = "/proc") -> bool | None:
    """Return whether a ``kaine.cycle`` process is visible under ``proc_root``.

    * ``True`` if any scanned ``cmdline`` matches :func:`argv_is_cycle`.
    * ``None`` if the process list cannot be read completely (including any
      ``cmdline`` read that raises an ``OSError`` other than the process
      having just exited).  ``None`` means "unknown; fail closed".
    * ``False`` if the directory was readable and no cycle was found.

    ``FileNotFoundError`` and ``ProcessLookupError`` are treated as a process
    that exited during the scan and are skipped.
    """
    return cycle_process_details(proc_root)[0]


def cycle_process_running() -> bool:
    """True if another process on this host is running ``kaine.cycle``.

    Scans ``/proc/*/cmdline`` and uses :func:`argv_is_cycle` to recognise a
    cycle by its argv.  This only sees processes on this host (and, from the
    host, in its containers); the bus client check covers other containers.
    All reads are guarded; never raises.
    """
    return cycle_process_state() is True
