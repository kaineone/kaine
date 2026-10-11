# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Record golden fixtures from the pymdp Nous engine for the NumPy backend.

This script runs only where ``pymdp`` and ``JAX`` are installed. It records
deterministic JSON fixtures under ``tests/fixtures/nous_golden/`` from:

1. ``build_generative_model`` at horizon 1, learning on (60 fixed obs steps).
2. The same live model at horizon 2 (10 fixed obs steps).
3. The benchmark tasks ``ExploitationPOMDP`` and ``TMazeEpistemicPOMDP``
   (20 random valid observations each, starting from the generative prior).

Re-recording is a deliberate operator step. Run as::

    python scripts/record_nous_golden.py [--out DIR]

Every generated observation is written into the fixture, and all float values
are serialized by ``json.dump`` with full Python-float precision.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Record pymdp Nous golden fixtures for the NumPy engine."
    )
    parser.add_argument(
        "--out",
        default="tests/fixtures/nous_golden",
        help="Directory to write the JSON fixtures (default: tests/fixtures/nous_golden).",
    )
    return parser.parse_args()


def _model_to_dict(model: Any, engine: Any) -> dict[str, Any]:
    """Serialize a GenerativeModel plus engine parameters needed for replay."""
    out: dict[str, Any] = {
        "A": [np.asarray(a).tolist() for a in model.A],
        "B": [np.asarray(b).tolist() for b in model.B],
        "C": [np.asarray(c).tolist() for c in model.C],
        "D": [np.asarray(d).tolist() for d in model.D],
        "A_dependencies": [list(dep) for dep in model.A_dependencies],
        "num_states": [int(n) for n in model.num_states],
        "num_obs": [int(n) for n in model.num_obs],
        "actions": list(model.actions),
        "policy_len": int(engine.policy_len),
        "num_iter": int(engine._num_iter),
    }

    pB = getattr(model, "pB", None)
    if pB is not None:
        out["pB"] = [np.asarray(pb).tolist() for pb in pB]
    else:
        out["pB"] = None

    bad = getattr(model, "B_action_dependencies", None)
    if bad is not None:
        out["B_action_dependencies"] = [list(dep) for dep in bad]

    if hasattr(model, "transition_max_concentration"):
        out["transition_max_concentration"] = float(model.transition_max_concentration)

    return out


def _policies_to_nested(engine: Any) -> Any:
    """Return the engine's cached policy_arr as nested ints, or None."""
    if engine._policies is None:
        return None
    arr = np.asarray(engine._policies)
    return arr.astype(int).tolist()


def _per_policy_neg_efe(engine: Any, obs: list[int], prior: Any, jnp: Any) -> list[float]:
    """Read the per-policy negative EFE by calling the jitted cycle directly."""
    obs_batched = [jnp.array([int(o)]) for o in obs]
    _, neg_efe = engine._jit_cycle(engine._agent, obs_batched, prior)
    return np.asarray(neg_efe).reshape(-1).tolist()


def _record_step(
    engine: Any,
    obs: list[int],
    jnp: Any,
    *,
    learning: bool,
    reset_prior: bool = False,
) -> dict[str, Any]:
    """Record one inference step, optionally resetting the prior first."""
    if reset_prior:
        engine._prior = list(engine._agent.D)

    per_policy_neg_efe = _per_policy_neg_efe(engine, obs, engine._prior, jnp)
    result = engine.infer(obs)

    record: dict[str, Any] = {
        "obs": obs,
        "posterior": result.posterior,
        "per_policy_neg_efe": per_policy_neg_efe,
        "policy_efe": result.policy_efe,
        "action_index": int(result.action_index),
        "pB_after": None,
        "carried_prior_after": None,
    }

    if learning:
        ls = engine.learned_state()
        record["pB_after"] = ls.get("pB")
        record["carried_prior_after"] = ls.get("carried_prior")

    return record


def _record_live_trajectory(
    engine: Any, rng: np.random.Generator, n: int, rule_switch: int, jnp: Any
) -> list[dict[str, Any]]:
    """Record a deterministic live-model trajectory with salience conditioning."""
    model = engine.model
    num_obs = model.num_obs
    steps: list[dict[str, Any]] = []
    prev_action = 0

    for i in range(n):
        if i < rule_switch:
            if prev_action == 1:
                salience = 2
            elif prev_action == 3:
                salience = 0
            else:
                salience = 1
        else:
            salience = int(rng.integers(0, num_obs[1]))

        affect = int(rng.integers(0, num_obs[2]))
        event = int(rng.integers(0, num_obs[3]))
        obs = [int(prev_action), salience, affect, event]

        step = _record_step(engine, obs, jnp, learning=True)
        steps.append(step)
        prev_action = int(step["action_index"])

    return steps


