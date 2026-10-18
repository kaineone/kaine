## ADDED Requirements

### Requirement: A sustained concern's drive event recurs until a broadcast accesses it
With `P_re` (`[affect] concern_reentry_s`) above 0, the affect module SHALL keep each active goal's latest drive event (its crossing, then each re-entry) pending until a broadcast accesses it, meaning a broadcast that is not inhibited carries it as a coalition member with a score at or above the broadcast's access threshold. While the event is pending and the goal's drive `D` is at or above its threshold, the module SHALL republish it on each of its own `P_Aff` timer updates as an `affect.drive` event with payload `{"drive": <name>, "value": D, "alert": false, "reentry": true}` and intensity `D`, at most once per goal per update and only when the previous copy is at least `P_Aff / 2` old. After an access the module SHALL publish the goal's next re-entry at the first timer update at least `P_re` after the access. Updates triggered by a broadcast SHALL NOT publish re-entries or copies. Every published copy's bus entry id SHALL join the module's drive entry ids. Pending state SHALL be cleared when the goal ends, on the sleep reset and on restore. When `P_re` is 0 the module SHALL behave bit for bit as the build without re-entry.

#### Scenario: A missed crossing recurs until accessed
- **WHEN** a drive crosses its threshold and no broadcast accesses the crossing
- **THEN** each later timer update at least `P_Aff / 2` after the previous copy publishes a re-entry at the drive's value, until a broadcast accesses one of them

#### Scenario: The interval runs from the access
- **WHEN** a broadcast accesses the goal's pending drive event at entity time `t`
- **THEN** no copy is published before `t + P_re`, and the next re-entry is published at the first timer update at or after `t + P_re`

#### Scenario: A broadcast that does not access it leaves it pending
- **WHEN** a broadcast carries the pending event below the access threshold, is inhibited, or does not carry it
- **THEN** the event stays pending and recurs at the next eligible timer update

#### Scenario: Broadcast-triggered updates publish no re-entry
- **WHEN** the module updates in response to a broadcast while a re-entry is due or an event is pending
- **THEN** it publishes no re-entry and no copy on that update

#### Scenario: Stops when the goal ends, on sleep and on restore
- **WHEN** the goal completes, is abandoned or cleared, the sleep reset runs, or the module is restored
- **THEN** no further copy for that goal is published from the old pending state

#### Scenario: Off is unchanged
- **WHEN** `concern_reentry_s` is 0
- **THEN** a sequence of updates, broadcasts and intents leaves drives, goals and published events identical to the build without re-entry
