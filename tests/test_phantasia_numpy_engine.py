# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""NumPy Phantasia engine: JAX-free learning, checkpoint interchange, disclosure."""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from kaine.boot import ConfigurationError, make_phantasia
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.phantasia import rssm_numpy
from kaine.modules.phantasia.encoder import observation_dim
from kaine.modules.phantasia.module import Phantasia
from kaine.modules.phantasia.world_model import (
    CheckpointMismatchError,
    DreamerV3WorldModel,
    NumpyDreamerV3WorldModel,
    load_world_model,
)


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _event(source: str, type_: str, payload=None, salience: float = 0.5) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload or {},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(events, *, inhibited: bool = False, tick: int = 1) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(
        tick_index=tick,
        selected_events=[(f"{i}-0", ev) for i, ev in enumerate(events)],
        inhibited=inhibited,
    )


async def _drain(bus: AsyncBus, stream: str = "phantasia.out") -> list[Event]:
    entries = await bus.read(stream, last_id="0")
    return [e for _, e in entries]


def _random_observations(steps: int, dim: int, seed: int) -> list[list[float]]:
    rng = np.random.default_rng(seed)
    arr = np.clip(rng.normal(0.5, 0.2, size=(steps, dim)), 0.0, 1.0).astype(np.float32)
    return arr.tolist()


def _walk(n: int, dim: int, seed: int) -> np.ndarray:
    """A fixed, reproducible random-walk trajectory, mirroring the JAX test."""
    return np.cumsum(np.random.default_rng(seed).normal(size=(n, dim)) * 0.25, axis=0).astype(np.float32)


def _pred_error(rssm, cfg, params, seq: np.ndarray) -> float:
    """Mean one-step predict_next_obs error along the trajectory."""
    state = rssm.initial_state(cfg)
    errs = []
    for t in range(seq.shape[0] - 1):
        pred = rssm.predict_next_obs(cfg, params, state)
        errs.append(float(np.mean(np.abs(pred - seq[t + 1]))))
        state = rssm.observe_step(cfg, params, state, seq[t])
    return sum(errs) / max(1, len(errs))


# ---------------------------------------------------------------------------
# 1. Learning without JAX
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("latent_kind", ["categorical", "gaussian"])
def test_learning_without_jax_trains_prior_and_improves_prediction(latent_kind):
    cfg = rssm_numpy.RSSMConfig(
        obs_dim=8,
        deter_dim=24,
        stoch_dim=16,
        stoch_classes=8,
        hidden_dim=24,
        latent_kind=latent_kind,
        learning_rate=3e-3,
    )
    init = rssm_numpy.init_params(cfg, seed=5)
    seq = _walk(12, cfg.obs_dim, seed=11)

    params = init
    losses = []
    for _ in range(120):
        result = rssm_numpy.sgd_update(cfg, params, seq, steps=1)
        assert not result.aborted, result.reason
        params = result.params
        losses.append(result.loss)

    assert losses[-1] < losses[0] * 0.9, (
        f"loss did not decrease: {losses[0]:.4f} -> {losses[-1]:.4f}"
    )

    for head in ("prior1", "prior_out"):
        delta = float(np.max(np.abs(params[head]["w"] - init[head]["w"])))
        assert delta > 1e-4, f"prior head {head!r} did not train (max |Δw|={delta:.2e})"

    err_before = _pred_error(rssm_numpy, cfg, init, seq)
    err_after = _pred_error(rssm_numpy, cfg, params, seq)
    assert err_after < err_before, (
        f"prediction error did not improve: {err_before:.4f} -> {err_after:.4f}"
    )


