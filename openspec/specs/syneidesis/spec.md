# syneidesis Specification

## Purpose
TBD - created by archiving change syneidesis. Update Purpose after archive.
## Requirements
### Requirement: SalienceStrategy protocol with v1 product-form implementation
Syneidesis SHALL accept a salience strategy implementing
`async score(event, context) -> float`. The shipped v1 strategy
`RuleBasedSalience` SHALL compute the score as the product of four terms —
`intensity`, `novelty`, `goal_relevance`, `thymos_modulation` — each in
the closed interval `[0.0, 1.0]`, with the final result clamped to the
same interval.

#### Scenario: Score equals the product of four terms
- **WHEN** intensity=0.8, novelty=0.5, goal_relevance=1.0, thymos_modulation=1.0
- **THEN** `RuleBasedSalience.score(event, context)` returns 0.4

#### Scenario: Score clamps when any term is zero
- **WHEN** any of the four terms is 0.0
- **THEN** the returned score is 0.0

#### Scenario: Custom strategy substitutes cleanly
- **WHEN** the caller passes a custom `SalienceStrategy` that always returns 0.9
- **THEN** `Syneidesis.select` uses that strategy without modification

### Requirement: Top-k coalition selection
`Syneidesis.select` SHALL return a `WorkspaceSnapshot` whose
`selected_events` is the top `top_k` events by salience, ordered
descending. The default `top_k` SHALL be 5 and SHALL be configurable at
construction time and adjustable at runtime via `set_top_k`.

#### Scenario: Top-5 of ten events
- **WHEN** ten events are presented with distinct salience scores
- **THEN** the returned snapshot contains exactly five events in
  descending salience order

#### Scenario: Fewer events than k
- **WHEN** two events are presented with `top_k=5`
- **THEN** the snapshot contains both events without padding

### Requirement: Executive inhibition flag
`Syneidesis.select` SHALL set `WorkspaceSnapshot.inhibited` to `True`
when the top-1 salience score is strictly less than
`publication_threshold`, and `False` otherwise. The cycle continues to
broadcast inhibited snapshots; action modules SHALL check the flag.

#### Scenario: Top score below threshold inhibits
- **WHEN** the highest event score is 0.20 and `publication_threshold=0.35`
- **THEN** `snapshot.inhibited == True`

#### Scenario: Top score above threshold does not inhibit
- **WHEN** the highest event score is 0.50 and `publication_threshold=0.35`
- **THEN** `snapshot.inhibited == False`

#### Scenario: Empty event list returns an inhibited snapshot
- **WHEN** `select` is called with no events
- **THEN** `snapshot.selected_events == []` and
  `snapshot.inhibited == True`

### Requirement: Novelty habituates repeated payloads
`NoveltyTracker` SHALL return a novelty score in `[0.0, 1.0]` where 1.0
denotes "fingerprint never seen in window" and the score SHALL decrease
monotonically as the same fingerprint is observed within the window.
The window size SHALL be configurable.

#### Scenario: First observation is fully novel
- **WHEN** `observe(event)` is called once for an event the tracker has
  never seen
- **THEN** the returned novelty equals 1.0

#### Scenario: Repeated observation reduces novelty
- **WHEN** the same event is observed 10 times in a window of 32
- **THEN** the tenth observation's novelty is strictly less than the
  first

### Requirement: Defaults that let the system run without Thymos and goals
`Syneidesis` SHALL accept `GoalScorer` and `ThymosModulator` collaborators
with static defaults returning 1.0, so the product-form score works before
Phase 4 lands the real Thymos and goal representation. The system SHALL
produce nonzero salience scores without either module present.

#### Scenario: Default scorer yields nonzero score
- **WHEN** `RuleBasedSalience` is constructed with the default static
  scorers and an event with intensity 0.6 and novelty 0.8 is scored
- **THEN** the returned score equals 0.48

### Requirement: Strategy error tolerance
Syneidesis SHALL tolerate `SalienceStrategy.score` exceptions by logging a
warning, recording that event's score as 0.0, and continuing to score the
remaining events on the same tick.

#### Scenario: One bad event does not crash the whole tick
- **WHEN** a strategy raises for one of three events presented to `select`
- **THEN** the returned snapshot contains the other two events ranked
  by their scores and the bad event has score 0.0 in
  `snapshot.salience_scores`

### Requirement: Placeholder salience factors are disclosed at runtime

`RuleBasedSalience` SHALL emit a one-time `log.warning` at construction when
the injected `goal_scorer` is a `StaticGoalScorer` or the `thymos_modulator`
is a `StaticThymosModulator`, naming which factor(s) are bypassed and the
constant value returned. This makes the degraded two-factor salience mode
visible in operator logs without requiring source inspection.

`RuleBasedSalience` implements a four-factor product salience:
`intensity × novelty × goal_relevance × thymos_modulation`. When either
factor is a static placeholder (returning a constant), the live salience is
effectively reduced to `intensity × novelty`. The scoring math is unchanged;
this requirement governs disclosure only.

#### Scenario: Static goal scorer warns at construction
- **WHEN** `RuleBasedSalience` is constructed with a `StaticGoalScorer`
- **THEN** a `WARNING`-level log message names `StaticGoalScorer` and the
  bypassed `goal_relevance` factor

#### Scenario: Static thymos modulator warns at construction
- **WHEN** `RuleBasedSalience` is constructed with a `StaticThymosModulator`
- **THEN** a `WARNING`-level log message names `StaticThymosModulator` and the
  bypassed `thymos_modulation` factor

#### Scenario: Real scorers emit no warning
- **WHEN** `RuleBasedSalience` is constructed with non-Static scorers
- **THEN** no warning is emitted

