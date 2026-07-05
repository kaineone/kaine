## ADDED Requirements

### Requirement: Per-agent models with familiarity score
Empatheia SHALL maintain a model per interacting agent (emotion histogram,
behavioral summary, reliability, interaction count, first/last seen) and SHALL
expose a `familiarity()` score in [0,1] that increases monotonically with
interaction count and model coverage. Agent profiles SHALL persist via a Qdrant-
backed store (with an in-memory backend for tests).

#### Scenario: Familiarity grows with interaction
- **WHEN** an agent is observed across many interactions
- **THEN** its `familiarity()` score is strictly greater than after a single
  interaction

#### Scenario: Profiles persist across restart
- **WHEN** an agent model is stored and the store is reopened
- **THEN** the agent model is recovered with its interaction count intact

### Requirement: Agent profile fork/merge persistence
Empatheia SHALL implement `serialize()` / `deserialize()` on `AgentStore` and a
corresponding `EmpatheiaMergeStrategy` (mirroring `MnemosMergeStrategy`) so that
agent profiles survive the fork/merge cycle used by the fork-merge subsystem. On
merge, the strategy MUST reconcile two diverged profile sets by combining
interaction counts and merging histograms; the merged profile SHALL be persisted
to Qdrant before the merge completes.

#### Scenario: Fork/merge round-trip preserves interaction count
- **WHEN** an agent profile is updated in a forked instance and the fork is merged
  back
- **THEN** the merged agent profile has an interaction count at least as large as
  the maximum of the two forked counts

#### Scenario: Serialize/deserialize round-trip is lossless
- **WHEN** an `AgentStore` is serialized and deserialized
- **THEN** every agent profile (id, histogram, interaction_count, familiarity) is
  recovered without loss

### Requirement: Familiarity is published for downstream coupling
Empatheia SHALL publish an `empatheia.agent_model` event on each update carrying
the agent id, the familiarity score, reliability, and interaction count, so that
Thymos can modulate affect coupling by familiarity.

#### Scenario: Update publishes familiarity
- **WHEN** an observation updates an agent model
- **THEN** an `empatheia.agent_model` event is published containing a numeric
  `familiarity` field

### Requirement: Social prediction errors as salience signals
Empatheia SHALL publish an `empatheia.social_error` event when an agent's
observed behavior deviates from its model beyond `deviation_threshold`, with
salience scaled by the magnitude of the deviation. `empatheia.social_error` is a
**salience-only signal**: it enters the global workspace and raises attention by
its salience value, enabling other modules to react to social surprise. It does
NOT carry raw behavioral data to the conversation surface. The evaluation sidecar
SHALL record every `empatheia.social_error` event (agent id, salience, deviation
magnitude, timestamp) for accuracy scoring.

#### Scenario: Out-of-character behavior raises salience
- **WHEN** an agent's observed emotion diverges sharply from its established
  histogram
- **THEN** an `empatheia.social_error` event is published with elevated salience

#### Scenario: In-character behavior is quiet
- **WHEN** an agent behaves consistently with its model
- **THEN** no `empatheia.social_error` event is published

#### Scenario: Social error enters the workspace as a salience signal only
- **WHEN** an `empatheia.social_error` event is published
- **THEN** it enters the global workspace with the declared salience value
- **AND** its payload contains only agent id, salience, and deviation magnitude
- **AND** raw behavioral data is not exposed on the conversation surface

#### Scenario: Sidecar records every social error
- **WHEN** an `empatheia.social_error` event is published
- **THEN** the evaluation sidecar records agent id, salience, deviation magnitude,
  and timestamp in the evaluation log

### Requirement: Empatheia depends on rename-audition-vox
Empatheia SHALL consume `audition.emotion` and `audition.transcription` events,
which exist only after the `rename-audition-vox` change is applied. Empatheia
MUST NOT be enabled in production until `rename-audition-vox` is merged.

#### Scenario: Correct event types post-rename
- **WHEN** Empatheia subscribes to emotion and transcription events
- **THEN** it subscribes to `audition.emotion` and `audition.transcription`
  (not the pre-rename `audio_in.*` event types)

### Requirement: FaithfulRenderer templates for empatheia events
The FaithfulRenderer SHALL include templates for `empatheia.agent_model` and
`empatheia.social_error` events so they render in human-readable form inside the
conscious coalition and evaluation logs.

#### Scenario: empatheia.agent_model renders with familiarity
- **WHEN** an `empatheia.agent_model` event is passed to the renderer
- **THEN** the output contains the agent label and a formatted familiarity value,
  not a raw dict repr

#### Scenario: empatheia.social_error renders as a social-surprise line
- **WHEN** an `empatheia.social_error` event is passed to the renderer
- **THEN** the output contains the agent label and the deviation magnitude
