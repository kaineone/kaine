# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Apply SPDX + copyright headers to all first-party Python source files.

Idempotent: running this script a second time changes nothing.
Usage::

    python scripts/apply_license_headers.py
"""
from __future__ import annotations

import pathlib
import sys

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

HEADER_LINE_1 = "# SPDX-License-Identifier: LicenseRef-CAL-0.2"
HEADER_LINE_2 = "# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>"
HEADER = f"{HEADER_LINE_1}\n{HEADER_LINE_2}\n"

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
    """Return sorted list of first-party .py files to process."""
    found: list[pathlib.Path] = []

    # Walk each included directory tree.
    for dir_name in INCLUDE_DIRS:
        dir_path = REPO_ROOT / dir_name
        if not dir_path.exists():
            continue
        for py_file in dir_path.rglob("*.py"):
            rel = py_file.relative_to(REPO_ROOT)
            if not _is_excluded(rel):
                found.append(py_file)

    # Top-level .py files (e.g. setup.py if present).
    for py_file in REPO_ROOT.glob("*.py"):
        rel = py_file.relative_to(REPO_ROOT)
        if not _is_excluded(rel):
            found.append(py_file)

    return sorted(set(found))


def _has_header(text: str) -> bool:
    """Return True if the file already contains the SPDX identifier."""
    # Scan only the first 10 lines for efficiency.
    for line in text.splitlines()[:10]:
        if "SPDX-License-Identifier" in line:
            return True
    return False


def _insert_header(text: str) -> str:
    """Return *text* with the header inserted in the correct position.

    Insertion order:
    1. Shebang line (``#!...``), if present — kept first.
    2. Coding cookie (``# -*- coding ...``), if present — kept second.
    3. **Header** (our two lines + a blank line separator).
    4. Remaining content.
    """
    lines = text.splitlines(keepends=True)
    insert_at = 0

    # Keep shebang first.
    if lines and lines[0].startswith("#!"):
        insert_at = 1

    # Keep coding cookie immediately after shebang (if present).
    if insert_at < len(lines) and lines[insert_at].startswith("# -*- coding"):
        insert_at += 1

    # Build the header block; add a blank separator if the next line isn't one.
    separator = "\n"
    next_line = lines[insert_at] if insert_at < len(lines) else ""
    if next_line.strip() == "":
        # Next line is already blank — don't add an extra one.
        header_block = HEADER
    else:
        header_block = HEADER + separator

    new_lines = lines[:insert_at] + [header_block] + lines[insert_at:]
    return "".join(new_lines)


def apply_headers(*, dry_run: bool = False) -> tuple[int, int]:
    """Apply headers to all first-party files.

    Returns ``(headered, already_had)`` counts.
    """
    files = _collect_files()
    headered = 0
    already_had = 0

    for path in files:
        text = path.read_text(encoding="utf-8")
        if _has_header(text):
            already_had += 1
            continue

        new_text = _insert_header(text)
        if not dry_run:
            path.write_text(new_text, encoding="utf-8")
        headered += 1

    return headered, already_had


def main() -> None:
    headered, already_had = apply_headers()
    total = headered + already_had
    print(
        f"apply_license_headers: {total} files scanned — "
        f"{headered} headered, {already_had} already had the header."
    )


if __name__ == "__main__":
    main()
