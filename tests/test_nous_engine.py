# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Engine tests.

The protocol / behavioural tests run against :class:`FakeEngine` (no pymdp, no
JAX) so they are always part of the green build. A small opt-in section
exercises the real :class:`PymdpEngine` only when the reasoning extra is present.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import pytest

from kaine.modules.nous.engine import (
    ActiveInferenceEngine,
    EngineResult,
    FakeEngine,
    normalised_entropy,
)


@dataclass
class _Ev:
    source: str
    payload: dict
    salience: float


class _Snap:
    def __init__(self, events):
        self.selected_events = [(str(i), e) for i, e in enumerate(events)]


def _snap():
    return _Snap([_Ev("soma", {}, 0.9)])


def test_fake_engine_satisfies_protocol():
    fake = FakeEngine()
    assert isinstance(fake, ActiveInferenceEngine)


def test_normalised_entropy_bounds():
    assert normalised_entropy([1.0, 0.0, 0.0]) == pytest.approx(0.0)
    assert normalised_entropy([0.25, 0.25, 0.25, 0.25]) == pytest.approx(1.0)
    assert normalised_entropy([]) == 0.0


def test_belief_update_changes_posterior():
    # Two scripted steps with different posteriors: the engine reports the new
    # posterior on the second step.
    p1 = [[1.0, 0.0, 0.0, 0.0], [0.9, 0.05, 0.05], [0.25] * 4, [0.25] * 4]
    p2 = [[0.0, 1.0, 0.0, 0.0], [0.1, 0.1, 0.8], [0.25] * 4, [0.25] * 4]
    fake = FakeEngine(posteriors=[p1, p2])
    r1 = fake.step(_snap())
    r2 = fake.step(_snap())
    assert r1.posterior[1] != r2.posterior[1]
    assert r2.posterior[1][2] == pytest.approx(0.8)


def test_fake_engine_exposes_policy_len():
    fake = FakeEngine()
    assert fake.policy_len == 1


def test_policy_selection_returns_lowest_efe():
    # Action index 2 has the lowest EFE -> request_speak.
    fake = FakeEngine(policy_efe=[0.9, 0.5, 0.05, 0.7])
    r = fake.step(_snap())
    assert r.action_index == 2
    assert r.action == "request_speak"


def test_timeout_returns_last_posterior_and_flag():
    p1 = [[1.0, 0.0, 0.0, 0.0], [0.9, 0.05, 0.05], [0.25] * 4, [0.25] * 4]
    p2 = [[0.0, 1.0, 0.0, 0.0], [0.1, 0.1, 0.8], [0.25] * 4, [0.25] * 4]
    # First step OK; second step times out -> returns the FIRST posterior.
    fake = FakeEngine(posteriors=[p1, p2], timeout_on=1)
    r1 = fake.step(_snap())
    assert r1.timed_out is False
    r2 = fake.step(_snap())
    assert r2.timed_out is True
    assert r2.posterior[1] == p1[1]


def test_engine_result_dominant_factor_picks_most_certain_perceptual():
    # Factor 1 is near point-mass (low entropy); factor 2 is uniform. Factor 0
    # (action latent) is excluded. dominant should be factor 1.
    r = EngineResult(
        posterior=[
            [1.0, 0.0, 0.0, 0.0],  # action latent, excluded
            [0.95, 0.025, 0.025],  # most certain perceptual
            [0.25, 0.25, 0.25, 0.25],
            [0.25, 0.25, 0.25, 0.25],
        ],
        policy_efe=[0.0, 0.0, 0.0, 0.0],
        action_index=0,
        action="no_op",
    )
    factor_idx, state_idx, expectation = r.dominant_factor()
    assert factor_idx == 1
    assert state_idx == 0
    assert expectation == pytest.approx(0.95)


# --------------------------------------------------------------------------
# Opt-in real-pymdp tests (skipped unless the reasoning extra is installed).
# --------------------------------------------------------------------------

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


def _jit_cache_sizes(engine) -> tuple[int, int, int]:
    jitted = (engine._jit_cycle, engine._jit_learn, engine._jit_propagate)
    for fn in jitted:
        assert hasattr(fn, "_cache_size"), (
            "jax.jit functions no longer expose _cache_size(); update this test "
            "to count compilations another way (do not drop the check)"
        )
    return tuple(fn._cache_size() for fn in jitted)


