## ADDED Requirements

### Requirement: A drive-led stimulus act after maturation (stage M)
With stimulus control enabled at `stage = "minimal"`, after the developmental phase, an accessed broadcast led by the entity's own boredom or restlessness drive event SHALL yield one signed stimulus act intent once `Delta_sc` has passed since the last. Its action SHALL be drawn uniformly from the currently allowed actions with a run-seeded generator. At most one intent per broadcast SHALL be emitted, and the trigger's basis SHALL be cited at the code site.

#### Scenario: Boredom leads an accessed broadcast
- **WHEN** stage M is on, the entity is mature, and its boredom drive event leads an accessed broadcast after `Delta_sc`
- **THEN** one act intent naming the stimulus effector is emitted with an action drawn from the allowed set

#### Scenario: Gain at its bound
- **WHEN** the gain is at `+G_max`
- **THEN** `louder` is not among the actions drawn

#### Scenario: Developmental phase
- **WHEN** the entity is in the developmental phase
- **THEN** the stir rule applies and no stimulus act is derived

### Requirement: Stimulus control is off in the workspace-mediation arms
Every workspace-mediation study file SHALL set `[stimulus_control].enabled = false`, and the boot SHALL refuse a workspace-mediation arm with stimulus control enabled.

#### Scenario: An arm enables it
- **WHEN** a workspace-mediation study file enables stimulus control
- **THEN** the boot fails with a configuration error
