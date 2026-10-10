# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Parity tests for the NumPy RSSM world-model core.

These tests compare the hand-written NumPy core against golden fixtures recorded
from the JAX core and run a JAX-free finite-difference check on the Gaussian
latent.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

import kaine.modules.phantasia.rssm_numpy as rssm

CASES = [
    "cat_small_t1",
    "cat_small_t16",
    "cat_small_freebits",
    "gauss_small_t16",
    "gauss_small_freebits",
    "cat_shipped",
]


def _fixture_path(name: str) -> Path:
    return (
        Path(__file__).resolve().parent
        / "fixtures"
        / "phantasia_golden"
        / f"{name}.npz"
    )


def _load_case(name: str):
    npz = np.load(_fixture_path(name), allow_pickle=False)

    raw_header = npz["__header__"]
    if raw_header.dtype.kind in ("U", "O"):
        header_str = raw_header.item()
    else:
        header_str = raw_header.tobytes().decode("utf-8")
    header = json.loads(header_str)
    cfg = rssm.RSSMConfig(**header["config"])

    params: dict[str, dict[str, np.ndarray]] = {}
    grads: dict[str, dict[str, np.ndarray]] = {}
    trained: dict[str, dict[str, np.ndarray]] = {}
    for key in npz.files:
        if key.startswith("params/"):
            _, group, name_ = key.split("/")
            params.setdefault(group, {})[name_] = npz[key]
        elif key.startswith("grads/"):
            _, group, name_ = key.split("/")
            grads.setdefault(group, {})[name_] = npz[key]
        elif key.startswith("trained/"):
            _, group, name_ = key.split("/")
            trained.setdefault(group, {})[name_] = npz[key]

    return cfg, params, grads, trained, npz["obs"], npz


@pytest.mark.parametrize("case_name", CASES)
def test_forward_parity(case_name: str) -> None:
    cfg, params, _, _, obs, npz = _load_case(case_name)

    state = rssm.initial_state(cfg)
    preds, deters, stochs = [], [], []
    for t in range(obs.shape[0]):
        preds.append(rssm.predict_next_obs(cfg, params, state))
        state = rssm.observe_step(cfg, params, state, obs[t], rng=None)
        deters.append(state.deter)
        stochs.append(state.stoch)

    pred = np.stack(preds, axis=0) if preds else np.zeros((0, cfg.obs_dim))
    deter = np.stack(deters, axis=0) if deters else np.zeros((0, cfg.deter_dim))
    stoch = np.stack(stochs, axis=0) if stochs else np.zeros((0, cfg.stoch_flat))

    imagine = []
    for _ in range(4):
        state = rssm.imagine_step(cfg, params, state, rng=None)
        imagine.append(rssm.decode(params, state.feature()))
    imagine = np.stack(imagine, axis=0)

    np.testing.assert_allclose(pred, npz["pred"], atol=1e-5, err_msg="pred")
    np.testing.assert_allclose(deter, npz["deter"], atol=1e-5, err_msg="deter")
    np.testing.assert_allclose(stoch, npz["stoch"], atol=1e-5, err_msg="stoch")
    np.testing.assert_allclose(
        imagine, npz["imagine_det"], atol=1e-5, err_msg="imagine_det"
    )


@pytest.mark.parametrize("case_name", CASES)
def test_loss_and_grads_parity(case_name: str) -> None:
    cfg, params, fixture_grads, _, obs, npz = _load_case(case_name)

    loss, grads = rssm.loss_and_grads(cfg, params, obs)
    np.testing.assert_allclose(loss, float(npz["loss"]), rtol=1e-5)

    fixture_keys = {f"grads/{g}/{n}" for g in fixture_grads for n in fixture_grads[g]}
    model_keys = {f"grads/{g}/{n}" for g in grads for n in grads[g]}
    assert model_keys == fixture_keys, f"missing/extra gradient leaves: {model_keys ^ fixture_keys}"

    for key in fixture_keys:
        _, group, name_ = key.split("/")
        np.testing.assert_allclose(
            grads[group][name_],
            fixture_grads[group][name_],
            rtol=1e-4,
            atol=1e-6,
            err_msg=key,
        )


@pytest.mark.parametrize("case_name", CASES)
def test_training_parity(case_name: str) -> None:
    cfg, params, _, _, obs, npz = _load_case(case_name)

    current = {g: {n: p.copy() for n, p in sub.items()} for g, sub in params.items()}
    train_loss = npz["train_loss"]
    for i in range(train_loss.shape[0]):
        result = rssm.sgd_update(cfg, current, obs, steps=1)
        assert not result.aborted, f"step {i} aborted unexpectedly"
        np.testing.assert_allclose(
            result.loss, float(train_loss[i]), rtol=1e-4, err_msg=f"train_loss[{i}]"
        )
        current = result.params

    for key in npz.files:
        if key.startswith("trained/"):
            _, group, name_ = key.split("/")
            np.testing.assert_allclose(
                current[group][name_],
                npz[key],
                atol=1e-5,
                err_msg=key,
            )


