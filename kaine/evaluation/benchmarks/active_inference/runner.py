# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Benchmark runner — tasks x seeds, JSONL output, summary verdict table.

For each task the runner:
  1. tunes the RL baseline's hyperparameters on *held-out* seeds and records the
     full grid (so the baseline is transparent, not strawmanned);
  2. for each evaluation seed, runs the AIF agent (driving the live Nous engine)
     and a freshly-trained Q-learning baseline, collecting per-episode returns
     and probe behaviour;
  3. computes decision quality, sample efficiency, and (on epistemic tasks) the
     value of epistemic action;
  4. classifies the per-task verdict (WIN / NULL / NEGATIVE) by a Mann–Whitney
     test across seeds, and writes one seeded, reproducible JSONL record per
     (task, seed, agent) plus a per-task verdict record;
  5. aggregates a suite verdict.

Everything is OFFLINE and synthetic: no bus, no intents, no entity, no cognitive
cycle. Re-running with the same seed set reproduces the verdicts.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np

from kaine.evaluation.benchmarks import write_jsonl
from kaine.evaluation.benchmarks.active_inference import envs as envs_mod
from kaine.evaluation.benchmarks.active_inference.aif_agent import AIFAgent
from kaine.evaluation.benchmarks.active_inference.envs import DiscretePOMDP
from kaine.evaluation.benchmarks.active_inference.metrics import (
    NEGATIVE,
    NULL,
    WIN,
    VerdictConfig,
    aggregate_verdict,
    classify_verdict,
    cumulative_regret,
    decision_quality,
    epistemic_value,
    steps_to_competence,
)
from kaine.evaluation.benchmarks.active_inference.rl_baseline import (
    QLearningConfig,
    train_q_agent,
    tune_hyperparameters,
)
from kaine.experiment.verdict import Outcome, Verdict

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class BenchmarkConfig:
    """Runner parameters (all seeded for reproducibility)."""

    seeds: tuple[int, ...] = (0, 1, 2, 3, 4, 5, 6, 7)
    rl_train_episodes: int = 800
    rl_eval_episodes: int = 100
    aif_eval_episodes: int = 100
    tune_holdout_seeds: tuple[int, ...] = (1001, 1002, 1003)
    tune_train_episodes: int = 400
    tune_eval_episodes: int = 50
    verdict: VerdictConfig = field(default_factory=VerdictConfig)
    # When the shared-seed suite orchestrator runs the benchmark it passes a
    # ``master_seed`` derived from the suite's single seed (via SeedSequence.spawn);
    # each per-seed env/RL rng is then derived from (master_seed, eval_seed) so the
    # benchmark's stream is a reproducible function of the MASTER seed instead of
    # an independent ``default_rng(eval_seed)``. ``None`` (standalone runs) keeps
    # the historical behaviour: the eval seed drives the rng directly.
    master_seed: Optional[int] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "seeds": list(self.seeds),
            "rl_train_episodes": self.rl_train_episodes,
            "rl_eval_episodes": self.rl_eval_episodes,
            "aif_eval_episodes": self.aif_eval_episodes,
            "tune_holdout_seeds": list(self.tune_holdout_seeds),
            "tune_train_episodes": self.tune_train_episodes,
            "tune_eval_episodes": self.tune_eval_episodes,
            "master_seed": self.master_seed,
            "verdict": self.verdict.as_dict(),
        }


def derive_seed(master_seed: Optional[int], seed: int) -> int:
    """Derive an independent-but-reproducible integer seed from a master seed.

    Uses ``numpy.random.SeedSequence([master_seed, seed]).spawn`` semantics: the
    child stream is reproducible given the master and independent across ``seed``
    values. When ``master_seed`` is ``None`` the eval ``seed`` is returned
    unchanged (standalone runs stay bit-identical to their historical behaviour).
    """
    if master_seed is None:
        return int(seed)
    child = np.random.SeedSequence([int(master_seed), int(seed)])
    return int(child.generate_state(1, dtype=np.uint32)[0])