@pytest.mark.parametrize("latent_kind", ["categorical", "gaussian"])
def test_long_training_matches_jax(latent_kind):
    """Long-horizon evidence that the NumPy engine trains the same model as JAX."""
    jax = pytest.importorskip("jax")
    jnp = jax.numpy
    jrssm = pytest.importorskip("external.dreamerv3.rssm")

    cfg = rssm_numpy.RSSMConfig(
        obs_dim=8,
        deter_dim=24,
        stoch_dim=16,
        stoch_classes=8,
        hidden_dim=24,
        latent_kind=latent_kind,
        learning_rate=3e-3,
    )
    jcfg = jrssm.RSSMConfig(
        obs_dim=cfg.obs_dim,
        deter_dim=cfg.deter_dim,
        stoch_dim=cfg.stoch_dim,
        stoch_classes=cfg.stoch_classes,
        hidden_dim=cfg.hidden_dim,
        latent_kind=cfg.latent_kind,
        learning_rate=cfg.learning_rate,
    )

    np_params = rssm_numpy.init_params(cfg, seed=5)
    jax_params = jax.tree_util.tree_map(
        lambda x: jnp.asarray(x, dtype=jnp.float32), np_params
    )
    seq = _walk(12, cfg.obs_dim, seed=11)
    seq_jax = jnp.asarray(seq, dtype=jnp.float32)

    def assert_nested_allclose(left, right, prefix):
        for key in left:
            path = f"{prefix}/{key}"
            if isinstance(left[key], dict):
                assert isinstance(right[key], dict)
                assert_nested_allclose(left[key], right[key], path)
            else:
                np.testing.assert_allclose(
                    np.asarray(left[key]),
                    np.asarray(right[key]),
                    atol=1e-5,
                    err_msg=f"leaf {path}",
                )

    def jax_pred_error(rssm, cfg_, params, trajectory):
        state = rssm.initial_state(cfg_)
        errs = []
        for t in range(trajectory.shape[0] - 1):
            pred = rssm.predict_next_obs(cfg_, params, state)
            errs.append(float(jnp.mean(jnp.abs(pred - trajectory[t + 1]))))
            state = rssm.observe_step(cfg_, params, state, trajectory[t])
        return sum(errs) / max(1, len(errs))

    np_p = np_params
    jax_p = jax_params
    for step in range(120):
        np_res = rssm_numpy.sgd_update(cfg, np_p, seq, steps=1)
        jax_res = jrssm.sgd_update(jcfg, jax_p, seq_jax, steps=1)
        assert not np_res.aborted, np_res.reason
        assert not getattr(jax_res, "aborted", False), getattr(jax_res, "reason", "")
        np.testing.assert_allclose(
            float(np_res.loss),
            float(jax_res.loss),
            rtol=1e-4,
            err_msg=f"loss mismatch at step {step}",
        )
        np_p = np_res.params
        jax_p = jax_res.params

    assert_nested_allclose(np_p, jax_p, "params")

    np_err = _pred_error(rssm_numpy, cfg, np_p, seq)
    jax_err = jax_pred_error(jrssm, jcfg, jax_p, seq_jax)
    np.testing.assert_allclose(
        np_err, jax_err, atol=1e-5, err_msg="final prediction error"
    )


# ---------------------------------------------------------------------------
# 2 & 3. Checkpoint interchange
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("direction", ["jax_to_numpy", "numpy_to_jax"])
def test_checkpoint_interchange_between_engines(direction: str):
    pytest.importorskip("jax")
    kwargs = dict(
        obs_dim=6,
        deter_dim=8,
        stoch_dim=4,
        stoch_classes=3,
        hidden_dim=8,
    )
    train_seq = _random_observations(10, kwargs["obs_dim"], seed=1)
    test_seq = _random_observations(5, kwargs["obs_dim"], seed=2)

    if direction == "jax_to_numpy":
        src = DreamerV3WorldModel(**kwargs)
        dst = NumpyDreamerV3WorldModel(**kwargs)
    else:
        src = NumpyDreamerV3WorldModel(**kwargs)
        dst = DreamerV3WorldModel(**kwargs)

    for _ in range(3):
        outcome = src.train(train_seq)
        assert outcome.learned and not outcome.aborted

    blob = src.export_params(extra={"encoder_version": 1})
    dst.import_params(blob, extra={"encoder_version": 1})

    src.reset_state()
    dst.reset_state()
    for obs in test_seq:
        e_src = src.observe(obs)
        e_dst = dst.observe(obs)
        assert abs(e_src - e_dst) <= 1e-5, (
            f"engine mismatch {direction}: {e_src:.6f} vs {e_dst:.6f}"
        )


# ---------------------------------------------------------------------------
# 4. Mismatch fails closed on the NumPy adapter
# ---------------------------------------------------------------------------


def test_numpy_adapter_fails_closed_on_checkpoint_mismatch():
    kwargs = dict(
        obs_dim=6,
        deter_dim=8,
        stoch_dim=4,
        stoch_classes=3,
        hidden_dim=8,
    )
    a = NumpyDreamerV3WorldModel(**kwargs)
    blob = a.export_params()

    b = NumpyDreamerV3WorldModel(**{**kwargs, "deter_dim": 16})
    before = b.export_params()

    with pytest.raises(CheckpointMismatchError):
        b.import_params(blob)

    after = b.export_params()
    assert before == after, "importer parameters changed after a failed import"


# ---------------------------------------------------------------------------
# 5. load_world_model engine dispatch
# ---------------------------------------------------------------------------


def test_load_world_model_selects_numpy_and_rejects_bogus_engine():
    kwargs = dict(
        deter_dim=8,
        stoch_dim=4,
        stoch_classes=3,
        hidden_dim=8,
    )
    numpy_wm = load_world_model("dreamerv3", 6, engine="numpy", **kwargs)
    assert isinstance(numpy_wm, NumpyDreamerV3WorldModel)

    with pytest.raises(ValueError, match=r"unknown phantasia engine 'bogus'"):
        load_world_model("dreamerv3", 6, engine="bogus", **kwargs)

    fake_wm = load_world_model("fake", 6, engine="bogus")
    assert fake_wm is not None


