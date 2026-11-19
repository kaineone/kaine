#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CI check: shipped defaults and the committed reference file must agree."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import tomllib

# Keep this import working when run from the repository root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kaine.config import list_all_defaults


CANDIDATE_REFERENCE_PATHS = (
    Path("config/reference.toml"),
    Path("docs/config_defaults.toml"),
    Path("docs/reference.toml"),
    Path("config/kaine.reference.toml"),
)


def _load_reference(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", type=Path, default=None)
    args = parser.parse_args()

    if args.reference is not None:
        candidates = [args.reference]
    else:
        candidates = [p for p in CANDIDATE_REFERENCE_PATHS if p.exists()]

    if not candidates:
        print("No reference file found; nothing to check.", file=sys.stderr)
        return 2

    expected = list_all_defaults()
    failed = False
    for path in candidates:
        actual = _load_reference(path)
        if actual != expected:
            failed = True
            print(f"DRIFT: {path} does not match list_all_defaults()", file=sys.stderr)
            print("expected keys:", sorted(expected), file=sys.stderr)
            print("reference keys:", sorted(actual), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())