@pytestmark_real
def test_real_pymdp_engine_compiles_nothing_after_construction():
    """Construction compiles every jitted path a live step takes.

    JAX compiles once per argument shape, and a compile costs ~100x a
    steady-state step (about 100 ms against about 1 ms on a desktop, seconds
    on a loaded CI runner). A compile left for the first live step lands inside
    the EFE deadline, so the first learning step overran it. This checks that
    directly and deterministically: the jit caches do not grow across the first
    live steps, which include the first learning step.
    """
    from kaine.modules.nous.engine import PymdpEngine

    engine = PymdpEngine(efe_timeout_ms=10_000.0)
    try:
        after_construction = _jit_cache_sizes(engine)
        assert all(n >= 1 for n in after_construction)
        for _ in range(4):
            engine.step(_snap())
        assert _jit_cache_sizes(engine) == after_construction
    finally:
        engine.close()


def _benchmark_task_model():
    # A model with its own factor layout (not Nous's default salience/affect/
    # event factors) and no transition learning.
    from kaine.evaluation.benchmarks.active_inference.aif_agent import (
        build_model_for_env,
    )
    from kaine.evaluation.benchmarks.active_inference.envs import ExploitationPOMDP

    return build_model_for_env(ExploitationPOMDP(n=3, obs_noise=0.02))


def _small_learning_model():
    # Nous's layout with non-default cardinalities; learns its transitions.
    from kaine.modules.nous.generative_model import build_generative_model

    return build_generative_model(event_clusters=("alpha", "beta"))


def _engine_state(engine) -> dict:
    return {
        "B": [b.tolist() for b in engine._get_B(engine._agent)],
        "pB": [pb.tolist() for pb in engine._get_pB(engine._agent)],
        "prior": engine._prior_lists(engine._prior),
        "prev_action": engine._prev_action,
        "prev_qs": None
        if engine._prev_qs is None
        else engine._posterior_lists(engine._prev_qs),
        "last_posterior": engine._last_posterior,
        "last_efe": engine._last_efe,
        "generation": engine._generation,
        "learned": engine.learned_state(),
    }


@pytestmark_real
@pytest.mark.parametrize(
    "make_model", [_benchmark_task_model, _small_learning_model],
    ids=["benchmark-task-model", "non-default-learning-model"],
)
def test_real_pymdp_warm_up_has_no_side_effects(make_model, monkeypatch):
    """A warmed engine behaves exactly like an unwarmed one on the same inputs.

    The warm-up exists only to fill the jit caches. It must work on any model,
    not only Nous's default layout, and it must not learn, move the carried
    prior or otherwise change what the engine computes.
    """
    from kaine.modules.nous.engine import PymdpEngine

    model = make_model()
    warmed = PymdpEngine(model, efe_timeout_ms=10_000.0)
    with monkeypatch.context() as m:
        m.setattr(PymdpEngine, "_warm_up", lambda self: None)
        unwarmed = PymdpEngine(model, efe_timeout_ms=10_000.0)
    try:
        assert _engine_state(warmed) == _engine_state(unwarmed)
        observations = [
            [0] * model.num_modalities,
            [n - 1 for n in model.num_obs],
            [min(1, n - 1) for n in model.num_obs],
            [0] * model.num_modalities,
        ]
        for obs in observations:
            a, b = warmed.infer(obs), unwarmed.infer(obs)
            assert not a.timed_out and not a.error, a.error_reason
            assert not b.timed_out and not b.error, b.error_reason
            assert (a.posterior, a.policy_efe, a.action_index) == (
                b.posterior, b.policy_efe, b.action_index,
            )
            assert _engine_state(warmed) == _engine_state(unwarmed)
    finally:
        warmed.close()
        unwarmed.close()


