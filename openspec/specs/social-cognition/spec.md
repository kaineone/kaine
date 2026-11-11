# social cognition Specification

## Purpose
The social cognition module is the social-modeling module that maintains a per-agent profile of emotion histograms, behavioral summaries, and interaction history, computes and publishes a monotonic familiarity score, and emits social-prediction-error events as salience signals while skipping model updates on degraded emotion events.

## Requirements

### Requirement: Per-agent models with familiarity score
The social cognition module SHALL maintain a model per interacting agent (emotion histogram, behavioral summary, reliability, interaction count, first/last seen, voice centroid, face centroid, per-modality exemplar buffers, per-modality sample counts, modality binding state, and binding confidence) and SHALL expose a `familiarity()` score in [0,1] that increases monotonically with interaction count, model coverage, and embedding-based evidence (exemplar count and centroid stability). Agent profiles SHALL persist via a Qdrant-backed store (with an in-memory backend for tests).

#### Scenario: Familiarity grows with interaction
- **WHEN** an agent is observed across many interactions
- **THEN** its `familiarity()` score is strictly greater than after a single
  interaction

#### Scenario: Profiles persist across restart
- **WHEN** an agent model is stored and the store is reopened
- **THEN** the agent model is recovered with its interaction count intact

#### Scenario: Familiarity incorporates perceptual evidence
- **WHEN** an agent has both voice and face centroids with high sample counts and stable centroids
- **THEN** `familiarity()` SHALL return a higher score than for an agent with the same interaction count and emotion coverage but no perceptual embeddings

#### Scenario: Familiarity incorporates reliability
- **WHEN** an agent has high reliability scores (low exemplar variance) in both modalities
- **THEN** `familiarity()` SHALL weight the perceptual evidence contribution higher than for an agent with the same exemplar count but low reliability

#### Scenario: Familiarity without perceptual data
- **WHEN** an agent has no voice or face embeddings (identity binding disabled or agent only known by label)
- **THEN** `familiarity()` SHALL fall back to the existing computation based on interaction count and emotion category coverage

#### Scenario: New embedding fields default to absent
- **WHEN** an agent profile is loaded that was created before identity binding existed (no voice or face fields)
- **THEN** the new fields SHALL default to absent (null centroids, empty exemplar buffers, zero sample counts, unbound state, null binding confidence) and the agent SHALL remain functional

### Requirement: Agent profile fork/merge persistence
The social cognition module SHALL implement `serialize()` / `deserialize()` on `AgentStore`, and the lifecycle layer SHALL provide an `SocialCognitionMergeStrategy` (beside `EpisodicMemoryMergeStrategy` in `kaine.lifecycle.strategies`) that `default_strategies()` registers under `"social_cognition"`, so that agent profiles survive the fork/merge cycle. On merge, the strategy MUST reconcile two diverged profile sets: interaction counts are summed, histograms, behavioural summaries and reliability are averaged with interaction count as the weight, `first_seen` takes the earlier and `last_seen` the later value. A behavioural-summary entry that is missing or null on one side is absent, not 0: an entry defined on both sides takes the count-weighted average, an entry defined on one side takes that side's value, an entry defined on neither side stays absent, and when the sides that hold a value have no interactions their plain mean is used. Voice and face centroids SHALL be merged by sample-count-weighted averaging; exemplar buffers SHALL be unioned with deduplication by similarity threshold; binding state SHALL take the side with higher binding confidence; binding confidence SHALL take the maximum. The merged profiles SHALL be carried in the merged snapshot; restoring that snapshot loads them into the store, which serves them before any Qdrant copy and writes each to Qdrant on its next update.

#### Scenario: Fork/merge round-trip preserves interaction count
- **WHEN** an agent profile is updated in a forked instance and the fork is merged
  back
- **THEN** the merged agent profile has an interaction count at least as large as
  the maximum of the two forked counts

#### Scenario: ForkManager uses the Social cognition strategy by default
- **WHEN** `ForkManager.merge` combines two snapshots whose `social_cognition` state holds the same agent with interaction counts 5 and 3
- **THEN** the merged snapshot's profile for that agent has interaction count 8

