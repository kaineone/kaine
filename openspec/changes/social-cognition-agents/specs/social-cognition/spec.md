## MODIFIED Requirements

### Requirement: Heard agents are attributed by channel
The social cognition module SHALL attribute heard emotion and speech to the configured operator label only when they arrive on an operator channel (configurable, by default the live microphone, the microphone and remote audio) or carry no channel. Audio from any other channel SHALL be attributed to a separate agent for that channel (`media:<channel>`), so voices from a film or other media never shape the entity's model of its operator. When speaker individuation is enabled, the agent SHALL instead be the voice cluster within the channel's pool, and the operator-pool and media-pool separation SHALL keep this protection.

#### Scenario: Film dialogue
- **WHEN** Audition publishes emotion from the playlist channel
- **THEN** it updates the `media:playlist` agent and leaves the operator's model unchanged

#### Scenario: The operator speaks
- **WHEN** Audition publishes emotion from the live microphone
- **THEN** it updates the operator's model as before

#### Scenario: Film dialogue with speaker individuation
- **WHEN** speaker individuation is enabled and Audition publishes emotion from the playlist channel
- **THEN** it updates a media-pool voice agent and leaves every operator-pool agent unchanged

## ADDED Requirements

### Requirement: Each agent model predicts the agent's next turn

When `[social_cognition].agent_model = "predictive"`, each agent SHALL hold an online model that predicts, from context, whether the agent's next turn starts within the response window and its latency, its expressed vocal-affect distribution, and its length. A new agent SHALL start from a prior shared across agents.

#### Scenario: A new agent starts from the shared prior

- **WHEN** a voice is heard for the first time
- **THEN** its first predictions equal the shared prior's

### Requirement: Agent prediction errors are precision-scaled reports

The predictive agent model's errors SHALL be published as `social_cognition.social_error`, scaled by the precision of that agent's recent errors as for other processors, in place of the histogram deviation. The event SHALL carry no transcript text.

#### Scenario: An agent that always answers stops answering

- **WHEN** an agent that has answered the entity's utterances within the response window many times does not answer
- **THEN** a `social_cognition.social_error` with elevated intensity is published for that agent

### Requirement: Engagement with the entity is inferred from response contingency

Each predictive agent model SHALL maintain a posterior that the agent is engaged with the entity, filtered from the contingency of its responses to the entity's utterances, and SHALL publish it as an agent fact. A sharp change SHALL be published as a candidate. No belief or goal state SHALL be attributed.

#### Scenario: Contingent replies raise engagement

- **WHEN** an agent replies promptly to several consecutive utterances of the entity
- **THEN** its engagement posterior rises above its prior

#### Scenario: Speech unrelated to the entity's utterances

- **WHEN** an agent speaks at times unrelated to the entity's utterances
- **THEN** its engagement posterior stays at or below its prior

### Requirement: The social drive's relief is unchanged by agent modelling

Enabling speaker individuation or the predictive agent model SHALL NOT change which events meet the social drive.

#### Scenario: Drive relief with the predictive model on

- **WHEN** the predictive agent model is enabled and any interaction is timed by the sequence module
- **THEN** the social drive is met exactly as with the model off
