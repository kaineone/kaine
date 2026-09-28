## ADDED Requirements

### Requirement: A JAX-free engine that computes and learns what the JAX core does

Phantasia SHALL provide a NumPy engine for `backend = "dreamerv3"`, selected by `[phantasia].engine = "numpy"` (default `"jax"`). It SHALL run the same RSSM world model as `external/dreamerv3/rssm.py`: encoder, GRU, prior and posterior heads, categorical (straight-through) and Gaussian latents, decoder, observation filtering, imagination, and the DreamerV3 loss with KL balancing and free bits. Sleep training SHALL use hand-written reverse-mode gradients of that loss, with the same non-finite loss and gradient guards. The NumPy engine SHALL import neither JAX nor any JAX-dependent library. An unknown engine SHALL be a configuration error at boot.

#### Scenario: Gradients match JAX
- **WHEN** the committed golden fixtures are replayed on the NumPy engine, on a host with or without JAX
- **THEN** the loss and every parameter gradient match the JAX core within rtol 1e-4 and atol 1e-6, for both latent kinds, with the free-bits floor active and inactive

#### Scenario: Training matches JAX over several steps
- **WHEN** five successive training steps run from the fixture's parameters on the fixture's sequence
- **THEN** each step's loss matches JAX within rtol 1e-4, and the final parameters match within atol 1e-5

#### Scenario: Gradients agree with finite differences without JAX
- **WHEN** a surrogate of the Gaussian-latent loss, which holds each stop-gradiented side at its value under the current parameters, is differentiated by central finite differences in float64
- **THEN** the NumPy engine's gradients agree within rtol 1e-4 on the sampled coordinates

#### Scenario: Runs with JAX absent
- **WHEN** a process with `jax`, `jaxlib`, `optax`, `chex` and `equinox` import-blocked builds the NumPy engine, then observes, imagines, trains, exports and imports
- **THEN** every call succeeds and the process exits 0

#### Scenario: A non-finite step installs nothing
- **WHEN** a training pass produces a non-finite loss or gradient on the NumPy engine
- **THEN** the pass is aborted, the parameters are unchanged, and the outcome reports `learned=False`

### Requirement: Checkpoints are interchangeable between engines

Both engines SHALL read and write learned weights through one shared codec with the `kaine-phantasia-rssm-npz-v1` format, float32 arrays, and the existing fail-closed validation. The checkpoint SHALL NOT record the engine.

#### Scenario: JAX weights load on the NumPy engine
- **WHEN** a checkpoint exported by the JAX engine is imported by the NumPy engine with the same configuration
- **THEN** it loads, and the NumPy engine's next `observe` returns the error the JAX engine returns for the same observation, within 1e-5

#### Scenario: NumPy weights load on the JAX engine
- **WHEN** a checkpoint exported by the NumPy engine is imported by the JAX engine
- **THEN** it loads and passes the same validation as a JAX-written checkpoint

#### Scenario: Mismatch fails closed on either engine
- **WHEN** a checkpoint whose header or array shapes differ from the running configuration is imported by either engine
- **THEN** `CheckpointMismatchError` is raised and the running model is untouched

## MODIFIED Requirements

### Requirement: Backend is disclosed on every phantasia.* event

Every `phantasia.*` event payload SHALL include a `"backend"` field naming the
world-model backend that produced the signal (`"fake"` or `"dreamerv3"`), and an
`"engine"` field naming the engine that computed it (`"jax"` or `"numpy"` for
`"dreamerv3"`, `null` for `"fake"`).
This requirement applies to `phantasia.world_error`, `phantasia.scenario`, and
any future `phantasia.*` event types.

The `backend = "fake"` config option SHALL be documented as a non-learning EMA
stub (not a world model) in `config/kaine.toml` so operators understand what
the shipped default produces.

#### Scenario: world_error discloses backend
- **WHEN** Phantasia publishes `phantasia.world_error`
- **THEN** the payload includes `"backend"` matching the configured backend name

#### Scenario: scenario discloses backend
- **WHEN** Phantasia generates and publishes `phantasia.scenario`
- **THEN** the payload includes `"backend"` matching the configured backend name

#### Scenario: events disclose the engine
- **WHEN** Phantasia publishes any `phantasia.*` event with `backend = "dreamerv3"`
- **THEN** the payload includes `"engine"` matching the configured engine

#### Scenario: fake backend is documented as a non-learning stub
- **WHEN** `config/kaine.toml` is inspected
- **THEN** the `[phantasia]` section contains a comment distinguishing
  `backend = "fake"` (EMA stub, no learning) from `backend = "dreamerv3"`
  (real RSSM with trained latents)
