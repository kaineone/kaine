## ADDED Requirements

### Requirement: A stimulus effector with a declared action set
KAINE SHALL provide a `stimulus` effector that declares the actions `pause`, `resume`, `next`, `previous`, `louder`, `quieter`, and `channel:<k>` for each operator-configured programme channel when two or more are configured.

#### Scenario: One channel
- **WHEN** the operator configures a single programme channel
- **THEN** the stimulus effector declares no `channel:<k>` action

### Requirement: The stimulus effector exists only when stimulus control is on
The stimulus effector and its request type SHALL be built and registered only when `[stimulus_control].enabled` is true and boot builds a playlist programme under its control, and the effector SHALL run only when the operator's effector whitelist names it. Both SHALL be off in the shipped configuration.

#### Scenario: Shipped configuration
- **WHEN** a signed act intent names the stimulus effector under the shipped configuration
- **THEN** the intent is dropped as for any effector that does not exist, and no stimulus request is made

#### Scenario: Built but not whitelisted
- **WHEN** stimulus control is enabled and the effector whitelist does not name `stimulus`
- **THEN** an act intent naming it is blocked before the effector runs and the blocked attempt is audited

### Requirement: The stimulus effector refuses out-of-bound commands
The stimulus effector SHALL refuse a command issued less than `Delta_sc` of entity time after the previous accepted command, a seek beyond `n_seek` within the last awake hour, and a gain change that would leave the range of plus or minus `G_max` decibels around the programme level. A refused command SHALL be reported as a failed action and audited, and SHALL change nothing.

#### Scenario: Too soon
- **WHEN** a `next` command arrives 10 s of entity time after a `louder` command with `Delta_sc = 30`
- **THEN** the command is refused, audited, and the programme position is unchanged

#### Scenario: Gain at its bound
- **WHEN** the gain is at `+G_max` and a `louder` command arrives
- **THEN** the command is refused and the gain stays at `+G_max`

### Requirement: The seek cap counts awake time
The awake time over which the stimulus effector counts seeks SHALL exclude every span in which the playlist clock is held by the `sleep` or `freeze` holder.

#### Scenario: Sleep does not refill the seek budget
- **WHEN** the entity has used its seeks and then sleeps for an hour
- **THEN** a seek after waking is still refused until an awake hour has passed

### Requirement: The stimulus effector refuses what the programme cannot take
The stimulus effector SHALL refuse an action outside its declared set, any command before the programme starts, while the stimulus-source-to-world crossfade holds it or after it ends, `pause` while the programme is paused by the entity, `resume` while it is not, and a switch to the current channel, each as a failed, audited action that changes nothing.

#### Scenario: Before the programme starts
- **WHEN** a `next` command arrives before either feed has read the programme
- **THEN** the command is refused and nothing changes

### Requirement: The gain bound cannot be widened
The configuration SHALL refuse a `[stimulus_control].gain_max_db` above 6 dB, the design's welfare bound on loudness, and a `gain_step_db` above `gain_max_db`.

#### Scenario: A wider bound
- **WHEN** the operator sets `gain_max_db = 9`
- **THEN** the boot refuses the section as invalid

### Requirement: Stimulus requests carry an action name only
The stimulus effector SHALL pass each accepted command to the programme in process, through the controller the boot registry hands to the feeds, as an action name that the controller turns into a pause holder, a seek, a gain in decibels or a channel index. It SHALL write no frame, sample or transcript anywhere, and its audit request SHALL be the action name only.

#### Scenario: An accepted seek
- **WHEN** an accepted `next` command is applied
- **THEN** the audit record's request is `{"action": "next"}` and no sensory content is written