def test_maxgrad_convention() -> None:
    assert rssm._maxgrad(0.1, 0.1) == 0.5
    assert rssm._maxgrad(0.2, 0.1) == 1.0
    assert rssm._maxgrad(0.0, 0.1) == 0.0


def test_clipgrad_convention() -> None:
    x = np.array([-5.1, -5.0, -4.9, 2.0, 2.1], dtype=np.float64)
    expected = np.array([0.0, 0.5, 1.0, 0.5, 0.0], dtype=np.float64)
    np.testing.assert_array_equal(rssm._clipgrad(x, -5.0, 2.0), expected)


def _deepcopy_params(
    params: dict[str, dict[str, np.ndarray]],
) -> dict[str, dict[str, np.ndarray]]:
    """Return a deep copy of a nested parameter dictionary."""
    return {g: {n: p.copy() for n, p in sub.items()} for g, sub in params.items()}


def _surrogate_loss(
    cfg: rssm.RSSMConfig,
    params: dict[str, dict[str, np.ndarray]],
    obs: np.ndarray,
    frozen_tape: list,
) -> float:
    """Surrogate loss whose derivative at theta0 equals the stop-gradient gradient."""
    _, live_tape = rssm._forward_sequence(cfg, params, obs)
    T = len(live_tape)
    scale = 1.0 / max(T, 1)
    total = 0.0
    free = float(cfg.kl_free_bits)
    for live, frozen in zip(live_tape, frozen_tape):
        recon_loss = float(np.mean((live.recon - live.obs) ** 2))
        dyn_kl = rssm._gaussian_kl_values(frozen.post_raw, live.prior_raw)["dyn"]
        rep_kl = rssm._gaussian_kl_values(live.post_raw, frozen.prior_raw)["dyn"]
        dyn_c = max(float(dyn_kl), free)
        rep_c = max(float(rep_kl), free)
        kl = cfg.kl_scale * (
            cfg.kl_balance * dyn_c + (1.0 - cfg.kl_balance) * rep_c
        )
        total += recon_loss + kl
    return float(total * scale)


def test_gaussian_surrogate_finite_differences() -> None:
    """Check gradients via central finite differences of a surrogate loss.

    Plain finite differences of sequence_loss cannot match the gradient returned
    by loss_and_grads because DreamerV3's KL balancing applies stop_gradient to
    either the posterior or prior inside the KL terms, so the training gradient
    is not the derivative of the loss value.  The surrogate loss freezes the
    stop-grad inputs to their values at theta0 and lets the remaining parameters
    vary, which makes its derivative at theta0 exactly equal to the
    stop-gradient gradient.
    """
    cfg = rssm.RSSMConfig(
        obs_dim=4,
        deter_dim=5,
        stoch_dim=3,
        hidden_dim=6,
        latent_kind="gaussian",
        kl_free_bits=0.0,
    )
    params = rssm.init_params(cfg, seed=7)
    rng = np.random.default_rng(8)
    params64 = {
        g: {n: p.astype(np.float64) for n, p in sub.items()}
        for g, sub in params.items()
    }
    for sub in params64.values():
        sub["b"] += 0.3 * rng.standard_normal(sub["b"].shape)

    obs = np.random.default_rng(9).uniform(size=(6, cfg.obs_dim)).astype(np.float64)
    _, grads = rssm.loss_and_grads(cfg, params64, obs)

    params64_frozen = _deepcopy_params(params64)
    _, frozen_tape = rssm._forward_sequence(cfg, params64_frozen, obs)

    loss_value = rssm.sequence_loss(cfg, params64, obs)
    surrogate_value = _surrogate_loss(cfg, params64, obs, frozen_tape)
    np.testing.assert_allclose(
        surrogate_value,
        loss_value,
        rtol=1e-12,
        err_msg="surrogate loss must equal sequence_loss at theta0",
    )

    rng_check = np.random.default_rng(10)
    eps = 1e-6
    for g, sub in params64.items():
        for n, p in sub.items():
            flat = p.reshape(-1)
            coords = rng_check.integers(0, flat.size, size=4)
            for idx in coords:
                orig = float(flat[idx])
                flat[idx] = orig + eps
                loss_plus = _surrogate_loss(cfg, params64, obs, frozen_tape)
                flat[idx] = orig - eps
                loss_minus = _surrogate_loss(cfg, params64, obs, frozen_tape)
                flat[idx] = orig
                numeric = (loss_plus - loss_minus) / (2.0 * eps)
                analytic = float(grads[g][n].reshape(-1)[idx])
                np.testing.assert_allclose(
                    numeric,
                    analytic,
                    rtol=1e-4,
                    atol=1e-8,
                    err_msg=f"finite-diff {g}/{n}[{idx}]",
                )


