# action-selection Specification

## Purpose
TBD - created by archiving change executive-action-intent. Update Purpose after archive.
## Requirements
### Requirement: Executive action selection gated by inhibition

After each experiential workspace broadcast, the cognitive cycle SHALL invoke an
executive action-selection step ("Volition") with the `WorkspaceSnapshot`. When
the snapshot is inhibited (the winning coalition did not clear Syneidesis's
publication threshold), the step SHALL produce **no** intents. When the snapshot
is not inhibited, the step MAY produce zero or more action intents according to
its policy. Action intents SHALL be published to the `volition.out` stream and
SHALL be the ONLY source of effector activation; no effector may act on the raw
broadcast.

#### Scenario: Inhibited snapshot produces no intents

- **WHEN** action selection runs on a snapshot whose `inhibited` is true
- **THEN** no intent is produced and nothing is published to `volition.out`

#### Scenario: Non-inhibited snapshot may produce an intent

- **WHEN** action selection runs on a non-inhibited snapshot whose conscious
  coalition contains content the policy is disposed to act on
- **THEN** a corresponding intent is published to `volition.out`

#### Scenario: Action selection runs only on experiential broadcasts

- **WHEN** a processing tick does not produce an experiential broadcast
- **THEN** action selection does not run for that tick

### Requirement: Action intents have an explicit kind and referent

Each intent SHALL declare a `kind` of `speak`, `think`, or `act`, and SHALL
reference the conscious content it concerns (an entry id and/or a summary) so
the realizing effector can act appropriately. The action-selection policy SHALL
be an injectable component so motivational inputs (drives, recalled context) can
be added later without changing the cycle wiring or the intent transport.

#### Scenario: Speak intent carries its referent

- **WHEN** the policy decides to speak about a conscious event
- **THEN** the emitted `speak` intent references that event's content

### Requirement: No action on the entity's own output; one intent in flight

The default policy SHALL NOT form a `speak` intent whose referent is the
entity's own prior external speech (no self-response feedback loop), and SHALL
NOT form a new `speak` intent while a prior one is still being realized
(one-in-flight guard).

#### Scenario: Entity's own speech does not trigger a response

- **WHEN** the conscious coalition contains only the entity's own
  `lingua.external` output
- **THEN** no `speak` intent is produced

#### Scenario: No overlapping speak intents

- **WHEN** a `speak` intent is still being realized
- **THEN** the policy does not emit another `speak` intent until it completes

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

