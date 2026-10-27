# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CLI: ``python -m kaine.evaluation.benchmarks.workspace_mediation_ablation``.

Runs the workspace-mediation test's development run offline. It exercises a
reduced pair of real processors (the interoception and vision modules) with the workspace on against a
pooled arm, measuring cross-module broadcast information gain. The modules are
driven by hand over an in-memory bus. It boots no entity and opens no network
connection. It is development tooling and does not test the hypothesis.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from kaine.evaluation.benchmarks.workspace_mediation_ablation.runner import (
    MediationConfig,
    format_summary,
    run_ablation,
    write_jsonl,
)
from kaine.evaluation.benchmarks.workspace_mediation_ablation.stimulus import (
    STIMULUS_BY_NAME,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kaine.evaluation.benchmarks.workspace_mediation_ablation",
        description=(
            "Offline development run of the workspace-mediation test. It runs "
            "a reduced pair of real processors (Interoception and Vision) with the workspace on "
            "against a pooled arm, measuring cross-module broadcast information gain. "
            "It boots no entity and opens no network connection. It is development "
            "tooling and does not test the hypothesis."
        ),
    )
    parser.add_argument(
        "--seed", type=int, default=1234, help="global seed; reproduces the verdict."
    )
    parser.add_argument("--ticks", type=int, default=160, help="ticks per arm.")
    parser.add_argument(
        "--warmup-ticks",
        type=int,
        default=40,
        help="initial learning period excluded from the information gain.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=2,
        help=(
            "workspace capacity; keep it below the per-tick candidate count so "
            "selection excludes."
        ),
    )
    parser.add_argument(
        "--access-threshold", type=float, default=0.05, help="broadcast access gate."
    )
    parser.add_argument(
        "--min-effect",
        type=float,
        default=0.05,
        help="minimum |dIG| for a non-NULL verdict.",
    )
    parser.add_argument(
        "--stimulus",
        choices=sorted(STIMULUS_BY_NAME),
        default="coupled",
        help="battery: 'coupled' (cross-module lag-2 relation) or 'independent' (no relation).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/evaluation/benchmarks/workspace_mediation_ablation.jsonl"),
        help="JSONL output path.",
    )
    parser.add_argument("--verbose", action="store_true", help="log progress.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    config = MediationConfig(
        seed=args.seed,
        ticks=args.ticks,
        warmup_ticks=args.warmup_ticks,
        top_k=args.top_k,
        access_threshold=args.access_threshold,
        min_effect=args.min_effect,
    )
    stimulus = STIMULUS_BY_NAME[args.stimulus]
    result = asyncio.run(run_ablation(config, stimulus=stimulus))
    write_jsonl(result["records"], args.out)
    print(format_summary(result))
    print(f"\nJSONL written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
