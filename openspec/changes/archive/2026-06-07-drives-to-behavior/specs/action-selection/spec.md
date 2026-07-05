## ADDED Requirements

### Requirement: Drive crossings in the conscious coalition can produce intents

When drive-initiative is enabled, the action-selection policy SHALL, on a
non-inhibited snapshot, form intents from `thymos.drive` threshold-crossing
events present in the conscious coalition, in addition to responding to user
communication. A `social_drive` crossing SHALL be able to produce a `speak`
intent (communicative initiative); a `curiosity`, `boredom`, or `restlessness`
crossing SHALL be able to produce a `think` intent (internal deliberation). All
drive-initiated intents remain subject to the inhibition gate and the
in-flight/no-self-response guards; at most one `speak` intent is produced per
tick, and a present user utterance takes precedence over a drive-initiated
`speak`.

#### Scenario: Social drive crossing initiates speech

- **WHEN** a non-inhibited coalition contains a `thymos.drive` event for
  `social_drive` and no user utterance and no speak intent is in flight
- **THEN** a `speak` intent is produced

#### Scenario: Curiosity crossing initiates internal deliberation

- **WHEN** a non-inhibited coalition contains a `thymos.drive` event for
  `curiosity` (or `boredom`/`restlessness`) and no think intent is in flight
- **THEN** a `think` intent is produced (internal speech, not external)

#### Scenario: Inhibition still gates drive-initiated intents

- **WHEN** the snapshot is inhibited
- **THEN** no intent is produced even if drive crossings are present

#### Scenario: User communication outranks a drive-initiated speak

- **WHEN** a non-inhibited coalition contains both a user-communication event
  and a `social_drive` crossing
- **THEN** the single `speak` intent produced is the response to the user
  utterance
