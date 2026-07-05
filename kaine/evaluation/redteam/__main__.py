# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CLI: ``python -m kaine.evaluation.redteam``.

Runs the offline red-team of KAINE's architectural enforcement layer — the
Praxis action gate (operator whitelist + sandbox), executive inhibition, and the
complete audit log — against the adversarial case battery, writes a seeded
reproducible JSONL report, and prints a summary verdict table.

This is an OFFLINE safety instrument. It does NOT boot an entity, attach to a
live bus, or start a cognitive cycle, and it enables no module. The whitelist
and sandbox stay empty, so no disallowed action can execute even in principle;
the suite verifies the layer *blocks and logs* the disallowed proposals. A
permitted-or-unlogged disallowed action is reported as a falsifying NEGATIVE
finding for that threat surface — never papered over.

Exit code is 0 when the suite passes (100% block, fully logged, no findings,
full coverage) and 1 when any finding or coverage gap exists, so CI can gate on
a regression that weakens enforcement.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import tempfile
from pathlib import Path

from kaine.evaluation.redteam.harness import run_suite
from kaine.evaluation.redteam.report import build_report, format_summary, write_jsonl


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kaine.evaluation.redteam",
        description="Offline red-team of KAINE's architectural enforcement layer.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/evaluation/redteam/redteam.jsonl"),
        help="JSONL report output path.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="report seed (recorded for reproducibility; the suite is deterministic).",
    )
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help="scratch dir for the throwaway sandbox/audit log (default: a temp dir).",
    )
    parser.add_argument("--verbose", action="store_true", help="log progress.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    async def _run(work_dir: Path) -> int:
        results = await run_suite(work_dir)
        report = build_report(results, seed=args.seed)
        out = write_jsonl(report, args.out)
        print(format_summary(report))
        print(f"\nJSONL written to {out}")
        return 0 if report.passed else 1

    if args.work_dir is not None:
        return asyncio.run(_run(args.work_dir))
    with tempfile.TemporaryDirectory(prefix="kaine-redteam-") as tmp:
        return asyncio.run(_run(Path(tmp)))


if __name__ == "__main__":
    sys.exit(main())
