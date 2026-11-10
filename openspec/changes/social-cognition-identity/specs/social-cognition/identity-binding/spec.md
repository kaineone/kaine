# Spec Delta

## Purpose

Cross-modal identity binding that matches speaker embeddings and face embeddings to known agents via exemplar buffers and consolidated centroids, binds voice and face to the same agent through temporal co-occurrence, and publishes identity updates when agents are recognized or newly encountered.

## ADDED Requirements

### Requirement: Speaker identification matches voice embeddings to known agents
The identity-binding system SHALL compare each incoming speaker embedding against known agents' voice exemplar buffers (during fast-binding phase) or voice centroids (after consolidation) and SHALL resolve to the best-matching agent when the similarity exceeds a configurable threshold. When no known agent exceeds the threshold, the system SHALL mint a new agent.

#### Scenario: Known speaker recognized
- **WHEN** an `audition.speaker_embedding` event arrives with an embedding whose cosine similarity to an existing agent's voice centroid exceeds the configured speaker identification threshold
- **THEN** the system SHALL resolve to that agent and publish a `social_cognition.identity_update` event with the agent id, modality `voice`, the similarity as confidence, and `is_new` false

#### Scenario: Unknown speaker triggers new agent
- **WHEN** an `audition.speaker_embedding` event arrives with an embedding whose cosine similarity to every known agent's voice representation is below the configured speaker identification threshold
- **THEN** the system SHALL mint a new agent, store the embedding as the first voice exemplar, and publish a `social_cognition.identity_update` event with the new agent id, modality `voice`, and `is_new` true

#### Scenario: Exemplar-based matching during fast-binding phase
- **WHEN** an agent has fewer voice exemplars than the configured consolidation threshold
- **THEN** speaker identification SHALL use nearest-exemplar comparison against the agent's voice exemplar buffer rather than centroid comparison

### Requirement: Face identification matches face embeddings to known agents
The identity-binding system SHALL compare each incoming face embedding against known agents' face exemplar buffers (during fast-binding phase) or face centroids (after consolidation) and SHALL resolve to the best-matching agent when the similarity exceeds a configurable threshold. When no known agent exceeds the threshold, the system SHALL mint a new agent.

#### Scenario: Known face recognized
- **WHEN** a `vision.face_detection` event arrives with a face embedding whose similarity to an existing agent's face centroid exceeds the configured face identification threshold
- **THEN** the system SHALL resolve to that agent and publish a `social_cognition.identity_update` event with the agent id, modality `face`, the similarity as confidence, and `is_new` false

#### Scenario: Unknown face triggers new agent
- **WHEN** a `vision.face_detection` event arrives with a face embedding whose similarity to every known agent's face representation is below the configured face identification threshold
- **THEN** the system SHALL mint a new agent, store the embedding as the first face exemplar, and publish a `social_cognition.identity_update` event with the new agent id, modality `face`, and `is_new` true

#### Scenario: Multiple faces in one frame
- **WHEN** a `vision.face_detection` event carries embeddings for more than one detected face
- **THEN** the system SHALL resolve each face independently against known agents, minting new agents as needed, and SHALL publish one `social_cognition.identity_update` per resolved face

### Requirement: Cross-modal binder associates voice and face through reliability-weighted temporal co-occurrence
The identity-binding system SHALL bind a voice identification and a face identification to the same agent when both occur within a configurable temporal co-occurrence window, operating as a convergence-zone correlator with Bayesian reliability weighting. Each co-occurrence observation updates a posterior probability (binding_confidence) that the voice and face share a common cause, following the MLE framework (Ernst & Banks, 2002). Agent merge triggers when accumulated binding_confidence exceeds a configurable threshold.

#### Scenario: Voice and face co-occur within window, binding confidence exceeds threshold
- **WHEN** a speaker identification resolves to agent A and a face identification resolves to agent B, both events occur within the configured co-occurrence window, agents A and B are distinct, and the accumulated binding_confidence between them exceeds the configured merge threshold
- **THEN** the system SHALL merge agents A and B into a single agent that holds both the voice and face representations, and SHALL publish a `social_cognition.identity_update` with the merged agent id and both modalities

#### Scenario: Co-occurrence below merge threshold
- **WHEN** a speaker identification and face identification co-occur within the window for distinct agents, but the accumulated binding_confidence has not yet exceeded the merge threshold
- **THEN** the system SHALL update the binding_confidence between the two agents using the Bayesian posterior from the current observation, weighted by each modality's reliability, without merging

