# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Learned-agency tests for Nous (real pymdp 1.0 + JAX).

Tests that exercise :class:`PymdpEngine` are gated exactly like the real-pymdp
tests in ``test_nous_engine.py``: they are skipped when the ``reasoning`` extra
is not installed. The FakeEngine smoke test runs in every environment.
"""
from __future__ import annotations

import asyncio
import logging

import numpy as np
import pytest

from kaine.modules.nous.engine import FakeEngine, PymdpEngine
from kaine.modules.nous.generative_model import (
    ACTION_FACTOR,
    SALIENCE_FACTOR,
)


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


def _default_obs(prev_action: int | None, salience: int) -> list[int]:
    return [prev_action if prev_action is not None else 0, salience, 1, 2]


class _Ev:
    def __init__(self, source, payload, salience):
        self.source = source
        self.payload = payload
        self.salience = salience


class _Snap:
    def __init__(self, events):
        self.selected_events = [(str(i), e) for i, e in enumerate(events)]


def _snap(salience=0.9):
    return _Snap([_Ev("soma", {}, salience)])


@pytestmark_real
def test_golden_diversity_chooses_more_than_one_action():
    engine = PymdpEngine(efe_timeout_ms=10_000.0)
    try:
        prev = None
        chosen = []
        for t in range(40):
            sal = 1 if t % 2 == 0 else 2
            obs = _default_obs(prev, sal)
            result = engine.infer(obs)
            chosen.append(result.action_index)
            prev = result.action_index
        assert len(set(chosen)) > 1
    finally:
        engine.close()


@pytestmark_real
def test_learning_concentrates_transition_belief_and_favours_action():
    engine = PymdpEngine(efe_timeout_ms=10_000.0)
    try:
        prev = None
        sal = 1
        chosen = []
        for _ in range(60):
            obs = _default_obs(prev, sal)
            result = engine.infer(obs)
            a = result.action_index
            chosen.append(a)
            prev = a
            # action 1 reliably raises the salience band next step.
            sal = 2 if a == 1 else 1
        counts = np.bincount(chosen, minlength=engine.model.num_actions)
        state = engine.learned_state()
        pB_sal = np.asarray(state["pB"][SALIENCE_FACTOR])
        # From state 1 (medium) under action 1, more mass moves to state 2 (high)
        # than stays at state 1.
        assert pB_sal[2, 1, 1] > pB_sal[1, 1, 1]
        assert counts[1] > max(counts[0], counts[2], counts[3])
    finally:
        engine.close()


@pytestmark_real
def test_carried_prior_matches_propagated_posterior():
    import jax.numpy as jnp

    engine = PymdpEngine(efe_timeout_ms=10_000.0)
    try:
        engine.infer(_default_obs(None, 2))
        result = engine.infer(_default_obs(engine._prev_action, 1))
        a = result.action_index
        row_a = jnp.asarray(engine._policies[a : a + 1, 0, :])
        manual_prior = engine._agent.update_empirical_prior(row_a, engine._prev_qs)
        for p, m in zip(engine._prior, manual_prior):
            np.testing.assert_allclose(np.asarray(p), np.asarray(m), atol=1e-6)
    finally:
        engine.close()


@pytestmark_real
def test_preservation_restores_pB_and_next_decision():
    engine = PymdpEngine(efe_timeout_ms=10_000.0)
    try:
        for _ in range(5):
            engine.infer(_default_obs(None, 2))
        state = engine.learned_state()
        next_obs = _default_obs(engine._prev_action, 1)
        expected = engine.infer(next_obs).action_index

        engine2 = PymdpEngine(engine.model, efe_timeout_ms=10_000.0)
        try:
            assert engine2.load_learned_state(state)
            actual = engine2.infer(next_obs).action_index
            assert actual == expected
            state2 = engine2.learned_state()
            for pb1, pb2 in zip(state["pB"], state2["pB"]):
                np.testing.assert_allclose(pb1, pb2, atol=1e-12)
        finally:
            engine2.close()
    finally:
        engine.close()


@pytestmark_real
def test_load_learned_state_rejects_invalid_pB_and_changes_nothing():
    engine = PymdpEngine(efe_timeout_ms=10_000.0)
    try:
        for _ in range(3):
            engine.infer(_default_obs(None, 2))
        good = engine.learned_state()
        original_prior = [np.asarray(p).copy() for p in engine._prior]

        bad_state = {**good, "pB": [np.zeros((2, 2)) for _ in good["pB"]]}
        assert not engine.load_learned_state(bad_state)

        bad_pB = [np.asarray(pb).copy() for pb in good["pB"]]
        bad_pB[0][0, 0, 0] = -1.0
        assert not engine.load_learned_state({**good, "pB": bad_pB})

        bad_pB2 = [np.asarray(pb).copy() for pb in good["pB"]]
        bad_pB2[0][0, 0, 0] = float("inf")
        assert not engine.load_learned_state({**good, "pB": bad_pB2})

        for p, orig in zip(engine._prior, original_prior):
            np.testing.assert_array_equal(np.asarray(p), orig)
    finally:
        engine.close()


@pytestmark_real
def test_timeout_leaves_learning_and_prior_unchanged():
    engine = PymdpEngine(efe_timeout_ms=0.001)
    try:
        initial_prior = [np.asarray(p).copy() for p in engine._prior]
        result = engine.infer(_default_obs(None, 2))
        assert result.timed_out
        for p, init in zip(engine._prior, initial_prior):
            np.testing.assert_allclose(np.asarray(p), init, atol=1e-12)
        state = engine.learned_state()
        for pb, model_pb in zip(state["pB"], engine.model.pB):
            np.testing.assert_allclose(pb, model_pb, atol=1e-12)
    finally:
        engine.close()


def test_module_serialize_and_deserialize_logs_info_when_no_learned_state(
    caplog,
):
    from kaine.bus.client import AsyncBus
    from kaine.bus.config import BusConfig
    from kaine.modules.nous.module import Nous

    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    try:
        caplog.set_level(logging.INFO)
        engine = FakeEngine()
        module = Nous(bus, engine=engine)
        state = module.serialize()
        assert "learned" in state
        assert state["learned"] == {}
        module.deserialize({})
        assert any(
            "snapshot has no learned model of its actions; starting from the prior"
            in rec.message
            for rec in caplog.records
        )
        # A learned key on a FakeEngine is a no-op and does not break.
        module.deserialize({"learned": {"pB": []}})
    finally:
        asyncio.run(bus.close())


def test_first_step_row_follows_the_policys_first_action_at_horizon_two():
    pytest.importorskip("pymdp")
    from kaine.modules.nous.engine import PymdpEngine
    from kaine.modules.nous.generative_model import ACTION_FACTOR

    engine = PymdpEngine(policy_len=2, efe_timeout_ms=10_000.0)
    try:
        for a in range(engine.model.num_actions):
            row = engine._first_step_row(a)
            assert int(row[0, ACTION_FACTOR]) == a
        # A two-step engine learns and propagates without error.
        for _ in range(3):
            r = engine.infer([0, 1, 1, 2])
            assert not r.error and not r.timed_out
    finally:
        engine.close()


@pytestmark_real
def test_live_path_observes_prev_action_and_keeps_action_factor_fixed():
    engine = PymdpEngine(efe_timeout_ms=10_000.0)
    try:
        prev_action = 0
        for t in range(60):
            salience = 0.9 if t % 2 == 0 else 0.2
            result = engine.step(_snap(salience))
            assert np.argmax(result.posterior[ACTION_FACTOR]) == prev_action
            prev_action = result.action_index
        pB0 = np.asarray(engine._agent.pB[ACTION_FACTOR])
        if pB0.ndim == 4 and pB0.shape[0] == 1:
            pB0 = pB0[0]
        np.testing.assert_array_equal(pB0, engine.model.B[ACTION_FACTOR])
    finally:
        engine.close()


@pytestmark_real
def test_revive_reproduces_per_action_efe():
    engine = PymdpEngine(efe_timeout_ms=10_000.0)
    try:
        prev = None
        sal = 1
        for _ in range(200):
            obs = _default_obs(prev, sal)
            result = engine.infer(obs)
            prev = result.action_index
            sal = 2 if prev == 1 else 1
        state = engine.learned_state()
        next_obs = _default_obs(engine._prev_action, 1)
        original_efe = engine.infer(next_obs).policy_efe

        engine2 = PymdpEngine(engine.model, efe_timeout_ms=10_000.0)
        try:
            assert engine2.load_learned_state(state)
            revived_efe = engine2.infer(next_obs).policy_efe
            np.testing.assert_allclose(original_efe, revived_efe, atol=1e-5)
        finally:
            engine2.close()
    finally:
        engine.close()


@pytestmark_real
def test_load_learned_state_rejects_zero_column_pB():
    engine = PymdpEngine(efe_timeout_ms=10_000.0)
    try:
        for _ in range(3):
            engine.infer(_default_obs(None, 2))
        good = engine.learned_state()
        original_prior = [np.asarray(p).copy() for p in engine._prior]
        original_agent_pB = [np.asarray(pb).copy() for pb in engine._agent.pB]

        bad_pB = [np.asarray(pb).copy() for pb in good["pB"]]
        bad_pB[1][:, 0, 0] = 0.0
        assert not engine.load_learned_state({**good, "pB": bad_pB})

        for p, orig in zip(engine._prior, original_prior):
            np.testing.assert_array_equal(np.asarray(p), orig)
        for pb, orig in zip(engine._agent.pB, original_agent_pB):
            np.testing.assert_array_equal(np.asarray(pb), orig)
    finally:
        engine.close()


@pytestmark_real
def test_record_taken_action_updates_carried_prior():
    import jax.numpy as jnp

    engine = PymdpEngine(efe_timeout_ms=10_000.0)
    try:
        result = engine.infer(_default_obs(None, 2))
        a = result.action_index
        b = (a + 1) % engine.model.num_actions
        engine.record_taken_action(b)
        assert engine._prev_action == b
        row_b = jnp.asarray(engine._first_step_row(b))
        expected_prior = engine._agent.update_empirical_prior(
            row_b, engine._prev_qs_committed
        )
        for p, e in zip(engine._prior, expected_prior):
            np.testing.assert_allclose(np.asarray(p), np.asarray(e), atol=1e-6)
    finally:
        engine.close()


@pytestmark_real
def test_transition_concentration_cap_bounds_evidence():
    from kaine.modules.nous.generative_model import build_generative_model

    model = build_generative_model(transition_max_concentration=3.0)
    engine = PymdpEngine(model, efe_timeout_ms=10_000.0)
    try:
        prev = None
        sal = 1
        for _ in range(50):
            obs = _default_obs(prev, sal)
            result = engine.infer(obs)
            prev = result.action_index
            sal = 2 if prev == 1 else 1
        for f in range(1, model.num_factors):
            pb = np.asarray(engine._agent.pB[f])
            if pb.ndim == 4 and pb.shape[0] == 1:
                pb = pb[0]
            b = np.asarray(engine._agent.B[f])
            if b.ndim == 4 and b.shape[0] == 1:
                b = b[0]
            col_sums = pb.sum(axis=0)
            assert np.all(col_sums <= 3.0 + 1e-4)
            expected_b = pb / col_sums[None, :, :]
            np.testing.assert_allclose(b, expected_b, atol=1e-6)
    finally:
        engine.close()


@pytestmark_real
def test_generation_race_drops_stale_result():
    engine = PymdpEngine(efe_timeout_ms=10_000.0)
    try:
        for _ in range(5):
            engine.infer(_default_obs(None, 2))

        engine2 = PymdpEngine(engine.model, efe_timeout_ms=10_000.0)
        try:
            for _ in range(10):
                engine2.infer(_default_obs(None, 1))
            state2 = engine2.learned_state()
        finally:
            engine2.close()

        original_infer = engine._infer

        def _infer_that_loads_mid_flight(obs):
            result = original_infer(obs)
            engine.load_learned_state(state2)
            return result

        engine._infer = _infer_that_loads_mid_flight
        engine.infer(_default_obs(engine._prev_action, 1))

        for pb_loaded, pb_self in zip(state2["pB"], engine.learned_state()["pB"]):
            np.testing.assert_allclose(pb_loaded, pb_self, atol=1e-12)
        for p_loaded, p_self in zip(state2["carried_prior"], engine._prior):
            np.testing.assert_allclose(
                p_loaded, np.asarray(p_self).reshape(-1), atol=1e-12
            )
    finally:
        engine.close()