# ---------------------------------------------------------------------------
# 6. make_phantasia engine validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_make_phantasia_builds_numpy_engine_and_rejects_invalid(bus: AsyncBus):
    section = {
        "backend": "dreamerv3",
        "engine": "numpy",
        "training_enabled": False,
        "trajectory_buffer_size": 64,
        "rollout_horizon": 4,
    }
    ph = make_phantasia(bus, section)
    assert isinstance(ph._wm, NumpyDreamerV3WorldModel)

    with pytest.raises(
        ConfigurationError,
        match=r'\[phantasia\].engine must be "jax" or "numpy", got \'cuda\'',
    ):
        make_phantasia(bus, {**section, "engine": "cuda"})


# ---------------------------------------------------------------------------
# 7. Disclosure: backend + engine in world_error payload
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disclosure_publishes_backend_and_engine(bus: AsyncBus):
    ph = Phantasia(bus, backend="dreamerv3", engine="numpy")
    await ph.initialize()
    try:
        await ph.on_workspace(_snapshot([_event("soma", "soma.report", salience=0.4)]))
        events = await _drain(bus)
        we = [e for e in events if e.type == "phantasia.world_error"]
        assert we
        assert we[-1].payload["backend"] == "dreamerv3"
        assert we[-1].payload["engine"] == "numpy"
    finally:
        await ph.shutdown()

    ph2 = Phantasia(bus, backend="fake")
    await ph2.initialize()
    try:
        await ph2.on_workspace(_snapshot([_event("soma", "soma.report", salience=0.4)]))
        events = await _drain(bus)
        we = [e for e in events if e.type == "phantasia.world_error"]
        assert we
        assert we[-1].payload["backend"] == "fake"
        assert we[-1].payload["engine"] is None
    finally:
        await ph2.shutdown()


# ---------------------------------------------------------------------------
# 8. JAX-free subprocess
# ---------------------------------------------------------------------------


def test_jax_free_subprocess_runs_numpy_engine():
    root = Path(__file__).resolve().parent.parent
    existing_pp = os.environ.get("PYTHONPATH", "")
    sep = os.pathsep
    new_pp = f"{root}{sep}{existing_pp}" if existing_pp else str(root)

    script = r'''
import sys

class _JaxBlocker:
    def find_spec(self, name, path, target=None):
        root = name.split(".")[0]
        if root in ("jax", "jaxlib", "optax", "chex", "equinox"):
            raise ModuleNotFoundError(f"{name} is blocked in this subprocess")
        return None

sys.meta_path.insert(0, _JaxBlocker())

import numpy as np
from kaine.modules.phantasia.world_model import load_world_model

obs_dim = 6
wm = load_world_model(
    "dreamerv3", obs_dim, engine="numpy",
    deter_dim=8, stoch_dim=4, stoch_classes=3, hidden_dim=8,
)

rng = np.random.default_rng(7)
obs_seq = np.clip(rng.normal(0.5, 0.2, size=(5, obs_dim)), 0, 1).astype(np.float32).tolist()
for obs in obs_seq:
    err = wm.observe(obs)
    assert 0.0 <= err <= 1.0

imagined = wm.imagine(3)
assert len(imagined) == 3
assert all(len(row) == obs_dim for row in imagined)

train_seq = np.clip(rng.normal(0.5, 0.2, size=(10, obs_dim)), 0, 1).astype(np.float32).tolist()
outcome = wm.train(train_seq)
assert outcome.learned and not outcome.aborted

blob = wm.export_params()
wm2 = load_world_model(
    "dreamerv3", obs_dim, engine="numpy",
    deter_dim=8, stoch_dim=4, stoch_classes=3, hidden_dim=8,
)
wm2.import_params(blob)
print("numpy-engine-jax-free-ok")
'''
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(root),
        env={**os.environ, "PYTHONPATH": new_pp},
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "numpy-engine-jax-free-ok" in result.stdout


# ---------------------------------------------------------------------------
# 9. Latency budget
# ---------------------------------------------------------------------------


def test_numpy_observe_latency_and_train_budget():
    obs_dim = observation_dim()
    wm = NumpyDreamerV3WorldModel(obs_dim)
    rng = np.random.default_rng(99)
    obs = np.clip(rng.normal(0.5, 0.2, size=(obs_dim,)), 0, 1).astype(np.float32).tolist()

    for _ in range(3):
        wm.observe(obs)

    times = []
    for _ in range(50):
        t0 = time.perf_counter()
        wm.observe(obs)
        times.append(time.perf_counter() - t0)
    median = float(np.median(times))
    assert median < 0.005, f"median observe {median * 1000:.2f} ms >= 5 ms"

    train_seq = np.clip(
        rng.normal(0.5, 0.2, size=(512, obs_dim)), 0, 1
    ).astype(np.float32).tolist()
    t0 = time.perf_counter()
    outcome = wm.train(train_seq)
    elapsed = time.perf_counter() - t0
    assert not outcome.aborted
    assert elapsed < 3.0, f"train(512) took {elapsed:.2f} s >= 3 s"
