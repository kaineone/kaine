# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tabular Q-learning baseline with history-keyed state.

This is the conventional, transparent model-free comparison for small discrete
POMDPs. It is ε-greedy tabular Q-learning where the state key is a sliding
window of the last ``memory + 1`` observation keys emitted by the environment.
With the default ``memory=None`` the window spans the whole episode
(``task.horizon``), giving the baseline the same observation history an explicit
belief-keeping agent would use (up to the horizon). ``memory=0`` recovers the
memoryless control that acts on the current observation only.

On the epistemic T-maze a non-zero memory can carry the cue observation
forward, so the baseline is *not* denied the cue information; what it lacks is
the AIF agent's explicit generative model and information-value machinery.

Deep RL is explicitly a non-goal — it would add dependencies and obscure the
comparison. Hyperparameters (α, γ, ε schedule) are tuned per task by a
small grid on held-out seeds (:func:`tune_hyperparameters`) and the chosen
values are recorded in every result, so the baseline is not strawmanned.
The memory is not tuned: it is fixed at the task horizon (the whole episode),
so the baseline has the same information as a belief-keeping agent.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

import numpy as np

from kaine.evaluation.benchmarks.active_inference.envs import DiscretePOMDP


@dataclass(frozen=True)
class QLearningConfig:
    """Tabular Q-learning hyperparameters.

    ``epsilon_start`` decays geometrically by ``epsilon_decay`` per *training*
    episode down to ``epsilon_min``. Evaluation episodes use ε = 0 (greedy).

    ``memory`` controls how many previous observation keys are included in the
    state key in addition to the current observation. ``None`` means the whole
    episode (``task.horizon``); ``0`` makes the agent memoryless.
    """

    alpha: float = 0.1  # learning rate
    gamma: float = 0.95  # discount
    epsilon_start: float = 1.0
    epsilon_min: float = 0.02
    epsilon_decay: float = 0.995
    memory: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "alpha": self.alpha,
            "gamma": self.gamma,
            "epsilon_start": self.epsilon_start,
            "epsilon_min": self.epsilon_min,
            "epsilon_decay": self.epsilon_decay,
            "memory": self.memory,
        }


class QLearningAgent:
    """ε-greedy tabular Q-learning over history-keyed states.

    The state key is a tuple of the last ``memory + 1`` observation keys (or
    the whole episode when ``memory`` is ``None``). The Q-table is a sparse dict
    mapping state keys to vectors of length ``num_actions``. Updates use the
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
        if config.memory is not None and int(config.memory) < 0:
            raise ValueError("memory must be a non-negative int or None")
        self._memory = task.horizon if config.memory is None else int(config.memory)
        self.q: dict[tuple[int, ...], np.ndarray] = {}
        self._history: deque[int] = deque(maxlen=self._memory + 1)
        self._epsilon = config.epsilon_start

    @property
    def memory(self) -> int:
        """Effective memory: the number of earlier observations in the state key."""
        return self._memory

    def _row(self, key: tuple[int, ...]) -> np.ndarray:
        """Return the Q-vector for ``key``, inserting zeros on first access."""
        if key not in self.q:
            self.q[key] = np.zeros(self._n_actions, dtype=float)
        return self.q[key]

    def reset_history(self, obs_key: int) -> tuple[int, ...]:
        """Start a new episode history and return the initial state key."""
        self._history.clear()
        self._history.append(obs_key)
        return tuple(self._history)

    def push(self, obs_key: int) -> tuple[int, ...]:
        """Append an observation key and return the new state key."""
        self._history.append(obs_key)
        return tuple(self._history)

    def select(self, state_key: tuple[int, ...], *, greedy: bool) -> int:
        if not greedy and self._rng.random() < self._epsilon:
            return int(self._rng.integers(0, self._n_actions))
        row = self._row(state_key)
        # Break ties randomly to avoid a fixed-action bias.
        best = np.flatnonzero(row == row.max())
        return int(self._rng.choice(best))

    def update(
        self,
        state_key: tuple[int, ...],
        action: int,
        reward: float,
        next_state_key: tuple[int, ...],
        done: bool,
    ) -> None:
        target = reward
        if not done:
            target += self._cfg.gamma * float(self._row(next_state_key).max())
        self._row(state_key)[action] += self._cfg.alpha * (
            target - self._row(state_key)[action]
        )

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
    state = agent.reset_history(task.rl_obs_key(obs))
    total = 0.0
    probed = False
    probe_step: int | None = None
    step = 0
    done = False
    while not done:
        action = agent.select(state, greedy=not train)
        next_obs, reward, done, info = task.step(action)
        next_state = agent.push(task.rl_obs_key(next_obs))
        if train:
            agent.update(state, action, reward, next_state, done)
        total += reward
        if info.get("is_probe") and not probed:
            probed = True
            probe_step = step
        state = next_state
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
    greedy evaluation returns, probe statistics, hyperparameters, and the
    effective memory length.
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
        "memory": agent.memory,
    }


def _default_grid(memory: int | None = None) -> list[QLearningConfig]:
    grid: list[QLearningConfig] = []
    for alpha in (0.05, 0.1, 0.3):
        for gamma in (0.9, 0.95, 0.99):
            for decay in (0.99, 0.995):
                grid.append(
                    QLearningConfig(alpha=alpha, gamma=gamma, epsilon_decay=decay, memory=memory)
                )
    return grid


def tune_hyperparameters(
    task: DiscretePOMDP,
    *,
    holdout_seeds: tuple[int, ...] = (101, 102, 103),
    train_episodes: int = 400,
    eval_episodes: int = 50,
    grid: list[QLearningConfig] | None = None,
    memory: int | None = None,
) -> tuple[QLearningConfig, list[dict[str, Any]]]:
    """Pick the Q-learning hyperparameters by a small grid on held-out seeds.

    Returns the chosen config (highest mean greedy-evaluation return averaged
    over the held-out seeds) and the full grid record (so the tuning is
    transparent and recorded, not hidden). Held-out seeds are disjoint from the
    benchmark's evaluation seeds so the baseline is tuned fairly, not on the
    seeds it is then scored on.
    """
    grid = grid or _default_grid(memory=memory)
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
