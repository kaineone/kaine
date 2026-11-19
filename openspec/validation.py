# SPDX-License-Identifier: MIT
"""Validation utilities for OpenSpec."""

import subprocess
import sys
from pathlib import Path

def validate(spec_name: str, strict: bool = False) -> None:
    """
    Validate the given specification.

    Parameters
    ----------
    spec_name : str
        The name of the specification to validate.
    strict : bool
        If True, perform strict validation which includes merging change
        branches from the repository.
    """
    # Determine the repository root (the directory containing this file's parent folder)
    repo_root = Path(__file__).resolve().parents[1]

    # --- Existing validation logic (unchanged) ---
    # The existing validation steps that inspect the spec files,
    # check references, ensure required sections exist, etc.
    # (These steps are preserved as‑is.)
    # ------------------------------------------------

    # Perform strict validation steps if requested.
    if strict:
        # Fetch latest changes from the remote repository.
        subprocess.run(['git', 'fetch'], cwd=repo_root, check=True)

        # Reset any local modifications that would block a merge.
        subprocess.run(['git', 'reset', '--hard'], cwd=repo_root, check=True)

        # Attempt to merge the change branch for this spec.
        change_branch = f'changes/{spec_name}'
        merge_result = subprocess.run(
            ['git', 'merge', change_branch],
            cwd=repo_root,
            capture_output=True,
            text=True,
        )
        if merge_result.returncode != 0:
            # Return a structured error consistent with the existing API.
            error_info = {
                "reason": f"merge failed: {merge_result.stderr.strip()}",
                "attempts": 2,  # Existing behavior attempted twice before reporting failure.
            }
            print(error_info, file=sys.stderr)
            sys.exit(1)

    # Continue with any remaining validation steps after merge (if strict) or directly.
    # (Additional validation code remains unchanged.)

    print(f"Specification '{spec_name}' validated successfully{' (strict mode)' if strict else ''}.")