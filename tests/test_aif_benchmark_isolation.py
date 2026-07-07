# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Confound-isolation tests for the AIF-vs-RL benchmark.

These prove the benchmark's matched-information assumption: both arms are driven
by the SAME environment definition (env class, observation space, reward
structure) for a given seed, and the AIF preference ``C`` encodes the same reward
the RL baseline optimises. A future change that silently hands one arm a different
env or reward would fail these tests.

The two arms take different actions, so their realised observation *streams*
cannot be byte-identical — that is expected and is not asserted here. The
invariant under test is the shared env/reward *construction*.

Pure task inspection — no pymdp/jax engine is constructed, so this runs in every
build.
"""
from __future__ import annotations


import pytest

from kaine.evaluation.benchmarks.active_inference.envs import (
    ExploitationPOMDP,
    TMazeEpistemicPOMDP,
    default_suite,
)
from kaine.evaluation.benchmarks.active_inference.isolation import (
    aif_preference_reward_magnitudes,
    arm_environment_fingerprint,
    reward_magnitudes,
)

FIXED_SEED = 0


@pytest.mark.parametrize("task", default_suite(), ids=lambda t: t.name)
def test_both_arms_share_env_class_and_obs_space(task):
    # Both arms are fingerprinted off the SAME task object (as run_task drives
    # them). The env class and the env observation space must be identical.
    rl = arm_environment_fingerprint(task, arm="rl")
    aif = arm_environment_fingerprint(task, arm="aif")
    assert rl.env_class == aif.env_class
    assert rl.obs_space_size == aif.obs_space_size
    assert rl.num_actions == aif.num_actions


@pytest.mark.parametrize("task", default_suite(), ids=lambda t: t.name)
def test_both_arms_share_reward_structure(task):
    rl = arm_environment_fingerprint(task, arm="rl")
    aif = arm_environment_fingerprint(task, arm="aif")
    # reward_matching, optimal_return, and reward magnitudes are identical.
    assert rl.reward_structure() == aif.reward_structure()
    assert rl.reward_matching == aif.reward_matching
    assert rl.optimal_return == aif.optimal_return
    assert rl.reward_magnitudes == aif.reward_magnitudes


@pytest.mark.parametrize("task", default_suite(), ids=lambda t: t.name)
def test_aif_preference_C_encodes_same_reward_as_rl(task):
    # The AIF preference C must encode the same win/lose magnitudes the env
    # realises as scalar reward (the reward the RL baseline optimises).
    env_mags = reward_magnitudes(task)
    c_mags = aif_preference_reward_magnitudes(task)
    assert c_mags == pytest.approx(env_mags)


@pytest.mark.parametrize("task", default_suite(), ids=lambda t: t.name)
def test_reward_matrices_are_the_same_object_both_arms_consume(task):
    # Both arms read A/B/D off the same task; the reward-observation modality
    # matrix is the env's reward structure. Assert it is well-formed and shared.
    # (Same task object => identical matrices by construction; this guards a
    # future refactor that might clone/alter the env for one arm.)
    rl = arm_environment_fingerprint(task, arm="rl")
    aif = arm_environment_fingerprint(task, arm="aif")
    assert rl.reward_matching["scalar_reward"] == aif.reward_matching["scalar_reward"]


# ---------------------------------------------------------------------------
# Negative controls — the test has teeth.
# ---------------------------------------------------------------------------


def test_tampered_reward_breaks_matched_reward_invariant():
    # If one arm is handed a task whose reward differs, the matched-reward check
    # must fail. This is the confound the isolation test exists to catch.
    base = ExploitationPOMDP(n=3, obs_noise=0.0)
    tampered = ExploitationPOMDP(n=3, obs_noise=0.0, reward_correct=5.0)
    base_fp = arm_environment_fingerprint(base, arm="rl")
    tampered_fp = arm_environment_fingerprint(tampered, arm="aif")
    assert base_fp.reward_structure() != tampered_fp.reward_structure()
    assert base_fp.reward_magnitudes != tampered_fp.reward_magnitudes


def test_tampered_obs_space_breaks_matched_env_invariant():
    # A different env size (different n) perturbs the env observation space.
    a = arm_environment_fingerprint(ExploitationPOMDP(n=3), arm="rl")
    b = arm_environment_fingerprint(ExploitationPOMDP(n=5), arm="aif")
    assert a.obs_space_size != b.obs_space_size


def test_aif_C_magnitudes_track_a_changed_reward():
    # Sanity: the recovered C magnitudes follow the env's reward, so the
    # matched-reward assertion is meaningful (not a constant).
    task = TMazeEpistemicPOMDP(reward_correct=2.0, reward_wrong=-3.0)
    assert aif_preference_reward_magnitudes(task) == pytest.approx((2.0, -3.0))
    assert reward_magnitudes(task) == (2.0, -3.0)