@pytestmark_real
def test_real_pymdp_engine_runs_within_budget():
    """The median live step fits inside the engine's own EFE deadline.

    What this protects: a Nous step must fit its per-tick deadline,
    ``efe_timeout_ms`` (engine default 250 ms, inside the ~300 ms cognitive
    cycle); a step that overruns it returns the stale posterior. The budget is
    therefore that documented default, read from the engine, not a number of
    our own.

    How it measures, and why: the median of several consecutive steps from a
    freshly constructed engine, so one descheduled step on a shared runner
    cannot fail the test, while a systematic slowdown of the step (the thing
    worth catching) still moves the median. One-time JIT compilation is
    excluded because it belongs to construction; the companion test
    ``test_real_pymdp_engine_compiles_nothing_after_construction`` proves no
    compile leaks into these steps, so nothing here has to be warmed first.
    The first learning step is among the samples.

    CI-noise allowance: a desktop median is about 1-2 ms, so the 250 ms budget
    leaves a margin of more than 100x for a slow or contended runner. The
    tighter 200 ms median target on real hardware is asserted by
    ``scripts/benchmark_nous_efe.py``, not here.
    """
    import inspect
    import statistics

    from kaine.modules.nous.engine import PymdpEngine

    budget_ms = float(
        inspect.signature(PymdpEngine).parameters["efe_timeout_ms"].default
    )
    # Measure raw compute: a generous deadline so the guard never trips here.
    engine = PymdpEngine(efe_timeout_ms=10_000.0)
    try:
        samples_ms: list[float] = []
        for _ in range(9):
            start = time.perf_counter()
            result = engine.step(_snap())
            samples_ms.append((time.perf_counter() - start) * 1000.0)
            assert not result.timed_out
            assert not result.error
            assert len(result.posterior) == 4
            assert len(result.policy_efe) == 4
            assert result.action in engine.actions
        median_ms = statistics.median(samples_ms)
        assert median_ms < budget_ms, (
            f"median step {median_ms:.1f} ms >= EFE deadline {budget_ms:.0f} ms "
            f"(samples: {[round(x, 1) for x in samples_ms]})"
        )
    finally:
        engine.close()


@pytestmark_real
def test_real_pymdp_engine_timeout_guard_returns_last_posterior():
    from kaine.modules.nous.engine import PymdpEngine

    # Impossibly tight deadline forces an overrun on the (uncompiled) first call.
    engine = PymdpEngine(efe_timeout_ms=0.001)
    try:
        result = engine.step(_snap())
        assert result.timed_out is True
        # Last posterior fallback is the uniform/initial one (well-formed).
        assert len(result.posterior) == 4
        assert result.action == engine.actions[0]
    finally:
        engine.close()


@pytestmark_real
def test_real_pymdp_engine_exposes_policy_len():
    from kaine.modules.nous.engine import PymdpEngine

    engine = PymdpEngine(policy_len=2)
    try:
        assert engine.policy_len == 2
    finally:
        engine.close()


@pytestmark_real
def test_real_pymdp_engine_per_action_efe_at_horizon_two():
    import numpy as np

    from kaine.modules.nous.engine import PymdpEngine, encode_snapshot_default
    from kaine.modules.nous.generative_model import ACTION_FACTOR

    engine = PymdpEngine(policy_len=2, efe_timeout_ms=10_000.0)
    try:
        # Warm-up inference to populate a posterior and cache the policy matrix.
        engine.infer(encode_snapshot_default(engine.model))

        policies = engine._policies
        assert policies.ndim == 3
        first = policies[:, 0, ACTION_FACTOR]
        n_policies = len(first)

        # Craft a neg-EFE vector where the best policy starts with action 2.
        candidates = np.where(first == 2)[0]
        assert len(candidates) > 0, "no policies start with action 2"
        target = int(candidates[0])
        # EFE = -neg_efe, so the best (lowest-EFE) policy has the HIGHEST neg-EFE.
        neg_efe = np.full(n_policies, -5.0, dtype=np.float32)
        neg_efe[target] = 10.0

        def _fake_cycle(agent, obs_batched, prior):
            import jax.numpy as jnp
            # Same shape as the real cycle's beliefs: (batch, time, states).
            qs = [jnp.array(p)[None, None, :] for p in engine._last_posterior]
            return qs, jnp.array(neg_efe)

        engine._jit_cycle = _fake_cycle
        result = engine.infer(encode_snapshot_default(engine.model))

        assert result.action_index == 2
        assert result.action == engine.actions[2]

        raw_efe = [-float(x) for x in neg_efe]
        expected = [float("inf")] * engine.model.num_actions
        for p_idx, a in enumerate(first):
            if 0 <= a < engine.model.num_actions and raw_efe[p_idx] < expected[a]:
                expected[a] = raw_efe[p_idx]
        assert result.policy_efe == pytest.approx(expected, nan_ok=True)
    finally:
        engine.close()


