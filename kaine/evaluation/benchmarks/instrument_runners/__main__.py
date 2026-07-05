# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CLI: ``python -m kaine.evaluation.benchmarks.instrument_runners <instrument>``.

Dispatches to one of the three controlled instrument runners — ``ab_divergence``,
``memory_coherence``, or ``self_model`` — under a fixed seed and stimulus battery,
writes seeded reproducible JSONL, and prints the verdict summary.

These are OFFLINE research instruments: they drive only deterministic / echo
clients and an in-memory Mnemos. They do NOT boot an entity, attach to live
modules, start a real bus connection, or open a network connection.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from kaine.evaluation.benchmarks.instrument_runners.ab_divergence_runner import (
    ABDivergenceConfig,
    format_summary as format_ab_summary,
    run_ab_divergence,
)
from kaine.evaluation.benchmarks.instrument_runners.memory_coherence_runner import (
    MemoryCoherenceConfig,
    format_summary as format_memory_summary,
    run_memory_coherence,
)
from kaine.evaluation.benchmarks.instrument_runners.self_model_runner import (
    SelfModelConfig,
    format_summary as format_self_model_summary,
    run_self_model,
)
from kaine.evaluation.benchmarks.instrument_runners.shared import write_jsonl

_DEFAULT_OUT = {
    "ab_divergence": "data/evaluation/benchmarks/ab_divergence_runner.jsonl",
    "memory_coherence": "data/evaluation/benchmarks/memory_coherence_runner.jsonl",
    "self_model": "data/evaluation/benchmarks/self_model_runner.jsonl",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kaine.evaluation.benchmarks.instrument_runners",
        description=(
            "Offline controlled runner for one of the passive measuring "
            "instruments (A/B divergence, memory coherence, self-model accuracy)."
        ),
    )
    parser.add_argument(
        "instrument",
        choices=("ab_divergence", "memory_coherence", "self_model"),
        help="which controlled instrument runner to execute.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=1234,
        help="global seed; the same seed reproduces the verdict.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="JSONL output path (defaults per instrument).",
    )
    args = parser.parse_args(argv)

    out = args.out or Path(_DEFAULT_OUT[args.instrument])

    if args.instrument == "ab_divergence":
        result = asyncio.run(run_ab_divergence(ABDivergenceConfig(seed=args.seed)))
        summary_text = format_ab_summary(result)
    elif args.instrument == "memory_coherence":
        result = asyncio.run(run_memory_coherence(MemoryCoherenceConfig(seed=args.seed)))
        summary_text = format_memory_summary(result)
    else:  # self_model
        result = asyncio.run(run_self_model(SelfModelConfig(seed=args.seed)))
        summary_text = format_self_model_summary(result)

    write_jsonl(result["records"], out)
    print(summary_text)
    print(f"\nJSONL written to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
