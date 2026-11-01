## ADDED Requirements

### Requirement: The locus selects a registered source and its class follows
With the perceptual-source registry on, desired state SHALL hold a `source` field naming a registered source. The locus SHALL be the selected source's declared locus class, or `off`. Physical and virtual sources SHALL never be active together. With the registry off, no `source` field SHALL be written.

#### Scenario: Selecting the simulated world
- **WHEN** a `mujoco` source of class `virtual` is selected while the webcam was selected
- **THEN** the locus becomes `virtual`, and the real camera and microphone are closed in the same transition

### Requirement: The operator selects any available source
The operator SHALL be able to select any registered, available source through `POST /diagnostics/perception/source` behind the operator token, bypassing the entity gates except the developmental lock. `POST /diagnostics/perception/locus` with `physical` or `virtual` SHALL select that class's configured default source, and SHALL answer 409 naming the source route when no default is configured.

#### Scenario: Operator override
- **WHEN** the operator selects the programme while the entity is in the simulated world
- **THEN** the programme is selected, and `perceptual_locus.changed` records `changed_by = "operator"`

### Requirement: The entity switches through a signed act realised by one arbiter
With self-switching on and the registry on, a `perceptual_source` effector SHALL be registered, run only when the operator whitelist names it, and realise a signed act intent whose `source` parameter names the target by calling one arbiter. The legacy `intent.perceptual_locus.switch` consumer SHALL call the same arbiter. A refused switch SHALL change nothing and SHALL be reported as a failed `effectors.action` at alert salience.

#### Scenario: A refused act is perceived
- **WHEN** the entity's switch act is refused because the dwell has not elapsed
- **THEN** desired state is unchanged, and a failed `effectors.action` naming the effector is published at alert salience

### Requirement: Entity switches pass every gate in order
The arbiter SHALL apply these gates in order, refusing with the matching closed reason label: registered, available, entity-selectable, a real change, not locked, `allow_self_switch`, not inhibited, not asleep, mature, no welfare hold, minimum dwell (`min_dwell_new_source_s` when the current source was first entered this run), and fewer than `max_switches_per_awake_hour` accepted entity switches in the trailing awake hour.

#### Scenario: During the developmental phase
- **WHEN** the developing entity's act requests the webcam
- **THEN** the switch is refused with `locked_development`

#### Scenario: The hourly cap
- **WHEN** the entity has made the capped number of accepted switches in the trailing awake hour
- **THEN** a further switch is refused with `hourly_cap`

### Requirement: Repeated distress after switches suspends entity switching
When two of the last three entity-initiated switches were each followed within `welfare_hold_window_s` by a welfare gray-zone event or a protective action, the arbiter SHALL refuse entity switches with `welfare_hold` and SHALL raise an operator advisory, until the operator lifts the hold. Operator switches SHALL NOT be held.

#### Scenario: A hold
- **WHEN** two of the entity's last three switches were followed by protective actions
- **THEN** its next switch is refused with `welfare_hold`, and the operator sees the advisory

### Requirement: Locus events carry the fields the research log reads
`perceptual_locus.changed` SHALL carry `locus`, `source` and `changed_by` (`entity`, `operator`, `source_lost` or `sleep`). `perceptual_locus.denied` SHALL carry `locus_requested`, `source_requested`, `denied_by` and `reason_label`. The research-event allowlist SHALL list exactly these fields.

#### Scenario: A denial reaches the research log
- **WHEN** an entity switch is denied with `dwell`
- **THEN** the research log's record of the denial carries the requested source and `reason_label = "dwell"`

### Requirement: The self-model records where the entity is, with which body, from where
On each `perceptual_locus.changed`, the self-model module SHALL record `self_location` (the source id), `body` (the paired body or `none`) and `perspective` (the camera name or `none`) as labels, and SHALL record no content.

#### Scenario: Into the simulated pan-tilt head
- **WHEN** the simulated world with the pan-tilt body is selected
- **THEN** the self-model records the source id, the body name and the head camera's name