def _record_benchmark_samples(
    engine: Any, rng: np.random.Generator, n: int, jnp: Any
) -> list[dict[str, Any]]:
    """Record ``n`` independent inference samples, each starting from ``D``."""
    num_modalities = len(engine.model.num_obs)
    samples: list[dict[str, Any]] = []

    for _ in range(n):
        obs = [int(rng.integers(0, engine.model.num_obs[m])) for m in range(num_modalities)]
        sample = _record_step(engine, obs, jnp, learning=False, reset_prior=True)
        samples.append(sample)

    return samples


def _write_fixture(path: Path, fixture: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(fixture, f, ensure_ascii=False)


def _file_size_kb(path: Path) -> float:
    return path.stat().st_size / 1024.0


def main() -> None:
    args = _parse_args()
    out_dir = Path(args.out)

    try:
        import jax
        import jax.numpy as jnp
        import pymdp
    except ImportError as exc:
        print(f"Skipping golden recording (pymdp/JAX unavailable): {exc}", file=sys.stderr)
        sys.exit(0)

    from kaine.evaluation.benchmarks.active_inference.aif_agent import build_model_for_env
    from kaine.evaluation.benchmarks.active_inference.envs import (
        ExploitationPOMDP,
        TMazeEpistemicPOMDP,
    )
    from kaine.modules.nous.engine import PymdpEngine
    from kaine.modules.nous.generative_model import build_generative_model

    rng = np.random.default_rng(20260927)

    meta_base = {
        "pymdp_version": getattr(pymdp, "__version__", "unknown"),
        "jax_version": getattr(jax, "__version__", "unknown"),
        "recorded_by": "scripts/record_nous_golden.py",
        "fixture_version": 1,
    }

    # -----------------------------------------------------------------------
    # Fixture 1: live model, horizon 1, learning, 60 steps
    # -----------------------------------------------------------------------
    model_live = build_generative_model()
    engine_live = PymdpEngine(model_live, efe_timeout_ms=60000, policy_len=1)
    live_steps = _record_live_trajectory(engine_live, rng, n=60, rule_switch=40, jnp=jnp)
    fixture_live = {
        "meta": meta_base,
        "model": _model_to_dict(model_live, engine_live),
        "policies": _policies_to_nested(engine_live),
        "steps": live_steps,
    }
    live_path = out_dir / "live_learning.json"
    _write_fixture(live_path, fixture_live)
    print(
        f"live_learning.json: {len(live_steps)} steps, "
        f"{_file_size_kb(live_path):.1f} KB"
    )

    # -----------------------------------------------------------------------
    # Fixture 2: live model, horizon 2, 10 steps
    # -----------------------------------------------------------------------
    model_horizon = build_generative_model()
    engine_horizon = PymdpEngine(model_horizon, efe_timeout_ms=60000, policy_len=2)
    horizon_steps = _record_live_trajectory(
        engine_horizon, rng, n=10, rule_switch=10, jnp=jnp
    )
    fixture_horizon = {
        "meta": meta_base,
        "model": _model_to_dict(model_horizon, engine_horizon),
        "policies": _policies_to_nested(engine_horizon),
        "steps": horizon_steps,
    }
    horizon_path = out_dir / "live_horizon2.json"
    _write_fixture(horizon_path, fixture_horizon)
    print(
        f"live_horizon2.json: {len(horizon_steps)} steps, "
        f"{_file_size_kb(horizon_path):.1f} KB"
    )

    # -----------------------------------------------------------------------
    # Fixture 3: benchmark tasks, 20 samples each
    # -----------------------------------------------------------------------
    benchmark_tasks: dict[str, Any] = {}
    for task in (ExploitationPOMDP(), TMazeEpistemicPOMDP()):
        task_model = build_model_for_env(task)
        task_engine = PymdpEngine(
            task_model, efe_timeout_ms=60000, policy_len=task.policy_len
        )
        samples = _record_benchmark_samples(task_engine, rng, n=20, jnp=jnp)
        benchmark_tasks[task.name] = {
            "model": _model_to_dict(task_model, task_engine),
            "policies": _policies_to_nested(task_engine),
            "samples": samples,
        }

    fixture_benchmark = {
        "meta": meta_base,
        "tasks": benchmark_tasks,
    }
    benchmark_path = out_dir / "benchmark_tasks.json"
    _write_fixture(benchmark_path, fixture_benchmark)
    total_samples = sum(len(t["samples"]) for t in benchmark_tasks.values())
    print(
        f"benchmark_tasks.json: {total_samples} samples, "
        f"{_file_size_kb(benchmark_path):.1f} KB"
    )


if __name__ == "__main__":
    main()
