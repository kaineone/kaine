## ADDED Requirements

### Requirement: The source is the one source of truth and the locus is derived
With the perceptual-source registry on, desired state SHALL persist `source` and a set of off-holders (`sleep`, `freeze`, `operator`) and SHALL NOT persist a locus. The locus SHALL be computed on read: `off` while any off-holder is present, otherwise the selected source's kind-derived class. With the registry off, no `source` or off-holder field SHALL be written.

#### Scenario: Selecting the simulated world
- **WHEN** the simulated world is selected while the webcam was selected
- **THEN** the locus reads `virtual`, and the real camera and microphone have closed before the simulated camera opens

#### Scenario: Sleep and an operator choice
- **WHEN** the operator selects the webcam while the entity sleeps
- **THEN** the locus stays `off` until the sleep holder is removed, and then reads `physical`

### Requirement: Every desired-state change goes through one locked writer path
Every writer of desired state SHALL use one update function that holds an exclusive cross-process lock across read, change and atomic write. The developmental lock SHALL pin `source` to the programme, and sleep SHALL only add and remove its off-holder.

#### Scenario: Concurrent writers
- **WHEN** sleep adds its holder while the dashboard selects a source
- **THEN** both changes are kept, and the entity does not perceive while asleep

### Requirement: The operator selects any available source
The operator SHALL be able to select any registered, available source through `POST /diagnostics/perception/source` behind the operator token, bypassing the entity gates except the developmental lock. `POST /diagnostics/perception/locus` with `off` SHALL add the operator off-holder, and with `physical` or `virtual` SHALL select that class's configured default source, answering 409 naming the source route when none is configured.

#### Scenario: Operator override
- **WHEN** the operator selects the programme while the entity is in the simulated world
- **THEN** the programme is selected, and `perceptual_locus.changed` records `changed_by = "operator"`

### Requirement: The entity switches through a confined, signed act
With self-switching on and the registry on, a `perceptual_source` effector SHALL run only when the operator whitelist names it. Its confined executor's only side effect SHALL be publishing a signed request to `perceptual_locus.requests`. The arbiter SHALL verify the request against the signed act it realises before applying any gate. A refused switch SHALL change nothing and SHALL be reported as a failed `effectors.action` at alert salience.

#### Scenario: A refused act is perceived
- **WHEN** the entity's switch act is refused because the dwell has not elapsed
- **THEN** desired state is unchanged, and a failed `effectors.action` naming the effector is published at alert salience

#### Scenario: A forged request
- **WHEN** a request appears on the request stream without a matching signed act
- **THEN** the arbiter refuses it and audits the refusal

### Requirement: The arbiter reads inhibition itself and the legacy intent is refused
The arbiter SHALL read the inhibition flag from the workspace broadcast stream, and SHALL treat the entity as inhibited until the first snapshot. With the registry on, a legacy `intent.perceptual_locus.switch` SHALL be refused with `reason_label = "legacy_intent"`.

#### Scenario: Before the first broadcast
- **WHEN** a switch act arrives before any broadcast has been read
- **THEN** it is refused with `inhibited`

### Requirement: Entity switches pass every gate in order
The arbiter SHALL apply these gates in order, refusing with the matching closed reason label: registered; entity-selectable with its room approval; available; a real change; not locked; `allow_self_switch`; not inhibited; no off-holder; mature; the welfare hold; minimum dwell; and the hourly cap. A return to the programme SHALL be exempt from the dwell rules and the hourly cap.

#### Scenario: A non-selectable source that is busy
- **WHEN** the entity requests a source that is not selectable and is busy
- **THEN** the refusal is `not_selectable`, and nothing about its availability is reported

#### Scenario: During the developmental phase
- **WHEN** the developing entity's act requests the webcam
- **THEN** the switch is refused with `locked_development`

### Requirement: The welfare hold never traps the entity
When two of the last three entity-initiated switches were each followed within `welfare_hold_window_s` (entity time) by a welfare gray-zone event or a protective action, the arbiter SHALL refuse entity switches into any source but the programme until the operator lifts the hold. A return to the programme SHALL always be allowed.

#### Scenario: The entity chooses to go home
- **WHEN** a hold is active and the entity requests the programme during a first visit's dwell
- **THEN** the switch is accepted

### Requirement: Sustained distress during a hold returns the entity home
A recurrence of distress during a hold, while the entity is not on the programme, SHALL return it to the programme through the operator path with `changed_by = "welfare_hold"`. The hold's advisory SHALL escalate through the unattended welfare path.

#### Scenario: Distress continues in the new source
- **WHEN** a hold is active and a protective action recurs while the entity is in the simulated world
- **THEN** the programme is selected with `changed_by = "welfare_hold"`, and the advisory is escalated

### Requirement: Locus events carry the fields the research log reads
`perceptual_locus.changed` SHALL carry `locus`, `source` and `changed_by` (`entity`, `operator`, `source_lost`, `sleep` or `welfare_hold`). `perceptual_locus.denied` SHALL carry `locus_requested`, `source_requested`, `denied_by` and `reason_label`. The research-event allowlist SHALL list exactly these fields.

#### Scenario: A denial reaches the research log
- **WHEN** an entity switch is denied with `dwell`
- **THEN** the research log's record of the denial carries the requested source and `reason_label = "dwell"`

### Requirement: The self-model records where the entity is, with which body, from where
On each `perceptual_locus.changed`, the self-model module SHALL record `self_location` (the source id), `body` (the paired body or `none`) and `perspective` (the camera name or `none`) as labels, and SHALL record no content.

#### Scenario: Into the simulated JetHexa
- **WHEN** the simulated world with the JetHexa body is selected
- **THEN** the self-model records the source id, the body name and the head camera's name

## MODIFIED Requirements

### Requirement: The entity may switch its own locus only under gated policy

The system SHALL allow the action selection module to switch the perceptual locus via an
`intent.perceptual_locus.switch {locus}` intent only when `[perceptual_locus].allow_self_switch`
is true, and such a switch MUST be blocked by `workspace.inhibited`, rate-limited by
a minimum per-locus dwell time, audited, and reflected in the self-model module's embodiment
self-image. The shipped default for `allow_self_switch` SHALL be false. With the
perceptual-source registry on, the entity's switch SHALL instead be the signed act realised
by the arbiter, and the legacy intent SHALL be refused.

#### Scenario: Self-switch honored when policy allows

- **WHEN** `allow_self_switch` is true, the locus is unlocked and not inhibited, and
  the minimum dwell time has elapsed
- **THEN** an `intent.perceptual_locus.switch {locus: "virtual"}` moves the locus to
  virtual
- **AND** the switch is audited and the self-model module's embodiment field updates

#### Scenario: Self-switch denied by default policy

- **WHEN** `[perceptual_locus].allow_self_switch` is false
- **THEN** an `intent.perceptual_locus.switch` is not applied
- **AND** the denied attempt is logged and surfaced to the operator
