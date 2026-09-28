# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""NumPy port of ``external/dreamerv3/rssm.py`` for the Phantasia world model.

This module is DERIVED FROM and ATTRIBUTED TO danijar/dreamerv3 (MIT; the pinned
upstream commit is recorded in ``external/dreamerv3/UPSTREAM`` and the upstream
notice is in ``NOTICE``).  It computes exactly the same RSSM world-model forward
pass and sequence loss as the JAX core, including the *gradients* of
``sequence_loss``, using only NumPy and the Python standard library.

What matches the JAX core exactly (within float32/64 round-off):

  * deterministic filtering: ``observe_step``, ``predict_next_obs``,
    ``imagine_step(rng=None)``;
  * ``sequence_loss`` and its gradients produced by
    ``loss_and_grads``;
  * ``sgd_update`` semantics, including NaN/Inf guards and float64 update
    arithmetic.

What intentionally does **not** match the JAX core:

  * random initialisation draws from ``numpy.random.default_rng`` instead of
    JAX's PRNG;
  * sampling during ``rollout`` / ``imagine_step(rng=...)`` uses NumPy's
    Generator (Gumbel-max for categorical latents), not JAX's threefry streams;
  * all internal arithmetic is performed in float64, but parameters are stored
    and returned as float32 so checkpoints stay layout-compatible.

No JAX, jaxlib, optax, chex, equinox or ``external.dreamerv3`` code is imported
or referenced at runtime.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RSSMConfig:
    """Hyper-parameters for the NumPy RSSM world-model core."""

    obs_dim: int
    deter_dim: int = 64
    stoch_dim: int = 16
    stoch_classes: int = 8
    hidden_dim: int = 64
    latent_kind: str = "categorical"
    learning_rate: float = 1e-3
    kl_balance: float = 0.8
    kl_free_bits: float = 0.1
    kl_scale: float = 1.0

    @property
    def stoch_flat(self) -> int:
        if self.latent_kind == "categorical":
            return self.stoch_dim * self.stoch_classes
        return self.stoch_dim

    @property
    def feature_dim(self) -> int:
        return self.deter_dim + self.stoch_flat


@dataclass
class RSSMState:
    """Recurrent + stochastic state at one time step."""

    deter: np.ndarray
    stoch: np.ndarray

    def feature(self) -> np.ndarray:
        return np.concatenate([self.deter, self.stoch], axis=-1)


@dataclass
class TrainResult:
    params: dict[str, dict[str, np.ndarray]]
    loss: float
    aborted: bool = False
    reason: str = ""


# ---------------------------------------------------------------------------
# Random init
# ---------------------------------------------------------------------------


def _latent_param_dim(cfg: RSSMConfig) -> int:
    if cfg.latent_kind == "categorical":
        return cfg.stoch_dim * cfg.stoch_classes
    return cfg.stoch_dim * 2


def _glorot(rng: np.random.Generator, fan_in: int, fan_out: int) -> dict[str, np.ndarray]:
    lim = math.sqrt(6.0 / (fan_in + fan_out))
    w = rng.uniform(-lim, lim, size=(fan_in, fan_out)).astype(np.float32)
    b = np.zeros((fan_out,), dtype=np.float32)
    return {"w": w, "b": b}


def init_params(cfg: RSSMConfig, seed: int = 0) -> dict[str, dict[str, np.ndarray]]:
    """Initialise all world-model parameters as a nested dict of float32 arrays.

    The layer order and shapes match ``external/dreamerv3/rssm.init_params``;
    the random numbers are NumPy's own draws, not JAX's PRNG.
    """
    rng = np.random.default_rng(seed)
    h, s, hid = cfg.deter_dim, cfg.stoch_flat, cfg.hidden_dim

    # Draw in the exact layer order listed in the spec.
    layers = [
        ("enc1", (cfg.obs_dim, hid)),
        ("enc2", (hid, hid)),
        ("gru_z", (s + h, h)),
        ("gru_r", (s + h, h)),
        ("gru_h", (s + h, h)),
        ("prior1", (h, hid)),
        ("prior_out", (hid, _latent_param_dim(cfg))),
        ("post1", (h + hid, hid)),
        ("post_out", (hid, _latent_param_dim(cfg))),
        ("dec1", (cfg.feature_dim, hid)),
        ("dec2", (hid, cfg.obs_dim)),
    ]

    return {name: _glorot(rng, fan_in, fan_out) for name, (fan_in, fan_out) in layers}


