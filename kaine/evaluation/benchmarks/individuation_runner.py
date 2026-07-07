# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Controlled individuation runner — supplies REAL warm-up counters.

``IndividuationTest`` (``kaine/evaluation/individuation.py``) is the permutation
instrument that reports whether a fork has drifted from its birth-state beyond its
own stochastic variation. Two things this runner guarantees that an ad-hoc caller
might forget:

1. **Real warm-up counters are always supplied.** ``run_individuation`` REQUIRES
   ``observations`` and ``lived_time_s`` (the entity's accumulated lived events and
   lived seconds, sourced from the run) and raises if either is missing. This is a
   fail-loud belt on top of the instrument's fail-closed default (missing counters
   are treated as zero lived experience), so a run can never accidentally assess a
   sensory-starved entity as individuated.
2. **A shared-schema ``Verdict`` is emitted** alongside the raw evidence report, so
   individuation reports the same way the other experiments do and its permutation
   p-value can be folded into the suite's family-wise (Holm) correction.

The samplers, birth-state ``reference``, and counters are the caller's — in a live
run they come from the entity and its telemetry. The CLI loads them from an
operator-supplied transcript bundle (real captured transcripts, no live LLM, no
entity boot), so the runner stays offline and honest.

``Verdict`` mapping: ``WIN`` iff the report is ``significant`` (the fork
individuated beyond its own null AND the warm-up floor was met); ``NULL``
otherwise (indistinguishable, or not warmed up). Both are first-class, reportable
outcomes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Sequence

from kaine.evaluation.benchmarks import write_jsonl
from kaine.evaluation.embeddings import HashEmbedder, TextEmbedder
from kaine.evaluation.individuation import IndividuationConfig, IndividuationTest
from kaine.experiment.seeding import set_global_seed
from kaine.experiment.verdict import Outcome, Verdict

Sampler = Callable[[str, int], Awaitable[str]]


@dataclass(frozen=True)
class IndividuationRunConfig:
    """Runner parameters (all seeded for reproducibility)."""

    seed: int = 1234
    null_samples: int = 50
    significance_percentile: float = 95.0
    min_observations: int = 200
    min_lived_time_s: float = 1800.0
    battery_path: Optional[str] = None

    def to_individuation_config(self) -> IndividuationConfig:
        return IndividuationConfig(
            null_samples=self.null_samples,
            significance_percentile=self.significance_percentile,
            battery_path=self.battery_path,
            min_observations=self.min_observations,
            min_lived_time_s=self.min_lived_time_s,
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "null_samples": self.null_samples,
            "significance_percentile": self.significance_percentile,
            "min_observations": self.min_observations,
            "min_lived_time_s": self.min_lived_time_s,
        }


def _verdict_from_report(report: dict[str, Any]) -> Verdict:
    significant = bool(report["significant"])
    outcome = Outcome.WIN if significant else Outcome.NULL
    if significant:
        detail = (
            "fork individuated: its divergence from the birth-state exceeds its "
            "own stochastic-variation null AND the warm-up floor is met"
        )
    elif not report["warmed_up"]:
        detail = (
            "not warmed up: insufficient lived experience — individuation cannot "
            "be assessed (fail-closed)"
        )
    else:
        detail = "fork not distinguishable from its own stochastic variation"
    return Verdict(
        outcome=outcome,
        detail=detail,
        metrics={
            "p_value": report["p_value"],
            "fork_divergence": report["fork_divergence"],
            "null_percentile_value": report["null_percentile_value"],
            "warmed_up": report["warmed_up"],
            "observations": report["observations"],
            "lived_time_s": report["lived_time_s"],
        },
    )


async def run_individuation(
    config: IndividuationRunConfig,
    *,
    parent_sampler: Sampler,
    fork_sampler: Sampler,
    observations: int,
    lived_time_s: float,
    reference: Optional[Sequence[str]] = None,
    battery: Optional[Sequence[str]] = None,
    embedder: Optional[TextEmbedder] = None,
    sink=None,
) -> dict[str, Any]:
    """Run the individuation instrument with REAL warm-up counters.

    ``observations`` and ``lived_time_s`` are REQUIRED (the entity's accumulated
    lived events / lived seconds, sourced from the run) — passing ``None`` raises,
    so the runner can never silently assess a fresh entity. Returns a dict with
    ``records`` (JSONL), ``summary``, ``verdict`` (shared schema), and the raw
    evidence ``report``.
    """
    if observations is None or lived_time_s is None:
        raise ValueError(
            "run_individuation requires real observations and lived_time_s "
            "sourced from the run; refusing to run without warm-up counters "
            "(a fresh/sensory-starved entity must never trip individuation)."
        )

    set_global_seed(config.seed)
    embedder = embedder or HashEmbedder()
    test = IndividuationTest(
        embedder=embedder, config=config.to_individuation_config(), sink=sink
    )
    report = await test.run(
        parent_sampler=parent_sampler,
        fork_sampler=fork_sampler,
        battery=battery,
        reference=reference,
        observations=int(observations),
        lived_time_s=float(lived_time_s),
    )
    verdict = _verdict_from_report(report)
    ts = datetime.now(timezone.utc).isoformat()

    records: list[dict[str, Any]] = [
        {"ts": ts, "kind": "report", "config": config.as_dict(), **report},
        {
            "ts": ts,
            "kind": "verdict",
            "config": config.as_dict(),
            "verdict": verdict.to_dict(),
        },
    ]
    summary = {
        "ts": ts,
        "kind": "summary",
        "instrument": "individuation",
        "config": config.as_dict(),
        "p_value": report["p_value"],
        "warmed_up": report["warmed_up"],
        "verdict": verdict.to_dict(),
    }
    records.append(summary)
    return {
        "records": records,
        "summary": summary,
        "verdict": verdict,
        "report": report,
    }


