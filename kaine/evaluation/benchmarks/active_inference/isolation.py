# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Confound-isolation accessors for the AIF-vs-RL benchmark.

The benchmark's fairness rests on a *matched-information* assumption (design.md,
runner docstring): both arms are driven by the **same environment** and the same
reward, and the AIF preference ``C`` encodes the *same* reward the RL baseline
optimises. The two arms take different actions, so their realised observation
*streams* cannot be byte-identical — that is expected and is NOT the invariant.
The invariant is that both arms are *constructed from the same env definition*:
same task/env class, same reward function/matrices, same observation space for a
given seed, and an AIF ``C`` derived from the same reward the RL agent sees.

This module captures, honestly and read-only, *what env/reward each arm receives*
from a task, so a test can assert the two fingerprints match. It changes no
benchmark behaviour: it only inspects the task's exposed env/reward surface (the
exact surface each arm already consumes).

  - The RL baseline consumes: ``rl_num_obs()`` (its Q-table observation space),
    ``num_actions()``, ``reward_matching()``, ``optimal_return()``, and the env's
    scalar reward via ``step()`` — characterised here by the reward matrices /
    matching the env exposes.
  - The AIF adapter consumes: the generative-model tensors ``A``/``B``/``D`` and
    the preference ``C`` (``build_model_for_env`` is a faithful repackaging of
    these), plus the SAME ``reward_matching()`` / ``optimal_return()``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from kaine.evaluation.benchmarks.active_inference.envs import DiscretePOMDP


@dataclass(frozen=True)
class ArmEnvironmentFingerprint:
    """A read-only capture of the env/reward an arm is driven by."""

    arm: str                       # "rl" | "aif"
    env_class: str                 # the task/env class name
    obs_space_size: int            # the ENV observation space both arms are driven by
    arm_index_space: int           # the per-arm internal index space (informational)
    num_actions: int
    reward_matching: dict[str, Any]
    optimal_return: float
    # The win/lose reward magnitudes the env's reward-observation modality
    # exposes — the matched-reward invariant both arms must share.
    reward_magnitudes: tuple[float, float]

    def reward_structure(self) -> tuple:
        """The reward structure both arms must share (matching + optimal + mags).

        ``reward_matching`` is rendered to a stable, comparable form."""
        return (
            _stable(self.reward_matching),
            round(self.optimal_return, 9),
            self.reward_magnitudes,
        )


def _stable(obj: Any) -> Any:
    """Render a nested dict/list to a hashable, comparison-stable structure."""
    if isinstance(obj, dict):
        return tuple(sorted((k, _stable(v)) for k, v in obj.items()))
    if isinstance(obj, (list, tuple)):
        return tuple(_stable(v) for v in obj)
    if isinstance(obj, float):
        return round(obj, 9)
    return obj


def reward_magnitudes(task: DiscretePOMDP) -> tuple[float, float]:
    """Extract the (win, lose) reward magnitudes the env realises.

    Both tasks expose ``reward_correct`` / ``reward_wrong`` as the scalar reward
    the RL baseline optimises; the AIF ``preference_C`` must encode the same
    magnitudes on its reward-observation modality. Read from the task directly so
    a divergence between the env reward and what an arm is handed is detectable.
    """
    return (float(task.reward_correct), float(task.reward_wrong))


def aif_preference_reward_magnitudes(task: DiscretePOMDP) -> tuple[float, float]:
    """The win/lose magnitudes encoded in the AIF preference ``C``.

    ``preference_C`` puts the reward preference on the reward-observation
    modality. We recover the underlying (win, lose) magnitudes by dividing out
    the documented preference scale (the envs scale C by 4.0 to make EFE's
    pragmatic term commensurate with the epistemic term). The recovered
    magnitudes must equal the env's scalar reward — the matched-reward invariant.
    """
    C = [np.asarray(c, dtype=float) for c in task.preference_C()]
    # The reward-obs modality is the one carrying nonzero preference. For both
    # shipped tasks it is the modality whose vector has a positive (win) and a
    # negative (lose) entry.
    scale = 4.0  # documented preference scale (see envs.preference_C docstrings)
    for c in C:
        if np.any(c > 0) and np.any(c < 0):
            win = float(np.max(c)) / scale
            lose = float(np.min(c)) / scale
            return (win, lose)
    raise ValueError("no reward-bearing modality found in preference_C")


def arm_environment_fingerprint(task: DiscretePOMDP, *, arm: str) -> ArmEnvironmentFingerprint:
    """Capture the env/reward fingerprint for one arm of the benchmark.

    ``arm`` is ``"rl"`` or ``"aif"``. Both fingerprints are taken from the SAME
    task object (which is how the runner drives them — ``run_task`` builds one
    task and hands it to both ``train_q_agent`` and ``AIFAgent``); this accessor
    records *what each arm reads off that task* so a test can assert they match.
    """
    if arm not in ("rl", "aif"):
        raise ValueError(f"arm must be 'rl' or 'aif', got {arm!r}")
    matching = task.reward_matching()
    optimal = float(task.optimal_return())
    mags = reward_magnitudes(task)
    # The ENV observation space both arms are driven by: the joint product of the
    # per-modality observation sizes the env emits (A's leading dims). This is a
    # property of the shared env, identical for both arms by construction — it is
    # exactly what a confound would perturb if one arm got a different env.
    env_obs_space = int(np.prod([int(np.asarray(a).shape[0]) for a in task.A]))
    # Each arm's internal index space differs by design (the RL baseline flattens
    # to a Q-table key off the observations it acts on; the AIF arm carries a
    # belief over the full generative model) — recorded for transparency, NOT a
    # matched invariant.
    if arm == "rl":
        arm_index_space = int(task.rl_num_obs())
    else:
        arm_index_space = env_obs_space
    return ArmEnvironmentFingerprint(
        arm=arm,
        env_class=type(task).__name__,
        obs_space_size=env_obs_space,
        arm_index_space=arm_index_space,
        num_actions=int(task.num_actions()),
        reward_matching=matching,
        optimal_return=optimal,
        reward_magnitudes=mags,
    )


__all__ = [
    "ArmEnvironmentFingerprint",
    "arm_environment_fingerprint",
    "reward_magnitudes",
    "aif_preference_reward_magnitudes",
]
