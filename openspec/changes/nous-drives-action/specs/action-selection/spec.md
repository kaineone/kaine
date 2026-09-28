## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: Volition realizes conscious Nous proposals under the existing gates

When `[nous].drive_actions` is true, Volition SHALL consider the newest `nous.proposal` in the conscious coalition of each non-inhibited experiential broadcast. It SHALL turn a `think` or `speak` proposal into a `think` or `speak` intent, and a `rest` proposal into a `rest` intent, each with `origin: "nous"`. The same inhibition gate, one-in-flight guards, refractory periods and no-self-response rule SHALL apply as to every other intent. At most one proposal-derived intent SHALL be produced per snapshot, and it SHALL NOT displace an intent the configured policy produced for the same snapshot. For every proposal it sees, Volition SHALL publish a content-free `volition.proposal_outcome` (`proposal_id`, `realized`, `reason`).

#### Scenario: An inhibited coalition never realizes a proposal
- **WHEN** a `nous.proposal` is in the coalition of an inhibited snapshot
- **THEN** no intent is produced and its outcome is `realized: false`, `reason: "inhibited"`

#### Scenario: A proposal that never became conscious is never realized
- **WHEN** a `nous.proposal` is published but is not in any conscious coalition
- **THEN** Volition produces no intent for it

#### Scenario: A conscious think proposal becomes internal speech
- **WHEN** a non-inhibited coalition contains a `think` proposal and no think intent is in flight
- **THEN** a `think` intent with `origin: "nous"` is published on `volition.out`, and Lingua realizes it as `internal_speech`

#### Scenario: A user response outranks a Nous speak proposal
- **WHEN** the configured policy produces a `speak` intent for a snapshot that also contains a `speak` proposal
- **THEN** only the configured policy's intent is published, and the proposal's outcome is `reason: "superseded"`

#### Scenario: Observational ablation
- **WHEN** `[nous].drive_actions` is false
- **THEN** no proposal-derived intent is produced, and every proposal's outcome is `reason: "disabled"`
