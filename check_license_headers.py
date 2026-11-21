#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

"""
Check that all source files contain an SPDX license identifier.
"""

import argparse
import os
import sys

# Extensions of source files to check.
EXTENSIONS = {".py", ".sh"}

# Directories to exclude from the search.
EXCLUDE_DIRS = {".git", "third_party", "build", "__pycache__"}

def file_has_spdx_header(path):
    """Return True if the file at `path` contains an SPDX license identifier."""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for i, line in enumerate(f):
                if "SPDX-License-Identifier:" in line:
                    return True
                if i >= 6:  # only look at the first few lines
                    break
        return False
    except Exception:
        # If the file cannot be read (binary, etc.), assume it's fine.
        return True

def should_check_file(filepath):
    _, ext = os.path.splitext(filepath)
    return ext.lower() in EXTENSIONS

def scan_path(root):
    missing = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Remove any excluded directories from traversal.
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for filename in filenames:
            full_path = os.path.join(dirpath, filename)
            if should_check_file(full_path) and not file_has_spdx_header(full_path):
                missing.append(full_path)
    return missing

def main():
    parser = argparse.ArgumentParser(description="Verify SPDX license headers")
    parser.add_argument(
        "paths",
        nargs="*",
        default=["."],
        help="Directories to scan for source files (default: current directory)",
    )
    args = parser.parse_args()

    all_missing = []
    for path in args.paths:
        all_missing.extend(scan_path(path))

    if all_missing:
        print("Missing SPDX license identifier in the following files:", file=sys.stderr)
        for f in sorted(all_missing):
            print(f, file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    sys.exit(main())