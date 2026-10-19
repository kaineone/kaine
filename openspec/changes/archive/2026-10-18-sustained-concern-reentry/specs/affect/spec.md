## ADDED Requirements

### Requirement: An active goal's drive event recurs while the drive stays above threshold
The affect module SHALL, on each update, for each active goal with a drive whose value `D` is at or above its threshold, publish an `affect.drive` event with payload `{"drive": <name>, "value": D, "alert": false, "reentry": true}` and intensity `D` when at least `P_re` entity seconds have passed since the goal's crossing or its previous re-entry, with `P_re` the `[affect] concern_reentry_s` value (default 30.0, finite and >= 0). The module SHALL record each re-entry's bus entry id among its drive entry ids, so an intent about it is about a drive. A re-entry SHALL NOT be published for a drive below threshold, for a goal without a drive, or for a goal that is no longer active, and the schedule SHALL be cleared when the goal ends and on the sleep reset. When `P_re` is 0 the module SHALL publish no re-entry and keep no re-entry state, so its behaviour SHALL be identical to the build without it.

#### Scenario: A sustained drive re-enters at its value
- **WHEN** a drive crossed at entity time 0, its goal stays active and the drive stays at or above threshold
- **THEN** a re-entry is published at the first update at or after `P_re`, then again `P_re` after it, each with intensity equal to the drive's value and `alert` false

#### Scenario: No re-entry below threshold
- **WHEN** the drive of an active goal is below its threshold at an update past its due time
- **THEN** no re-entry is published, and one is published at the first later update with the drive at or above threshold

#### Scenario: Re-entry stops when the goal ends
- **WHEN** the goal completes, is abandoned (including the stall horizon) or is cleared by the sleep reset
- **THEN** no further re-entry for it is published

#### Scenario: An intent about a re-entry does not relieve boredom
- **WHEN** an intent names the coalition key of a boredom re-entry
- **THEN** boredom is unchanged and restlessness is relieved

#### Scenario: Off reproduces the previous behaviour
- **WHEN** `concern_reentry_s` is 0
- **THEN** a sequence of ticks and intents leaves the drive values, goals and published events identical to the build without re-entry