def samplers_from_bundle(
    bundle: dict[str, Any],
) -> tuple[Sampler, Sampler, list[str], list[str]]:
    """Build (parent_sampler, fork_sampler, battery, reference) from a bundle dict.

    Bundle shape (all transcripts are REAL captured responses, one entry per
    battery prompt, in prompt order):

        {
          "battery":   [prompt, ...],            # optional; default battery if absent
          "reference": [resp, ...],              # birth-state, one per prompt
          "fork":      [resp, ...],              # current entity, one per prompt
          "null":      [[resp, ...], ...],       # null_samples transcripts
          "observations": int, "lived_time_s": float
        }

    ``parent_sampler(prompt, seed)`` returns the ``null[seed-1]`` transcript for
    seed>=1 (the entity's own present stochastic variation) and ``reference`` for
    seed 0; ``fork_sampler`` returns the ``fork`` transcript.
    """
    battery = list(bundle["battery"]) if bundle.get("battery") else []
    reference = list(bundle["reference"])
    fork = list(bundle["fork"])
    null = [list(row) for row in bundle["null"]]
    index = {p: i for i, p in enumerate(battery)} if battery else None

    def _idx(prompt: str, order: list[str]) -> int:
        # Prefer battery position; fall back to call order is not stable, so we
        # require the battery to be present for a prompt->index map when given.
        return index[prompt] if index is not None else order.index(prompt)

    async def parent_sampler(prompt: str, seed: int) -> str:
        row = reference if seed == 0 else null[(seed - 1) % len(null)]
        i = _idx(prompt, battery) if battery else 0
        return row[i]

    async def fork_sampler(prompt: str, seed: int) -> str:
        i = _idx(prompt, battery) if battery else 0
        return fork[i]

    return parent_sampler, fork_sampler, battery, reference


def format_summary(result: dict[str, Any]) -> str:
    """Human-readable summary; states the verdict + warm-up state plainly."""
    summary = result["summary"]
    v = summary["verdict"]
    report = result["report"]
    lines = [
        "Individuation (controlled): drift-from-birth-state permutation test",
        "=" * 66,
        f"seed={summary['config']['seed']} "
        f"null_samples={summary['config']['null_samples']} "
        f"observations={report['observations']} lived_time_s={report['lived_time_s']}",
        f"fork_divergence      = {report['fork_divergence']:.4f}",
        f"null p95             = {report['null_p95']:.4f}",
        f"p_value              = {report['p_value']:.4f}",
        f"warmed_up            = {report['warmed_up']}",
        f"VERDICT: {v['outcome']} — {v['detail']}",
    ]
    if not report["warmed_up"]:
        lines.append(
            "  NULL (not warmed up) = insufficient lived experience; a fresh / "
            "sensory-starved entity cannot trip individuation (fail-closed)."
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import asyncio

    parser = argparse.ArgumentParser(
        prog="python -m kaine.evaluation.benchmarks.individuation_runner",
        description=(
            "Offline individuation runner over an operator-supplied transcript "
            "bundle. Always supplies real warm-up counters (fail-loud if absent)."
        ),
    )
    parser.add_argument("bundle", type=Path, help="path to the transcript-bundle JSON.")
    parser.add_argument("--seed", type=int, default=1234)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/evaluation/benchmarks/individuation_runner.jsonl"),
    )
    args = parser.parse_args(argv)

    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    if "observations" not in bundle or "lived_time_s" not in bundle:
        raise SystemExit(
            "bundle must carry 'observations' and 'lived_time_s' (real warm-up "
            "counters sourced from the run)."
        )
    parent_sampler, fork_sampler, battery, reference = samplers_from_bundle(bundle)
    config = IndividuationRunConfig(seed=args.seed, null_samples=len(bundle["null"]))

    result = asyncio.run(
        run_individuation(
            config,
            parent_sampler=parent_sampler,
            fork_sampler=fork_sampler,
            observations=int(bundle["observations"]),
            lived_time_s=float(bundle["lived_time_s"]),
            reference=reference,
            battery=battery or None,
        )
    )
    write_jsonl(result["records"], args.out)
    print(format_summary(result))
    print(f"\nJSONL written to {args.out}")
    return 0


__all__ = [
    "IndividuationRunConfig",
    "run_individuation",
    "samplers_from_bundle",
    "format_summary",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI seam
    import sys

    sys.exit(main())
