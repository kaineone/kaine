# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phantasia world model: FakeWorldModel protocol, rollout, NaN guard, no AC."""
from __future__ import annotations

import math

import pytest

from kaine.modules.phantasia.world_model import (
    FakeWorldModel,
    TrainOutcome,
    WorldModel,
    load_world_model,
)


def test_fake_satisfies_protocol_without_jax():
    wm = FakeWorldModel(obs_dim=5)
    assert isinstance(wm, WorldModel)
    # All protocol methods present and callable without JAX.
    assert callable(wm.observe)
    assert callable(wm.imagine)
    assert callable(wm.train)
    assert callable(wm.reset_state)
    assert callable(wm.parameter_names)


def test_observe_returns_error_in_unit_range():
    wm = FakeWorldModel(obs_dim=4)
    # First observe seeds state → zero error.
    assert wm.observe([1.0, 0.0, 0.0, 0.0]) == 0.0
    err = wm.observe([0.0, 1.0, 0.0, 0.0])
    assert 0.0 <= err <= 1.0
    assert err > 0.0  # the second obs diverges from the first


def test_imagine_rollout_shape():
    wm = FakeWorldModel(obs_dim=6)
    wm.observe([0.5] * 6)
    rollout = wm.imagine(horizon=8)
    assert len(rollout) == 8
    for step in rollout:
        assert len(step) == 6
        assert all(isinstance(v, float) for v in step)


def test_imagine_zero_horizon_is_empty():
    wm = FakeWorldModel(obs_dim=3)
    assert wm.imagine(0) == []


def test_train_returns_outcome():
    wm = FakeWorldModel(obs_dim=3)
    out = wm.train([[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]])
    assert isinstance(out, TrainOutcome)
    assert not out.aborted
    assert out.steps == 2
    assert math.isfinite(out.loss)


def test_train_empty_trajectory_is_noop():
    wm = FakeWorldModel(obs_dim=3)
    out = wm.train([])
    assert out.steps == 0
    assert not out.aborted


def test_nan_loss_aborts_without_corruption():
    wm = FakeWorldModel(obs_dim=3)
    # Train once to move the internal "weight" off its initial value.
    wm.train([[0.1, 0.2, 0.3]])
    good_params = wm.parameter_names()
    good_decay = wm._decay

    # Feed a NaN — training must abort and NOT corrupt in-memory state.
    out = wm.train([[float("nan"), 0.0, 0.0]])
    assert out.aborted
    assert math.isnan(out.loss)
    # In-memory state unchanged (decay restored to last known good).
    assert wm._decay == good_decay
    assert wm.parameter_names() == good_params
    # Model still usable afterward.
    assert 0.0 <= wm.observe([0.1, 0.2, 0.3]) <= 1.0


def test_no_actor_critic_params_after_training():
    wm = FakeWorldModel(obs_dim=4)
    wm.train([[0.1, 0.2, 0.3, 0.4]] * 3)
    names = " ".join(wm.parameter_names()).lower()
    for banned in ("actor", "critic", "policy", "value", "return", "reward"):
        assert banned not in names, f"world model exposes a {banned!r} parameter"


def test_load_world_model_fake_backend():
    wm = load_world_model("fake", obs_dim=7)
    assert isinstance(wm, FakeWorldModel)
    assert wm.obs_dim == 7


def test_load_world_model_unknown_backend_raises():
    with pytest.raises(ValueError, match="unknown phantasia backend"):
        load_world_model("totally-not-real", obs_dim=4)


def test_obs_dim_mismatch_raises():
    wm = FakeWorldModel(obs_dim=4)
    with pytest.raises(ValueError):
        wm.observe([1.0, 2.0])  # wrong width


# ---------------------------------------------------------------------------
# DreamerV3 learning loop (jax-gated): the predictive core must ACTUALLY LEARN.
#
# This is the verification the paper demands of the configuration under test
# (the learning world model). The clean-room RSSM publishes its world error and
# imagines off the PRIOR, so the prior must train, not just the reconstruction
# path. We assert, over repeated sgd_update steps on a FIXED short trajectory:
#   1. the loss decreases,
#   2. the PRIOR heads (prior1 / prior_out) move off their initialisation
#      (they get gradient ONLY from the KL term — the real defect that was
#      fixed: the old reconstruction-only loss never called the prior), and
#   3. predict_next_obs error on the trained sequence drops (the prior learned
#      to predict the next latent, so imagined predictions improve).
# ---------------------------------------------------------------------------


