# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the NumPy-only Nous active-inference backend."""
from __future__ import annotations

import json
import math
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from kaine.modules.nous.generative_model import build_generative_model
from kaine.modules.nous.numpy_engine import NumpyActiveInferenceEngine


def _fixture_path(name: str) -> Path:
    return Path(__file__).parent / "fixtures" / "nous_golden" / name


def _pymdp_available() -> bool:
    try:
        import jax  # noqa: F401
        import pymdp  # noqa: F401

        return True
    except Exception:
        return False


def test_live_learning_replay() -> None:
    """The NumPy engine reproduces the golden live-learning trajectory."""
    engine = NumpyActiveInferenceEngine()
    fixture = json.loads(_fixture_path("live_learning.json").read_text())
    last_step = None
    for step in fixture["steps"]:
        obs = [int(o) for o in step["obs"]]
        result = engine.infer(obs)
        last_step = step

        assert result.action_index == int(step["action_index"])
        assert len(result.policy_efe) == len(step["policy_efe"])
        for got, exp in zip(result.policy_efe, step["policy_efe"]):
            assert (math.isinf(got) and math.isinf(exp)) or abs(got - float(exp)) < 1e-4

    assert last_step is not None
    state = engine.learned_state()

    if "pB_after" in last_step and last_step["pB_after"] is not None:
        for got, exp in zip(state["pB"], last_step["pB_after"]):
            np.testing.assert_allclose(
                np.asarray(got, dtype=np.float64),
                np.asarray(exp, dtype=np.float64),
                rtol=1e-4,
                atol=1e-4,
            )

    if (
        "carried_prior_after" in last_step
        and last_step["carried_prior_after"] is not None
    ):
        for got, exp in zip(state["carried_prior"], last_step["carried_prior_after"]):
            np.testing.assert_allclose(
                np.asarray(got, dtype=np.float64),
                np.asarray(exp, dtype=np.float64),
                atol=1e-4,
            )

    engine.close()


@pytest.mark.skipif(not _pymdp_available(), reason="reasoning extra (pymdp/jax) not installed")
def test_cross_engine_learned_state_interchange() -> None:
    """Pymdp and NumPy engines can load each other's learned states."""
    from kaine.modules.nous.engine import PymdpEngine

    model = build_generative_model()
    # This compares the engines' learning, not their planning deadline. At the
    # default 250 ms, a step slowed by parallel load (JAX compiles on first use)
    # times out, keeps the last posterior and skips learning, so the two engines
    # diverge for a reason unrelated to interchange.
    no_deadline_ms = 60_000.0
    numpy_engine = NumpyActiveInferenceEngine(model, efe_timeout_ms=no_deadline_ms)
    pymdp_engine = PymdpEngine(model, efe_timeout_ms=no_deadline_ms)

    sequence = [
        [0, 1, 2, 3],
        [0, 2, 1, 3],
        [0, 1, 1, 3],
    ]
    for obs in sequence:
        assert not numpy_engine.infer(obs).timed_out
        assert not pymdp_engine.infer(obs).timed_out

    # NumPy -> pymdp
    state = numpy_engine.learned_state()
    assert pymdp_engine.load_learned_state(state)

    probe_obs = [0, 2, 2, 3]
    r_pymdp = pymdp_engine.infer(probe_obs)
    r_numpy = numpy_engine.infer(probe_obs)
    np.testing.assert_allclose(r_pymdp.policy_efe, r_numpy.policy_efe, atol=1e-4)
    assert r_pymdp.action_index == r_numpy.action_index

    # pymdp -> NumPy
    state2 = pymdp_engine.learned_state()
    numpy_engine2 = NumpyActiveInferenceEngine(model, efe_timeout_ms=no_deadline_ms)
    assert numpy_engine2.load_learned_state(state2)

    r_numpy2 = numpy_engine2.infer(probe_obs)
    r_pymdp2 = pymdp_engine.infer(probe_obs)
    np.testing.assert_allclose(r_numpy2.policy_efe, r_pymdp2.policy_efe, atol=1e-4)
    assert r_numpy2.action_index == r_pymdp2.action_index

    numpy_engine.close()
    pymdp_engine.close()
    numpy_engine2.close()


def test_timeout_path() -> None:
    """A slow backend cycle triggers the shared timeout guard."""
    engine = NumpyActiveInferenceEngine()
    engine._efe_timeout_s = 0.001
    real_cycle = engine._cycle

    def slow_cycle(agent: Any, obs: list[int], prior: Any) -> tuple[Any, np.ndarray]:
        time.sleep(0.2)
        return real_cycle(agent, obs, prior)

    engine._cycle = slow_cycle  # type: ignore[assignment]
    obs = [0] * engine.model.num_modalities
    result = engine.infer(obs)
    assert result.timed_out
    assert not result.error
    engine.close()


def test_record_taken_action() -> None:
    """Recording a different action re-propagates the carried prior under it."""
    engine = NumpyActiveInferenceEngine()
    try:
        result = engine.infer([0, 1, 2, 3])
        taken = (result.action_index + 1) % engine.model.num_actions
        engine.record_taken_action(taken)
        assert engine._prev_action == taken
        expected = engine._propagate(
            engine._agent, engine._first_step_row(taken), engine._prev_qs_committed
        )
        for got, exp in zip(engine._prior, expected):
            np.testing.assert_allclose(np.asarray(got), np.asarray(exp), atol=1e-12)
    finally:
        engine.close()


