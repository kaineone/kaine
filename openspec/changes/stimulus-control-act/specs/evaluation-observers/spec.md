## ADDED Requirements

### Requirement: The welfare record gives stimulus-control use per viewing
When stimulus control is enabled, the welfare log SHALL carry a cumulative per-viewing `stimulus_control` record, written by the welfare observer on its affect summary interval and when it stops, giving accepted commands by action and per awake hour, refused commands by action, automatic releases of the `entity` pause, the share of awake time it held the programme, the time-weighted gain distribution, and the item identifiers (channel index, manifest order) in the order visited.

#### Scenario: A viewing with skips
- **WHEN** a viewing ends in which the entity issued two `next` commands and one refused `louder`
- **THEN** the welfare record for that viewing gives `next: 2`, one refused command and the item identifiers in the order visited

### Requirement: The stimulus-control readout compares what follows the entity's acts
The `stimulus_control` record SHALL give, for awake samples within the credit window after the entity's own realized stimulus act and for all other awake samples, the seconds, boredom's above-threshold share, the mean alert excess and the mean learning progress, and the number of acts after which boredom fell within the window.

#### Scenario: Novelty after an act
- **WHEN** an act's window brings alert excess while the rest of the viewing brings none
- **THEN** the readout's mean alert excess is higher after the entity's own acts than otherwise

### Requirement: The stimulus-control records are content-free and absent when off
The `stimulus_control` record SHALL hold no sensory content, title, path or text. The run manifest SHALL record the stage and every bound when stimulus control is enabled; with it off, no record is written and the manifest is unchanged.

#### Scenario: Stimulus control off
- **WHEN** stimulus control is disabled
- **THEN** no `stimulus_control` record is written and the run manifest has no stimulus-control field

### Requirement: The record shows the paused share and its bound
The `stimulus_control` record SHALL give the share of the trailing awake hour held by the entity's pauses, its maximum over the viewing, and the count of pauses the share bound refused.

#### Scenario: The bound binds
- **WHEN** pause after pause is sent for two hours
- **THEN** the record's trailing-hour maximum is at most 25 % and it counts the pauses the bound refused

### Requirement: The readout shows how the credit window credited
The `stimulus_control` record SHALL split the readout's samples within the credit window by the action whose realization opened it, and SHALL count the boredom crossings credited as the entity's own response only because they fell in the window.

#### Scenario: A louder and a next
- **WHEN** a `louder` and later a `next` each open a window
- **THEN** the readout gives each action's window separately, and an end the window alone credited is counted once

### Requirement: Stimulus control off is bit-identical to absent
With stimulus control off, a seeded entity-free harness over the affect module, the action layer, the effectors module, the welfare records and the playlist video source, driven by a script that includes realized stimulus actions and a signed act intent naming the stimulus effector, SHALL produce the digest of the build before the component, and SHALL produce a different digest with the credit window on.

#### Scenario: The disabled build
- **WHEN** the harness runs on a build with stimulus control off
- **THEN** its digest equals the golden captured on origin/main d7fabdc0
