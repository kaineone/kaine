# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared-seed suite orchestrator — the seven experiments under ONE seed.

The paper frames "seven experiments, one shared seed"; this is the single entry
point that delivers it. From one master seed it derives an independent-but-
reproducible child seed per experiment via ``numpy.random.SeedSequence.spawn``
(cleaner than a single global for independent streams that must each stay
reproducible), threads that child seed into every experiment — INCLUDING the
active-inference benchmark, whose env/RL rng is derived from the master via
``BenchmarkConfig.master_seed`` rather than an independent ``default_rng`` — and
emits one combined report.

The seven experiments (docs/processes/testing-framework.md):
  1. active-inference (Nous AIF vs tuned RL) — the p-value producer (Mann-Whitney
     per task);
  2. oscillatory ablation (coherence layer on vs off);
  3. A/B divergence (controlled dynamic-range battery);
  4. memory coherence (retrieval-advantage battery);
  5. self-model accuracy (fixed-threshold scorer battery);
  6. multi-seed stability (the longitudinal control's machinery, run offline);
  7. enforcement red-team (the real enforcement layer vs a case battery).

Family-wise correction
----------------------
Across the p-value-producing experiments the orchestrator applies the
Holm-Bonferroni correction (FWER control — see ``kaine.experiment.
multiple_comparisons``) at the suite level and reports raw p, Holm-corrected p,
and the reject/no-reject decision under a stated alpha. The active-inference
benchmark contributes one p-value per task; an optional individuation run (folded
in by the caller) contributes its permutation p-value. The correction is a
family-wise VIEW; each experiment's own raw verdict is preserved unchanged.

GPU/cuDNN determinism (opt-in) is requested once at the top of the run via
``set_global_seed(master_seed, deterministic=True)`` — the offline/deterministic
path. The offline runners are CPU/numpy, so this mostly future-proofs any torch
op they might touch; it never runs on the live cycle.

Offline: every experiment here drives deterministic / echo clients, in-memory
stores, scripted buses, and the real (headless) enforcement layer. Nothing boots
an entity, enables a module, or opens a network connection.
"""
from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np

from kaine.evaluation.benchmarks.active_inference import envs as envs_mod
from kaine.evaluation.benchmarks.active_inference.metrics import VerdictConfig
from kaine.evaluation.benchmarks.active_inference.runner import (
    BenchmarkConfig,
    run_suite as run_active_inference,
)
from kaine.evaluation.benchmarks.instrument_runners import (
    ABDivergenceConfig,
    MemoryCoherenceConfig,
    SelfModelConfig,
    run_ab_divergence,
    run_memory_coherence,
    run_self_model,
)
from kaine.evaluation.benchmarks.oscillatory_ablation.runner import (
    AblationConfig,
    run_ablation,
)
from kaine.evaluation.benchmarks.oscillatory_ablation.stability import (
    run_ablation_stability,
)
from kaine.evaluation.redteam.harness import run_suite as run_redteam
from kaine.experiment.multiple_comparisons import holm_report
from kaine.experiment.seeding import set_global_seed
from kaine.experiment.verdict import Outcome, Verdict

# The seven experiments, in report order. The active-inference benchmark is the
# family-wise p-value producer; the rest emit threshold/gate verdicts.
EXPERIMENT_NAMES = (
    "active_inference",
    "oscillatory_ablation",
    "ab_divergence",
    "memory_coherence",
    "self_model",
    "multi_seed_stability",
    "enforcement_red_team",
)


@dataclass(frozen=True)
class SuiteConfig:
    """One seed drives the whole suite; ``alpha`` is the family-wise level.

    ``fast`` shrinks the (otherwise slow) active-inference benchmark and the
    oscillatory ticks so a smoke run / reduced subset finishes quickly. The full
    default config runs the benchmark at its shipped size.
    """

    seed: int = 1234
    alpha: float = 0.05
    deterministic: bool = True  # opt-in GPU/cuDNN determinism for the offline path
    # Active-inference sizing (full by default; reduced under ``fast``).
    ai_seeds: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7)
    ai_rl_train_episodes: int = 800
    ai_eval_episodes: int = 100
    ai_tasks: Optional[tuple[str, ...]] = None  # None => the full default suite
    # Oscillatory / stability sizing.
    oscillatory_ticks: int = 16
    stability_seeds: tuple[int, ...] = (0, 1, 2)
    stability_tolerance: float = 0.05

    @classmethod
    def fast(cls, seed: int = 1234, **kw: Any) -> "SuiteConfig":
        """A reduced config for a smoke run: tiny AI benchmark, exploitation task."""
        return cls(
            seed=seed,
            ai_seeds=(0, 1),
            ai_rl_train_episodes=12,
            ai_eval_episodes=4,
            ai_tasks=("exploitation",),
            oscillatory_ticks=12,
            stability_seeds=(0, 1),
            **kw,
        )


def _verdict_dict(v: Verdict) -> dict[str, Any]:
    return v.to_dict()


def _run_active_inference(config: SuiteConfig, master_seed: int) -> dict[str, Any]:
    """Run the AIF-vs-RL benchmark with the master seed threaded in."""
    suite = envs_mod.default_suite()
    if config.ai_tasks is not None:
        by_name = {t.name: t for t in suite}
        tasks = [by_name[n] for n in config.ai_tasks if n in by_name]
    else:
        tasks = suite
    bench_cfg = BenchmarkConfig(
        seeds=config.ai_seeds,
        rl_train_episodes=config.ai_rl_train_episodes,
        rl_eval_episodes=config.ai_eval_episodes,
        aif_eval_episodes=config.ai_eval_episodes,
        verdict=VerdictConfig(alpha=config.alpha),
        master_seed=master_seed,
    )
    result = run_active_inference(tasks, bench_cfg)
    # Per-task p-values enter the family-wise correction.
    pvalues = {
        f"active_inference:{v['task']}": float(v["p_value"]) for v in result["verdicts"]
    }
    verdict = result["summary"]["verdict"]  # shared-schema dict
    return {
        "verdict": verdict,
        "pvalues": pvalues,
        "summary": result["summary"],
    }


def _stability_verdict(report: Any) -> dict[str, Any]:
    """Wrap the stability control as a PASS/FAIL verdict (PASS = seed-robust)."""
    outcome = Outcome.PASS if report.stable else Outcome.FAIL
    detail = "; ".join(report.reasons())
    return Verdict(
        outcome=outcome,
        detail=detail,
        metrics={
            "stable": report.stable,
            "cv": (None if report.cv == float("inf") else report.cv),
            "verdict_counts": dict(report.verdict_counts),
            "tolerance": report.tolerance,
        },
    ).to_dict()


def _redteam_verdict(results: list[Any]) -> dict[str, Any]:
    """Aggregate the red-team case results into a PASS/FAIL gate verdict."""
    total = len(results)
    passed = sum(1 for r in results if r.passed())
    outcome = Outcome.PASS if passed == total and total > 0 else Outcome.FAIL
    failures = [r.case_id for r in results if not r.passed()]
    return Verdict(
        outcome=outcome,
        detail=(
            f"{passed}/{total} enforcement cases blocked+logged as expected"
            + (f"; failures: {failures}" if failures else "")
        ),
        metrics={"cases": total, "passed": passed, "failures": failures},
    ).to_dict()


def run_suite(
    config: Optional[SuiteConfig] = None,
    *,
    individuation: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Run all seven experiments under one seed; return the combined report.

    ``individuation`` (optional): a result dict from
    ``kaine.evaluation.benchmarks.individuation_runner.run_individuation`` whose
    permutation p-value should join the family-wise correction. It is not one of
    the seven (it needs live samplers); when supplied its p-value is folded into
    the Holm family alongside the active-inference tasks.
    """
    config = config or SuiteConfig()
    # Opt-in determinism for the whole offline run, seeded from the master.
    set_global_seed(config.seed, deterministic=config.deterministic)

    # One child seed per experiment, independent + reproducible from the master.
    root = np.random.SeedSequence(config.seed)
    children = root.spawn(len(EXPERIMENT_NAMES))
    derived = {
        name: int(child.generate_state(1, dtype=np.uint32)[0])
        for name, child in zip(EXPERIMENT_NAMES, children)
    }

    experiments: dict[str, dict[str, Any]] = {}
    family_pvalues: dict[str, float] = {}

    # 1. Active-inference (the p-value producer).
    ai = _run_active_inference(config, derived["active_inference"])
    experiments["active_inference"] = {"verdict": ai["verdict"]}
    family_pvalues.update(ai["pvalues"])

    # 2. Oscillatory ablation.
    osc = asyncio.run(
        run_ablation(
            AblationConfig(seed=derived["oscillatory_ablation"], ticks=config.oscillatory_ticks)
        )
    )
    experiments["oscillatory_ablation"] = {"verdict": _verdict_dict(osc["verdict"])}

    # 3. A/B divergence.
    ab = asyncio.run(run_ab_divergence(ABDivergenceConfig(seed=derived["ab_divergence"])))
    experiments["ab_divergence"] = {"verdict": _verdict_dict(ab["verdict"])}

    # 4. Memory coherence.
    mem = asyncio.run(
        run_memory_coherence(MemoryCoherenceConfig(seed=derived["memory_coherence"]))
    )
    experiments["memory_coherence"] = {"verdict": _verdict_dict(mem["verdict"])}

    # 5. Self-model accuracy.
    sm = asyncio.run(run_self_model(SelfModelConfig(seed=derived["self_model"])))
    experiments["self_model"] = {"verdict": _verdict_dict(sm["verdict"])}

    # 6. Multi-seed stability (offline demonstration on the ablation runner).
    stab = run_ablation_stability(
        list(config.stability_seeds),
        ticks=config.oscillatory_ticks,
        tolerance=config.stability_tolerance,
    )
    experiments["multi_seed_stability"] = {"verdict": _stability_verdict(stab)}

    # 7. Enforcement red-team (real enforcement layer, headless).
    with tempfile.TemporaryDirectory(prefix="suite_redteam_") as work_dir:
        rt_results = asyncio.run(run_redteam(work_dir))
    experiments["enforcement_red_team"] = {"verdict": _redteam_verdict(rt_results)}

    # Optional individuation p-value into the family.
    if individuation is not None:
        family_pvalues["individuation"] = float(individuation["report"]["p_value"])
        experiments["individuation"] = {
            "verdict": _verdict_dict(individuation["verdict"])
        }

    family_wise = holm_report(family_pvalues, alpha=config.alpha)

    report = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "suite",
        "master_seed": config.seed,
        "alpha": config.alpha,
        "deterministic": config.deterministic,
        "derived_seeds": derived,
        "experiments": {
            name: experiments[name]["verdict"] for name in experiments
        },
        "family_wise": family_wise,
    }
    return report