def _run_aif_seed(
    task: DiscretePOMDP,
    aif_agent: AIFAgent,
    seed: int,
    eval_episodes: int,
) -> dict[str, Any]:
    """Run the AIF agent on a task for one seed, collecting eval returns/probe.

    The agent (and its live engine) is reused across seeds; only the env RNG is
    re-seeded, so the AIF decision policy is deterministic given the model and
    the observation stream. Belief is reset at each episode boundary.
    """
    rng = np.random.default_rng(seed)
    returns: list[float] = []
    probe_flags: list[bool] = []
    probe_steps: list[int] = []
    for _ in range(eval_episodes):
        obs = task.reset(rng)
        aif_agent.reset_belief()
        total = 0.0
        probed = False
        probe_step: Optional[int] = None
        step = 0
        done = False
        while not done:
            action = aif_agent.act(obs)
            obs, reward, done, info = task.step(action)
            total += reward
            if info.get("is_probe") and not probed:
                probed = True
                probe_step = step
            step += 1
        returns.append(total)
        probe_flags.append(probed)
        if probe_step is not None:
            probe_steps.append(probe_step)
    return {
        "eval_returns": returns,
        "probe_rate": float(np.mean(probe_flags)) if probe_flags else 0.0,
        "mean_probe_step": float(np.mean(probe_steps)) if probe_steps else None,
    }


