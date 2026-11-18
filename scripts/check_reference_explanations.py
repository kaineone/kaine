#!/usr/bin/env python3
"""CI check: every reference entry must have a non-placeholder explanation.

A reference entry is a non-empty bullet under docs/reference*. Fail when any
entry contains TODO/TBD/XXX/placeholder text.
"""

from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BAD_TOKENS = re.compile(r"\b(TODO|TBD|XXX|FIXME|placeholder)\b", re.IGNORECASE)


def main() -> int:
    files = []
    for base in (ROOT / "docs", ROOT):
        if (base / "reference").is_dir():
            files.extend((base / "reference").rglob("*"))
    files = [p for p in files if p.is_file()]
    if not files:
        print("no reference files found; nothing to check")
        return 0

    failures = []
    for path in files:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if BAD_TOKENS.search(stripped):
                failures.append(f"{path.relative_to(ROOT)}:{line_no}: {stripped}")

    if failures:
        print("Reference entries contain placeholder explanations:")
        for failure in failures:
            print(failure)
        return 1
    print(f"checked {len(files)} reference file(s): OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())