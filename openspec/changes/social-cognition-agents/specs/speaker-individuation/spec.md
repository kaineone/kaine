## ADDED Requirements

### Requirement: Voiced segments are embedded by a local speaker model

When `[social_cognition].speaker_individuation` is true, each voiced segment the audition module analyses for tone SHALL be embedded by a local speaker-embedding model provisioned at setup with its license recorded. The model SHALL run on the host with no network access, and SHALL NOT be made by Meta or derived from a Meta model.

#### Scenario: Embedding without network

- **WHEN** a voiced segment is embedded with outbound network blocked
- **THEN** the embedding is produced and no connection is attempted

### Requirement: Agents form by clustering voices within a channel pool

Speaker embeddings SHALL be clustered online without labels into agents, in two separate pools, one for operator channels and one for media channels. A segment SHALL update only an agent of its own pool.

#### Scenario: Two speakers on one microphone

- **WHEN** two different people speak in turn on the live microphone
- **THEN** two agents form in the operator pool

#### Scenario: A film voice never joins an operator agent

- **WHEN** a film character whose voice resembles the operator's speaks on the playlist channel
- **THEN** the segment updates or forms an agent in the media pool and no operator-pool agent changes

### Requirement: The entity's own voice forms no agent

Segments inside the speaking gate's open window SHALL NOT be embedded, and segments matching the reserved cluster of the entity's own synthetic voice SHALL NOT update or form any agent.

#### Scenario: Own speech replayed into the audio path

- **WHEN** the vocal module's output is played into the audition path outside the speaking window
- **THEN** it matches the reserved self cluster and no agent changes

### Requirement: Only voice centroids persist

Each agent SHALL persist as a centroid, spread and count in the speaker-embedding space plus its agent-model parameters. No audio and no per-segment embedding SHALL persist. Centroids SHALL be privacy-filter vector fields, never displayed or logged. When `[social_cognition].persist_operator_voices` is false, operator-pool agents SHALL NOT persist across a restart.

#### Scenario: No segment embeddings on disk

- **WHEN** the social cognition store is read after a conversation
- **THEN** it holds one centroid per agent and no per-segment embedding or audio

#### Scenario: Operator voices not persisted

- **WHEN** `persist_operator_voices` is false and the cycle restarts
- **THEN** no operator-pool agent is restored, and media-pool agents are restored