def run_task(
    task: DiscretePOMDP,
    config: BenchmarkConfig,
    *,
    records_out: list[dict[str, Any]],
) -> dict[str, Any]:
    """Run one task across all seeds; return the per-task verdict record.

    Appends per-(seed, agent) JSONL records to ``records_out`` plus the verdict
    record. Both agents see the same env reward and observation model; the AIF
    preference ``C`` encodes the same reward (disclosed in ``reward_matching``).
    """
    # Per-task timestamp (deliberate): each task's records share one ``ts`` while
    # the suite summary stamps its own, so a multi-task run's records carry the
    # task they belong to rather than one suite-wide instant.
    ts = datetime.now(timezone.utc).isoformat()
    is_epistemic = envs_mod.is_epistemic(task)
    optimal = task.optimal_return()
    matching = task.reward_matching()

    # 1. Tune the RL baseline on held-out seeds (recorded, not hidden).
    log.info("tuning RL baseline for task %s", task.name)
    best_cfg, grid_record = tune_hyperparameters(
        task,
        holdout_seeds=config.tune_holdout_seeds,
        train_episodes=config.tune_train_episodes,
        eval_episodes=config.tune_eval_episodes,
    )

    # 2. Build the AIF agent once (live engine), reuse across seeds.
    aif_agent = AIFAgent(task)

    aif_scores: list[float] = []
    rl_scores: list[float] = []
    aif_probe_rates: list[float] = []
    rl_probe_rates: list[float] = []
    aif_probe_steps: list[float] = []
    rl_probe_steps: list[float] = []
    rl_steps_to_competence: list[Optional[int]] = []
    aif_regret: list[float] = []
    rl_regret: list[float] = []

    try:
        for seed in config.seeds:
            # Derive this seed's env/RL rng from the master seed when the suite
            # orchestrator set one; else the eval seed drives the rng directly.
            rng_seed = derive_seed(config.master_seed, seed)
            # --- AIF (no learning episodes; competent from the model) ---------
            aif_rec = _run_aif_seed(task, aif_agent, rng_seed, config.aif_eval_episodes)
            aif_dq = decision_quality(aif_rec["eval_returns"])
            aif_scores.append(aif_dq["mean"])
            aif_probe_rates.append(aif_rec["probe_rate"])
            if aif_rec["mean_probe_step"] is not None:
                aif_probe_steps.append(aif_rec["mean_probe_step"])
            aif_regret.append(cumulative_regret(aif_rec["eval_returns"], optimal))
            records_out.append(
                {
                    "ts": ts,
                    "kind": "run",
                    "task": task.name,
                    "epistemic": is_epistemic,
                    "agent": "aif",
                    "seed": seed,
                    "reward_matching": matching,
                    "hyperparameters": {"policy_len": getattr(task, "policy_len", 1)},
                    "eval_returns": aif_rec["eval_returns"],
                    "decision_quality": aif_dq,
                    "steps_to_competence": 0,  # competent from the generative model
                    "cumulative_regret": aif_regret[-1],
                    "probe_rate": aif_rec["probe_rate"],
                    "mean_probe_step": aif_rec["mean_probe_step"],
                    "optimal_return": optimal,
                }
            )

            # --- RL baseline (train then greedy-eval) -------------------------
            rl_rec = train_q_agent(
                task,
                best_cfg,
                seed=rng_seed,
                train_episodes=config.rl_train_episodes,
                eval_episodes=config.rl_eval_episodes,
            )
            rl_dq = decision_quality(rl_rec["eval_returns"])
            rl_scores.append(rl_dq["mean"])
            rl_probe_rates.append(rl_rec["probe_rate"])
            if rl_rec["mean_probe_step"] is not None:
                rl_probe_steps.append(rl_rec["mean_probe_step"])
            stc = steps_to_competence(rl_rec["train_returns"], optimal)
            rl_steps_to_competence.append(stc)
            rl_regret.append(cumulative_regret(rl_rec["eval_returns"], optimal))
            records_out.append(
                {
                    "ts": ts,
                    "kind": "run",
                    "task": task.name,
                    "epistemic": is_epistemic,
                    "agent": "rl",
                    "seed": seed,
                    "reward_matching": matching,
                    "hyperparameters": rl_rec["hyperparameters"],
                    "eval_returns": rl_rec["eval_returns"],
                    "decision_quality": rl_dq,
                    "steps_to_competence": stc,
                    "cumulative_regret": rl_regret[-1],
                    "probe_rate": rl_rec["probe_rate"],
                    "mean_probe_step": rl_rec["mean_probe_step"],
                    "optimal_return": optimal,
                }
            )
    finally:
        aif_agent.close()

    # 3. Verdict across seeds.
    verdict = classify_verdict(aif_scores, rl_scores, config.verdict)

    epi: Optional[dict[str, Any]] = None
    if is_epistemic:
        epi = epistemic_value(
            aif_probe_rate=float(np.mean(aif_probe_rates)) if aif_probe_rates else 0.0,
            rl_probe_rate=float(np.mean(rl_probe_rates)) if rl_probe_rates else 0.0,
            aif_mean_probe_step=float(np.mean(aif_probe_steps)) if aif_probe_steps else None,
            rl_mean_probe_step=float(np.mean(rl_probe_steps)) if rl_probe_steps else None,
        )

    verdict_record = {
        "ts": ts,
        "kind": "verdict",
        "task": task.name,
        "epistemic": is_epistemic,
        "verdict": verdict["verdict"],
        "p_value": verdict["p_value"],
        "effect_size_r": verdict["effect_size_r"],
        "mean_aif": verdict["mean_aif"],
        "mean_rl": verdict["mean_rl"],
        "delta": verdict["delta"],
        "optimal_return": optimal,
        "rl_steps_to_competence": rl_steps_to_competence,
        "aif_cumulative_regret_mean": float(np.mean(aif_regret)) if aif_regret else 0.0,
        "rl_cumulative_regret_mean": float(np.mean(rl_regret)) if rl_regret else 0.0,
        "epistemic_value": epi,
        "rl_hyperparameters": best_cfg.as_dict(),
        "rl_tuning_grid": grid_record,
        "reward_matching": matching,
        "n_seeds": len(config.seeds),
        # Shared cross-experiment verdict schema (experiment-run-identity). The
        # legacy string `verdict` key above is preserved for existing consumers;
        # `shared_verdict` is the canonical object every experiment now emits.
        "shared_verdict": Verdict(
            outcome=Outcome(verdict["verdict"]),
            detail=f"AIF vs RL on {task.name}",
            metrics={
                "p_value": verdict["p_value"],
                "effect_size_r": verdict["effect_size_r"],
                "mean_aif": verdict["mean_aif"],
                "mean_rl": verdict["mean_rl"],
                "delta": verdict["delta"],
            },
        ).to_dict(),
    }
    records_out.append(verdict_record)
    return verdict_record


