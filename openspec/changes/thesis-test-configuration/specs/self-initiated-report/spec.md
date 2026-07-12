## ADDED Requirements

### Requirement: Report threshold above the conscious threshold

The self-initiated report policy SHALL treat "worth saying" as a distinct, HIGHER
bar than "conscious": it forms an external `speak` intent only when the selected
coalition's precision-weighted surprise crosses a report threshold set above the
workspace publication (conscious) threshold. A coalition that is conscious but
below the report threshold produces no external speech.

#### Scenario: Conscious but not reportworthy stays silent

- **WHEN** a non-inhibited coalition's precision-weighted surprise is above the
  publication threshold but below the report threshold
- **THEN** the policy forms no `speak` intent (the entity is aware but silent)

#### Scenario: High surprise reports

- **WHEN** a non-inhibited coalition's precision-weighted surprise crosses the
  report threshold, no prior speak is in flight, and the refractory interval has
  elapsed
- **THEN** the policy forms exactly one `speak` intent about that coalition

### Requirement: Self-initiated, not input-triggered

The policy SHALL form intents from the entity's OWN workspace state — precision-
weighted surprise — and SHALL NOT depend on any user utterance or transcription
event. It never answers input; it reports its own state.

#### Scenario: No utterance is needed to speak

- **WHEN** the coalition contains only the entity's own predictive signals (no
  user-utterance / transcription event) and crosses the report threshold
- **THEN** the policy still forms a `speak` intent (report is self-initiated)

#### Scenario: Inhibited snapshot yields nothing

- **WHEN** the snapshot is inhibited (no coalition crossed the conscious threshold)
- **THEN** the policy forms no intent

### Requirement: Novelty and refractory gating (no streams, no stale queues)

The policy SHALL suppress repetition and flooding: it SHALL NOT re-report a
coalition whose content signature matches the last report, SHALL honor a minimum
refractory interval between reports, and SHALL respect one-in-flight guards for
both `speak` and `think` so a new intent is never formed while a prior one is
being realized. Because a report always describes the CURRENT coalition, stale
states are dropped rather than queued.

#### Scenario: Refractory interval suppresses chatter

- **WHEN** a reportworthy coalition occurs before the refractory interval since the
  last report has elapsed
- **THEN** the policy forms no new `speak` intent

#### Scenario: One-in-flight prevents a backlog

- **WHEN** a prior `speak` intent is still being realized (its guard armed) and a
  new reportworthy coalition occurs
- **THEN** the policy forms no new `speak` intent; when the guard clears, only the
  then-current state can be reported (no queued backlog)

#### Scenario: Repeated content is not re-reported

- **WHEN** two consecutive reportworthy coalitions share the same content signature
- **THEN** the second does not produce a `speak` intent

### Requirement: Internal think at a lower bar than external speak

The policy SHALL support an internal `think` channel gated by a threshold at or
below the report threshold and its own refractory/one-in-flight guards, so the
entity's internal monologue (saved, observed) can be more frequent than its rare
external speech.

#### Scenario: Moderate surprise thinks but does not speak

- **WHEN** surprise crosses the think threshold but not the report threshold, no
  think is in flight, and the think refractory has elapsed
- **THEN** the policy forms a `think` intent and no `speak` intent
