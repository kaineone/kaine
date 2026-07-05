# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Atomic adapter promotion + retention for voice-alignment training.

Training writes a LoRA adapter to `<adapter_output_dir>/<timestamp>.tmp/`.
Once the capability-loss eval passes, `promote()` atomically renames
the tmp dir to its final `<timestamp>/` and re-points
`<adapter_output_dir>/current` to it. Both operations use
`os.replace` so concurrent readers (Lingua in any future auto-reload
mode) never see a partial state.

`prune()` enforces a retention cap, removing the oldest accepted
adapters but never the one `current` points at.
"""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


CURRENT_LINK = "current"


def tmp_dir_for(adapter_output_dir: Path, timestamp: str) -> Path:
    """Return the staging path for an in-progress adapter."""
    return adapter_output_dir / f"{timestamp}.tmp"


def final_dir_for(adapter_output_dir: Path, timestamp: str) -> Path:
    return adapter_output_dir / timestamp


def promote(tmp_dir: Path, final_dir: Path) -> Path:
    """Move tmp_dir to final_dir atomically and re-point `current`.

    Both `os.replace` calls are atomic on POSIX filesystems. The
    `current` symlink is updated via a temp-symlink + replace
    sequence so readers either see the old target or the new target,
    never a missing symlink.
    """
    final_dir.parent.mkdir(parents=True, exist_ok=True)
    if final_dir.exists():
        raise FileExistsError(
            f"adapter promotion target already exists: {final_dir}"
        )
    os.replace(tmp_dir, final_dir)
    _update_current_symlink(final_dir.parent, final_dir)
    return final_dir


def reject(tmp_dir: Path) -> None:
    """Tear down a tmp adapter that failed the capability-loss check."""
    if tmp_dir.exists():
        shutil.rmtree(tmp_dir, ignore_errors=True)


def current_path(adapter_output_dir: Path) -> Optional[Path]:
    """Resolve the `current` symlink target, or None if absent."""
    link = adapter_output_dir / CURRENT_LINK
    if not link.is_symlink() and not link.exists():
        return None
    try:
        return link.resolve(strict=True)
    except (OSError, RuntimeError):
        return None


def list_accepted(adapter_output_dir: Path) -> list[Path]:
    """Accepted adapter dirs, oldest first by mtime.

    Excludes any `.tmp` staging dirs, the `current` symlink itself,
    and the `PENDING_OPERATOR_RELOAD` marker file.
    """
    if not adapter_output_dir.exists():
        return []
    entries: list[Path] = []
    for p in adapter_output_dir.iterdir():
        if p.name == CURRENT_LINK:
            continue
        if p.name == "PENDING_OPERATOR_RELOAD":
            continue
        if p.name.endswith(".tmp"):
            continue
        if p.is_dir() and not p.is_symlink():
            entries.append(p)
    entries.sort(key=lambda x: x.stat().st_mtime)
    return entries


def prune(adapter_output_dir: Path, *, keep: int) -> list[Path]:
    """Evict accepted adapters beyond the retention cap.

    Returns the list of evicted paths. The `current` symlink target
    is never evicted even if it's the oldest.
    """
    if keep < 1:
        raise ValueError("keep must be >= 1")
    accepted = list_accepted(adapter_output_dir)
    if len(accepted) <= keep:
        return []
    protected = current_path(adapter_output_dir)
    overflow = len(accepted) - keep
    evicted: list[Path] = []
    for candidate in accepted:
        if overflow <= 0:
            break
        if protected is not None and candidate.resolve() == protected:
            continue
        shutil.rmtree(candidate, ignore_errors=True)
        evicted.append(candidate)
        overflow -= 1
    return evicted


def _update_current_symlink(adapter_output_dir: Path, target: Path) -> None:
    link = adapter_output_dir / CURRENT_LINK
    tmp_link = adapter_output_dir / f"{CURRENT_LINK}.swap"
    if tmp_link.exists() or tmp_link.is_symlink():
        tmp_link.unlink()
    # Use a relative target so the symlink keeps working if the
    # adapter directory tree is moved as a unit.
    try:
        rel_target = os.path.relpath(target, adapter_output_dir)
    except ValueError:
        rel_target = str(target)
    os.symlink(rel_target, tmp_link)
    os.replace(tmp_link, link)
