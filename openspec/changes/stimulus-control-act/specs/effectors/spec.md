## ADDED Requirements

### Requirement: A stimulus effector with a declared, bounded action set
KAINE SHALL provide a `stimulus` effector that declares the actions `pause`, `resume`, `next`, `previous`, `louder`, `quieter`, and `channel:<k>` for each operator-configured programme channel when more than one is configured. It SHALL run only when `[stimulus_control].enabled` is true and the operator's whitelist names it, and both SHALL be off in the shipped configuration.

#### Scenario: Shipped configuration
- **WHEN** an act intent names the stimulus effector under the shipped configuration
- **THEN** no stimulus request is written and the blocked attempt is audited

#### Scenario: One channel
- **WHEN** the operator configures a single programme channel
- **THEN** the stimulus effector declares no `channel:<k>` action

### Requirement: The stimulus effector refuses out-of-bound commands
The stimulus effector SHALL refuse a command issued less than `Delta_sc` of entity time after the previous stimulus command, a seek beyond `n_seek` per awake hour, and a gain change that would leave the range of plus or minus `G_max` decibels around the programme level. A refused command SHALL be reported as a failed action and audited, and SHALL change nothing.

#### Scenario: Too soon
- **WHEN** a `next` command arrives 10 s of entity time after a `louder` command with `Delta_sc = 30`
- **THEN** the command is refused, audited, and the programme position is unchanged

#### Scenario: Gain at its bound
- **WHEN** the gain is at `+G_max` and a `louder` command arrives
- **THEN** the command is refused and the gain stays at `+G_max`

### Requirement: Stimulus requests carry flags and numbers only
The stimulus effector SHALL pass each accepted command to the feeds through the perception desired state as a pause flag, a seek count, a gain in decibels or a channel index, and SHALL write no frame, sample or transcript anywhere.

#### Scenario: An accepted seek
- **WHEN** an accepted `next` command is applied
- **THEN** the desired state holds a seek count and no sensory content
