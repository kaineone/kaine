# empatheia Specification

## Purpose
Empatheia is the social-modeling module that maintains a per-agent profile of emotion histograms, behavioral summaries, and interaction history, computes and publishes a monotonic familiarity score, and emits social-prediction-error events as salience signals while skipping model updates on degraded emotion events.

## Requirements

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
Empatheia SHALL implement `serialize()` / `deserialize()` on `AgentStore`, and the lifecycle layer SHALL provide an `EmpatheiaMergeStrategy` (beside `MnemosMergeStrategy` in `kaine.lifecycle.strategies`) that `default_strategies()` registers under `"empatheia"`, so that agent profiles survive the fork/merge cycle. On merge, the strategy MUST reconcile two diverged profile sets: interaction counts are summed, histograms, behavioural summaries and reliability are averaged with interaction count as the weight, `first_seen` takes the earlier and `last_seen` the later value. The merged profiles SHALL be carried in the merged snapshot; restoring that snapshot loads them into the store, which serves them before any Qdrant copy and writes each to Qdrant on its next update.

#### Scenario: Fork/merge round-trip preserves interaction count
- **WHEN** an agent profile is updated in a forked instance and the fork is merged
  back
- **THEN** the merged agent profile has an interaction count at least as large as
  the maximum of the two forked counts

#### Scenario: ForkManager uses the Empatheia strategy by default
- **WHEN** `ForkManager.merge` combines two snapshots whose `empatheia` state holds the same agent with interaction counts 5 and 3
- **THEN** the merged snapshot's profile for that agent has interaction count 8

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

### Requirement: Empatheia skips agent-model fold on degraded emotion events

`Empatheia._handle_emotion()` SHALL skip the agent-model fold (and NOT
increment `interaction_count`) when the incoming `audition.emotion` payload
carries `"degraded": true`.  A non-running emotion model MUST NOT inflate
familiarity or interaction counts.

#### Scenario: degraded emotion event

- **WHEN** an `audition.emotion` event arrives with `"degraded": true`
- **THEN** Empatheia does not update the agent model
- **AND** interaction_count is not incremented

#### Scenario: real emotion event

- **WHEN** an `audition.emotion` event arrives without `"degraded": true`
- **THEN** Empatheia folds the observation into the agent model normally

### Requirement: Heard agents are attributed by channel
Empatheia SHALL attribute heard emotion and speech to the configured operator label only when they arrive on an operator channel (configurable, by default the live microphone, the microphone and remote audio) or carry no channel. Audio from any other channel SHALL be attributed to a separate agent for that channel (`media:<channel>`), so voices from a film or other media never shape the entity's model of its operator.

#### Scenario: Film dialogue
- **WHEN** Audition publishes emotion from the playlist channel
- **THEN** it updates the `media:playlist` agent and leaves the operator's model unchanged

#### Scenario: The operator speaks
- **WHEN** Audition publishes emotion from the live microphone
- **THEN** it updates the operator's model as before

### Requirement: Empatheia preserves its own agent profiles
Empatheia SHALL capture every agent profile it holds (in its store, not only those cached since boot) in preservation, and a revived Empatheia SHALL restore exactly those profiles into its own configured collection, re-embedding them with the running embedder. A failure to read the profiles SHALL fail the preservation.

#### Scenario: Profiles not touched since boot
- **WHEN** Empatheia is preserved holding profiles that were stored before this boot and not read since
- **THEN** those profiles are in the bundle and are restored on revive
