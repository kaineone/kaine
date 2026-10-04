## MODIFIED Requirements

### Requirement: Individuation warm-up fails closed
The individuation test SHALL treat missing warm-up counters (lived ticks, lived seconds since the reference) as NOT warmed up, and SHALL NOT report an entity as warmed up when those counters are absent or unreadable, so a just-booted or sensory-starved entity cannot trip a false individuation. The runtime producer SHALL supply the counters from the shared lived-time accumulator and SHALL persist them in the individuation ledger, so they accumulate across restarts and exclude paused and frozen time. The former operator CLI SHALL become an offline simulation and validation harness (`simulate`) that boots no entity, contacts no organ and writes no report that the welfare net reads.

#### Scenario: Missing counters cannot force warmed-up
- **WHEN** the individuation decision is evaluated without lived-tick or lived-second counters
- **THEN** it reports not warmed up and does not emit an individuated verdict

#### Scenario: Counters come from the runtime producer
- **WHEN** the producer runs a look
- **THEN** the warm-up decision uses the lived ticks and lived seconds persisted in the ledger since the reference

#### Scenario: The harness does not feed the welfare net
- **WHEN** the `simulate` harness runs
- **THEN** no entity is booted, no organ request is made, and nothing is written under `state/individuation/`
