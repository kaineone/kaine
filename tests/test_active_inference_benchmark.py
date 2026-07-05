# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the offline AIF-vs-RL benchmark.

The fast tests (envs, RL baseline, verdict classifier, offline/no-boot
guarantee) run in every green build. A small opt-in section drives the *real*
pymdp engine through the AIF adapter and is skipped unless the reasoning extra
(pymdp/jax) is installed — that section proves the harness actually exercises
active inference (the EFE agent provably out-info-seeks a no-exploration
baseline), not a mock.
"""
from __future__ import annotations

import numpy as np
import pytest

from kaine.evaluation.benchmarks.active_inference.envs import (
    ExploitationPOMDP,
    TMazeEpistemicPOMDP,
    default_suite,
    is_epistemic,
)
from kaine.evaluation.benchmarks.active_inference.metrics import (
    NEGATIVE,
    NULL,
    WIN,
    VerdictConfig,
    aggregate_verdict,
    classify_verdict,
    cumulative_regret,
    rank_biserial,
    steps_to_competence,
)
from kaine.evaluation.benchmarks.active_inference.rl_baseline import (
    QLearningConfig,
    run_episode,
    train_q_agent,
)
from kaine.evaluation.benchmarks.active_inference.runner import derive_seed


# ---------------------------------------------------------------------------
# Environments
# ---------------------------------------------------------------------------


def test_default_suite_has_epistemic_and_exploitation():
    suite = default_suite()
    assert any(is_epistemic(t) for t in suite), "suite must include an epistemic task"
    assert any(not is_epistemic(t) for t in suite), "suite must include an exploitation task"


def test_tmaze_generative_tensors_are_valid_distributions():
    task = TMazeEpistemicPOMDP()
    # A columns (per modality) sum to 1 over the observation axis.
    for a in task.A:
        sums = a.sum(axis=0)
        assert np.allclose(sums, 1.0), "A must be a proper likelihood"
    # B columns sum to 1 over next-state axis, per action slice.
    for b in task.B:
        sums = b.sum(axis=0)
        assert np.allclose(sums, 1.0), "B must be a proper transition"
    for d in task.D:
        assert np.isclose(d.sum(), 1.0)


def test_tmaze_requires_probe_to_win_reliably():
    # An oracle that probes the cue then commits beats blind commitment.
    task = TMazeEpistemicPOMDP(cue_validity=0.98)
    assert task.optimal_return() > 0.9
    # Blind commitment (always go to an arm) is a 50/50 over the +1/-1 swing ~ 0.
    rng = np.random.default_rng(0)
    blind = []
    for _ in range(200):
        task.reset(rng)
        # straight to middle then left arm, no cue
        _o, _r, done, _i = task.step(task.MIDDLE)
        o, r, done, info = task.step(task.LEFT)
        blind.append(r)
    assert abs(np.mean(blind)) < 0.3, "blind commitment should be ~chance"


def test_exploitation_optimal_mapping_is_solvable_without_probing():
    task = ExploitationPOMDP(n=3, obs_noise=0.0)
    rng = np.random.default_rng(0)
    # Acting on the observed context perfectly should achieve optimal return.
    wins = 0
    N = 300
    for _ in range(N):
        obs = task.reset(rng)
        ctx_obs = obs[0]
        _o, r, _done, _info = task.step(ctx_obs)
        wins += r > 0
    assert wins / N > 0.99, "fully-observed exploitation is solvable by obs->action"
    assert task.probe_action is None


def test_env_step_after_done_raises():
    task = ExploitationPOMDP()
    rng = np.random.default_rng(0)
    task.reset(rng)
    task.step(0)
    with pytest.raises(RuntimeError):
        task.step(0)


def test_env_parameterisation_sensitivity_axes():
    # Noise / horizon / info-cost are all parameterisable (sensitivity runs).
    t = TMazeEpistemicPOMDP(cue_validity=0.9, horizon=6, step_cost=0.05, obs_noise=0.1)
    assert t.horizon == 6
    assert t.step_cost == 0.05
    assert 0.0 <= t.obs_noise < 0.5
    e = ExploitationPOMDP(n=5, obs_noise=0.2)
    assert e.num_actions() == 5


# ---------------------------------------------------------------------------
# RL baseline
# ---------------------------------------------------------------------------


def test_qlearning_learns_exploitation():
    task = ExploitationPOMDP(n=3, obs_noise=0.0)
    rec = train_q_agent(
        task,
        QLearningConfig(alpha=0.2, gamma=0.95, epsilon_decay=0.99),
        seed=0,
        train_episodes=600,
        eval_episodes=100,
    )
    # A trained tabular learner solves the fully-observed mapping near-optimally.
    assert np.mean(rec["eval_returns"]) > 0.85


def test_qlearning_deterministic_under_seed():
    task = ExploitationPOMDP()
    cfg = QLearningConfig()
    r1 = train_q_agent(task, cfg, seed=7, train_episodes=100, eval_episodes=20)
    r2 = train_q_agent(task, cfg, seed=7, train_episodes=100, eval_episodes=20)
    assert r1["eval_returns"] == r2["eval_returns"]


def test_qlearning_zero_epsilon_does_not_probe_tmaze():
    # A no-exploration (epsilon=0) Q-learner that starts with a zero Q-table
    # breaks ties randomly and almost never *systematically* seeks the cue. This
    # is the no-exploration baseline the AIF agent is compared against.
    task = TMazeEpistemicPOMDP(cue_validity=0.98)
    cfg = QLearningConfig(epsilon_start=0.0, epsilon_min=0.0)
    from kaine.evaluation.benchmarks.active_inference.rl_baseline import QLearningAgent

    rng = np.random.default_rng(0)
    agent = QLearningAgent(task, cfg, rng)
    probe_rate = np.mean(
        [run_episode(task, agent, rng, train=False)[1]["probed"] for _ in range(200)]
    )
    # With no value signal and no exploration it does not reliably probe.
    assert probe_rate < 0.6


# ---------------------------------------------------------------------------
# Verdict classifier — WIN / NULL / NEGATIVE boundaries
# ---------------------------------------------------------------------------


def test_verdict_win_on_clearly_separated_distributions():
    aif = [1.0, 1.0, 0.98, 1.0, 0.99, 1.0, 0.97, 1.0]
    rl = [0.0, 0.1, -0.05, 0.05, 0.0, -0.1, 0.02, 0.0]
    v = classify_verdict(aif, rl)
    assert v["verdict"] == WIN
    assert v["p_value"] < 0.05
    assert v["effect_size_r"] > 0.3


def test_verdict_negative_when_aif_clearly_lower():
    aif = [0.0, 0.1, -0.05, 0.05, 0.0, -0.1, 0.02, 0.0]
    rl = [1.0, 1.0, 0.98, 1.0, 0.99, 1.0, 0.97, 1.0]
    v = classify_verdict(aif, rl)
    assert v["verdict"] == NEGATIVE
    assert v["effect_size_r"] < -0.3


def test_verdict_null_on_overlapping_distributions():
    rng = np.random.default_rng(0)
    aif = list(rng.normal(0.5, 0.1, 12))
    rl = list(rng.normal(0.5, 0.1, 12))
    v = classify_verdict(aif, rl)
    assert v["verdict"] == NULL


def test_verdict_null_on_identical_constant_distributions():
    aif = [0.5] * 8
    rl = [0.5] * 8
    v = classify_verdict(aif, rl)
    assert v["verdict"] == NULL
    assert v["p_value"] == 1.0


def test_verdict_significant_but_tiny_effect_is_null():
    # Significant by p-value but a small effect size must NOT be a WIN: the
    # min-effect floor keeps practically-negligible separations as NULL.
    aif = [0.51, 0.52, 0.50, 0.515, 0.505, 0.52, 0.51, 0.50]
    rl = [0.50, 0.50, 0.49, 0.50, 0.495, 0.50, 0.50, 0.49]
    v = classify_verdict(aif, rl, VerdictConfig(alpha=0.05, min_effect=0.95))
    assert v["verdict"] == NULL


def test_rank_biserial_sign_and_range():
    a = np.array([3.0, 4.0, 5.0])
    b = np.array([0.0, 1.0, 2.0])
    from scipy import stats

    u, _p = stats.mannwhitneyu(a, b, alternative="two-sided")
    r = rank_biserial(a, b, float(u))
    assert r == pytest.approx(1.0)  # a strictly dominates b


def test_aggregate_verdict_rules():
    assert aggregate_verdict([WIN, WIN]) == WIN
    assert aggregate_verdict([WIN, NULL]) == WIN
    assert aggregate_verdict([NEGATIVE, NULL]) == NEGATIVE
    assert aggregate_verdict([WIN, NEGATIVE]) == NULL  # mixed -> reported as null
    assert aggregate_verdict([NULL, NULL]) == NULL


def test_steps_to_competence_and_regret():
    # A learning curve that ramps to optimal returns a finite step count.
    curve = [0.0] * 30 + [1.0] * 30
    stc = steps_to_competence(curve, optimal_return=1.0, fraction=0.8, window=10)
    assert stc is not None and stc >= 30
    # A curve that never reaches threshold returns None.
    assert steps_to_competence([0.0] * 40, optimal_return=1.0) is None
    assert cumulative_regret([0.9, 0.9], optimal_return=1.0) == pytest.approx(0.2)


# ---------------------------------------------------------------------------
# Master-seed derivation (shared-seed suite threading)
# ---------------------------------------------------------------------------


def test_derive_seed_none_master_returns_seed_unchanged():
    """With no master seed the eval seed drives the rng directly, so standalone
    runs stay bit-identical to their historical behaviour."""
    assert derive_seed(None, 5) == 5
    assert derive_seed(None, 0) == 0


def test_derive_seed_is_deterministic_function_of_master():
    """Same (master, seed) -> same derived seed (SeedSequence is pure)."""
    assert derive_seed(1234, 3) == derive_seed(1234, 3)
    assert derive_seed(7, 0) == derive_seed(7, 0)


def test_derive_seed_differs_across_master_seeds():
    """A different master seed yields a different derived stream for the same
    eval seed — so the master seed genuinely perturbs the benchmark, and two
    eval seeds under one master are independent."""
    assert derive_seed(1, 3) != derive_seed(2, 3)
    assert derive_seed(1234, 0) != derive_seed(1234, 1)


# ---------------------------------------------------------------------------
# Offline / no-boot guarantee
# ---------------------------------------------------------------------------


def test_benchmark_source_does_not_reference_live_system_apis():
    """The benchmark's own source must not touch the bus, the entity, the Nous
    module, or a running cognitive cycle.

    The AIF adapter deliberately reuses the live pymdp *engine* construction
    path (``generative_model`` + ``PymdpEngine``), so the Nous package's
    ``__init__`` transitively imports type/protocol modules — importing
    dataclasses/protocols is not "starting a cognitive cycle". The meaningful
    offline guarantee is that *the benchmark code itself* never connects a bus,
    constructs a ``Nous`` module, or boots/starts a cycle or entity. This asserts
    that on every benchmark source file.
    """
    import inspect

    from kaine.evaluation.benchmarks.active_inference import (
        aif_agent,
        envs,
        metrics,
        rl_baseline,
        runner,
    )
    from kaine.evaluation.benchmarks.active_inference import __main__ as cli

    forbidden = (
        "EventBus",
        "BusClient",
        "CognitiveCycle",
        "CycleEngine",
        "start_entity",
        ".boot(",
        "import kaine.bus",
        "from kaine.bus",
        "import kaine.entity",
        "from kaine.entity",
        # constructing the live Nous *module* (the engine alone is allowed)
        "Nous(",
        "import Nous",
    )
    for mod in (envs, rl_baseline, metrics, aif_agent, runner, cli):
        src = inspect.getsource(mod)
        for token in forbidden:
            assert token not in src, f"{mod.__name__} references forbidden {token!r}"


def test_aif_adapter_only_imports_engine_not_module():
    """The AIF adapter imports the engine + generative model, never the Nous
    module (which is what wires the bus). Pure engine reuse, no live wiring."""
    import inspect

    from kaine.evaluation.benchmarks.active_inference import aif_agent

    src = inspect.getsource(aif_agent)
    assert "from kaine.modules.nous.engine import" in src
    assert "from kaine.modules.nous.generative_model import" in src
    assert "kaine.modules.nous.module" not in src


# ---------------------------------------------------------------------------
# Opt-in real-pymdp tests — prove the harness exercises active inference.
# ---------------------------------------------------------------------------


def _pymdp_available() -> bool:
    try:
        import jax  # noqa: F401
        import pymdp  # noqa: F401

        return True
    except Exception:
        return False


pytestmark_real = pytest.mark.skipif(
    not _pymdp_available(), reason="reasoning extra (pymdp/jax) not installed"
)


@pytestmark_real
def test_aif_agent_reuses_live_pymdp_engine():
    from kaine.evaluation.benchmarks.active_inference.aif_agent import AIFAgent
    from kaine.modules.nous.engine import PymdpEngine

    task = ExploitationPOMDP()
    agent = AIFAgent(task)
    try:
        # The adapter drives the *live* PymdpEngine, not a private reimpl.
        assert isinstance(agent._engine, PymdpEngine)
    finally:
        agent.close()


@pytestmark_real
def test_aif_agent_solves_exploitation():
    from kaine.evaluation.benchmarks.active_inference.aif_agent import AIFAgent

    task = ExploitationPOMDP(n=3, obs_noise=0.02)
    agent = AIFAgent(task)
    try:
        rng = np.random.default_rng(0)
        correct = 0
        N = 80
        for _ in range(N):
            obs = task.reset(rng)
            agent.reset_belief()
            a = agent.act(obs)
            _o, r, _done, _info = task.step(a)
            correct += r > 0
        assert correct / N > 0.85, "AIF should solve the fully-observed mapping"
    finally:
        agent.close()


@pytestmark_real
def test_aif_provably_outprobes_no_exploration_baseline_on_epistemic_task():
    """The harness exercises real active inference, not a mock.

    On the epistemic T-maze, a correctly-wired EFE agent (driving the live Nous
    engine) probes the cue far more reliably than an epsilon=0 Q-learner, and
    its info-seeking measurably improves its return. If the AIF path were a mock
    (no real EFE epistemic term), it could not produce this gap.
    """
    from kaine.evaluation.benchmarks.active_inference.aif_agent import AIFAgent
    from kaine.evaluation.benchmarks.active_inference.rl_baseline import (
        QLearningAgent,
        QLearningConfig,
    )

    task = TMazeEpistemicPOMDP(cue_validity=0.98)
    rng = np.random.default_rng(0)

    # --- AIF agent: measure probe rate + return ---------------------------
    aif = AIFAgent(task)
    try:
        aif_returns = []
        aif_probe = []
        for _ in range(40):
            obs = task.reset(rng)
            aif.reset_belief()
            total = 0.0
            probed = False
            done = False
            while not done:
                a = aif.act(obs)
                obs, r, done, info = task.step(a)
                total += r
                probed = probed or info.get("is_probe", False)
            aif_returns.append(total)
            aif_probe.append(probed)
    finally:
        aif.close()

    # --- no-exploration baseline: epsilon=0 Q-learner ---------------------
    base = QLearningAgent(task, QLearningConfig(epsilon_start=0.0, epsilon_min=0.0), rng)
    base_returns = []
    base_probe = []
    for _ in range(40):
        ret, info = run_episode(task, base, rng, train=False)
        base_returns.append(ret)
        base_probe.append(info["probed"])

    aif_probe_rate = float(np.mean(aif_probe))
    base_probe_rate = float(np.mean(base_probe))
    # The AIF agent out-info-seeks the no-exploration baseline by a wide margin,
    assert aif_probe_rate > 0.9, f"AIF probe rate {aif_probe_rate} too low"
    assert aif_probe_rate - base_probe_rate > 0.5, "AIF must out-probe the baseline"
    # and that info-seeking pays off (near-optimal vs ~chance).
    assert np.mean(aif_returns) > 0.8
    assert np.mean(aif_returns) > np.mean(base_returns) + 0.5


@pytestmark_real
def test_seeded_runs_reproduce_verdict():
    """Same seeds -> identical per-task verdicts (reproducibility requirement)."""
    from kaine.evaluation.benchmarks.active_inference.runner import (
        BenchmarkConfig,
        run_suite,
    )

    cfg = BenchmarkConfig(
        seeds=(0, 1, 2),
        rl_train_episodes=200,
        rl_eval_episodes=30,
        aif_eval_episodes=30,
        tune_holdout_seeds=(1001,),
        tune_train_episodes=120,
        tune_eval_episodes=20,
    )
    r1 = run_suite(default_suite(), cfg)
    r2 = run_suite(default_suite(), cfg)
    v1 = [(v["task"], v["verdict"]) for v in r1["verdicts"]]
    v2 = [(v["task"], v["verdict"]) for v in r2["verdicts"]]
    assert v1 == v2
    assert r1["summary"]["suite_verdict"] == r2["summary"]["suite_verdict"]


@pytestmark_real
def test_epistemic_task_verdict_is_win():
    """End-to-end: on the epistemic task the AIF agent should WIN (its belief +
    info-value machinery beats the belief-free baseline). This is the headline
    claim the benchmark exists to test — and with the shipped defaults it holds.
    """
    from kaine.evaluation.benchmarks.active_inference.runner import (
        BenchmarkConfig,
        run_task,
    )

    task = TMazeEpistemicPOMDP(cue_validity=0.98)
    cfg = BenchmarkConfig(
        seeds=(0, 1, 2, 3, 4),
        rl_train_episodes=300,
        rl_eval_episodes=40,
        aif_eval_episodes=40,
        tune_holdout_seeds=(1001,),
        tune_train_episodes=150,
        tune_eval_episodes=20,
    )
    records: list = []
    verdict = run_task(task, cfg, records_out=records)
    assert verdict["verdict"] == WIN
    assert verdict["mean_aif"] > verdict["mean_rl"]
    assert verdict["epistemic_value"]["probe_rate_gap"] > 0.4
