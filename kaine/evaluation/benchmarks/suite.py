# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared-seed suite orchestrator — the eight experiments under ONE seed.

The paper frames "one shared seed" across the experiments; this is the single entry
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
  7. enforcement red-team (the real enforcement layer vs a case battery);
  8. workspace-mediation ablation (competitive workspace vs flat fan-in — the
     paper's primary experiment; the second p-value producer via a sign test over
     per-seed coupling deltas).

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
from kaine.evaluation.benchmarks.workspace_mediation_ablation.measures import (
    sign_test_pvalue,
)
from kaine.evaluation.benchmarks.workspace_mediation_ablation.runner import (
    MediationConfig,
    run_ablation as run_workspace_mediation,
)
from kaine.evaluation.benchmarks.workspace_mediation_ablation.stimulus import (
    SOMA_SALIENT_STIMULUS,
)
from kaine.evaluation.redteam.harness import run_suite as run_redteam
from kaine.experiment.multiple_comparisons import holm_report
from kaine.experiment.seeding import set_global_seed
from kaine.experiment.verdict import Outcome, Verdict

# The eight experiments, in report order. The active-inference benchmark and the
# workspace-mediation ablation are family-wise p-value producers; the rest emit
# threshold/gate verdicts.
EXPERIMENT_NAMES = (
    "active_inference",
    "oscillatory_ablation",
    "ab_divergence",
    "memory_coherence",
    "self_model",
    "multi_seed_stability",
    "enforcement_red_team",
    "workspace_mediation",
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
    # Workspace-mediation sizing. The per-seed coupling deltas form the
    # distribution the sign-test p-value (the family contribution) is computed on,
    # so several seeds are needed for a meaningful test.
    mediation_ticks: int = 24
    mediation_seeds: tuple[int, ...] = (0, 1, 2, 3, 4)
    mediation_min_effect: float = 0.15

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
            mediation_ticks=16,
            mediation_seeds=(0, 1, 2),
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


def _mediation_aggregate_verdict(
    deltas: list[Any], pvalue: float, config: SuiteConfig
) -> Verdict:
    """Aggregate the multi-seed coupling deltas into a WIN / NULL / NEGATIVE verdict.

    WIN requires BOTH a mean delta above ``mediation_min_effect`` AND a
    sign-test p-value significant at the family alpha — competitive mediation
    increases coupling, and does so consistently across seeds, not by luck on one.
    A mean delta at or below ``-min_effect`` is NEGATIVE (adverse). Otherwise NULL
    (the fan-in prompt-assembler outcome). Undefined everywhere -> underpowered.
    """
    defined = [float(d) for d in deltas if d is not None]
    if not defined:
        return Verdict(
            outcome=Outcome.NULL,
            detail="UNDERPOWERED — coupling undefined across all seeds",
            metrics={"underpowered": True, "n_seeds": len(deltas), "pvalue": pvalue},
        )
    mean_delta = sum(defined) / len(defined)
    metrics = {
        "mean_coupling_delta": mean_delta,
        "pvalue": pvalue,
        "n_seeds": len(deltas),
        "n_defined": len(defined),
        "min_effect": config.mediation_min_effect,
        "alpha": config.alpha,
    }
    if mean_delta >= config.mediation_min_effect and pvalue <= config.alpha:
        return Verdict(
            outcome=Outcome.WIN,
            detail=(
                f"competitive mediation increases cross-module coupling "
                f"(mean delta {mean_delta:.3f} >= {config.mediation_min_effect}, "
                f"sign-test p={pvalue:.4f} <= {config.alpha}) — does work flat "
                "fan-in does not"
            ),
            metrics=metrics,
        )
    if mean_delta <= -config.mediation_min_effect:
        return Verdict(
            outcome=Outcome.NEGATIVE,
            detail=(
                f"competitive mediation REDUCES coupling (mean delta {mean_delta:.3f} "
                f"<= -{config.mediation_min_effect}) — adverse to the thesis"
            ),
            metrics=metrics,
        )
    return Verdict(
        outcome=Outcome.NULL,
        detail=(
            f"competitive mediation makes no consistent, significant change to "
            f"coupling (mean delta {mean_delta:.3f}, sign-test p={pvalue:.4f}) — "
            "the fan-in prompt-assembler outcome"
        ),
        metrics=metrics,
    )


def _run_workspace_mediation(
    config: SuiteConfig, base_seed: int
) -> dict[str, Any]:
    """Run the mediation ablation across seeds; return verdict + family p-value.

    The primary measure (``coupling_delta``) is collected per seed; the family
    contribution is the sign-test p-value that its median is > 0 (a significant,
    consistent increase in coupling). The displayed verdict is the multi-seed
    aggregate.
    """
    deltas: list[Any] = []
    for s in config.mediation_seeds:
        res = asyncio.run(
            run_workspace_mediation(
                MediationConfig(
                    seed=base_seed + int(s),
                    ticks=config.mediation_ticks,
                    min_effect=config.mediation_min_effect,
                ),
                stimulus=SOMA_SALIENT_STIMULUS,
            )
        )
        deltas.append(res["effect"]["coupling_delta"])
    pvalue = sign_test_pvalue(deltas)
    verdict = _mediation_aggregate_verdict(deltas, pvalue, config)
    return {"verdict": verdict.to_dict(), "pvalue": pvalue, "deltas": deltas}


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

    # 8. Workspace-mediation ablation — the paper's primary experiment and the
    # second family-wise p-value producer (sign-test over per-seed coupling deltas).
    wm = _run_workspace_mediation(config, derived["workspace_mediation"])
    experiments["workspace_mediation"] = {"verdict": wm["verdict"]}
    family_pvalues["workspace_mediation"] = wm["pvalue"]

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
    lines.append("Evaluation suite — eight experiments under one shared seed")
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
