## ADDED Requirements

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
Phantasia SHALL perform all training in-memory. The trajectory buffer SHALL NOT
be serialized to disk. Any upstream disk-serialization hooks from the vendored
code SHALL be bypassed. Training SHALL occur only when `training_enabled` is
true and SHALL abort without corrupting in-memory state if the loss becomes
non-finite. No `.pt`, `.pkl`, `.npy`, `.arrow`, or `.jsonl` files SHALL be
written to `/tmp` or the project directory during a training pass.

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