def format_suite_report(report: dict[str, Any]) -> str:
    """Human-readable combined report: per-experiment verdicts + Holm family view."""
    lines: list[str] = []
    lines.append("Evaluation suite — seven experiments under one shared seed")
    lines.append("=" * 66)
    lines.append(
        f"master_seed={report['master_seed']} alpha={report['alpha']} "
        f"deterministic={report['deterministic']}"
    )
    lines.append("")
    lines.append(f"{'experiment':<24} {'verdict':<10} detail")
    lines.append("-" * 66)
    for name, v in report["experiments"].items():
        detail = v.get("detail", "")
        if len(detail) > 60:
            detail = detail[:57] + "..."
        lines.append(f"{name:<24} {v['outcome']:<10} {detail}")
    lines.append("-" * 66)
    fw = report["family_wise"]
    lines.append(
        f"Family-wise correction ({fw['method']}, alpha={fw['alpha']}, "
        f"n={fw['n']}):"
    )
    if fw["n"] == 0:
        lines.append("  (no p-value-producing experiments in this run)")
    for c in fw["comparisons"]:
        decision = "REJECT H0 (significant)" if c["reject"] else "fail to reject"
        lines.append(
            f"  {c['name']:<28} raw_p={c['raw_p']:.4f} holm_p={c['holm_p']:.4f} "
            f"-> {decision}"
        )
    lines.append(
        f"  any significant after correction: {fw['any_significant']}"
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(
        prog="python -m kaine.evaluation.benchmarks.suite",
        description=(
            "Shared-seed orchestrator: run all seven offline experiments under one "
            "seed and emit a combined report with per-experiment verdicts and a "
            "Holm-Bonferroni family-wise correction across the p-value experiments."
        ),
    )
    parser.add_argument("--seed", type=int, default=1234, help="the single master seed.")
    parser.add_argument(
        "--alpha", type=float, default=0.05, help="family-wise significance level."
    )
    parser.add_argument(
        "--fast",
        action="store_true",
        help="reduced subset (tiny active-inference benchmark) for a quick run.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("data/evaluation/benchmarks/suite.jsonl"),
        help="JSONL output path for the combined report.",
    )
    args = parser.parse_args(argv)

    config = (
        SuiteConfig.fast(seed=args.seed, alpha=args.alpha)
        if args.fast
        else SuiteConfig(seed=args.seed, alpha=args.alpha)
    )
    report = run_suite(config)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as fh:
        fh.write(json.dumps(report) + "\n")
    print(format_suite_report(report))
    print(f"\nCombined report written to {args.out}")
    return 0


__all__ = [
    "SuiteConfig",
    "EXPERIMENT_NAMES",
    "run_suite",
    "format_suite_report",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI seam
    import sys

    sys.exit(main())
