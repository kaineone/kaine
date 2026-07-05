## ADDED Requirements

### Requirement: thymos.emotion event discloses unavailable appraisal dimensions

The `thymos.emotion` event payload SHALL carry `"norm_compatibility_available": false`
until Eidolon norm signals are wired into the appraisal pipeline.  While
`norm_compatibility_available` is false, the DISGUST classification branch is
unreachable by design.

#### Scenario: norm_compatibility not wired

- **WHEN** a `thymos.emotion` event is published
- **AND** the Eidolon norm signal is not integrated
- **THEN** the payload carries `"norm_compatibility_available": false`
- **AND** downstream consumers MUST NOT interpret the numeric norm value as a real measurement

---

### Requirement: thymos.emotion event discloses goal_significance method

The `thymos.emotion` event payload SHALL carry
`"goal_significance_method": "token_overlap_v1"` so consumers know the
published `goal_significance` appraisal score is a bag-of-words heuristic,
not a semantic relevance measure.

#### Scenario: goal_significance is a proxy

- **WHEN** a `thymos.emotion` event is published
- **THEN** the payload carries `"goal_significance_method": "token_overlap_v1"`

---

### Requirement: GoalLedger.relevance returns zero with no active goals

`GoalLedger.relevance()` SHALL return `0.0` when no active goals are
registered, preventing spurious small positive values from acting as
goal-significance noise in the appraisal.

#### Scenario: no active goals

- **WHEN** `GoalLedger.relevance()` is called and no goals are in the ACTIVE state
- **THEN** the return value is `0.0`

---

### Requirement: PassiveDecay regulation is visible in traces

`PassiveDecay.suggest()` SHALL emit a one-time `log.debug` message on its
first call so that the absence of an active regulation policy is visible in
traces rather than silently doing nothing every tick.

#### Scenario: first use of PassiveDecay

- **WHEN** `PassiveDecay.suggest()` is called for the first time
- **THEN** a debug log message is emitted naming the passive policy
- **AND** subsequent calls do not repeat the message
