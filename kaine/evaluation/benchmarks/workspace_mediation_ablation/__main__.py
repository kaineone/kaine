# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CLI: ``python -m kaine.evaluation.benchmarks.workspace_mediation_ablation``.

Runs the workspace-mediation ablation (competitive workspace vs flat fan-in) over
the real Soma and Chronos modules under a fixed seed, writes seeded reproducible
JSONL, and prints the verdict summary.

OFFLINE research instrument: the modules are driven by hand over an in-memory
bus. It does NOT boot an entity, start a real bus connection, or open a network
connection.
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
            "Offline workspace-mediation ablation: the system as built "
            "(competitive workspace) vs a matched flat fan-in control, same seed."
        ),
    )
    parser.add_argument(
        "--seed", type=int, default=1234, help="global seed; reproduces the verdict."
    )
    parser.add_argument("--ticks", type=int, default=24, help="ticks per arm.")
    parser.add_argument(
        "--top-k",
        type=int,
        default=2,
        help=(
            "workspace capacity. Keep it below the per-tick candidate count so "
            "competitive selection actually excludes (the shipped default 5 does "
            "not compete on the minimal set)."
        ),
    )
    parser.add_argument(
        "--window", type=int, default=6, help="sliding window for error correlation."
    )
    parser.add_argument(
        "--min-effect",
        type=float,
        default=0.15,
        help=(
            "minimum |coupling_delta| for a non-NULL verdict. A positive delta "
            "above this is WIN; at or below -min-effect is NEGATIVE; within is NULL "
            "(the fan-in prompt-assembler outcome)."
        ),
    )
    parser.add_argument(
        "--stimulus",
        choices=sorted(STIMULUS_BY_NAME),
        default="soma_salient",
        help=(
            "battery: 'soma_salient' (coverage: Soma made salient + competition), "
            "'neutral' (quiet substrate, NULL/underpowered reachable), or "
            "'decoupled' (control where coupling should be weak)."
        ),
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
        top_k=args.top_k,
        window=args.window,
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