@pytestmark_real
def test_real_pymdp_engine_seeded_posterior_is_the_timeout_fallback():
    from kaine.modules.nous.engine import PymdpEngine

    engine = PymdpEngine(efe_timeout_ms=0.001)
    try:
        seeded = []
        for size in engine.model.num_states:
            dist = [0.0] * size
            dist[-1] = 1.0
            seeded.append(dist)

        assert engine.seed_posterior(seeded) is True

        result = engine.step(_snap())
        assert result.timed_out is True
        assert result.posterior == seeded
        assert result.action == engine.actions[0]
    finally:
        engine.close()


@pytestmark_real
def test_real_pymdp_engine_rejects_mismatched_posterior():
    from kaine.modules.nous.engine import PymdpEngine

    engine = PymdpEngine(efe_timeout_ms=0.001)
    try:
        sizes = list(engine.model.num_states)
        uniform = [[1.0 / n] * n for n in sizes]

        # Wrong factor count.
        assert engine.seed_posterior(uniform[:-1]) is False
        result = engine.step(_snap())
        assert result.timed_out is True
        assert result.posterior == uniform

        # Right count but one factor one element short.
        short = [list(d) for d in uniform]
        if short:
            short[-1] = short[-1][:-1]
        assert engine.seed_posterior(short) is False
        result = engine.step(_snap())
        assert result.timed_out is True
        assert result.posterior == uniform

        # A NaN value.
        nan_post = [list(d) for d in uniform]
        if nan_post and nan_post[-1]:
            nan_post[-1][0] = float("nan")
        assert engine.seed_posterior(nan_post) is False
        result = engine.step(_snap())
        assert result.timed_out is True
        assert result.posterior == uniform

        # A negative value.
        neg_post = [list(d) for d in uniform]
        if neg_post and neg_post[-1]:
            neg_post[-1][0] = -0.1
        assert engine.seed_posterior(neg_post) is False
        result = engine.step(_snap())
        assert result.timed_out is True
        assert result.posterior == uniform
    finally:
        engine.close()


# --------------------------------------------------------------------------
# H1: EngineResult error field — distinguishes crashes from genuine no_ops
# --------------------------------------------------------------------------


def test_engine_result_error_defaults_false():
    """Successful EngineResult has error=False and empty error_reason."""
    r = EngineResult(
        posterior=[[1.0, 0.0, 0.0, 0.0], [0.5, 0.5], [0.25] * 4, [0.25] * 4],
        policy_efe=[0.0, 0.0, 0.0, 0.0],
        action_index=0,
        action="no_op",
    )
    assert r.error is False
    assert r.error_reason == ""
    assert r.timed_out is False


def test_engine_result_error_fields_populate():
    """EngineResult with error=True carries a non-empty reason."""
    r = EngineResult(
        posterior=[[1.0, 0.0], [0.5, 0.5]],
        policy_efe=[0.0, 0.0],
        action_index=0,
        action="no_op",
        error=True,
        error_reason="RuntimeError: numerical instability",
    )
    assert r.error is True
    assert "RuntimeError" in r.error_reason
    assert r.timed_out is False


def test_fake_engine_error_on_returns_error_result():
    """FakeEngine.error_on simulates a non-timeout crash on the given step."""
    p1 = [[1.0, 0.0, 0.0, 0.0], [0.9, 0.05, 0.05], [0.25] * 4, [0.25] * 4]
    fake = FakeEngine(posteriors=[p1], error_on=1)
    r0 = fake.step(_snap())
    assert r0.error is False
    r1 = fake.step(_snap())
    assert r1.error is True
    assert r1.timed_out is False
    assert r1.error_reason != ""
    # Posterior is last-good stale priors, not fresh.
    assert r1.posterior == p1


def test_timeout_and_error_mutually_exclusive_in_fake():
    """FakeEngine timeout path still sets timed_out=True and error=False."""
    fake = FakeEngine(timeout_on=0)
    r = fake.step(_snap())
    assert r.timed_out is True
    assert r.error is False
