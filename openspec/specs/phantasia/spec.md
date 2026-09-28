# phantasia Specification

## Purpose
Phantasia is KAINE's world model and imagination module. It is a DreamerV3-style recurrent state-space model that predicts the next workspace observation while the being is awake, publishing its prediction error as a salience signal. During sleep it imagines trajectories seeded by replayed memories and trains in memory on waking experience. It is a world model only: it has no actor, critic or reward, and Nous selects actions. This capability defines the model and its engines (JAX, and a NumPy engine that trains the same model), what its events disclose, zero persistence of experience data, and the opt-in persistence of its learned weights.

## Requirements

### Requirement: Vendored danijar/dreamerv3 RSSM world model
Phantasia SHALL vendor danijar/dreamerv3 under `external/dreamerv3/` at a pinned
upstream commit hash recorded in `external/dreamerv3/UPSTREAM`, with an SPDX MIT
license notice. The `[worldmodel]` optional extra SHALL declare `jax[cpu]` and
the required transitive deps. Phantasia SHALL use the vendored RSSM core
(recurrent + stochastic latent transition, encoder, decoder, imagination rollout)
and SHALL NOT instantiate the actor, critic, or return heads; policy selection
remains Nous's responsibility. The world model SHALL be accessible behind a
`WorldModel` protocol so a `FakeWorldModel` can substitute in tests without
requiring JAX or the vendored code.

#### Scenario: Actor-critic is absent
- **WHEN** Phantasia constructs its world model
- **THEN** no actor, critic, or return head is instantiated or loaded

#### Scenario: FakeWorldModel passes tests without JAX
- **WHEN** the test suite runs with only core project deps (no `[worldmodel]` extra)
- **THEN** all Phantasia tests pass using the `FakeWorldModel` stub

#### Scenario: Upstream commit is recorded
- **WHEN** the vendored directory is inspected
- **THEN** `external/dreamerv3/UPSTREAM` exists and contains a non-empty commit hash
  and SPDX MIT declaration

### Requirement: Observations are workspace summaries, not raw senses
Phantasia SHALL encode each `WorkspaceSnapshot` to a fixed-width observation
vector (salience-weighted coalition + affect summary + inhibition flag) using a
versioned encoder. No raw audio or image bytes SHALL appear in the observation
vector or the trajectory buffer.

#### Scenario: Observation vector contains no raw sense data
- **WHEN** Phantasia encodes a tick for its world model
- **THEN** the observation vector is derived from the workspace snapshot and
  contains no raw audio or image bytes

#### Scenario: Encoder version stamp is present
- **WHEN** the encoder is inspected
- **THEN** it exposes a non-empty `VERSION` string

### Requirement: Waking world-prediction error
Phantasia SHALL predict the next latent state each waking tick and SHALL publish
a `phantasia.world_error` event whose salience reflects the magnitude of the
predicted-minus-actual latent. `phantasia.world_error` is a salience-only signal
and SHALL NOT carry imagined scenario content.

#### Scenario: Surprising trajectory raises world error
- **WHEN** the actual next workspace state diverges from the world model's
  prediction
- **THEN** the published `phantasia.world_error` has elevated salience

#### Scenario: world_error carries no scenario content
- **WHEN** a `phantasia.world_error` event is inspected
- **THEN** the payload contains no imagined trajectory or scenario field

### Requirement: Offline imagined-scenario generation and workspace re-injection
Phantasia SHALL, on a `mnemos.replay` cue received during offline maintenance,
roll out imagined trajectories from that seed up to `rollout_horizon` and publish
them as `phantasia.scenario` events. `phantasia.scenario` events SHALL be
re-injected into the workspace broadcast during maintenance so that Nous, Thymos,
and Eidolon process them via `on_workspace` (associative consolidation, paper
§3.3.5 phase 3).

#### Scenario: Replay cue produces a scenario
- **WHEN** Phantasia receives a `mnemos.replay` cue during maintenance
- **THEN** it publishes at least one `phantasia.scenario` event

#### Scenario: Scenario is re-injected into workspace broadcast
- **WHEN** a `phantasia.scenario` event is published during maintenance
- **THEN** the scenario is re-injected into the workspace broadcast so
  Nous, Thymos, and Eidolon process it via on_workspace

### Requirement: In-memory-only training; zero-persistence
Phantasia SHALL perform all training in-memory and SHALL NOT serialize the
trajectory buffer or any raw-sense-derived data to disk. Any upstream
disk-serialization hooks from the vendored code SHALL be bypassed. Training
SHALL occur only when `training_enabled` is true and SHALL abort without
corrupting in-memory state if the loss becomes non-finite. No `.pt`, `.pkl`,
`.npy`, `.arrow`, or `.jsonl` files SHALL be written to `/tmp` or the project
directory during a training pass. Learned world-model parameters are NOT
sense data: they MAY be persisted, but only via the explicit, opt-in
weight-persistence requirement below — a training pass itself writes nothing.

