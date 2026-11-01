## ADDED Requirements

### Requirement: A drive-led stimulus act after maturation (stage M)
With stage M installed, after the developmental phase, a non-inhibited broadcast whose leading member (the member with the highest salience score) is the entity's own boredom or restlessness drive event SHALL yield one signed stimulus act intent once `Delta_sc` of entity time has passed since the last. Its action SHALL be drawn uniformly from the actions the programme can take now, with a generator seeded from the run seed, and the trigger's basis SHALL be cited at the code site.

#### Scenario: Boredom leads an accessed broadcast
- **WHEN** stage M is on, the entity is mature, and its boredom drive event leads an accessed broadcast after `Delta_sc`
- **THEN** one act intent naming the stimulus effector is emitted with an action drawn from the allowed set

#### Scenario: Gain at its bound
- **WHEN** the gain is at `+G_max`
- **THEN** `louder` is not among the actions drawn

#### Scenario: Developmental phase
- **WHEN** the entity is in the developmental phase
- **THEN** no stimulus act is derived

### Requirement: Stage M never draws pause
The stage-M source SHALL leave `pause` out of the actions it draws from, so that no pause is random deprivation; the effector SHALL keep `pause` and its bounds for stage L.

#### Scenario: Pause allowed
- **WHEN** the programme would take `pause`, `next` and `louder`
- **THEN** stage M draws only `next` or `louder`, and with `pause` the only allowed action it forms no intent

### Requirement: Stage M forms only acts the effector would take now
The stage-M source SHALL form a stimulus intent only when the stimulus effector's own interval check passes, so that realization latency never turns an act formed at the `Delta_sc` boundary into a refusal.

#### Scenario: At the interval's boundary
- **WHEN** a lead arrives 30.02 s after an intent whose act was realized 0.08 s after it formed
- **THEN** no intent forms, so no act is refused for its interval

### Requirement: Stage M wraps the policy only when the act can run
Boot SHALL install the stage-M source around the configured action-selection policy only when `[stimulus_control].enabled` is true with `stage = "minimal"`, a playlist programme is under its control, the effectors module is on and its whitelist names the stimulus effector. The source SHALL pass the wrapped policy's intents and hooks unchanged and add at most one stimulus intent per broadcast; otherwise the policy SHALL be the wrapped one.

#### Scenario: Not whitelisted
- **WHEN** stimulus control is enabled but the effector whitelist does not name the stimulus effector
- **THEN** the policy is not wrapped and the boot logs that no stimulus act is derived

### Requirement: Stimulus control is refused in the between-arm studies and without the welfare net
The boot SHALL refuse, before any module starts and with the stimulus-control refusal exit code, a workspace-mediation or workspace-feedback study whose merged configuration enables stimulus control, stimulus control enabled while `[preservation.welfare_response].enabled` is false, and an invalid `[stimulus_control]` section.

#### Scenario: No welfare net
- **WHEN** stimulus control is enabled and the welfare response is off
- **THEN** the boot fails with the stimulus-control refusal exit code

#### Scenario: An arm enables it
- **WHEN** the operator configuration enables stimulus control and a workspace-mediation study is selected
- **THEN** the boot fails with the stimulus-control refusal exit code