def run_suite(
    tasks: Optional[list[DiscretePOMDP]] = None,
    config: Optional[BenchmarkConfig] = None,
) -> dict[str, Any]:
    """Run the whole suite; return a result dict with all JSONL records + summary."""
    tasks = tasks if tasks is not None else envs_mod.default_suite()
    config = config or BenchmarkConfig()
    records: list[dict[str, Any]] = []
    verdicts: list[dict[str, Any]] = []
    for task in tasks:
        v = run_task(task, config, records_out=records)
        verdicts.append(v)
    suite_verdict = aggregate_verdict([v["verdict"] for v in verdicts])
    summary = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": "suite",
        "suite_verdict": suite_verdict,
        # Shared cross-experiment verdict schema (experiment-run-identity).
        "verdict": Verdict(
            outcome=Outcome(suite_verdict),
            detail="AIF (Nous active inference) vs RL (tabular Q-learning) suite",
            metrics={"n_tasks": len(verdicts)},
        ).to_dict(),
        "per_task": [
            {
                "task": v["task"],
                "epistemic": v["epistemic"],
                "verdict": v["verdict"],
                "mean_aif": v["mean_aif"],
                "mean_rl": v["mean_rl"],
                "p_value": v["p_value"],
                "effect_size_r": v["effect_size_r"],
            }
            for v in verdicts
        ],
        "config": config.as_dict(),
    }
    records.append(summary)
    return {"records": records, "summary": summary, "verdicts": verdicts}


def format_summary_table(result: dict[str, Any]) -> str:
    """Human-readable summary table; states NULL/NEGATIVE plainly."""
    summary = result["summary"]
    lines: list[str] = []
    lines.append("AIF (Nous active inference) vs RL (tabular Q-learning) benchmark")
    lines.append("=" * 70)
    header = f"{'task':<20} {'epistemic':<10} {'AIF':>8} {'RL':>8} {'p':>8} {'effect':>8}  verdict"
    lines.append(header)
    lines.append("-" * len(header))
    for row in summary["per_task"]:
        lines.append(
            f"{row['task']:<20} {str(bool(row['epistemic'])):<10} "
            f"{row['mean_aif']:>8.3f} {row['mean_rl']:>8.3f} "
            f"{row['p_value']:>8.3f} {row['effect_size_r']:>8.3f}  {row['verdict']}"
        )
    lines.append("-" * len(header))
    sv = summary["suite_verdict"]
    lines.append(f"SUITE VERDICT: {sv}")
    if sv == NULL:
        lines.append(
            "  NULL = AIF statistically matches the baseline (or a mixed suite). "
            "This is a reportable result, not a harness failure."
        )
    elif sv == NEGATIVE:
        lines.append(
            "  NEGATIVE = AIF underperforms the baseline. Reportable: it would "
            "motivate the complementary reasoning module (paper §6.3)."
        )
    else:
        lines.append(
            "  WIN = AIF beats the baseline beyond the significance + effect-size "
            "floor on every task with no negative."
        )
    return "\n".join(lines)


__all__ = [
    "BenchmarkConfig",
    "derive_seed",
    "run_task",
    "run_suite",
    "write_jsonl",
    "format_summary_table",
]
