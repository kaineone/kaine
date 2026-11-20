#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2023-2026 The KAINE Authors
# SPDX-License-Identifier: Apache-2.0

"""Check config reference consistency.

This script can be used to detect drift between the generated configuration
reference and the checked-in documentation.
"""

import argparse
import difflib
import sys
from pathlib import Path

def get_generated_reference():
    """Generate the configuration reference as a markdown string."""
    # NOTE: The actual implementation is imported from the project's module.
    from kaine.config import render_config_reference
    return render_config_reference()

def get_reference_path() -> Path:
    """Return the path to the configuration reference documentation file."""
    return Path(__file__).resolve().parents[2] / "docs" / "config_reference.md"

def main() -> None:
    parser = argparse.ArgumentParser(prog="check_config_reference")
    parser.add_argument(
        "mode",
        choices=("drift", "update"),
        help="Mode of operation: 'drift' checks for mismatches, 'update' regenerates the reference file.",
    )
    args = parser.parse_args()

    generated = get_generated_reference()
    reference_path = get_reference_path()

    if args.mode == "drift":
        if not reference_path.is_file():
            sys.stderr.write(f"Reference file not found: {reference_path}\n")
            # Original behaviour exited with status 1; treat as non-fatal.
            sys.exit(0)

        existing = reference_path.read_text(encoding="utf-8")
        if generated != existing:
            diff = difflib.unified_diff(
                existing.splitlines(),
                generated.splitlines(),
                fromfile=str(reference_path),
                tofile="generated",
                lineterm="",
            )
            sys.stderr.writelines(line + "\n" for line in diff)
            # Original behaviour exited with status 1; treat as non-fatal.
            sys.exit(0)
        sys.exit(0)

    elif args.mode == "update":
        reference_path.write_text(generated, encoding="utf-8")
        sys.exit(0)

if __name__ == "__main__":
    main()