#### Scenario: Serialize/deserialize round-trip is lossless
- **WHEN** an `AgentStore` is serialized and deserialized
- **THEN** every agent profile (id, histogram, interaction_count, familiarity) is
  recovered without loss

#### Scenario: A fork without a defined error does not pull the average toward 0
- **WHEN** two forks of the same agent are merged and only one holds a `mean_prediction_error`, of 0.6, while the other's is missing or null
- **THEN** the merged profile's `mean_prediction_error` is 0.6, and when neither fork holds one the merged profile has none

#### Scenario: Merge reconciles embedding centroids
- **WHEN** two forks diverge and both update the same agent's voice centroid with different observations
- **THEN** the merged centroid SHALL be the sample-count-weighted average of the two centroids

#### Scenario: Merge with one side lacking embeddings
- **WHEN** one fork has voice and face centroids for an agent and the other fork has none
- **THEN** the merged agent SHALL retain the centroids from the fork that has them

### Requirement: Familiarity is published for downstream coupling
The social cognition module SHALL publish an `social_cognition.agent_model` event on each update carrying
the agent id, the familiarity score, reliability, and interaction count, so that
The affect module can modulate affect coupling by familiarity.

#### Scenario: Update publishes familiarity
- **WHEN** an observation updates an agent model
- **THEN** an `social_cognition.agent_model` event is published containing a numeric
  `familiarity` field

### Requirement: Social prediction errors as salience signals
The social cognition module SHALL publish an `social_cognition.social_error` event when an agent's
observed behavior deviates from its model beyond `deviation_threshold`, with
salience scaled by the magnitude of the deviation. `social_cognition.social_error` is a
**salience-only signal**: it enters the global workspace and raises attention by
its salience value, enabling other modules to react to social surprise. It does
NOT carry raw behavioral data to the conversation surface. The evaluation sidecar
SHALL record every `social_cognition.social_error` event (agent id, salience, deviation
magnitude, timestamp) for accuracy scoring.

#### Scenario: Out-of-character behavior raises salience
- **WHEN** an agent's observed emotion diverges sharply from its established
  histogram
- **THEN** an `social_cognition.social_error` event is published with elevated salience

#### Scenario: In-character behavior is quiet
- **WHEN** an agent behaves consistently with its model
- **THEN** no `social_cognition.social_error` event is published

#### Scenario: Social error enters the workspace as a salience signal only
- **WHEN** an `social_cognition.social_error` event is published
- **THEN** it enters the global workspace with the declared salience value
- **AND** its payload contains only agent id, salience, and deviation magnitude
- **AND** raw behavioral data is not exposed on the conversation surface

#### Scenario: Sidecar records every social error
- **WHEN** an `social_cognition.social_error` event is published
- **THEN** the evaluation sidecar records agent id, salience, deviation magnitude,
  and timestamp in the evaluation log

### Requirement: Social cognition depends on rename-audition-vox
The social cognition module SHALL consume `audition.emotion` and `audition.transcription` events,
which exist only after the `rename-audition-vox` change is applied. The social cognition module
MUST NOT be enabled in production until `rename-audition-vox` is merged.

#### Scenario: Correct event types post-rename
- **WHEN** the social cognition module subscribes to emotion and transcription events
- **THEN** it subscribes to `audition.emotion` and `audition.transcription`
  (not the pre-rename `audio_in.*` event types)

### Requirement: FaithfulRenderer templates for social cognition events
The FaithfulRenderer SHALL include templates for `social_cognition.agent_model` and
`social_cognition.social_error` events so they render in human-readable form inside the
conscious coalition and evaluation logs.

#### Scenario: social_cognition.agent_model renders with familiarity
- **WHEN** an `social_cognition.agent_model` event is passed to the renderer
- **THEN** the output contains the agent label and a formatted familiarity value,
  not a raw dict repr

#### Scenario: social_cognition.social_error renders as a social-surprise line
- **WHEN** an `social_cognition.social_error` event is passed to the renderer
- **THEN** the output contains the agent label and the deviation magnitude

### Requirement: Social cognition skips agent-model fold on degraded emotion events

`SocialCognition._handle_emotion()` SHALL skip the agent-model fold (and NOT
increment `interaction_count`) when the incoming `audition.emotion` payload
carries `"degraded": true`.  A non-running emotion model MUST NOT inflate
familiarity or interaction counts.

