# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tabular Q-learning baseline — the honest model-free comparison.

This is the conventional, transparent baseline for small discrete POMDPs
(design.md): ε-greedy tabular Q-learning over the *observation*–action space.
The baseline has **no belief state** — it indexes its Q-table by the env's raw
observation key (:meth:`DiscretePOMDP.rl_obs_key`). That is the point of the
comparison: it asks whether the AIF agent's explicit belief + information-value
machinery beats a model-free learner that lacks it. On the epistemic T-maze the
baseline can *see* the cue observation when it happens to stand on the cue, but
it has no model carrying that information into a belief about the hidden reward
condition, so it cannot deliberately value probing.

Deep RL is explicitly a non-goal — it would add dependencies and obscure the
comparison. Hyperparameters (α, γ, ε schedule) are tuned per task by a small
grid on held-out seeds (:func:`tune_hyperparameters`) and the chosen values are
recorded in every result, so the baseline is not strawmanned.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from kaine.evaluation.benchmarks.active_inference.envs import DiscretePOMDP


@dataclass(frozen=True)
class QLearningConfig:
    """Tabular Q-learning hyperparameters.

    ``epsilon_start`` decays geometrically by ``epsilon_decay`` per *training*
    episode down to ``epsilon_min``. Evaluation episodes use ε = 0 (greedy).
    """

    alpha: float = 0.1  # learning rate
    gamma: float = 0.95  # discount
    epsilon_start: float = 1.0
    epsilon_min: float = 0.02
    epsilon_decay: float = 0.995

    def as_dict(self) -> dict[str, float]:
        return {
            "alpha": self.alpha,
            "gamma": self.gamma,
            "epsilon_start": self.epsilon_start,
            "epsilon_min": self.epsilon_min,
            "epsilon_decay": self.epsilon_decay,
        }


class QLearningAgent:
    """ε-greedy tabular Q-learning over (obs-key, action).

    The Q-table is a dense ``(num_obs_keys, num_actions)`` array. Updates use the
    standard temporal-difference rule. Action selection is ε-greedy during
    training and greedy (ε = 0) during evaluation.
    """

    def __init__(
        self,
        task: DiscretePOMDP,
        config: QLearningConfig,
        rng: np.random.Generator,
    ) -> None:
        self._task = task
        self._cfg = config
        self._rng = rng
        self._n_actions = task.num_actions()
        self._n_obs = int(task.rl_num_obs())
        self.q = np.zeros((self._n_obs, self._n_actions), dtype=float)
        self._epsilon = config.epsilon_start

    @property
    def epsilon(self) -> float:
        return self._epsilon

    def select(self, obs_key: int, *, greedy: bool) -> int:
        if not greedy and self._rng.random() < self._epsilon:
            return int(self._rng.integers(0, self._n_actions))
        row = self.q[obs_key]
        # Break ties randomly to avoid a fixed-action bias.
        best = np.flatnonzero(row == row.max())
        return int(self._rng.choice(best))

    def update(self, obs_key: int, action: int, reward: float, next_key: int, done: bool) -> None:
        target = reward
        if not done:
            target += self._cfg.gamma * float(self.q[next_key].max())
        self.q[obs_key, action] += self._cfg.alpha * (target - self.q[obs_key, action])

    def decay_epsilon(self) -> None:
        self._epsilon = max(self._cfg.epsilon_min, self._epsilon * self._cfg.epsilon_decay)


def run_episode(
    task: DiscretePOMDP,
    agent: QLearningAgent,
    rng: np.random.Generator,
    *,
    train: bool,
) -> tuple[float, dict[str, Any]]:
    """Run one episode; learn if ``train``. Returns (return, info-summary)."""
    obs = task.reset(rng)
    obs_key = task.rl_obs_key(obs)
    total = 0.0
    probed = False
    probe_step: int | None = None
    step = 0
    done = False
    while not done:
        action = agent.select(obs_key, greedy=not train)
        next_obs, reward, done, info = task.step(action)
        next_key = task.rl_obs_key(next_obs)
        if train:
            agent.update(obs_key, action, reward, next_key, done)
        total += reward
        if info.get("is_probe") and not probed:
            probed = True
            probe_step = step
        obs_key = next_key
        step += 1
    return total, {"probed": probed, "probe_step": probe_step, "steps": step}


def train_q_agent(
    task: DiscretePOMDP,
    config: QLearningConfig,
    *,
    seed: int,
    train_episodes: int,
    eval_episodes: int,
) -> dict[str, Any]:
    """Train then greedily evaluate a Q-agent on a task.

    Returns a record with the learning curve (per-episode training returns), the
    greedy evaluation returns, and probe statistics — enough for the metrics
    layer to compute decision quality, sample efficiency, and probe behaviour.
    """
    rng = np.random.default_rng(seed)
    agent = QLearningAgent(task, config, rng)
    train_returns: list[float] = []
    for _ in range(train_episodes):
        ret, _info = run_episode(task, agent, rng, train=True)
        train_returns.append(ret)
        agent.decay_epsilon()
    eval_returns: list[float] = []
    probe_flags: list[bool] = []
    probe_steps: list[int] = []
    for _ in range(eval_episodes):
        ret, info = run_episode(task, agent, rng, train=False)
        eval_returns.append(ret)
        probe_flags.append(bool(info["probed"]))
        if info["probe_step"] is not None:
            probe_steps.append(int(info["probe_step"]))
    return {
        "train_returns": train_returns,
        "eval_returns": eval_returns,
        "probe_rate": float(np.mean(probe_flags)) if probe_flags else 0.0,
        "mean_probe_step": float(np.mean(probe_steps)) if probe_steps else None,
        "hyperparameters": config.as_dict(),
    }


def _default_grid() -> list[QLearningConfig]:
    grid: list[QLearningConfig] = []
    for alpha in (0.05, 0.1, 0.3):
        for gamma in (0.9, 0.95, 0.99):
            for decay in (0.99, 0.995):
                grid.append(
                    QLearningConfig(alpha=alpha, gamma=gamma, epsilon_decay=decay)
                )
    return grid


def tune_hyperparameters(
    task: DiscretePOMDP,
    *,
    holdout_seeds: tuple[int, ...] = (101, 102, 103),
    train_episodes: int = 400,
    eval_episodes: int = 50,
    grid: list[QLearningConfig] | None = None,
) -> tuple[QLearningConfig, list[dict[str, Any]]]:
    """Pick the Q-learning hyperparameters by a small grid on held-out seeds.

    Returns the chosen config (highest mean greedy-evaluation return averaged
    over the held-out seeds) and the full grid record (so the tuning is
    transparent and recorded, not hidden). Held-out seeds are disjoint from the
    benchmark's evaluation seeds so the baseline is tuned fairly, not on the
    seeds it is then scored on.
    """
    grid = grid or _default_grid()
    records: list[dict[str, Any]] = []
    best_cfg = grid[0]
    best_score = -np.inf
    for cfg in grid:
        seed_scores: list[float] = []
        for s in holdout_seeds:
            rec = train_q_agent(
                task,
                cfg,
                seed=s,
                train_episodes=train_episodes,
                eval_episodes=eval_episodes,
            )
            seed_scores.append(float(np.mean(rec["eval_returns"])))
        score = float(np.mean(seed_scores))
        records.append({"hyperparameters": cfg.as_dict(), "holdout_score": score})
        if score > best_score:
            best_score = score
            best_cfg = cfg
    return best_cfg, records


__all__ = [
    "QLearningConfig",
    "QLearningAgent",
    "run_episode",
    "train_q_agent",
    "tune_hyperparameters",
]
