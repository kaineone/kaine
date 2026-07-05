## ADDED Requirements

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
