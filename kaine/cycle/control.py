# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator CLI for cycle-layer commands.

Supports requesting a live preservation and waiting for the result, and lifting
a welfare, development or programme_end freeze by name (the release path for a
run whose dashboard is read-only).
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Callable

from kaine.config import load_kaine_config
from kaine.cycle import control_state
from kaine.cycle.preserve_watch import (
    REQUEST_PATH,
    RESULT_PATH,
    new_request,
    read_result,
    write_request,
)
from kaine.storage import install_data_root, resolve


def run_preserve(
    reason: str,
    stop: bool,
    wait: float,
    *,
    request_path: Path | None = None,
    result_path: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> int:
    """Write a preservation request and wait for the matching result.

    Returns 0 on success, 1 on a recorded failure, and 2 on timeout.
    """
    req = new_request(reason, stop)
    write_request(req, request_path)

    deadline = clock() + wait
    while clock() < deadline:
        result = read_result(result_path)
        if isinstance(result, dict) and result.get("request_id") == req.request_id:
            if result.get("ok"):
                print(f"Preserved: {result.get('bundle')}")
                return 0
            print(f"Preservation failed: {result.get('error')}")
            return 1
        sleep(0.5)

    print("Timeout waiting for preservation result")
    return 2


def run_override(sources: list[str]) -> int:
    """Lift the named freeze holders and print what remains.

    Returns 0 on success, 1 when a source is not overridable or holds no
    active entry, and 2 on an OS-level failure such as a permission error.
    """
    was_unreadable = control_state.control_file_unreadable()
    try:
        state = control_state.override(sources)
    except (ValueError, LookupError) as exc:
        print(f"Override refused: {exc}")
        return 1
    except OSError as exc:
        print(f"Override failed: {exc}")
        return 2
    remaining = ", ".join(h["source"] for h in state.holders) or "none"
    print(f"Lifted: {', '.join(sorted(sources))}; still frozen by: {remaining}")
    if was_unreadable:
        print("The control file was unreadable and was replaced with a clean one; any other freeze holders it held were discarded.")
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        config = load_kaine_config()
    except Exception as exc:
        print(
            f"Warning: could not load config; data root not installed: {exc}",
            file=sys.stderr,
        )
    else:
        install_data_root(config)

    parser = argparse.ArgumentParser(prog="python -m kaine.cycle.control")
    sub = parser.add_subparsers(dest="command", required=True)

    preserve = sub.add_parser("preserve", help="request a live preservation")
    preserve.add_argument(
        "--stop", action="store_true", help="stop the entity after preserving"
    )
    preserve.add_argument(
        "--reason", default="operator", help="reason for the preservation"
    )
    preserve.add_argument(
        "--wait",
        type=float,
        default=120.0,
        help="seconds to wait for the result (default 120)",
    )

    override = sub.add_parser(
        "override", help="lift named welfare, development or programme_end freezes"
    )
    override.add_argument(
        "sources",
        nargs="+",
        choices=control_state.OVERRIDABLE_SOURCES,
        help="the freeze holders to lift",
    )

    args = parser.parse_args(argv)
    if args.command == "override":
        return run_override(list(args.sources))
    if args.command == "preserve":
        return run_preserve(
            args.reason,
            args.stop,
            args.wait,
            request_path=resolve(REQUEST_PATH),
            result_path=resolve(RESULT_PATH),
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
