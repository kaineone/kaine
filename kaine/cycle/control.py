# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator CLI for cycle-layer commands.

Currently supports requesting a live preservation and waiting for the result.
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path
from typing import Callable

from kaine.cycle.preserve_watch import (
    new_request,
    read_result,
    write_request,
)


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


def main(argv: list[str] | None = None) -> int:
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

    args = parser.parse_args(argv)
    if args.command == "preserve":
        return run_preserve(args.reason, args.stop, args.wait)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
