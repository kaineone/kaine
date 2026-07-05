"""Self-contained JAX RSSM world-model core.

DERIVED FROM and ATTRIBUTED TO danijar/dreamerv3 (MIT; pinned commit recorded in
``external/dreamerv3/UPSTREAM``). This is a faithful re-implementation of the
DreamerV3 Recurrent State-Space Model *world model* only:

  * encoder MLP                      observation -> embedding
  * deterministic recurrent state    GRU cell  ("deter" / h)
  * stochastic latent                categorical or Gaussian ("stoch" / z)
  * decoder MLP                      latent -> reconstructed observation
  * imagination rollout              prior-only multi-step latent rollout

The actor, critic, return head, and reward head are DELIBERATELY EXCLUDED.
KAINE selects actions with Nous (pymdp active inference); Phantasia is a pure
world model with no reward signal and no policy.

Runtime dependency is JAX only (``jax`` + ``jax.numpy``). No ``einops``/``chex``/
``ninjax``/``elements``/``embodied`` are needed. It runs CPU-only under the
``[worldmodel]`` optional extra. Importing this module without JAX raises
``ImportError`` — Phantasia catches that and reports a clear "extra not
installed" error rather than crashing module import.

ZERO-PERSISTENCE: this core has NO disk I/O. There is no checkpoint save, no
replay-buffer flush, no logging to disk. Parameters live in plain Python dicts
of JAX arrays held in memory by the caller. The upstream disk-serialization
hooks are simply not implemented here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

try:  # pragma: no cover - exercised only under the [worldmodel] extra
    import jax
    import jax.numpy as jnp
except Exception as exc:  # pragma: no cover
    raise ImportError(
        "dreamerv3 RSSM requires JAX. Install the world-model extra: "
        "pip install '.[worldmodel]'"
    ) from exc


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RSSMConfig:
    """Hyper-parameters for the RSSM world-model core.

    `latent_kind` selects the stochastic latent:
      - "categorical": `stoch_classes` one-hot groups (DreamerV3 default).
      - "gaussian": a diagonal-Gaussian latent.
    """

    obs_dim: int
    deter_dim: int = 64
    stoch_dim: int = 16          # number of categorical groups OR gaussian dims
    stoch_classes: int = 8       # classes per group (categorical only)
    hidden_dim: int = 64
    latent_kind: str = "categorical"
    learning_rate: float = 1e-3
    # DreamerV3 KL-objective knobs (dynamics/representation balancing + free bits).
    # `kl_balance` weights the dynamics term (prior learns the posterior) vs the
    # representation term (posterior is pulled toward the prior); DreamerV3's
    # ~0.8/0.2 split.
    kl_balance: float = 0.8
    # `kl_free_bits` is a floor (in nats) on the per-step TOTAL latent KL below
    # which the term contributes no gradient — DreamerV3's anti-collapse trick.
    # DreamerV3 ships 1.0, but that value is sized for its ~1024-unit (32x32)
    # latent whose total KL runs to tens of nats; this clean-room core uses a
    # far more compact latent (the shipped 16x8 categorical is ~128 units, total
    # KL ~0.3 nat early in training), so a 1.0 floor would clamp the dynamics
    # term to a constant and the PRIOR would never receive gradient — i.e. the
    # world model would never learn to predict, contradicting the hypothesis the
    # paper tests. We therefore scale the floor down to keep it a light
    # anti-collapse guard that still leaves the dynamics term active. Operators
    # sizing up the latent should raise this proportionally.
    kl_free_bits: float = 0.1
    # `kl_scale` is the overall weight of the KL term relative to reconstruction.
    kl_scale: float = 1.0

    @property
    def stoch_flat(self) -> int:
        if self.latent_kind == "categorical":
            return self.stoch_dim * self.stoch_classes
        return self.stoch_dim

    @property
    def feature_dim(self) -> int:
        """Width of the model state fed to encoder/decoder heads."""
        return self.deter_dim + self.stoch_flat


@dataclass
class RSSMState:
    """The recurrent + stochastic model state at one step."""

    deter: Any   # (deter_dim,)
    stoch: Any   # (stoch_flat,)

    def feature(self) -> Any:
        return jnp.concatenate([self.deter, self.stoch], axis=-1)


# ---------------------------------------------------------------------------
# Parameter init
# ---------------------------------------------------------------------------


def _dense(key, fan_in: int, fan_out: int) -> dict[str, Any]:
    # Glorot/Xavier-ish uniform init.
    lim = jnp.sqrt(6.0 / (fan_in + fan_out))
    w = jax.random.uniform(key, (fan_in, fan_out), minval=-lim, maxval=lim)
    b = jnp.zeros((fan_out,))
    return {"w": w, "b": b}


def _apply_dense(params: dict[str, Any], x: Any) -> Any:
    return x @ params["w"] + params["b"]


def init_params(cfg: RSSMConfig, seed: int = 0) -> dict[str, Any]:
    """Initialise all world-model parameters as a nested dict of JAX arrays.

    The parameter tree contains ONLY world-model components — there is no
    actor, critic, reward, or return head anywhere in this tree.
    """
    k = jax.random.PRNGKey(seed)
    keys = jax.random.split(k, 12)
    h, s, hid = cfg.deter_dim, cfg.stoch_flat, cfg.hidden_dim

    return {
        # Encoder: obs -> embedding (feeds ONLY the posterior, never the GRU —
        # the deterministic recurrence must stay observation-free so the prior
        # can reproduce it during imagination/prediction).
        "enc1": _dense(keys[0], cfg.obs_dim, hid),
        "enc2": _dense(keys[1], hid, hid),
        # GRU cell: input = prev stoch only (no action head in this world model,
        # and NO current observation — DreamerV3's deterministic state depends on
        # the previous latent, not the current frame). Hidden = deter.
        "gru_z": _dense(keys[2], s + h, h),   # update gate
        "gru_r": _dense(keys[3], s + h, h),   # reset gate
        "gru_h": _dense(keys[4], s + h, h),   # candidate
        # Prior head: deter -> stoch logits/params (imagination)
        "prior1": _dense(keys[5], h, hid),
        "prior_out": _dense(keys[6], hid, _latent_param_dim(cfg)),
        # Posterior head: [deter, embed] -> stoch logits/params (observe)
        "post1": _dense(keys[7], h + hid, hid),
        "post_out": _dense(keys[8], hid, _latent_param_dim(cfg)),
        # Decoder: feature -> reconstructed obs
        "dec1": _dense(keys[9], cfg.feature_dim, hid),
        "dec2": _dense(keys[10], hid, cfg.obs_dim),
    }


def _latent_param_dim(cfg: RSSMConfig) -> int:
    if cfg.latent_kind == "categorical":
        return cfg.stoch_dim * cfg.stoch_classes
    # gaussian: mean + log-std
    return cfg.stoch_dim * 2


# ---------------------------------------------------------------------------
# Core ops
# ---------------------------------------------------------------------------


def initial_state(cfg: RSSMConfig) -> RSSMState:
    return RSSMState(
        deter=jnp.zeros((cfg.deter_dim,)),
        stoch=jnp.zeros((cfg.stoch_flat,)),
    )


def _encode(params: dict[str, Any], obs: Any) -> Any:
    x = jnp.tanh(_apply_dense(params["enc1"], obs))
    x = jnp.tanh(_apply_dense(params["enc2"], x))
    return x


def _gru(params: dict[str, Any], deter: Any, gru_in: Any) -> Any:
    cat = jnp.concatenate([gru_in, deter], axis=-1)
    z = jax.nn.sigmoid(_apply_dense(params["gru_z"], cat))
    r = jax.nn.sigmoid(_apply_dense(params["gru_r"], cat))
    cat_r = jnp.concatenate([gru_in, r * deter], axis=-1)
    cand = jnp.tanh(_apply_dense(params["gru_h"], cat_r))
    return (1.0 - z) * deter + z * cand


def _latent_sample(cfg: RSSMConfig, raw: Any, key) -> Any:
    """Turn raw latent params into a flat stochastic sample vector.

    For the categorical latent the discrete one-hot is non-differentiable, so we
    use the DreamerV3 STRAIGHT-THROUGH estimator: the forward value is the hard
    one-hot, but gradients flow as if the sample were the softmax probabilities
    (``onehot + probs - stop_gradient(probs)`` is bit-identical to ``onehot`` in
    the forward pass). Without this, reconstruction gradients never reach the
    encoder or the latent heads and the stochastic latent stays untrained.
    """
    if cfg.latent_kind == "categorical":
        logits = raw.reshape((cfg.stoch_dim, cfg.stoch_classes))
        probs = jax.nn.softmax(logits, axis=-1)
        if key is None:
            # Deterministic: argmax one-hot (most-likely class per group).
            idx = jnp.argmax(logits, axis=-1)
        else:
            idx = jax.random.categorical(key, logits, axis=-1)
        onehot = jax.nn.one_hot(idx, cfg.stoch_classes)
        # Straight-through: hard sample forward, soft gradient backward.
        sample = onehot + (probs - jax.lax.stop_gradient(probs))
        return sample.reshape((-1,))
    # gaussian (reparameterised — already differentiable in mean/log-std)
    mean, log_std = jnp.split(raw, 2, axis=-1)
    std = jnp.exp(jnp.clip(log_std, -5.0, 2.0))
    if key is None:
        return mean
    eps = jax.random.normal(key, mean.shape)
    return mean + std * eps


def _prior(cfg: RSSMConfig, params: dict[str, Any], deter: Any, key) -> tuple[Any, Any]:
    h = jnp.tanh(_apply_dense(params["prior1"], deter))
    raw = _apply_dense(params["prior_out"], h)
    stoch = _latent_sample(cfg, raw, key)
    return stoch, raw


def _posterior(
    cfg: RSSMConfig, params: dict[str, Any], deter: Any, embed: Any, key
) -> tuple[Any, Any]:
    x = jnp.concatenate([deter, embed], axis=-1)
    h = jnp.tanh(_apply_dense(params["post1"], x))
    raw = _apply_dense(params["post_out"], h)
    stoch = _latent_sample(cfg, raw, key)
    return stoch, raw


def _decode(params: dict[str, Any], feature: Any) -> Any:
    x = jnp.tanh(_apply_dense(params["dec1"], feature))
    return _apply_dense(params["dec2"], x)


def observe_step(
    cfg: RSSMConfig,
    params: dict[str, Any],
    state: RSSMState,
    obs: Any,
    key=None,
) -> RSSMState:
    """One filtering step: advance deter via GRU (prev stoch only), then the
    posterior latent from the *current* observation embedding.

    The observation enters ONLY through the posterior, never the deterministic
    GRU — so the deterministic transition is identical to the one used during
    imagination/prediction, and the prior is trained on the same dynamics it is
    later asked to predict from."""
    embed = _encode(params, obs)
    deter = _gru(params, state.deter, state.stoch)
    stoch, _ = _posterior(cfg, params, deter, embed, key)
    return RSSMState(deter=deter, stoch=stoch)


def imagine_step(
    cfg: RSSMConfig,
    params: dict[str, Any],
    state: RSSMState,
    key=None,
) -> RSSMState:
    """One imagination step: advance deter via GRU using prior latent only.

    No observation is consumed — this is the pure forward (dreaming) dynamics.
    The GRU advances on the previous latent alone, exactly as in ``observe_step``
    minus the posterior correction, so prediction matches the trained dynamics.
    """
    deter = _gru(params, state.deter, state.stoch)
    stoch, _ = _prior(cfg, params, deter, key)
    return RSSMState(deter=deter, stoch=stoch)


def predict_next_obs(
    cfg: RSSMConfig, params: dict[str, Any], state: RSSMState
) -> Any:
    """Decode the predicted next observation from the prior of one imagined step."""
    nxt = imagine_step(cfg, params, state, key=None)
    return _decode(params, nxt.feature())


# ---------------------------------------------------------------------------
# Loss + training (in-memory only; NaN-guarded by the caller wrapper)
# ---------------------------------------------------------------------------


def _categorical_kl(cfg: RSSMConfig, logits_p: Any, logits_q: Any) -> Any:
    """KL(p || q) summed over all categorical groups, from raw logits.

    `p` and `q` are flat raw-logit vectors reshaped to (stoch_dim, classes);
    the result is the total KL in nats across the groups for one step.
    """
    lp = jax.nn.log_softmax(logits_p.reshape((cfg.stoch_dim, cfg.stoch_classes)), axis=-1)
    lq = jax.nn.log_softmax(logits_q.reshape((cfg.stoch_dim, cfg.stoch_classes)), axis=-1)
    p = jnp.exp(lp)
    return jnp.sum(p * (lp - lq))


def _gaussian_kl(raw_p: Any, raw_q: Any) -> Any:
    """KL(N_p || N_q) summed over dims, from raw [mean, log_std] vectors."""
    mp, lsp = jnp.split(raw_p, 2, axis=-1)
    mq, lsq = jnp.split(raw_q, 2, axis=-1)
    lsp = jnp.clip(lsp, -5.0, 2.0)
    lsq = jnp.clip(lsq, -5.0, 2.0)
    var_p = jnp.exp(2.0 * lsp)
    var_q = jnp.exp(2.0 * lsq)
    # KL between diagonal Gaussians, per-dim, summed.
    kl = lsq - lsp + (var_p + (mp - mq) ** 2) / (2.0 * var_q) - 0.5
    return jnp.sum(kl)


def _latent_kl_terms(
    cfg: RSSMConfig, post_raw: Any, prior_raw: Any
) -> tuple[Any, Any]:
    """DreamerV3 KL-balanced terms over the stochastic latent.

    Returns ``(dyn, rep)`` where:
      * ``dyn`` = KL( sg(posterior) || prior )  — trains the PRIOR to predict the
        posterior latent (the dynamics/world-prediction objective).
      * ``rep`` = KL( posterior || sg(prior) )  — regularises the posterior
        toward the prior (the representation objective).
    The stop-gradients keep the two objectives from interfering, exactly as in
    DreamerV3's KL balancing.
    """
    if cfg.latent_kind == "categorical":
        dyn = _categorical_kl(cfg, jax.lax.stop_gradient(post_raw), prior_raw)
        rep = _categorical_kl(cfg, post_raw, jax.lax.stop_gradient(prior_raw))
    else:
        dyn = _gaussian_kl(jax.lax.stop_gradient(post_raw), prior_raw)
        rep = _gaussian_kl(post_raw, jax.lax.stop_gradient(prior_raw))
    return dyn, rep


def sequence_loss(
    cfg: RSSMConfig, params: dict[str, Any], obs_seq: Any
) -> Any:
    """DreamerV3 world-model loss over a sequence of observations (T, obs_dim).

    Two terms, summed over the sequence (the standard DreamerV3 world-model
    objective, with NO reward / return / value / continue head — those do not
    exist in this clean-room core):

      * Reconstruction: decode the POSTERIOR feature and match the observation.
        Straight-through sampling lets this gradient reach the encoder and the
        latent heads.
      * KL: pull the PRIOR toward the posterior (dynamics) and the posterior
        toward the prior (representation), with DreamerV3 KL balancing
        (``kl_balance``) and a per-step free-bits floor (``kl_free_bits``). This
        is what trains the prior heads — without it the prior, and therefore
        ``predict_next_obs``/``rollout`` (which run off the prior), never learn.
    """
    state = initial_state(cfg)

    def step(carry, obs):
        st = carry
        embed = _encode(params, obs)
        # Observation-free deterministic update (prev latent only): the SAME
        # transition the prior must predict from at imagination time.
        deter = _gru(params, st.deter, st.stoch)
        # Prior predicts the latent from deter alone; posterior corrects with obs.
        _, prior_raw = _prior(cfg, params, deter, None)
        stoch, post_raw = _posterior(cfg, params, deter, embed, None)
        new_state = RSSMState(deter=deter, stoch=stoch)
        recon = _decode(params, new_state.feature())
        recon_loss = jnp.mean((recon - obs) ** 2)
        dyn, rep = _latent_kl_terms(cfg, post_raw, prior_raw)
        # Free-bits floor: no gradient once a term is already below the floor.
        free = cfg.kl_free_bits
        dyn = jnp.maximum(dyn, free)
        rep = jnp.maximum(rep, free)
        kl = cfg.kl_scale * (cfg.kl_balance * dyn + (1.0 - cfg.kl_balance) * rep)
        return new_state, recon_loss + kl

    # Manual scan to keep RSSMState a plain dataclass (lax.scan needs pytrees;
    # a Python loop is fine for the short in-memory sequences Phantasia uses).
    total = 0.0
    for t in range(obs_seq.shape[0]):
        state, loss = step(state, obs_seq[t])
        total = total + loss
    return total / jnp.maximum(obs_seq.shape[0], 1)


@dataclass
class TrainResult:
    params: dict[str, Any]
    loss: float
    aborted: bool = False
    reason: str = ""


def sgd_update(
    cfg: RSSMConfig,
    params: dict[str, Any],
    obs_seq: Any,
    *,
    steps: int = 1,
) -> TrainResult:
    """In-memory SGD on the reconstruction loss.

    NaN/Inf GUARD: if the loss becomes non-finite at any step, abort and return
    the LAST KNOWN-GOOD params (the ones passed in), unmodified, with
    `aborted=True`. The caller therefore never installs corrupted weights.
    """
    loss_fn = lambda p: sequence_loss(cfg, p, obs_seq)
    grad_fn = jax.value_and_grad(loss_fn)

    good = params  # last known-good snapshot
    last_loss = float("nan")
    for _ in range(max(1, int(steps))):
        loss, grads = grad_fn(good)
        loss_val = float(loss)
        if not jnp.isfinite(loss):
            return TrainResult(
                params=good, loss=last_loss, aborted=True, reason="non-finite loss"
            )
        # Also guard against non-finite gradients before applying them.
        finite_grads = all(
            bool(jnp.all(jnp.isfinite(leaf)))
            for leaf in jax.tree_util.tree_leaves(grads)
        )
        if not finite_grads:
            return TrainResult(
                params=good, loss=loss_val, aborted=True, reason="non-finite gradient"
            )
        candidate = jax.tree_util.tree_map(
            lambda p, g: p - cfg.learning_rate * g, good, grads
        )
        good = candidate
        last_loss = loss_val
    return TrainResult(params=good, loss=last_loss, aborted=False)


def rollout(
    cfg: RSSMConfig,
    params: dict[str, Any],
    state: RSSMState,
    horizon: int,
    seed: int = 0,
) -> Any:
    """Imagine `horizon` steps forward and return decoded observations.

    Returns an array of shape (horizon, obs_dim). Prior-only (dreaming).
    """
    key = jax.random.PRNGKey(seed)
    outs = []
    st = state
    for _ in range(max(0, int(horizon))):
        key, sub = jax.random.split(key)
        st = imagine_step(cfg, params, st, key=sub)
        outs.append(_decode(params, st.feature()))
    if not outs:
        return jnp.zeros((0, cfg.obs_dim))
    return jnp.stack(outs, axis=0)