def test_empty_sequence() -> None:
    cfg = rssm.RSSMConfig(
        obs_dim=4,
        deter_dim=5,
        stoch_dim=3,
        hidden_dim=6,
        latent_kind="gaussian",
        kl_free_bits=0.0,
    )
    params = rssm.init_params(cfg, seed=0)
    obs = np.zeros((0, cfg.obs_dim), dtype=np.float64)
    loss, grads = rssm.loss_and_grads(cfg, params, obs)
    assert loss == 0.0
    for sub in grads.values():
        for arr in sub.values():
            assert np.all(arr == 0.0)


def test_nan_obs_aborts_sgd_update() -> None:
    cfg = rssm.RSSMConfig(
        obs_dim=4,
        deter_dim=5,
        stoch_dim=3,
        hidden_dim=6,
        latent_kind="gaussian",
        kl_free_bits=0.0,
    )
    params = rssm.init_params(cfg, seed=11)
    obs = np.full((2, cfg.obs_dim), np.nan, dtype=np.float32)
    result = rssm.sgd_update(cfg, params, obs, steps=1)
    assert result.aborted
    assert result.reason == "non-finite loss"
    assert result.params is params
    for sub in params.values():
        for arr in sub.values():
            assert np.all(np.isfinite(arr))


def test_inf_param_aborts_sgd_update() -> None:
    cfg = rssm.RSSMConfig(
        obs_dim=4,
        deter_dim=5,
        stoch_dim=3,
        hidden_dim=6,
        latent_kind="gaussian",
        kl_free_bits=0.0,
    )
    params = rssm.init_params(cfg, seed=12)
    params["dec2"]["w"][0, 0] = np.inf
    obs = np.random.default_rng(13).uniform(size=(3, cfg.obs_dim)).astype(np.float32)
    result = rssm.sgd_update(cfg, params, obs, steps=1)
    assert result.aborted
    assert result.params is params
    assert np.isinf(params["dec2"]["w"][0, 0])


def test_rollout_sampling_reproducible() -> None:
    cfg = rssm.RSSMConfig(
        obs_dim=5,
        deter_dim=6,
        stoch_dim=4,
        stoch_classes=3,
        hidden_dim=8,
        latent_kind="categorical",
    )
    params = rssm.init_params(cfg, seed=14)
    state = rssm.initial_state(cfg)

    r1 = rssm.rollout(cfg, params, state, 10, seed=14)
    r2 = rssm.rollout(cfg, params, state, 10, seed=14)
    np.testing.assert_array_equal(r1, r2)

    r3 = rssm.rollout(cfg, params, state, 10, seed=15)
    assert not np.array_equal(r1, r3)


def test_rollout_peaked_prior_matches_deterministic() -> None:
    cfg = rssm.RSSMConfig(
        obs_dim=5,
        deter_dim=6,
        stoch_dim=4,
        stoch_classes=3,
        hidden_dim=8,
        latent_kind="categorical",
    )
    params = rssm.init_params(cfg, seed=16)
    b = params["prior_out"]["b"]
    for g in range(cfg.stoch_dim):
        b[g * cfg.stoch_classes] += 50.0

    state = rssm.initial_state(cfg)
    sampled = rssm.rollout(cfg, params, state, 6, seed=17)

    det = []
    st = state
    for _ in range(6):
        st = rssm.imagine_step(cfg, params, st, rng=None)
        det.append(rssm.decode(params, st.feature()))
    det = np.stack(det, axis=0)

    np.testing.assert_allclose(sampled, det, atol=1e-6)


def test_jax_blocked_subprocess() -> None:
    """The NumPy RSSM core can be imported and used with JAX et al. blocked."""
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

import json
import numpy as np
import kaine.modules.phantasia.rssm_numpy as rssm

npz = np.load("tests/fixtures/phantasia_golden/cat_small_t16.npz", allow_pickle=False)
header = json.loads(npz["__header__"].item())
cfg = rssm.RSSMConfig(**header["config"])

params = {}
for key in npz.files:
    if key.startswith("params/"):
        _, g, n = key.split("/")
        params.setdefault(g, {})[n] = npz[key]

obs = npz["obs"]
loss, grads = rssm.loss_and_grads(cfg, params, obs)
assert np.isfinite(loss)

result = rssm.sgd_update(cfg, params, obs, steps=1)
assert not result.aborted
print("rssm-numpy-jax-free-ok")
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
    assert "rssm-numpy-jax-free-ok" in result.stdout
