# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Check that a pull request is small enough to review safely.

Measures commits and changed files between BASE and HEAD. Merge commits from
main into the branch are excluded, and the file diff uses the merge base so
changes already on BASE are not counted.
"""

from __future__ import annotations

import argparse
import subprocess
import sys


def measure(repo: str, base: str, head: str) -> tuple[int, int]:
    """Return the number of non-merge commits and changed files for the PR."""
    count = subprocess.run(
        ["git", "-C", repo, "rev-list", "--count", "--no-merges", f"{base}..{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    commits = int(count.stdout.strip())

    names = subprocess.run(
        ["git", "-C", repo, "diff", "--name-only", f"{base}...{head}"],
        check=True,
        capture_output=True,
        text=True,
    )
    files = len([line for line in names.stdout.splitlines() if line])
    return commits, files


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Check that a PR is small enough to review safely.",
    )
    parser.add_argument("base", help="base ref")
    parser.add_argument("head", help="head ref")
    parser.add_argument("--max-commits", type=int, default=15, help="commit limit")
    parser.add_argument("--max-files", type=int, default=40, help="file limit")
    parser.add_argument(
        "--allow-large", action="store_true", help="allow exceeding limits"
    )
    parser.add_argument("--repo", default=".", help="path to the git repository")
    args = parser.parse_args(argv)

    try:
        commits, files = measure(args.repo, args.base, args.head)
    except subprocess.CalledProcessError as exc:
        sys.stderr.write(f"git failed: {exc.stderr.strip()}\n")
        return 2

    print(
        f"pr-scope: {commits} commit(s) (limit {args.max_commits}), "
        f"{files} file(s) (limit {args.max_files})"
    )

    overs: list[str] = []
    if commits > args.max_commits:
        overs.append(f"commit limit exceeded ({commits} > {args.max_commits})")
    if files > args.max_files:
        overs.append(f"file limit exceeded ({files} > {args.max_files})")

    if overs:
        if args.allow_large:
            print("allowed: --allow-large")
            return 0
        for msg in overs:
            print(msg)
        print(
            "hint: split the change into smaller pull requests, rebuilt from "
            "current main; for an intentional large change add the large-change "
            "label (CI) or pass --allow-large (local)"
        )
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
