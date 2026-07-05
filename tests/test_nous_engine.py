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


@pytestmark_real
def test_real_pymdp_engine_runs_within_budget():
    from kaine.modules.nous.engine import PymdpEngine

    engine = PymdpEngine(efe_timeout_ms=10_000.0)
    try:
        # Warm, then measure a single step.
        engine.step(_snap())
        start = time.perf_counter()
        result = engine.step(_snap())
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        assert not result.timed_out
        assert len(result.posterior) == 4
        assert len(result.policy_efe) == 4
        assert result.action in engine.actions
        # Generous bound — the benchmark asserts the real <=200ms median.
        assert elapsed_ms < 1000.0
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
