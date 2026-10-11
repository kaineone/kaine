# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Fast tests for the history-keyed Q-learning baseline."""
from __future__ import annotations

import numpy as np
import pytest

from kaine.evaluation.benchmarks.active_inference.envs import (
    ExploitationPOMDP,
    TMazeEpistemicPOMDP,
)
from kaine.evaluation.benchmarks.active_inference.rl_baseline import (
    QLearningAgent,
    QLearningConfig,
    train_q_agent,
)


def test_default_memory_is_horizon():
    task = TMazeEpistemicPOMDP()
    agent = QLearningAgent(task, QLearningConfig(), np.random.default_rng(0))
    assert agent.memory == task.horizon


def test_memory_zero_state_key_is_current_obs_only():
    task = TMazeEpistemicPOMDP()
    agent = QLearningAgent(
        task, QLearningConfig(memory=0), np.random.default_rng(0)
    )
    assert agent.reset_history(5) == (5,)
    assert agent.push(7) == (7,)


def test_default_memory_distinguishes_history():
    task = TMazeEpistemicPOMDP()
    agent = QLearningAgent(task, QLearningConfig(), np.random.default_rng(0))

    start = 0
    next_common = 9
    agent.reset_history(start)
    after_a = agent.push(1)
    state_a = agent.push(next_common)

    agent.reset_history(start)
    after_b = agent.push(2)
    state_b = agent.push(next_common)

    assert after_a != after_b
    assert state_a != state_b


def test_negative_memory_raises():
    task = TMazeEpistemicPOMDP()
    with pytest.raises(ValueError):
        QLearningAgent(
            task, QLearningConfig(memory=-1), np.random.default_rng(0)
        )


def test_memory_none_still_solves_exploitation():
    task = ExploitationPOMDP(n=3, obs_noise=0.0)
    rec = train_q_agent(
        task,
        QLearningConfig(alpha=0.2, gamma=0.95, epsilon_decay=0.99, memory=None),
        seed=0,
        train_episodes=600,
        eval_episodes=100,
    )
    assert np.mean(rec["eval_returns"]) > 0.85
    assert rec["memory"] == 1


def test_tmaze_default_memory_deterministic():
    task = TMazeEpistemicPOMDP()
    cfg = QLearningConfig()
    r1 = train_q_agent(task, cfg, seed=0, train_episodes=100, eval_episodes=20)
    r2 = train_q_agent(task, cfg, seed=0, train_episodes=100, eval_episodes=20)
    assert r1["eval_returns"] == r2["eval_returns"]
    assert r1["memory"] == task.horizon
