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


def _add_pq_subcommands(subparsers) -> None:
    # gen-keypair
    gen = subparsers.add_parser(
        "gen-keypair",
        help="Generate an ML-KEM-768 keypair for a trustee (post-quantum).",
    )
    gen.add_argument("--trustee-id", required=True, help="Trustee identifier.")
    gen.add_argument(
        "--out-dir",
        default=".",
        help="Directory to write the private key PEM (default current dir).",
    )

    # escrow (split + wrap)
    esc = subparsers.add_parser(
        "escrow",
        help="Split a DEK into ML-KEM-wrapped Shamir shares.",
    )
    esc.add_argument("--entity-id", required=True, help="Entity identifier.")
    esc.add_argument("--dek-file", required=True, help="Path to a 32-byte raw DEK file.")
    esc.add_argument("--trustees", required=True, help="Path to trustees.toml.")
    esc.add_argument(
        "--threshold",
        type=int,
        default=2,
        help="Shamir threshold k (default 2).",
    )
    esc.add_argument("--out", required=True, help="Output bundle JSON path.")

    # recover
    rec = subparsers.add_parser(
        "recover",
        help="Open sealed shares and Shamir-combine into a DEK.",
    )
    rec.add_argument(
        "--bundle",
        required=True,
        help="Path to the bundle JSON.",
    )
    rec.add_argument(
        "--privkey",
        action="append",
        required=True,
        help="Trustee private key PEM path (repeat, one per share).",
    )
    rec.add_argument(
        "--out",
        required=True,
        help="Path to write the recovered (raw) DEK.",
    )

    # publish
    pub = subparsers.add_parser(
        "publish",
        help="Publish a bundle to a GitHub escrow repository (via gh CLI).",
    )
    pub.add_argument("--bundle", required=True, help="Path to bundle JSON.")
    pub.add_argument("--repo", required=True, help="GitHub repo (e.g. kaineone/escrow-kaineone).")


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

    if args.command == "gen-keypair":
        import pathlib

        from cryptography.hazmat.primitives import serialization

        from kaine.security.custody.pq_escrow import gen_trustee_keypair

        pub, priv_pem = gen_trustee_keypair()
        out_dir = pathlib.Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        priv_path = out_dir / f"{args.trustee_id}.pem"
        priv_path.write_bytes(priv_pem)
        priv_path.chmod(0o600)
        print(f"trustee id : {args.trustee_id}")
        print("public key (base64, paste into trustees.toml 'public_key_mlkem768'):")
        import base64

        print(base64.b64encode(pub).decode("ascii"))
        print(f"private key written to: {priv_path} (keep OFFLINE)")
        return 0

    if args.command == "escrow":
        import json
        import pathlib

        from kaine.security.custody.pq_escrow import (
            escrow_dek,
            load_trustees,
            serialize_bundle,
        )

        dek = pathlib.Path(args.dek_file).read_bytes()
        trustees = load_trustees(pathlib.Path(args.trustees))
        bundle = escrow_dek(dek, args.entity_id, trustees, threshold=args.threshold)
        out_path = pathlib.Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(serialize_bundle(bundle), indent=2), encoding="utf-8")
        print(f"wrote {out_path} ({len(bundle.shares)} shares, {args.threshold}-of-{len(trustees)})")
        return 0

    if args.command == "recover":
        import json
        import pathlib

        from cryptography.hazmat.primitives import serialization

        from kaine.security.custody.pq_escrow import (
            deserialize_bundle,
            open_share,
            recover_dek,
        )

        bundle = deserialize_bundle(json.loads(pathlib.Path(args.bundle).read_text()))
        opened = []
        for i, priv_path in enumerate(args.privkey):
            priv = serialization.load_pem_private_key(
                pathlib.Path(priv_path).read_bytes(), password=None
            )
            sh = bundle.shares[i]
            x, share = open_share(sh, priv)
            opened.append((x, share))
            print(f"  opened share for {sh.trustee_id} (x={x})")
        dek = recover_dek(opened)
        out_path = pathlib.Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(dek)
        out_path.chmod(0o600)
        print(f"recovered DEK written to {out_path}")
        return 0

    if args.command == "publish":
        import json
        import pathlib

        from kaine.security.custody.pq_escrow import (
            deserialize_bundle,
            publish_to_github,
        )

        bundle = deserialize_bundle(json.loads(pathlib.Path(args.bundle).read_text()))
        publish_to_github(args.repo, bundle.entity_id, bundle)
        print(f"published bundle for {bundle.entity_id} to {args.repo}")
        return 0

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
