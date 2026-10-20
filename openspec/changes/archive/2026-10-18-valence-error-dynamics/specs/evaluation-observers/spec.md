## ADDED Requirements

### Requirement: The welfare log gives affect welfare shares
The welfare observer SHALL write an `affect_welfare` record to its JSONL log every `affect_summary_interval_s` of unfrozen time (default 300 s) when new affect samples were read, and when it stops if anything changed since the last record. The record SHALL give, cumulatively since the observer started, the awake seconds counted, the configured bar, the share of awake time with valence below `-negative_valence_bar` (default 0.5), and for each drive in a fixed table (curiosity, boredom, social_drive, restlessness) the share of goal ends without the entity's own response (abandoned with reason `without_response`, `stalled` or `cap`) among those ends and the ends completed with reason `own_response`, and the rate of those uncontrolled ends per awake hour. Time SHALL be measured between consecutive `affect.state` timestamps, each gap capped, and gaps that start inside a sleep (between `sleep.sleep.started` and `sleep.sleep.completed`) SHALL not count. A share with no denominator SHALL be null.

#### Scenario: Negative-valence share from a synthetic run
- **WHEN** the observer reads 100 s of awake affect states, 25 s of them with valence -0.6, plus a 50 s sleep with valence -0.6
- **THEN** the record gives 100 awake seconds and a negative-valence share of 0.25

#### Scenario: Uncontrolled-end share per drive
- **WHEN** boredom goals end three times `without_response` and once `own_response`, and a restlessness goal ends `stalled`
- **THEN** the boredom share is 0.75, and restlessness has a share of 1.0

### Requirement: Affect welfare records are content-free
The `affect_welfare` record SHALL contain only the `ts` string, the `record` label, and numbers (or null) computed by the observer, under fixed key names. It SHALL NOT be published on the bus, and no field SHALL be copied from a source event payload.

#### Scenario: A drive name outside the table is not recorded
- **WHEN** a goal event names an unknown drive
- **THEN** no key in the record contains that name