#### Scenario: Training disabled skips the training pass
- **WHEN** maintenance runs with `training_enabled` false
- **THEN** the world-model weights are not updated

#### Scenario: No disk artifacts appear during training
- **WHEN** a training pass completes successfully
- **THEN** no new `.pt`, `.pkl`, `.npy`, `.arrow`, or `.jsonl` files exist in
  `/tmp` or the project directory that were not present before the pass

#### Scenario: No actor-critic params in optimizer state
- **WHEN** the optimizer state is inspected after a training pass
- **THEN** no actor or critic parameter tensors appear in the optimizer state

#### Scenario: NaN loss aborts training without corruption
- **WHEN** the training loss becomes non-finite
- **THEN** the training pass aborts and in-memory model state is not corrupted

#### Scenario: Trajectory buffer is never serialized
- **WHEN** `serialize()` is called or a weight checkpoint is written
- **THEN** the trajectory buffer contents appear in neither the serialized
  state nor the checkpoint bytes

### Requirement: FaithfulRenderer templates for Phantasia events
The `FaithfulRenderer` SHALL include registered templates for
`phantasia.world_error` and `phantasia.scenario` events so they render as
human-readable plain text.

#### Scenario: world_error event renders via its template
- **WHEN** `FaithfulRenderer` renders a `phantasia.world_error` event
- **THEN** the output names the source, type, and salience value and does not
  fall back to the generic key=value fallback

#### Scenario: scenario event renders via its template
- **WHEN** `FaithfulRenderer` renders a `phantasia.scenario` event
- **THEN** the output names the source, type, and a summary of the imagined
  trajectory and does not fall back to the generic key=value fallback

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

### Requirement: Opt-in persistence of learned world-model weights
Phantasia SHALL persist learned world-model parameters across restarts when
`[phantasia].persist_weights` is true, and SHALL ship with
`persist_weights = false`. When enabled, Phantasia SHALL load the checkpoint
at `checkpoint_path` during initialization if it exists, SHALL save after
each successful (non-aborted, at-least-one-step) training pass, and SHALL
save on shutdown. Checkpoint writes SHALL be atomic
(write-temp-then-replace) and SHALL be encrypted at rest whenever
`[security.state_encryption]` is enabled. The checkpoint SHALL embed the
world-model configuration (observation dimension, RSSM dimensions, latent
kind, encoder version); loading a checkpoint whose configuration does not
match the running model SHALL fail closed with an operator-actionable error
— never a silent discard-and-reinitialize. Enabling `persist_weights` with a
backend that cannot export real learned parameters (the `fake` EMA stub)
SHALL be a configuration error at construction. The decommission backup
bundle SHALL include the checkpoint file when one exists, as transferable
cognitive state per CAL Article 4.2(b).

#### Scenario: Weights survive a restart
- **WHEN** `persist_weights` is true, a training pass completes, the module
  shuts down, and a new Phantasia instance initializes with the same
  `checkpoint_path`
- **THEN** the new instance's world model carries the saved parameters
  instead of a fresh random initialization

#### Scenario: Save after successful sleep training
- **WHEN** `persist_weights` is true and a sleep-window training pass
  completes with at least one step and without abort
- **THEN** the checkpoint at `checkpoint_path` is (re)written atomically

#### Scenario: Aborted training does not overwrite the checkpoint
- **WHEN** a training pass aborts (non-finite loss)
- **THEN** the existing checkpoint file is left unchanged

#### Scenario: Encrypted at rest
- **WHEN** `[security.state_encryption]` is enabled and a checkpoint is saved
- **THEN** the bytes on disk are an AES-256-GCM envelope, and loading
  decrypts them transparently

#### Scenario: Incompatible checkpoint fails closed
- **WHEN** the checkpoint's embedded configuration (e.g. `obs_dim` after an
  encoder version bump) does not match the running world model
- **THEN** initialization raises an operator-actionable error naming the
  mismatch and the checkpoint file is not modified

#### Scenario: Fake backend cannot persist
- **WHEN** Phantasia is constructed with `persist_weights = true` and
  `backend = "fake"`
- **THEN** construction raises a configuration error (the EMA stub has no
  real learned parameters to persist)

#### Scenario: Shipped default is off
- **WHEN** the committed `config/kaine.toml` is inspected
- **THEN** `[phantasia].persist_weights` is false

#### Scenario: Decommission backup includes the checkpoint
- **WHEN** `capture_backup` runs and `state/phantasia/world_model.ckpt`
  exists
- **THEN** the bundle contains the checkpoint and the manifest inventory and
  restore notes reference it

### Requirement: Only a pass that learned counts as consolidation
A training pass SHALL report whether it updated learned parameters. Phantasia SHALL count a pass toward `successful_training_passes`, and save weights after it, only when it did. A world model that does not learn (the fake world model) SHALL never produce consolidation evidence.

#### Scenario: The fake world model trains
- **WHEN** Phantasia runs a sleep training pass on the fake world model
- **THEN** `successful_training_passes` does not increase

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
