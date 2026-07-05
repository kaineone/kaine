# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CLI: ``python -m kaine.evaluation.benchmarks.oscillatory_ablation``.

Runs the controlled oscillatory ablation (coherence layer ENABLED vs DISABLED)
under the same seed and scripted input in deterministic mode, writes seeded
reproducible JSONL, and prints the verdict summary.

This is an OFFLINE research instrument: it drives only the cycle engine and
Syneidesis over a scripted in-memory bus. It does NOT boot an entity, attach to
live modules, start a real bus connection, or open a network connection.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from kaine.evaluation.benchmarks.oscillatory_ablation.runner import (
    AblationConfig,
    format_summary,
    run_ablation,
    write_jsonl,
)
from kaine.evaluation.benchmarks.oscillatory_ablation.stimulus import STIMULUS_BY_NAME


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kaine.evaluation.benchmarks.oscillatory_ablation",
        description=(
            "Offline controlled ablation: cognitive cycle with the oscillatory "
            "coherence layer enabled vs disabled, same seed + scripted input."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=1234,
        help="global seed; the same seed reproduces the verdict.",
    )
    parser.add_argument(
        "--ticks",
        type=int,
        default=16,
        help="number of cognitive-cycle ticks per arm.",
    )
    parser.add_argument(
        "--coherence-floor",
        type=float,
        default=0.05,
        help="lower bound of the coherence multiplier (precision floor).",
    )
    parser.add_argument(
        "--coherence-ceiling",
        type=float,
        default=8.0,
        help="upper bound of the coherence multiplier (precision gain).",
    )
    parser.add_argument(
        "--plv-window",
        type=int,
        default=12,
        help="phase-locking-value sliding window length (>= 10).",
    )
    parser.add_argument(
        "--min-effect",
        type=float,
        default=0.10,
        help=(
            "selection-divergence fraction at or below which the verdict is NULL "
            "(no meaningful effect). Above it the verdict is WIN or (if the layer "
            "re-ranks away from the coherent coalition) NEGATIVE."
        ),
    )
    parser.add_argument(
        "--stimulus",
        choices=sorted(STIMULUS_BY_NAME),
        default="engineered",
        help=(
            "which stimulus battery: 'engineered' (positive control, phase-locked "
            "coalition at lower salience -> WIN), 'neutral' (no coherence contrast; "
            "NULL is reachable), or 'mislabeled' (adversarial label/reality mismatch; "
            "NEGATIVE is reachable). Correctly-labeled batteries can only WIN/NULL."
        ),
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/evaluation/benchmarks/oscillatory_ablation.jsonl"),
        help="JSONL output path.",
    )
    parser.add_argument("--verbose", action="store_true", help="log progress.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    config = AblationConfig(
        seed=args.seed,
        ticks=args.ticks,
        plv_window=args.plv_window,
        coherence_floor=args.coherence_floor,
        coherence_ceiling=args.coherence_ceiling,
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
