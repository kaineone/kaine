# SPDX-License-Identifier: LicenseRef-CAL-0.2
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


def cycle_process_running() -> bool:
    """True if another process on this host is running ``kaine.cycle``.

    Scans ``/proc/*/cmdline`` and uses :func:`argv_is_cycle` to recognise a
    cycle by its argv.  This only sees processes on this host (and, from the
    host, in its containers); the bus client check covers other containers.
    All reads are guarded; never raises.
    """
    if not os.path.isdir("/proc"):
        return False
    self_pid = os.getpid()
    try:
        proc_entries = os.listdir("/proc")
    except Exception:
        return False
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
            raw = (Path("/proc") / name / "cmdline").read_bytes()
        except Exception:
            continue
        if not raw:
            continue
        if argv_is_cycle(raw.split(b"\0")):
            return True
    return False