def test_generation_guard() -> None:
    """A step that crosses load_learned_state is dropped, not committed."""
    engine = NumpyActiveInferenceEngine()
    seed_obs = [0, 1, 2, 3]
    engine.infer(seed_obs)
    snapshot = engine.learned_state()

    real_cycle = engine._cycle
    engine._efe_timeout_s = 1.0

    def slow_cycle(agent: Any, obs: list[int], prior: Any) -> tuple[Any, np.ndarray]:
        time.sleep(0.3)
        return real_cycle(agent, obs, prior)

    engine._cycle = slow_cycle  # type: ignore[assignment]

    result_holder: list[object] = []

    def runner() -> None:
        result_holder.append(engine.infer([0, 0, 2, 3]))

    t = threading.Thread(target=runner)
    t.start()
    time.sleep(0.05)
    # This increments the generation while the first infer is still in-flight.
    assert engine.load_learned_state(snapshot)
    t.join(timeout=2.0)

    result = result_holder[0]
    assert isinstance(result, object)  # typing shim
    # The stale result is dropped and does not commit the inference action.
    typed = result  # type: ignore[unbound]
    assert typed.action_index == 0
    assert not typed.timed_out
    assert not typed.error
    engine.close()


def test_load_learned_state_rejection() -> None:
    """Invalid learned state is rejected without side effects."""
    engine = NumpyActiveInferenceEngine()
    engine.infer([0, 1, 2, 3])
    before = engine.learned_state()

    bad = {
        "pB": [[[1.0]]],  # wrong shape
        "carried_prior": before["carried_prior"],
        "last_action_index": 0,
    }
    assert not engine.load_learned_state(bad)
    engine.close()


def test_jax_blocked_subprocess() -> None:
    """The NumPy engine can be constructed and stepped with jax/pymdp blocked."""
    script = r'''
import sys

class _JaxBlocker:
    def find_spec(self, name, path, target=None):
        root = name.split(".")[0]
        if root in ("jax", "jaxlib", "equinox", "pymdp"):
            raise ModuleNotFoundError(f"{name} is blocked in this subprocess")
        return None

sys.meta_path.insert(0, _JaxBlocker())

from kaine.modules.nous.numpy_engine import NumpyActiveInferenceEngine
from kaine.modules.nous.generative_model import build_generative_model
from kaine.modules.nous.engine import encode_snapshot_default

engine = NumpyActiveInferenceEngine(build_generative_model())
obs = encode_snapshot_default(engine.model)
for _ in range(3):
    engine.infer(obs)
engine.close()
print("numpy-engine-ok")
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "numpy-engine-ok" in result.stdout


def test_make_nous_selects_numpy_backend() -> None:
    """boot.make_nous honours [nous].backend = "numpy"."""
    from kaine.boot import ConfigurationError, make_nous

    fakeredis = pytest.importorskip("fakeredis.aioredis")
    from kaine.bus.client import AsyncBus, BusConfig

    bus = AsyncBus(
        BusConfig(password="x", audit_required=False),
        client=fakeredis.FakeRedis(decode_responses=True),
    )
    section = {"backend": "numpy", "planning_horizon": 1}
    module = make_nous(bus, section)
    engine = getattr(module, "engine", getattr(module, "_engine", None))
    assert isinstance(engine, NumpyActiveInferenceEngine), type(engine)

    # Unknown backend must raise.
    with pytest.raises(ConfigurationError):
        make_nous(bus, {"backend": "unknown", "planning_horizon": 1})


def test_numpy_backend_has_no_reasoning_requirement() -> None:
    """[nous].backend = "numpy" must not pull in the reasoning extra."""
    from kaine.extras import REQUIREMENTS

    numpy_cfg = {"modules": {"nous": True}, "nous": {"backend": "numpy"}}
    for req in REQUIREMENTS["nous"]:
        pred = getattr(req, "predicate", None)
        if pred is None or pred(numpy_cfg):
            assert req.import_name not in {"pymdp", "jax"}, (
                f"{req.import_name} required for numpy backend"
            )

    # Default/pymdp backend still requires both.
    pymdp_cfg = {"modules": {"nous": True}, "nous": {}}
    required = {
        req.import_name
        for req in REQUIREMENTS["nous"]
        if getattr(req, "predicate", None) is None or req.predicate(pymdp_cfg)
    }
    assert "pymdp" in required
    assert "jax" in required


def test_median_step_latency() -> None:
    """The NumPy engine's median step on the live model is under 200 ms."""
    engine = NumpyActiveInferenceEngine()
    obs = [0] * engine.model.num_modalities

    # Warm-up steps so the first-call overhead is excluded.
    for _ in range(3):
        engine.infer(obs)

    times = [engine.infer(obs).elapsed_ms for _ in range(10)]
    median = statistics.median(times)
    assert median < 200.0, f"median step latency {median:.2f} ms >= 200 ms"
    engine.close()
