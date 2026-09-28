# action-selection Specification

## Purpose
Volition is KAINE's executive action layer, the only path from a conscious workspace snapshot to an effector. This capability defines how intents are selected: the inhibition gate checked first, explicit intent kinds and referents, no action on the entity's own output, one intent of each kind in flight, drive-initiated intents, and the realization of conscious Nous proposals under those same gates.

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

Each intent SHALL declare a `kind` of `speak`, `think`, `act`, or `rest`, and SHALL
reference the conscious content it concerns (an entry id and/or a summary) so
the realizing effector can act appropriately. The action-selection policy SHALL
be an injectable component so motivational inputs (drives, recalled context,
Nous proposals) can be added without changing the cycle wiring or the intent
transport. An intent that realizes a Nous proposal SHALL carry `origin: "nous"`.

#### Scenario: Speak intent carries its referent

- **WHEN** the policy decides to speak about a conscious event
- **THEN** the emitted `speak` intent references that event's content

#### Scenario: Rest intent is not an effector action

- **WHEN** a `rest` intent is published
- **THEN** Praxis does not act on it and Lingua does not realize it

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

### Requirement: Volition realizes conscious Nous proposals under the existing gates

When `[nous].drive_actions` is true, Volition SHALL consider the most salient `nous.proposal` in the conscious coalition of each non-inhibited experiential broadcast. It SHALL turn a `think` or `speak` proposal into a `think` or `speak` intent, and a `rest` proposal into a `rest` intent, each with `origin: "nous"`. The same inhibition gate, one-in-flight guards, refractory periods and no-self-response rule SHALL apply as to every other intent. At most one proposal-derived intent SHALL be produced per snapshot, and it SHALL NOT displace an intent the configured policy produced for the same snapshot. The configured policy SHALL decide on the coalition with every `nous.proposal` removed. For every proposal it sees, Volition SHALL publish a content-free `volition.proposal_outcome` (`proposal_id`, `realized`, `reason`) on the `volition_feedback.out` stream, never on `volition.out`.

#### Scenario: An inhibited coalition never realizes a proposal
- **WHEN** a `nous.proposal` is in the coalition of an inhibited snapshot
- **THEN** no intent is produced, nothing is published to `volition.out`, and its outcome on `volition_feedback.out` is `realized: false`, `reason: "inhibited"`

#### Scenario: A proposal that never became conscious is never realized
- **WHEN** a `nous.proposal` is published but is not in any conscious coalition
- **THEN** Volition produces no intent for it

#### Scenario: A conscious think proposal becomes internal speech
- **WHEN** a non-inhibited coalition contains a `think` proposal and no think intent is in flight
- **THEN** a `think` intent with `origin: "nous"` is published on `volition.out`, and Lingua realizes it as `internal_speech`

#### Scenario: A user response outranks a Nous speak proposal
- **WHEN** the configured policy produces a `speak` intent for a snapshot that also contains a `speak` proposal
- **THEN** only the configured policy's intent is published, and the proposal's outcome is `reason: "superseded"`

#### Scenario: The configured policy never acts on a proposal itself
- **WHEN** a coalition contains a `nous.proposal` and other members
- **THEN** the configured policy decides on the coalition without the proposal, so none of its intents is about the proposal, and it produces the same intents whether `[nous].drive_actions` is true or false

#### Scenario: A lost realization never mutes a kind
- **WHEN** a Nous `think` or `speak` intent is realized under any configured policy, and the matching speech never becomes conscious
- **THEN** that kind's in-flight guard clears after the guard timeout, and a later proposal or policy intent of that kind can be realized again

#### Scenario: Observational ablation
- **WHEN** `[nous].drive_actions` is false
- **THEN** no proposal-derived intent is produced, and every proposal's outcome is `reason: "disabled"`
