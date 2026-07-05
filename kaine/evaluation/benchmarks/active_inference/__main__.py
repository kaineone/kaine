# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""CLI: ``python -m kaine.evaluation.benchmarks.active_inference``.

Runs the offline AIF-vs-RL benchmark on the default suite (or a chosen subset),
writes seeded reproducible JSONL, and prints the summary verdict table.

This is an OFFLINE research instrument: it constructs synthetic discrete POMDPs
and runs headless. It does NOT boot an entity, attach to the bus, or start a
cognitive cycle, and it enables no module.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from kaine.evaluation.benchmarks.active_inference import envs as envs_mod
from kaine.evaluation.benchmarks.active_inference.metrics import VerdictConfig
from kaine.evaluation.benchmarks.active_inference.runner import (
    BenchmarkConfig,
    format_summary_table,
    run_suite,
    write_jsonl,
)


def _build_tasks(names: list[str] | None):
    suite = envs_mod.default_suite()
    if not names:
        return suite
    by_name = {t.name: t for t in suite}
    chosen = []
    for n in names:
        if n not in by_name:
            raise SystemExit(
                f"unknown task {n!r}; available: {', '.join(sorted(by_name))}"
            )
        chosen.append(by_name[n])
    return chosen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m kaine.evaluation.benchmarks.active_inference",
        description="Offline benchmark: Nous active inference vs an RL baseline.",
    )
    parser.add_argument(
        "--seeds",
        type=int,
        default=8,
        help="number of evaluation seeds (0..N-1). Same seeds reproduce the verdict.",
    )
    parser.add_argument(
        "--rl-train-episodes",
        type=int,
        default=800,
        help="Q-learning training episodes per seed.",
    )
    parser.add_argument(
        "--eval-episodes",
        type=int,
        default=100,
        help="evaluation episodes per seed (both agents).",
    )
    parser.add_argument(
        "--tasks",
        nargs="*",
        default=None,
        help="task names to run (default: the full suite).",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/evaluation/benchmarks/active_inference.jsonl"),
        help="JSONL output path.",
    )
    parser.add_argument(
        "--alpha", type=float, default=0.05, help="verdict significance level."
    )
    parser.add_argument(
        "--min-effect",
        type=float,
        default=0.3,
        help="minimum |rank-biserial r| for a WIN/NEGATIVE (else NULL).",
    )
    parser.add_argument("--verbose", action="store_true", help="log progress.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    tasks = _build_tasks(args.tasks)
    config = BenchmarkConfig(
        seeds=tuple(range(args.seeds)),
        rl_train_episodes=args.rl_train_episodes,
        rl_eval_episodes=args.eval_episodes,
        aif_eval_episodes=args.eval_episodes,
        verdict=VerdictConfig(alpha=args.alpha, min_effect=args.min_effect),
    )

    result = run_suite(tasks, config)
    write_jsonl(result["records"], args.out)
    print(format_summary_table(result))
    print(f"\nJSONL written to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