#### Scenario: Voice and face already bound to same agent
- **WHEN** a speaker identification and face identification both resolve to the same existing agent within the co-occurrence window
- **THEN** the system SHALL update the agent's exemplar buffers and centroids for both modalities without merging, and SHALL increase the agent's binding confidence

#### Scenario: No co-occurring detection
- **WHEN** a speaker identification occurs and no face identification occurs within the co-occurrence window (or vice versa)
- **THEN** the system SHALL NOT attempt cross-modal binding for that event

### Requirement: Per-modality reliability weighting
The identity-binding system SHALL compute per-modality reliability for each agent from the intra-cluster variance of the exemplar buffer. Low-variance exemplar clusters indicate high reliability. Reliability SHALL weight identity match confidence and binding decisions.

#### Scenario: Reliability computed from exemplar variance
- **WHEN** an agent has two or more exemplars in a modality's buffer
- **THEN** the system SHALL compute the intra-cluster variance (mean squared cosine distance from centroid) and store it as that modality's reliability score (inverse variance, normalized to [0, 1])

#### Scenario: Low-reliability modality down-weighted in binding
- **WHEN** a cross-modal co-occurrence is evaluated and one modality has low reliability (high exemplar variance)
- **THEN** that modality's contribution to the binding_confidence posterior SHALL be reduced proportionally to its reliability

#### Scenario: Single exemplar has default reliability
- **WHEN** an agent has only one exemplar in a modality (no variance computable)
- **THEN** that modality's reliability SHALL default to a configurable floor value (conservative, low)

### Requirement: Two-phase identity learning with exemplar buffer and centroid consolidation
The identity-binding system SHALL implement a two-phase learning process: a fast-binding phase using individual exemplar storage and nearest-exemplar matching, and a slow-consolidation phase using centroid representations.

#### Scenario: Exemplar accumulation during fast binding
- **WHEN** a new embedding arrives for an agent whose exemplar count for that modality is below the configured consolidation threshold
- **THEN** the system SHALL store the embedding in the agent's exemplar buffer for that modality with a timestamp

#### Scenario: Consolidation when exemplar diversity is sufficient
- **WHEN** an agent's exemplar count for a modality reaches the configured consolidation threshold AND the intra-cluster variance of the exemplars exceeds the configured diversity floor
- **THEN** the system SHALL compute a centroid from the exemplars and transition to centroid-based matching for that modality

#### Scenario: Centroid update after consolidation
- **WHEN** a new embedding arrives for an agent that has consolidated a centroid for that modality
- **THEN** the system SHALL update the centroid using an exponential moving average and MAY prune the exemplar buffer to retain only diverse exemplars

#### Scenario: Exemplar buffer is bounded
- **WHEN** the exemplar buffer for an agent and modality reaches the configured maximum buffer size
- **THEN** the system SHALL evict the least diverse exemplar (most similar to the centroid or to other exemplars) to make room

### Requirement: Identity binding is config-gated and ships disabled
The identity-binding system SHALL be gated by configuration flags and SHALL ship disabled. Enabling it SHALL require both the speaker embedding extractor in audition and the face detection pipeline in vision to be enabled.

#### Scenario: Disabled by default
- **WHEN** the system boots with shipped default configuration
- **THEN** identity binding SHALL NOT run, no identity consumers SHALL subscribe to bus events, and no `social_cognition.identity_update` events SHALL be published

#### Scenario: Partial enablement
- **WHEN** only speaker embedding extraction is enabled (face detection disabled)
- **THEN** speaker identification SHALL function independently, minting and recognizing agents by voice only, without cross-modal binding

#### Scenario: Face-only enablement
- **WHEN** only face detection is enabled (speaker embedding disabled)
- **THEN** face identification SHALL function independently, minting and recognizing agents by face only, without cross-modal binding

### Requirement: Identity update events carry structured identity evidence
Each `social_cognition.identity_update` event SHALL carry `agent_id` (string), `modality` (one of `voice`, `face`, or `both`), `confidence` (float in [0, 1]), `is_new` (boolean), and `binding_confidence` (float in [0, 1] or null when no cross-modal binding exists for the agent).

#### Scenario: Event payload completeness
- **WHEN** a `social_cognition.identity_update` event is published
- **THEN** the event payload SHALL contain all required fields with values in their specified ranges
