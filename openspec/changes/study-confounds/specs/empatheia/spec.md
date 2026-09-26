## ADDED Requirements

### Requirement: Heard agents are attributed by channel
Empatheia SHALL attribute heard emotion and speech to the configured operator label only when they arrive on an operator channel (configurable, by default the live microphone, the microphone and remote audio) or carry no channel. Audio from any other channel SHALL be attributed to a separate agent for that channel (`media:<channel>`), so voices from a film or other media never shape the entity's model of its operator.

#### Scenario: Film dialogue
- **WHEN** Audition publishes emotion from the playlist channel
- **THEN** it updates the `media:playlist` agent and leaves the operator's model unchanged

#### Scenario: The operator speaks
- **WHEN** Audition publishes emotion from the live microphone
- **THEN** it updates the operator's model as before