def _walk(rssm, n: int, dim: int, *, seed: int):
    """A fixed, reproducible random-walk trajectory (T, dim) as a jnp array."""
    import jax
    import jax.numpy as jnp

    steps = jax.random.normal(jax.random.PRNGKey(seed), (n, dim)) * 0.25
    return jnp.cumsum(steps, axis=0).astype(jnp.float32)


def _pred_error(rssm, cfg, params, seq) -> float:
    """Mean one-step predict_next_obs error along the trajectory."""
    import jax.numpy as jnp

    state = rssm.initial_state(cfg)
    errs = []
    for t in range(seq.shape[0] - 1):
        pred = rssm.predict_next_obs(cfg, params, state)
        errs.append(float(jnp.mean(jnp.abs(pred - seq[t + 1]))))
        state = rssm.observe_step(cfg, params, state, seq[t])
    return sum(errs) / max(1, len(errs))


@pytest.mark.parametrize("latent_kind", ["categorical", "gaussian"])
def test_dreamerv3_learning_loop_trains_prior_and_improves_prediction(latent_kind):
    pytest.importorskip("jax")
    import jax.numpy as jnp

    from external.dreamerv3 import rssm

    cfg = rssm.RSSMConfig(
        obs_dim=8,
        deter_dim=24,
        stoch_dim=16,
        stoch_classes=8,
        hidden_dim=24,
        latent_kind=latent_kind,
        learning_rate=3e-3,
    )
    init = rssm.init_params(cfg, seed=5)
    seq = _walk(rssm, 12, cfg.obs_dim, seed=11)

    # Train on the fixed trajectory, recording the loss trace.
    params = init
    losses = []
    for _ in range(120):
        result = rssm.sgd_update(cfg, params, seq, steps=1)
        assert not result.aborted, result.reason
        params = result.params
        losses.append(result.loss)

    # 1. The loss decreases meaningfully (not just noise).
    assert losses[-1] < losses[0] * 0.9, (
        f"loss did not decrease: {losses[0]:.4f} -> {losses[-1]:.4f}"
    )

    # 2. The PRIOR heads moved off init — the KL term actually trained them.
    #    (Before the fix the prior received zero gradient and stayed frozen.)
    for head in ("prior1", "prior_out"):
        delta = float(jnp.max(jnp.abs(params[head]["w"] - init[head]["w"])))
        assert delta > 1e-4, f"prior head {head!r} did not train (max |Δw|={delta:.2e})"

    # 3. predict_next_obs error on the trained sequence drops — imagined
    #    predictions (which run off the prior) genuinely improved.
    err_before = _pred_error(rssm, cfg, init, seq)
    err_after = _pred_error(rssm, cfg, params, seq)
    assert err_after < err_before, (
        f"prediction error did not improve: {err_before:.4f} -> {err_after:.4f}"
    )


def test_dreamerv3_loss_is_recon_plus_kl_not_recon_only():
    """The loss must include the prior/posterior KL, not be reconstruction-only.

    Regression guard for the original defect: a reconstruction-only loss leaves
    the prior heads with zero gradient. We verify the KL term is present and
    positive by checking the per-step loss exceeds the pure reconstruction MSE.
    """
    pytest.importorskip("jax")
    import jax.numpy as jnp

    from external.dreamerv3 import rssm

    cfg = rssm.RSSMConfig(
        obs_dim=6, deter_dim=16, stoch_dim=8, stoch_classes=4, hidden_dim=16
    )
    params = rssm.init_params(cfg, seed=2)
    seq = _walk(rssm, 6, cfg.obs_dim, seed=3)

    total = float(rssm.sequence_loss(cfg, params, seq))

    # Reconstruction-only baseline (posterior decode, no KL) for the same params.
    state = rssm.initial_state(cfg)
    recon_total = 0.0
    for t in range(seq.shape[0]):
        state = rssm.observe_step(cfg, params, state, seq[t])
        recon = rssm._decode(params, state.feature())
        recon_total += float(jnp.mean((recon - seq[t]) ** 2))
    recon_only = recon_total / seq.shape[0]

    assert total > recon_only, (
        f"loss ({total:.4f}) is not larger than reconstruction-only "
        f"({recon_only:.4f}); the KL term appears to be missing"
    )


def test_dreamerv3_no_actor_critic_reward_params():
    """Paper invariant: the clean-room core is a PURE world model — no actor,
    critic, reward, return, or continue head anywhere in the param tree."""
    pytest.importorskip("jax")

    from external.dreamerv3 import rssm

    cfg = rssm.RSSMConfig(obs_dim=5)
    names = " ".join(rssm.init_params(cfg, seed=0).keys()).lower()
    for banned in ("actor", "critic", "policy", "value", "return", "reward", "cont"):
        assert banned not in names, f"world-model param tree exposes {banned!r}"
