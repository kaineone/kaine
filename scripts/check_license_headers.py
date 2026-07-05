# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Check that every first-party Python source file carries the SPDX header.

Exits 0 if all files are compliant; exits 1 (printing offenders) if any are
missing the header.

Reusable helper::

    from scripts.check_license_headers import missing_headers
    offenders = missing_headers()  # list[str] of repo-relative paths
"""
from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Directories to walk (relative to repo root).
INCLUDE_DIRS = ["kaine", "scripts", "tests"]

# Exclusion patterns — matched against each path component.
EXCLUDE_PARTS = {
    "external",
    ".venv",
    "build",
    "dist",
    "__pycache__",
}
EXCLUDE_SUFFIXES = {".egg-info"}

SPDX_MARKER = "SPDX-License-Identifier"


def _is_excluded(path: pathlib.Path) -> bool:
    """Return True if *path* should be skipped."""
    for part in path.parts:
        if part in EXCLUDE_PARTS:
            return True
        for suffix in EXCLUDE_SUFFIXES:
            if part.endswith(suffix):
                return True
    return False


def _collect_files() -> list[pathlib.Path]:
    """Return sorted list of first-party .py files to check."""
    found: list[pathlib.Path] = []

    for dir_name in INCLUDE_DIRS:
        dir_path = REPO_ROOT / dir_name
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            rel = py_file.relative_to(REPO_ROOT)
            if not _is_excluded(rel):
                found.append(py_file)

    # Top-level .py files.
    for py_file in REPO_ROOT.glob("*.py"):
        rel = py_file.relative_to(REPO_ROOT)
        if not _is_excluded(rel):
            found.append(py_file)

    return sorted(set(found))


def _has_header(path: pathlib.Path) -> bool:
    """Return True if the file carries the SPDX identifier."""
    try:
        with path.open(encoding="utf-8") as fh:
            for i, line in enumerate(fh):
                if i >= 10:
                    break
                if SPDX_MARKER in line:
                    return True
    except OSError:
        pass
    return False


def missing_headers() -> list[str]:
    """Return repo-relative paths of first-party .py files missing the header.

    Returns an empty list if all files are compliant.
    """
    offenders: list[str] = []
    for path in _collect_files():
        if not _has_header(path):
            offenders.append(str(path.relative_to(REPO_ROOT)))
    return offenders


def main() -> None:
    offenders = missing_headers()
    if offenders:
        print(
            f"check_license_headers: {len(offenders)} file(s) missing the SPDX header:"
        )
        for f in offenders:
            print(f"  {f}")
        sys.exit(1)
    else:
        files = _collect_files()
        print(
            f"check_license_headers: all {len(files)} first-party .py files carry the header. OK."
        )
        sys.exit(0)


if __name__ == "__main__":
    main()
