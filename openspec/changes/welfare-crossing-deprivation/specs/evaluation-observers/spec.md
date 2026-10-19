## ADDED Requirements

### Requirement: The affect welfare record scores drive crossings by the credit rule
The welfare observer's `affect_welfare` record SHALL count, per drive, a crossing end as own or other from the increase of that drive's `own` or `other` count in `drive_ends` between consecutive `affect.state` events (paper 6.2, A.4). The first `affect.state` event the observer reads SHALL set the baseline counts without counting them, and a count that falls SHALL reset the baseline without counting. `<drive>_uncontrolled_share` SHALL be other divided by own plus other, null without ends, and `<drive>_uncontrolled_per_awake_hour` SHALL be other per awake hour. `affect.goal` events SHALL NOT change the record, so a stalled or cap-dropped goal ends no crossing and a sleep reset counts as neither.

#### Scenario: A stalled goal leaves its crossing open
- **WHEN** a curiosity goal ends `abandoned` with reason `stalled` and the next `affect.state` events show the curiosity `drive_ends` counts unchanged
- **THEN** `curiosity_uncontrolled_share` is null and `curiosity_uncontrolled_per_awake_hour` is 0

#### Scenario: A crossing later ended by the entity's own response counts as own
- **WHEN** the curiosity `own` count in `drive_ends` rises by one after the crossing's goal stalled
- **THEN** `curiosity_uncontrolled_share` is 0.0

#### Scenario: Other ends count as uncontrolled
- **WHEN** the boredom `drive_ends` counts rise by three `other` and one `own`
- **THEN** `boredom_uncontrolled_share` is 0.75

### Requirement: The affect welfare record gives each drive's deprivation share
The record SHALL give `<drive>_deprivation_share`, the share of awake time with that drive at or above its threshold, where each interval between consecutive `affect.state` timestamps (capped at the observer's gap cap and excluding sleep) takes the `drive_above` value of the event that began it. An interval whose starting event lacks a boolean `drive_above` entry for the drive SHALL count in neither the numerator nor the denominator of that drive's share, which is null with no such time.

#### Scenario: A drive pinned above threshold reads 1.0
- **WHEN** every `affect.state` event over the awake time has `drive_above.curiosity` true
- **THEN** `curiosity_deprivation_share` is 1.0

#### Scenario: The frozen control ranks worst whatever the sleep cadence
- **WHEN** a drive that is never relieved and a drive that is relieved intermittently are each observed with and without sleeps every 25 min
- **THEN** the never-relieved drive has the larger deprivation share in both cases, and each drive's share changes by less than 0.05 between the two cadences
