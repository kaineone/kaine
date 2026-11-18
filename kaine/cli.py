"""Command-line interface helpers for KAINE."""

from __future__ import annotations

import argparse

BASIC_TIERS: tuple[str, ...] = ("basic",)
ALL_TIERS: tuple[str, ...] = ("basic", "standard", "advanced", "full")


def selected_tiers(*, full: bool = False) -> list[str]:
    """Return the tier names covered by a CLI invocation."""
    return list(ALL_TIERS if full else BASIC_TIERS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kaine")
    parser.add_argument(
        "--full",
        action="store_true",
        help="Cover all configuration tiers instead of only the basic tier.",
    )
    return parser


def tiers_from_args(args: argparse.Namespace) -> list[str]:
    return selected_tiers(full=bool(getattr(args, "full", False)))
