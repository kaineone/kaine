## ADDED Requirements

### Requirement: Effectors execute only in response to an act intent

Praxis SHALL execute an effector only in response to an `act` intent emitted by
the executive action-selection step. Praxis SHALL NOT act directly on the
workspace broadcast. Because action intents originate only from the
inhibition-gated action-selection step, an inhibited entity performs no
effector actions.

#### Scenario: Praxis runs an effector for an act intent

- **WHEN** an `act` intent naming a registered effector is delivered to Praxis
- **THEN** Praxis invokes that effector and records the action in its audit log

#### Scenario: Praxis does not act without an intent

- **WHEN** a workspace broadcast occurs but no `act` intent is issued
- **THEN** Praxis invokes no effector
