## Why

Phantasia's world model (the DreamerV3 RSSM core in `external/dreamerv3/rssm.py`) runs on JAX. JAX has no wheels for Termux or 32-bit ARM, so Phantasia cannot run on the Pixel 6a, and the portability program's target of a full entity on that host fails at Phantasia now that Nous has a NumPy engine. The model is small: two-layer MLPs of width 64, one GRU cell, a 16×8 categorical latent, one plain SGD step per sleep pass. NumPy handles it, except that NumPy has no automatic differentiation, and Phantasia *learns*: a copy that could only predict and imagine would be a world model that never improves, which is not the model the paper tests. So the NumPy engine must train, and its gradients must be proven equal to JAX's.

## What Changes

- **A NumPy RSSM engine** (`kaine/modules/phantasia/rssm_numpy.py`) that computes what `external/dreamerv3/rssm.py` computes, for the same parameters:
  - the forward pieces: encoder, GRU, prior and posterior heads, straight-through categorical and reparameterised Gaussian latents, decoder, `observe_step`, `imagine_step`, `predict_next_obs`, `rollout`;
  - the DreamerV3 loss: reconstruction plus KL balancing with stop-gradients and the free-bits floor;
  - **hand-written reverse-mode gradients** of that loss through time (backpropagation through the GRU, the heads, the straight-through estimator, the KL terms, the clips and the free-bits `max`), following JAX's conventions at ties;
  - `sgd_update` with the same non-finite loss and gradient guards (abort, keep the last good parameters).
- **An engine key.** `[phantasia].engine` selects `"jax"` (default) or `"numpy"` for `backend = "dreamerv3"`. The backend name, and therefore what every `phantasia.*` event discloses as `backend`, is unchanged: both engines run the same learning model. Events additionally disclose `engine`.
- **Parity is proven against JAX**, not asserted:
  - golden fixtures recorded from the JAX core are committed as JSON: forward outputs on deterministic paths, loss values and full parameter gradients for categorical and Gaussian latents, with the free-bits floor both active and inactive, and a multi-step training trajectory;
  - the NumPy engine reproduces them within stated tolerances on every host, including hosts without JAX;
  - an independent JAX-free check: central finite differences of the NumPy loss on the Gaussian latent (the one whose loss is differentiable everywhere it is evaluated) agree with the NumPy gradients.
- **Checkpoints are interchangeable.** Both engines read and write the same `kaine-phantasia-rssm-npz-v1` blob through one shared codec, so learned weights persisted on a JAX host load on a NumPy host and the other way round.
- **The stack becomes engine-aware:** the extras check (`worldmodel` is needed only for the JAX engine), the install planner's Termux entry, and the Tier 1 profile.

## Capabilities

### Modified Capabilities
- `phantasia`: a JAX-free engine that computes and learns what the JAX core does, selectable per host, with interchangeable checkpoints; events disclose the engine.

## Impact

- New: `kaine/modules/phantasia/rssm_numpy.py`, `scripts/record_phantasia_golden.py`, `tests/fixtures/phantasia_golden/*.json`, tests.
- Changed: `kaine/modules/phantasia/world_model.py` (shared checkpoint codec, a NumPy-engine adapter, `load_world_model` engine selection), `kaine/modules/phantasia/module.py` (engine disclosure), `kaine/boot.py` (pass `[phantasia].engine`), `kaine/extras.py`, `kaine/install_target.py`, `config/kaine.toml`, `config/profiles/tier1.toml`, docs.
- Unchanged: `external/dreamerv3/rssm.py` and the JAX engine's behaviour, including its parameter initialisation.