# ---------------------------------------------------------------------------
# Core forward helpers
# ---------------------------------------------------------------------------


def _to_float64(arr: np.ndarray) -> np.ndarray:
    return arr.astype(np.float64, copy=False)


def _params_to_float64(params: dict[str, dict[str, np.ndarray]]) -> dict[str, dict[str, np.ndarray]]:
    return {
        group: {name: _to_float64(param) for name, param in sub.items()}
        for group, sub in params.items()
    }


def _state_to_float64(state: RSSMState) -> RSSMState:
    return RSSMState(deter=_to_float64(state.deter), stoch=_to_float64(state.stoch))


def initial_state(cfg: RSSMConfig) -> RSSMState:
    return RSSMState(
        deter=np.zeros((cfg.deter_dim,), dtype=np.float64),
        stoch=np.zeros((cfg.stoch_flat,), dtype=np.float64),
    )


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def _apply_dense(params: dict[str, np.ndarray], x: np.ndarray) -> np.ndarray:
    return x @ params["w"] + params["b"]


def _encode(params: dict[str, dict[str, np.ndarray]], obs: np.ndarray) -> np.ndarray:
    x = np.tanh(_apply_dense(params["enc1"], obs))
    return np.tanh(_apply_dense(params["enc2"], x))


def _gru(
    params: dict[str, dict[str, np.ndarray]],
    deter: np.ndarray,
    gru_in: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """GRU transition; returns (new_deter, cat, z, r, cat_r, cand)."""
    cat = np.concatenate([gru_in, deter], axis=-1)
    z_pre = _apply_dense(params["gru_z"], cat)
    z = _sigmoid(z_pre)
    r_pre = _apply_dense(params["gru_r"], cat)
    r = _sigmoid(r_pre)
    cat_r = np.concatenate([gru_in, r * deter], axis=-1)
    h_pre = _apply_dense(params["gru_h"], cat_r)
    cand = np.tanh(h_pre)
    new_deter = (1.0 - z) * deter + z * cand
    return new_deter, cat, z, r, cat_r, cand


def _latent_sample(
    cfg: RSSMConfig,
    raw: np.ndarray,
    rng: Optional[np.random.Generator],
) -> np.ndarray:
    """Deterministic or sampled stochastic latent vector."""
    if cfg.latent_kind == "categorical":
        logits = raw.reshape((cfg.stoch_dim, cfg.stoch_classes))
        if rng is None:
            idx = np.argmax(logits, axis=-1)
        else:
            idx = np.argmax(logits + rng.gumbel(size=logits.shape), axis=-1)
        sample = np.zeros_like(logits)
        sample[np.arange(cfg.stoch_dim), idx] = 1.0
        return sample.reshape((-1,))
    # gaussian
    mean, log_std = np.split(raw, 2, axis=-1)
    mean = mean.reshape((-1,))
    log_std = log_std.reshape((-1,))
    std = np.exp(np.clip(log_std, -5.0, 2.0))
    if rng is None:
        return mean
    return mean + std * rng.standard_normal(mean.shape)


def _prior(
    cfg: RSSMConfig,
    params: dict[str, dict[str, np.ndarray]],
    deter: np.ndarray,
    rng: Optional[np.random.Generator],
) -> tuple[np.ndarray, np.ndarray]:
    h_pre = _apply_dense(params["prior1"], deter)
    h = np.tanh(h_pre)
    raw = _apply_dense(params["prior_out"], h)
    return _latent_sample(cfg, raw, rng), raw


def _posterior(
    cfg: RSSMConfig,
    params: dict[str, dict[str, np.ndarray]],
    deter: np.ndarray,
    embed: np.ndarray,
    rng: Optional[np.random.Generator],
) -> tuple[np.ndarray, np.ndarray]:
    x = np.concatenate([deter, embed], axis=-1)
    h_pre = _apply_dense(params["post1"], x)
    h = np.tanh(h_pre)
    raw = _apply_dense(params["post_out"], h)
    return _latent_sample(cfg, raw, rng), raw


def _decode(params: dict[str, dict[str, np.ndarray]], feature: np.ndarray) -> np.ndarray:
    x = np.tanh(_apply_dense(params["dec1"], feature))
    return _apply_dense(params["dec2"], x)


def decode(params: dict[str, dict[str, np.ndarray]], feature: np.ndarray) -> np.ndarray:
    """Decode a feature vector back to an observation (float64)."""
    params64 = _params_to_float64(params)
    return _decode(params64, _to_float64(feature))


def observe_step(
    cfg: RSSMConfig,
    params: dict[str, dict[str, np.ndarray]],
    state: RSSMState,
    obs: np.ndarray,
    rng: Optional[np.random.Generator] = None,
) -> RSSMState:
    """One filtering step; observation enters only through the posterior."""
    params64 = _params_to_float64(params)
    st = _state_to_float64(state)
    obs64 = _to_float64(obs)
    embed = _encode(params64, obs64)
    deter, _, _, _, _, _ = _gru(params64, st.deter, st.stoch)
    stoch, _ = _posterior(cfg, params64, deter, embed, rng)
    return RSSMState(deter=deter, stoch=stoch)


def imagine_step(
    cfg: RSSMConfig,
    params: dict[str, dict[str, np.ndarray]],
    state: RSSMState,
    rng: Optional[np.random.Generator] = None,
) -> RSSMState:
    """One prior-only imagination step."""
    params64 = _params_to_float64(params)
    st = _state_to_float64(state)
    deter, _, _, _, _, _ = _gru(params64, st.deter, st.stoch)
    stoch, _ = _prior(cfg, params64, deter, rng)
    return RSSMState(deter=deter, stoch=stoch)


def predict_next_obs(
    cfg: RSSMConfig,
    params: dict[str, dict[str, np.ndarray]],
    state: RSSMState,
) -> np.ndarray:
    """Decode the predicted next observation from one deterministic imagined step."""
    params64 = _params_to_float64(params)
    st = _state_to_float64(state)
    nxt = imagine_step(cfg, params64, st, rng=None)
    return _decode(params64, nxt.feature())


def rollout(
    cfg: RSSMConfig,
    params: dict[str, dict[str, np.ndarray]],
    state: RSSMState,
    horizon: int,
    seed: int = 0,
) -> np.ndarray:
    """Imagine ``horizon`` prior steps and return decoded observations."""
    params64 = _params_to_float64(params)
    st = _state_to_float64(state)
    rng = np.random.default_rng(seed)
    horizon = max(0, int(horizon))
    outs: list[np.ndarray] = []
    for _ in range(horizon):
        st = imagine_step(cfg, params64, st, rng=rng)
        outs.append(_decode(params64, st.feature()))
    if not outs:
        return np.zeros((0, cfg.obs_dim), dtype=np.float64)
    return np.stack(outs, axis=0)


# ---------------------------------------------------------------------------
# Loss and hand-written back-propagation through time
# ---------------------------------------------------------------------------


def _softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    """Stable softmax matching ``jax.nn.softmax``."""
    x = x - np.max(x, axis=axis, keepdims=True)
    e = np.exp(x)
    return e / np.sum(e, axis=axis, keepdims=True)


def _log_softmax(x: np.ndarray, axis: int = -1) -> np.ndarray:
    """Stable log-softmax matching ``jax.nn.log_softmax``."""
    x = x - np.max(x, axis=axis, keepdims=True)
    return x - np.log(np.sum(np.exp(x), axis=axis, keepdims=True))


def _maxgrad(x: float, c: float) -> float:
    """Gradient of ``jnp.maximum(x, c)`` w.r.t. x at equality convention."""
    if x > c:
        return 1.0
    if x == c:
        return 0.5
    return 0.0


def _clipgrad(x: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Gradient of ``jnp.clip(x, lo, hi)`` w.r.t. x at the bounds convention."""
    x = np.asarray(x)
    g = np.where((x > lo) & (x < hi), 1.0, 0.0)
    g = np.where(x == lo, 0.5, g)
    g = np.where(x == hi, 0.5, g)
    return g


def _dense_backward(
    x: np.ndarray,
    W: np.ndarray,
    b: np.ndarray,
    dy: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Backward through ``y = x @ W + b``; matches JAX dense gradient."""
    dW = np.outer(x, dy)
    db = dy.copy()
    dx = dy @ W.T
    return dx, dW, db


def _categorical_kl_values(
    cfg: RSSMConfig,
    post_raw: np.ndarray,
    prior_raw: np.ndarray,
) -> dict[str, Any]:
    logits_p = post_raw.reshape((cfg.stoch_dim, cfg.stoch_classes))
    logits_q = prior_raw.reshape((cfg.stoch_dim, cfg.stoch_classes))
    lp = _log_softmax(logits_p, axis=-1)
    lq = _log_softmax(logits_q, axis=-1)
    p = np.exp(lp)
    q = np.exp(lq)
    kl = np.sum(p * (lp - lq))
    return {
        "kind": "categorical",
        "p": p,
        "q": q,
        "lp": lp,
        "lq": lq,
        "dyn": kl,
        "rep": kl,
    }


def _gaussian_kl_values(
    post_raw: np.ndarray,
    prior_raw: np.ndarray,
) -> dict[str, Any]:
    mp, lsp_raw = np.split(post_raw, 2, axis=-1)
    mq, lsq_raw = np.split(prior_raw, 2, axis=-1)
    lsp = np.clip(lsp_raw, -5.0, 2.0)
    lsq = np.clip(lsq_raw, -5.0, 2.0)
    var_p = np.exp(2.0 * lsp)
    var_q = np.exp(2.0 * lsq)
    kl = lsq - lsp + (var_p + (mp - mq) ** 2) / (2.0 * var_q) - 0.5
    total = np.sum(kl)
    return {
        "kind": "gaussian",
        "post_mean": mp.reshape((-1,)),
        "post_log_std_raw": lsp_raw.reshape((-1,)),
        "post_log_std_clip": lsp.reshape((-1,)),
        "prior_mean": mq.reshape((-1,)),
        "prior_log_std_raw": lsq_raw.reshape((-1,)),
        "prior_log_std_clip": lsq.reshape((-1,)),
        "var_p": var_p.reshape((-1,)),
        "var_q": var_q.reshape((-1,)),
        "dyn": total,
        "rep": total,
    }


class _StepTape:
    __slots__ = (
        "obs",
        "enc_mid_pre",
        "enc_mid",
        "embed_pre",
        "embed",
        "deter_prev",
        "stoch_prev",
        "gru_cat",
        "z",
        "r",
        "cat_r",
        "cand",
        "deter",
        "prior_h_pre",
        "prior_h",
        "prior_raw",
        "post_h_pre",
        "post_h",
        "post_raw",
        "stoch",
        "feature",
        "dec_mid_pre",
        "dec_mid",
        "recon",
        "kl_values",
    )

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


def _forward_sequence(
    cfg: RSSMConfig,
    params64: dict[str, dict[str, np.ndarray]],
    obs_seq: np.ndarray,
) -> tuple[float, list[_StepTape]]:
    T = obs_seq.shape[0]
    state = initial_state(cfg)
    tape: list[_StepTape] = []
    total = 0.0
    scale = 1.0 / max(T, 1)

    for t in range(T):
        obs_t = obs_seq[t]

        # Encoder
        enc_mid_pre = _apply_dense(params64["enc1"], obs_t)
        enc_mid = np.tanh(enc_mid_pre)
        embed_pre = _apply_dense(params64["enc2"], enc_mid)
        embed = np.tanh(embed_pre)

        # GRU
        deter, cat, z, r, cat_r, cand = _gru(params64, state.deter, state.stoch)

        # Prior and posterior (deterministic latent sample for loss)
        prior_h_pre = _apply_dense(params64["prior1"], deter)
        prior_h = np.tanh(prior_h_pre)
        prior_raw = _apply_dense(params64["prior_out"], prior_h)

        post_in = np.concatenate([deter, embed], axis=-1)
        post_h_pre = _apply_dense(params64["post1"], post_in)
        post_h = np.tanh(post_h_pre)
        post_raw = _apply_dense(params64["post_out"], post_h)
        stoch = _latent_sample(cfg, post_raw, rng=None)

        feature = np.concatenate([deter, stoch], axis=-1)
        dec_mid_pre = _apply_dense(params64["dec1"], feature)
        dec_mid = np.tanh(dec_mid_pre)
        recon = _apply_dense(params64["dec2"], dec_mid)

        recon_loss = np.mean((recon - obs_t) ** 2)

        if cfg.latent_kind == "categorical":
            kl_values = _categorical_kl_values(cfg, post_raw, prior_raw)
        else:
            kl_values = _gaussian_kl_values(post_raw, prior_raw)

        dyn = float(kl_values["dyn"])
        rep = float(kl_values["rep"])
        free = cfg.kl_free_bits
        dyn_c = max(dyn, free)
        rep_c = max(rep, free)
        kl = cfg.kl_scale * (cfg.kl_balance * dyn_c + (1.0 - cfg.kl_balance) * rep_c)

        tape.append(
            _StepTape(
                obs=obs_t,
                enc_mid_pre=enc_mid_pre,
                enc_mid=enc_mid,
                embed_pre=embed_pre,
                embed=embed,
                deter_prev=state.deter,
                stoch_prev=state.stoch,
                gru_cat=cat,
                z=z,
                r=r,
                cat_r=cat_r,
                cand=cand,
                deter=deter,
                prior_h_pre=prior_h_pre,
                prior_h=prior_h,
                prior_raw=prior_raw,
                post_h_pre=post_h_pre,
                post_h=post_h,
                post_raw=post_raw,
                stoch=stoch,
                feature=feature,
                dec_mid_pre=dec_mid_pre,
                dec_mid=dec_mid,
                recon=recon,
                kl_values=kl_values,
            )
        )

        total = total + (recon_loss + kl)
        state = RSSMState(deter=deter, stoch=stoch)

    return float(total * scale), tape


def _backward_sequence(
    cfg: RSSMConfig,
    params64: dict[str, dict[str, np.ndarray]],
    tape: list[_StepTape],
) -> dict[str, dict[str, np.ndarray]]:
    T = len(tape)
    scale = 1.0 / max(T, 1)

    grads: dict[str, dict[str, np.ndarray]] = {
        group: {name: np.zeros_like(param) for name, param in sub.items()}
        for group, sub in params64.items()
    }

    d_deter = np.zeros((cfg.deter_dim,), dtype=np.float64)
    d_stoch = np.zeros((cfg.stoch_flat,), dtype=np.float64)

    for t in range(T - 1, -1, -1):
        step = tape[t]

        # --- Reconstruction -------------------------------------------------
        d_recon = 2.0 * (step.recon - step.obs) / cfg.obs_dim * scale

        # decoder2: dense only
        d_dec_mid, dW, db = _dense_backward(
            step.dec_mid,
            params64["dec2"]["w"],
            params64["dec2"]["b"],
            d_recon,
        )
        grads["dec2"]["w"] += dW
        grads["dec2"]["b"] += db

        # decoder1: tanh + dense
        dpre = d_dec_mid * (1.0 - step.dec_mid**2)
        d_feature, dW, db = _dense_backward(
            step.feature,
            params64["dec1"]["w"],
            params64["dec1"]["b"],
            dpre,
        )
        grads["dec1"]["w"] += dW
        grads["dec1"]["b"] += db
        d_deter += d_feature[: cfg.deter_dim]
        d_stoch += d_feature[cfg.deter_dim :]

        # --- KL -------------------------------------------------------------
        dyn = float(step.kl_values["dyn"])
        rep = float(step.kl_values["rep"])
        w_dyn = scale * cfg.kl_scale * cfg.kl_balance * _maxgrad(dyn, cfg.kl_free_bits)
        w_rep = scale * cfg.kl_scale * (1.0 - cfg.kl_balance) * _maxgrad(rep, cfg.kl_free_bits)

        if cfg.latent_kind == "categorical":
            p = step.kl_values["p"]
            q = step.kl_values["q"]
            lp = step.kl_values["lp"]
            lq = step.kl_values["lq"]

            # dynamics term: gradient to the prior only
            d_prior_logits = w_dyn * (q - p)
            # representation term: gradient to the posterior only
            KL_g = np.sum(p * (lp - lq), axis=-1, keepdims=True)
            d_post_logits = w_rep * p * ((lp - lq) - KL_g)

            d_prior_raw = d_prior_logits.reshape((-1,))
            d_post_raw = d_post_logits.reshape((-1,))

            # straight-through sample gradient into the posterior
            g = d_stoch.reshape((cfg.stoch_dim, cfg.stoch_classes))
            sum_gp = np.sum(p * g, axis=-1, keepdims=True)
            d_post_raw += (p * (g - sum_gp)).reshape((-1,))

        else:
            mp = step.kl_values["post_mean"]
            lsp_raw = step.kl_values["post_log_std_raw"]
            var_p = step.kl_values["var_p"]
            mq = step.kl_values["prior_mean"]
            lsq_raw = step.kl_values["prior_log_std_raw"]
            var_q = step.kl_values["var_q"]

            cp = _clipgrad(lsp_raw, -5.0, 2.0)
            cq = _clipgrad(lsq_raw, -5.0, 2.0)

            # dynamics term -> prior
            d_mq = -(mp - mq) / var_q
            d_lsq = (1.0 - (var_p + (mp - mq) ** 2) / var_q) * cq
            d_prior_raw = np.concatenate([w_dyn * d_mq, w_dyn * d_lsq])

            # representation term -> posterior
            d_mp = (mp - mq) / var_q
            d_lsp = (-1.0 + var_p / var_q) * cp
            d_post_raw = np.concatenate([w_rep * d_mp, w_rep * d_lsp])

            # deterministic sample is the mean: gradient flows to mean only
            d_mean = d_stoch.copy()
            d_log_std = np.zeros_like(d_mean)
            d_post_raw += np.concatenate([d_mean, d_log_std])

        # --- Posterior head -------------------------------------------------
        d_post_h, dW, db = _dense_backward(
            step.post_h,
            params64["post_out"]["w"],
            params64["post_out"]["b"],
            d_post_raw,
        )
        grads["post_out"]["w"] += dW
        grads["post_out"]["b"] += db
        dpre = d_post_h * (1.0 - step.post_h**2)
        d_post_in, dW, db = _dense_backward(
            np.concatenate([step.deter, step.embed], axis=-1),
            params64["post1"]["w"],
            params64["post1"]["b"],
            dpre,
        )
        grads["post1"]["w"] += dW
        grads["post1"]["b"] += db
        d_deter += d_post_in[: cfg.deter_dim]
        d_embed = d_post_in[cfg.deter_dim :]

        # --- Encoder --------------------------------------------------------
        dpre2 = d_embed * (1.0 - step.embed**2)
        _, dW, db = _dense_backward(
            step.enc_mid,
            params64["enc2"]["w"],
            params64["enc2"]["b"],
            dpre2,
        )
        grads["enc2"]["w"] += dW
        grads["enc2"]["b"] += db
        d_enc_mid = dpre2 @ params64["enc2"]["w"].T
        dpre1 = d_enc_mid * (1.0 - step.enc_mid**2)
        _, dW, db = _dense_backward(
            step.obs,
            params64["enc1"]["w"],
            params64["enc1"]["b"],
            dpre1,
        )
        grads["enc1"]["w"] += dW
        grads["enc1"]["b"] += db

        # --- Prior head -----------------------------------------------------
        d_prior_h, dW, db = _dense_backward(
            step.prior_h,
            params64["prior_out"]["w"],
            params64["prior_out"]["b"],
            d_prior_raw,
        )
        grads["prior_out"]["w"] += dW
        grads["prior_out"]["b"] += db
        dpre = d_prior_h * (1.0 - step.prior_h**2)
        d_deter_from_prior, dW, db = _dense_backward(
            step.deter,
            params64["prior1"]["w"],
            params64["prior1"]["b"],
            dpre,
        )
        grads["prior1"]["w"] += dW
        grads["prior1"]["b"] += db
        d_deter += d_deter_from_prior

        # --- GRU ------------------------------------------------------------
        d_cand = d_deter * step.z
        d_z = d_deter * (step.cand - step.deter_prev)
        d_deter_prev = d_deter * (1.0 - step.z)

        # candidate path
        dpre_h = d_cand * (1.0 - step.cand**2)
        d_cat_r, dW, db = _dense_backward(
            step.cat_r,
            params64["gru_h"]["w"],
            params64["gru_h"]["b"],
            dpre_h,
        )
        grads["gru_h"]["w"] += dW
        grads["gru_h"]["b"] += db
        d_stoch_prev_h = d_cat_r[: cfg.stoch_flat]
        d_rdeter = d_cat_r[cfg.stoch_flat :]

        d_r = d_rdeter * step.deter_prev
        d_deter_prev += d_rdeter * step.r

        # gates
        dpre_z = d_z * step.z * (1.0 - step.z)
        dpre_r = d_r * step.r * (1.0 - step.r)

        d_cat_z, dW, db = _dense_backward(
            step.gru_cat,
            params64["gru_z"]["w"],
            params64["gru_z"]["b"],
            dpre_z,
        )
        grads["gru_z"]["w"] += dW
        grads["gru_z"]["b"] += db
        d_cat_r_gate, dW, db = _dense_backward(
            step.gru_cat,
            params64["gru_r"]["w"],
            params64["gru_r"]["b"],
            dpre_r,
        )
        grads["gru_r"]["w"] += dW
        grads["gru_r"]["b"] += db

        d_cat = d_cat_z + d_cat_r_gate
        d_stoch_prev_zr = d_cat[: cfg.stoch_flat]
        d_deter_prev += d_cat[cfg.stoch_flat :]

        # carry gradients back to the previous step
        d_deter = d_deter_prev
        d_stoch = d_stoch_prev_h + d_stoch_prev_zr

    return grads


def sequence_loss(
    cfg: RSSMConfig,
    params: dict[str, dict[str, np.ndarray]],
    obs_seq: np.ndarray,
) -> float:
    """DreamerV3 world-model loss over a sequence of observations."""
    params64 = _params_to_float64(params)
    obs64 = _to_float64(obs_seq)
    loss, _ = _forward_sequence(cfg, params64, obs64)
    return loss


def loss_and_grads(
    cfg: RSSMConfig,
    params: dict[str, dict[str, np.ndarray]],
    obs_seq: np.ndarray,
) -> tuple[float, dict[str, dict[str, np.ndarray]]]:
    """Loss and its parameter gradients for ``sequence_loss``."""
    params64 = _params_to_float64(params)
    obs64 = _to_float64(obs_seq)
    loss, tape = _forward_sequence(cfg, params64, obs64)
    if not tape:
        grads = {
            group: {name: np.zeros_like(param) for name, param in sub.items()}
            for group, sub in params64.items()
        }
    else:
        grads = _backward_sequence(cfg, params64, tape)
    return loss, grads


def sgd_update(
    cfg: RSSMConfig,
    params: dict[str, dict[str, np.ndarray]],
    obs_seq: np.ndarray,
    *,
    steps: int = 1,
) -> TrainResult:
    """NaN/Inf-guarded in-memory SGD on ``sequence_loss``."""
    good = params
    last_loss = float("nan")

    for _ in range(max(1, int(steps))):
        loss, grads = loss_and_grads(cfg, good, obs_seq)
        loss_val = float(loss)

        if not math.isfinite(loss_val):
            return TrainResult(
                params=good,
                loss=last_loss,
                aborted=True,
                reason="non-finite loss",
            )

        all_finite = all(
            bool(np.all(np.isfinite(leaf)))
            for sub in grads.values()
            for leaf in sub.values()
        )
        if not all_finite:
            return TrainResult(
                params=good,
                loss=loss_val,
                aborted=True,
                reason="non-finite gradient",
            )

        good = {
            group: {
                name: (np.asarray(param.astype(np.float64) - cfg.learning_rate * grads[group][name], dtype=np.float32))
                for name, param in sub.items()
            }
            for group, sub in good.items()
        }
        last_loss = loss_val

    return TrainResult(params=good, loss=last_loss, aborted=False)
