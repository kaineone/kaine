## ADDED Requirements

### Requirement: Novelty after the entity's own stimulus act is its own response
When stimulus control is enabled, boredom relief by alert excess or learning progress arriving within `Delta_resp` (the affect module's response window, `goal_response_window_s`) after a realized stimulus act of the entity SHALL be credited `own`, and a boredom crossing that ends in that window, by the relief step or by the build step when boredom would not have fallen without any relief, SHALL count as ended by the entity's own response.

#### Scenario: A skip brings a scene cut
- **WHEN** the entity's `next` act is realized and the resulting alerts relieve boredom within `Delta_resp`
- **THEN** that relief is credited `own`

### Requirement: A realized stimulus act is a successful stimulus action
A realized stimulus act SHALL be an `effectors.action` event for the `stimulus` effector with `success = true`; a failed act or another effector's act SHALL open no credit window.

#### Scenario: A refused command
- **WHEN** the entity's stimulus command is refused and boredom is relieved by alert excess just after
- **THEN** the relief is credited as the current rule credits it

### Requirement: The credit rule is unchanged outside the window and when off
Outside a credit window, and with stimulus control off, the credit rule SHALL be unchanged. With stimulus control off, the affect module SHALL read no effectors stream.

#### Scenario: The window has closed
- **WHEN** boredom is relieved by alert excess more than `Delta_resp` after the entity's last realized stimulus act
- **THEN** the relief is credited as the current rule credits it

#### Scenario: Stimulus control off
- **WHEN** stimulus control is disabled
- **THEN** relief by alert excess is credited as the current rule credits it
