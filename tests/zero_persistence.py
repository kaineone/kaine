# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Hermetic helpers for the zero-persistence test suite."""
from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Iterable
from pathlib import Path
from types import TracebackType


class WriteRecorder:
    """Install a process-wide audit hook once and record ``open`` write events
    only while an instance is active. Exception-safe and re-entrant for nested
    use in the same process."""
    _hook_installed: bool = False
    _depth: int = 0
    _writes: list[str] = []

    def __enter__(self) -> WriteRecorder:
        if not WriteRecorder._hook_installed:
            WriteRecorder._hook_installed = True

            def _audit_hook(event: str, args: tuple) -> None:
                # An exception raised in an audit hook propagates to the audited
                # operation, so the hook must never raise: any surprise in the
                # event arguments is ignored rather than breaking an unrelated open.
                try:
                    _record(event, args)
                except Exception:
                    return

            def _record(event: str, args: tuple) -> None:
                if event != "open" or WriteRecorder._depth == 0:
                    return
                try:
                    if len(args) < 3:
                        return
                    path, mode, flags = args
                except Exception:
                    return
                if isinstance(path, int):
                    return
                is_write = False
                if isinstance(mode, str):
                    if any(ch in mode for ch in "wax+"):
                        is_write = True
                elif mode is None:
                    if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
                        is_write = True
                if not is_write:
                    return
                try:
                    p = os.fspath(path)
                except Exception:
                    return
                if isinstance(p, bytes):
                    try:
                        p = os.fsdecode(p)
                    except Exception:
                        return
                WriteRecorder._writes.append(p)

            sys.addaudithook(_audit_hook)

        if WriteRecorder._depth == 0:
            WriteRecorder._writes.clear()
        WriteRecorder._depth += 1
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool | None:
        WriteRecorder._depth = max(0, WriteRecorder._depth - 1)
        return False

    @property
    def writes(self) -> list[str]:
        return list(WriteRecorder._writes)


def redirect_temp(tmp_path: Path, monkeypatch) -> Path:
    """Create a private temp directory under ``tmp_path`` and redirect
    ``TMPDIR`` / ``tempfile.tempdir`` to it."""
    private = tmp_path / "tmp"
    private.mkdir()
    monkeypatch.setenv("TMPDIR", str(private))
    monkeypatch.setattr(tempfile, "tempdir", str(private))
    return private


def leaked_writes(writes: list[str], extensions: Iterable[str]) -> list[str]:
    """Return recorded write paths whose lower-cased suffix is banned."""
    ext_set = {ext.lower() for ext in extensions}
    return [p for p in writes if Path(p).suffix.lower() in ext_set]


def scan(root: Path, extensions: Iterable[str]) -> set[Path]:
    """Return all files under ``root`` whose suffix is in ``extensions``."""
    found: set[Path] = set()
    if not root.exists():
        return found
    ext_set = {ext.lower() for ext in extensions}
    for path in root.rglob("*"):
        try:
            if path.is_file() and path.suffix.lower() in ext_set:
                found.add(path)
        except OSError:
            continue
    return found


def format_zero_persistence_failure(by_path: dict[str, set[str]]) -> str:
    lines = "\n".join(
        f"  {path}  [{', '.join(sorted(detectors))}]"
        for path, detectors in sorted(by_path.items())
    )
    return "ZERO-PERSISTENCE VIOLATED: wrote disk artifacts:\n" + lines