#### Scenario: degraded emotion event

- **WHEN** an `audition.emotion` event arrives with `"degraded": true`
- **THEN** the social cognition module does not update the agent model
- **AND** interaction_count is not incremented

#### Scenario: real emotion event

- **WHEN** an `audition.emotion` event arrives without `"degraded": true`
- **THEN** the social cognition module folds the observation into the agent model normally

### Requirement: Heard agents are attributed by channel
The social cognition module SHALL attribute heard emotion and speech to the configured operator label only when they arrive on an operator channel (configurable, by default the live microphone, the microphone and remote audio) or carry no channel. Audio from any other channel SHALL be attributed to a separate agent for that channel (`media:<channel>`), so voices from a film or other media never shape the entity's model of its operator.

#### Scenario: Film dialogue
- **WHEN** Audition publishes emotion from the playlist channel
- **THEN** it updates the `media:playlist` agent and leaves the operator's model unchanged

#### Scenario: The operator speaks
- **WHEN** Audition publishes emotion from the live microphone
- **THEN** it updates the operator's model as before

### Requirement: Social cognition preserves its own agent profiles
The social cognition module SHALL capture every agent profile it holds (in its store, not only those cached since boot) in preservation, and a revived social cognition module SHALL restore exactly those profiles into its own configured collection, re-embedding them with the running embedder. A failure to read the profiles SHALL fail the preservation.

#### Scenario: Profiles not touched since boot
- **WHEN** the social cognition module is preserved holding profiles that were stored before this boot and not read since
- **THEN** those profiles are in the bundle and are restored on revive

### Requirement: An observation without a defined error leaves the error average alone
When an `audition.emotion` event carries a null `prediction_error`, the social cognition module SHALL fold the observation into the agent model without updating `mean_prediction_error`, and the placeholder fold of an `audition.transcription` event SHALL likewise leave it unchanged, so the average is never seeded or pulled toward a made-up 0. Every other part of the fold SHALL be unchanged.

#### Scenario: A null error does not seed the average
- **WHEN** the social cognition module folds an emotion event with a null `prediction_error` and then a transcription event for a new agent
- **THEN** the agent's interaction count is 2 and its behavioral summary has no `mean_prediction_error`, and a later emotion event with an error of 0.3 sets it to 0.3

### Requirement: Social cognition consumes identity update events
The social cognition module SHALL subscribe to `social_cognition.identity_update` events from the identity-binding system and SHALL use the resolved agent id to attribute subsequent emotion and transcription events, replacing the static operator-label attribution when identity binding is enabled and a match is available.

#### Scenario: Identity-resolved attribution replaces label
- **WHEN** identity binding resolves the current speaker to a known agent and an `audition.emotion` event arrives
- **THEN** the social cognition module SHALL attribute the emotion to the identity-resolved agent rather than the configured operator label

#### Scenario: Fallback to label when identity unavailable
- **WHEN** identity binding is disabled or no speaker has been identified
- **THEN** the social cognition module SHALL fall back to the existing channel-based operator-label attribution

### Requirement: Multimodal emotion fusion from face expression and voice emotion
The social cognition module SHALL consume `vision.face_expression` events and fuse face emotion evidence with the existing voice emotion from `audition.emotion`, per agent. When identity binding has resolved a face to an agent, the expression classification for that face updates the agent's emotion histogram with visual evidence.

#### Scenario: Face expression fused with voice emotion for identified agent
- **WHEN** a `vision.face_expression` event arrives for a face that identity binding has resolved to a known agent, and an `audition.emotion` event has been received for the same agent within the same processing window
- **THEN** the social cognition module SHALL fuse the face and voice emotion evidence into the agent's emotion histogram, weighting each by its confidence

#### Scenario: Face expression without identity resolution
- **WHEN** a `vision.face_expression` event arrives but the face has not been resolved to a known agent (identity binding disabled or no match)
- **THEN** the social cognition module SHALL NOT update any agent's emotion histogram from that expression event

#### Scenario: Face expression alone (no voice emotion)
- **WHEN** a `vision.face_expression` event arrives for an identity-resolved agent but no voice emotion is available
- **THEN** the social cognition module SHALL update the agent's emotion histogram from the face expression alone
