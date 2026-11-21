#!/usr/bin/env python3
"""Check that every first-party Python file carries an SPDX license header."""

from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
_FIRST_PARTY_DIRECTORIES = ("kaine", "scripts", "tests")

_Spdx_RE = re.compile(r"SPDX-License-Identifier")


def _first_party_files() -> list[pathlib.Path]:
    """Return the sorted list of first-party Python files."""
    files: set[pathlib.Path] = set()

    for directory in _FIRST_PARTY_DIRECTORIES:
        base = ROOT / directory
        if base.is_dir():
            for path in base.rglob("*.py"):
                if "__pycache__" not in path.parts:
                    files.add(path)

    for path in ROOT.glob("*.py"):
        files.add(path)

    return sorted(files)


def _file_has_spdx_header(path: pathlib.Path) -> bool:
    """Return ``True`` if *path* contains an SPDX header within the first few lines."""
    try:
        with path.open("r", encoding="utf-8") as fp:
            for i, line in enumerate(fp):
                if i > 30:
                    break
                if _Spdx_RE.search(line):
                    return True
    except (OSError, UnicodeError):
        return False

    return False


def missing_headers() -> list[pathlib.Path]:
    """Return first-party Python files that do not contain an SPDX header."""
    return [path for path in _first_party_files() if not _file_has_spdx_header(path)]


def main() -> int:
    offenders = missing_headers()
    if offenders:
        for path in offenders:
            print(path)
        return 1

    print("All first-party files have SPDX license headers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())