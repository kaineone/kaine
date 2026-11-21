# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CLI for entity key custody operations.

Usage::

    python -m kaine.security.custody migrate [--state-root STATE] [--dry-run] [--force]
"""

from __future__ import annotations

import argparse
import sys


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m kaine.security.custody",
        description="Entity key custody management.",
    )
    subparsers = parser.add_subparsers(dest="command")

    migrate = subparsers.add_parser(
        "migrate",
        help="Migrate entity state from v1/plaintext to v2 per-entity encryption.",
    )
    migrate.add_argument(
        "--state-root",
        default="state",
        help="Path to the state root directory (default: state).",
    )
    migrate.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing.",
    )
    migrate.add_argument(
        "--force",
        action="store_true",
        help="Force migration even if some entities already have a DEK.",
    )

    return parser


def _print_summary(summary: object) -> None:
    """Print a clean, content-free summary of the migration."""
    results = getattr(summary, "results", [])
    total_entities = len(results)
    total_encrypted = 0
    total_reencrypted = 0
    total_skipped_v2 = 0
    total_errors = 0
    skipped_entities = 0

    for result in results:
        if getattr(result, "skipped", False):
            skipped_entities += 1
            print(f"  {result.entity_id}: skipped (DEK already exists)")
            continue

        encrypted = getattr(result, "encrypted_count", 0)
        reencrypted = getattr(result, "re_encrypted_count", 0)
        skipped_v2 = getattr(result, "skipped_v2_count", 0)
        errors = getattr(result, "error_count", 0)

        total_encrypted += encrypted
        total_reencrypted += reencrypted
        total_skipped_v2 += skipped_v2
        total_errors += errors

        error_info = getattr(result, "error", None)
        if error_info and not getattr(result, "files", []):
            print(f"  {result.entity_id}: error: {error_info}")
        else:
            file_count = encrypted + reencrypted + skipped_v2 + errors
            print(f"  {result.entity_id}: {file_count} files "
                  f"(encrypted={encrypted} re-encrypted={reencrypted} "
                  f"skipped-v2={skipped_v2} errors={errors})")

    print()
    print(f"entities: {total_entities} total, {skipped_entities} skipped")
    print(f"files: encrypted={total_encrypted} re-encrypted={total_reencrypted} "
          f"skipped-v2={total_skipped_v2} errors={total_errors}")

    summary_errors = getattr(summary, "errors", [])
    if summary_errors:
        print(f"\n{len(summary_errors)} error(s):")
        for err in summary_errors:
            print(f"  {err}")

    if getattr(summary, "dry_run", False):
        print("\ndry run -- no files were modified")
    elif total_errors == 0:
        print("\nmigration complete")
    else:
        print("\nmigration completed with errors")


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "migrate":
        import logging

        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)s %(name)s: %(message)s",
        )

        from kaine.security.custody.migrate import MigrationError, migrate

        try:
            summary = migrate(
                args.state_root,
                dry_run=args.dry_run,
                force=args.force,
            )
        except MigrationError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1

        _print_summary(summary)
        return 1 if summary.errors else 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
