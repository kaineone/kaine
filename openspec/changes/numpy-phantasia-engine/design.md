## Context

`DreamerV3WorldModel` (`kaine/modules/phantasia/world_model.py`) wraps the clean-room JAX core `external/dreamerv3/rssm.py`:
- **Parameters:** a dict of dense layers `{"w": (in, out), "b": (out,)}` named `enc1 enc2 gru_z gru_r gru_h prior1 prior_out post1 post_out dec1 dec2`, float32.
- **Waking:** `observe(obs)` decodes `predict_next_obs` from the current state, then advances with `observe_step` (deterministic, `key=None`), and returns the clipped mean absolute error.
- **Imagination:** `imagine(h)` runs `rollout` with `jax.random.PRNGKey(0)`, sampling latents.
- **Sleep training:** `train(trajectory)` runs one `sgd_update` step over the whole buffer (up to `trajectory_buffer_size = 512` observations) with `value_and_grad` of `sequence_loss`, then installs the parameters unless the loss or a gradient is non-finite.
- **Persistence:** `export_params`/`import_params` read and write an NPZ with a JSON header and fail closed on any mismatch.

## Decisions

### Scope and arithmetic
- The NumPy engine supports exactly `RSSMConfig`: both latent kinds, every dimension, `kl_balance`, `kl_free_bits`, `kl_scale`, `learning_rate`.
- Parameters are stored as float32, as in JAX, so checkpoints are byte-compatible in layout and dtype. Each forward and backward pass computes in float64 from those parameters, and the SGD update is applied in float64 and cast back to float32. Parity tolerances are therefore bounded by JAX's float32 arithmetic, not by the NumPy engine.

### Gradients
- A forward pass over the sequence keeps a per-step tape of the intermediates the backward pass needs: pre-activations, gates, the concatenated inputs, softmax probabilities, the one-hot sample, the KL values. The backward pass walks the tape in reverse, accumulating parameter gradients and carrying `d deter` and `d stoch` to the previous step, exactly as `jax.value_and_grad` differentiates the Python loop in `sequence_loss`.
- Conventions copied from JAX, each with a test:
  - **Straight-through:** the forward value is the hard one-hot; the backward pass differentiates `probs` (softmax Jacobian), and the `argmax` contributes nothing.
  - **`stop_gradient` in KL balancing:** `dyn` differentiates only the prior raw output; `rep` differentiates only the posterior raw output.
  - **`jnp.maximum(x, free)`:** gradient 1 when `x > free`, 0 when `x < free`, 0.5 at equality.
  - **`jnp.clip(log_std, -5, 2)`:** gradient 1 strictly inside; at the bounds and outside it follows the `minimum(maximum(...))` rule, which gives 0.5 at each bound, 0 outside.
  - **The mean over time:** the loss divides by `max(T, 1)`.
- **Verification.** Golden gradients from `jax.value_and_grad` on fixed parameters and sequences must be reproduced (rtol 1e-4, atol 1e-6 per array). On the Gaussian latent, whose deterministic loss is differentiable wherever it is evaluated, central finite differences in float64 check the NumPy gradients on every host without JAX (rtol 1e-4 on a sample of coordinates per array). A categorical finite-difference check is meaningless because the `argmax` is piecewise constant, so categorical correctness rests on the JAX golden gradients.

### Randomness
- JAX's counter-based PRNG (threefry, partitionable in JAX 0.10) is not reproduced. Reimplementing it would tie the NumPy engine to one JAX version's key-splitting and bit-to-float conventions.
- **Initialisation.** The NumPy engine draws its own Glorot-uniform parameters from `numpy.random.default_rng(seed)`, with the same shapes, bounds and zero biases. A fresh model is therefore a different random draw on each engine for the same seed. The JAX engine's initialisation is unchanged, so no existing configuration or preserved being is affected.
- **Rollout sampling.** Imagination draws categorical samples with the NumPy generator (Gumbel-max), seeded per rollout as the JAX engine seeds `PRNGKey(0)`.
- **Parity scope.** Parity is defined on given parameters and on the deterministic paths: `observe`, `predict_next_obs`, the loss and its gradients, and `sgd_update`. A trained model moves between engines through the checkpoint. Rollout parity is statistical: with a peaked prior both engines produce the same argmax trajectory, and a test covers that case.

### The seam
- `load_world_model(backend, obs_dim, engine=..., **kwargs)`:
  - `backend = "dreamerv3"` with `engine = "jax"` (default) builds `DreamerV3WorldModel`;
  - `engine = "numpy"` builds `NumpyDreamerV3WorldModel`;
  - any other engine raises `ValueError`, which boot surfaces as a configuration error;
  - `engine` has no meaning for `backend = "fake"`.
- Both adapters implement the same `WorldModel` protocol and return the same `TrainOutcome` (with `learned=True` only for a pass that updated parameters). They share one checkpoint codec (`_encode_checkpoint`/`_decode_checkpoint` in `world_model.py`), which moves out of `DreamerV3WorldModel` unchanged: the same header, validation and fail-closed errors. The header does not record the engine, so blobs are interchangeable.
- `NumpyDreamerV3WorldModel` and `rssm_numpy.py` import only NumPy and the standard library. A subprocess test runs construction, observe, imagine, train, export and import with `jax`, `jaxlib`, `optax`, `chex` and `equinox` import-blocked.
- `phantasia.*` events keep `backend` and add `engine` (`"jax"`, `"numpy"`, or `null` for the fake backend).

### Budget
- On the desktop CPU: an `observe` step takes under 5 ms, and one training pass over a full 512-observation buffer takes under 3 s. The Termux budget is measured on the device during the Termux install work, not asserted here.

## Risks

- **Silent gradient errors** would make the being learn a subtly wrong world model. They are mitigated by two independent checks: JAX golden gradients (categorical and Gaussian, free bits active and inactive, several sequence lengths including 1), and JAX-free finite differences. A training-trajectory fixture then catches drift that single-step checks could miss: five successive `sgd_update` steps must match JAX's losses (rtol 1e-4) and parameters (atol 1e-5).
- **Float32 versus float64:** tolerances are stated per check. They are not loosened to make a test pass. A failure is investigated.
